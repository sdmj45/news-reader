"""GDELT Article List (GAL) collection.

**Schema verified against live data on 2026-11-14.** ``scripts/probe_gdelt.py`` downloaded
``20261114183100.gal.json.gz`` (1,791 records, 1.4 MB decompressed) and measured it. What the
measurement found, and what this parser is therefore built on:

===============  ========  ====================================================
field            present   note
===============  ========  ====================================================
``date``          100.0%   ISO 8601 with ``Z``. GDELT states ~30% are the real
                           publication time; the rest are first-seen times.
``url``           100.0%   0 invalid, 0 duplicates within one file.
``domain``        100.0%
``outletName``    100.0%   Falls back to the domain when the outlet is unnamed.
``title``         100.0%
``lang``          100.0%   en 26%, es 13%, de 10%, fr 6%, then 40+ others.
``desc``           97.2%   Median 150 characters - a standfirst, not an article.
``outletLogo``     96.2%   Not stored: the application does not display logos.
``image``          95.5%
``outletTwitter``  63.5%   Not stored.
``author``         37.2%
===============  ========  ====================================================

545 distinct domains in a single minute's file, so GAL is a genuine firehose rather than a
curated feed. It is also indiscriminate: the same file carries Reuters wire copy, golf
leaderboards and marketing blogs. :func:`is_low_value_domain` is deliberately *not* here -
filtering GDELT by quality is a later problem, and the registry restricts GAL to the languages
the application serves rather than pretending to judge outlets.

**Licensing.** GDELT indexes other publishers' pages; it does not license their content. Every
GAL record therefore arrives as ``LicenseType.UNKNOWN``, which means title, outlet, timestamp
and link are stored and the 150-character ``desc`` is *measured and discarded*. That is the
distinction specification section 1.3 requires, and it is why GAL's high description coverage
does not translate into displayed descriptions.

**File layout**, confirmed by probing rather than assumed:

* ``https://data.gdeltproject.org/gdeltv3/gal/YYYYMMDDHHMM00.gal.json.gz`` - gzip, UTF-8,
  one JSON object per line, no enclosing array.
* Despite the announcement's "produced each minute", files appear in a short burst in the
  minutes *after* each quarter hour. A probe of 33 consecutive minute-stamps found 9 files.
  :meth:`GDELTGALCollector.discover_files` searches that way instead of guessing one URL.
* ``/gdeltv3/gal/feed.rss`` carries the same articles as RSS, but measured on the same day it
  supplies **title, link and pubDate only** - no description, no language, no outlet name.
  :class:`GDELTRSSCollector` handles it and the registry prefers the JSON-NL files.

Nothing in this file fabricates GDELT data, and no test asserts live collection without
reaching the network.

Reference: https://blog.gdeltproject.org/announcing-the-gdelt-article-list-rss-feed/
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
import time
from collections import Counter
from datetime import UTC, datetime

from app.collectors.base import (
    BaseCollector,
    CollectionResult,
    CollectionStats,
    CollectorError,
)
from app.collectors.rss_collector import RSSCollector
from app.models.article import Article, Category, article_id_for, content_hash_for
from app.models.licensing import allows_description_display, allows_summary_publication
from app.models.source import NewsSource, SourceType
from app.processors import normalization as norm

logger = logging.getLogger(__name__)

#: Where the per-minute GAL files live. The registry entry points here, not at one file.
GAL_BASE_URL = "https://data.gdeltproject.org/gdeltv3/gal"

#: Files appear in a burst after each quarter hour, so each quarter is searched across a
#: six-minute window. Measured: a 33-minute sweep found 9 files, all within such windows.
GAL_MINUTES_PER_QUARTER = 6

#: How far back to search when no cursor exists yet. Six quarters is about ninety minutes.
GAL_DEFAULT_QUARTERS_BACK = 6

#: Articles kept from any one domain per run.
#:
#: Measured on 2026-11-14: a French-filtered GAL run returned 184 articles of which 29 came
#: from one Tunisian daily and 16 from an Algerian one that was re-publishing its 2020
#: archive. GDELT dates those by first-seen, so a site dumping old content looks like the
#: freshest news on the service and takes over a reading list sorted newest-first.
#:
#: A cap is the right shape of fix because the problem is concentration, not the publisher:
#: five articles from a regional paper is coverage, two hundred is a flood. It is not a
#: quality judgement and no domain is excluded.
MAX_ARTICLES_PER_DOMAIN = 5

#: Documented key, then the spellings seen in GDELT's other v3 products. Checked in order.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "seendate", "datetime", "pubdate"),
    "url": ("url", "docurl", "documentidentifier"),
    "domain": ("domain", "sourcecommonname", "domainname"),
    "outlet": ("outletname", "outlet", "sourcecommonname", "sourcename"),
    "title": ("title", "headline"),
    "desc": ("desc", "description", "snippet", "excerpt"),
    "lang": ("lang", "language"),
    "author": ("author", "byline"),
    "image": ("image", "socialimage", "imageurl"),
}

#: A single GAL file can be large; this caps one parse so a surprise does not exhaust memory.
MAX_RECORDS_PER_PAYLOAD = 50_000


def _get(record: dict, field: str) -> str:
    """Case-insensitive lookup across the known aliases. Returns ``""`` when absent."""
    lowered = {str(k).lower(): v for k, v in record.items()}
    for alias in _FIELD_ALIASES[field]:
        value = lowered.get(alias)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list)) and str(value).strip():
            return str(value).strip()
    return ""


class GDELTGALCollector(BaseCollector):
    """Parses GDELT GAL JSON-NL: one JSON object per line.

    Malformed lines are counted and skipped rather than failing the payload - a single bad
    record in a file of thousands should cost one article, not the run. A payload in which
    *no* line parses raises, because that means the format is not what this parser targets,
    and that is exactly the condition this module must not paper over.
    """

    name = "gdelt_gal"

    def supports(self, source: NewsSource) -> bool:
        return source.source_type is SourceType.GDELT_GAL_JSONNL

    def __init__(
        self,
        *args,
        files_per_run: int = 2,
        languages: frozenset[str] | None = None,
        max_per_domain: int = MAX_ARTICLES_PER_DOMAIN,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        #: GAL is a firehose; one file is ~1,800 articles. Two per run keeps a scheduled
        #: collection to a few thousand records rather than tens of thousands.
        self._files_per_run = files_per_run
        #: Keep only these languages. Empty or None keeps everything. Measured on a real
        #: file: 1,791 records across 40+ languages, of which 104 were French - so for a
        #: French news reader this filter is the difference between signal and noise.
        self._languages = languages or frozenset()
        #: See MAX_ARTICLES_PER_DOMAIN. Zero disables the cap.
        self._max_per_domain = max_per_domain

    @staticmethod
    def candidate_urls(now: datetime, quarters_back: int = GAL_DEFAULT_QUARTERS_BACK) -> list[str]:
        """GAL file URLs worth trying, newest first.

        Derived from the clock rather than from a directory listing, because
        ``/gdeltv3/gal/`` returns 404 - there is no index to read.
        """
        base = now.replace(second=0, microsecond=0)
        urls: list[str] = []
        for quarter in range(quarters_back):
            mark = base - dt.timedelta(minutes=(base.minute % 15) + 15 * quarter)
            for offset in range(GAL_MINUTES_PER_QUARTER):
                stamp = (mark + dt.timedelta(minutes=offset)).strftime("%Y%m%d%H%M00")
                urls.append(f"{GAL_BASE_URL}/{stamp}.gal.json.gz")
        # Newest first: within a quarter the later minute is the newer file.
        return sorted(set(urls), reverse=True)

    @staticmethod
    def timestamp_of(url: str) -> str:
        """The ``YYYYMMDDHHMMSS`` stamp in a GAL filename, used as the incremental cursor."""
        return url.rsplit("/", 1)[-1].split(".", 1)[0]

    async def collect(
        self,
        source: NewsSource,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> CollectionResult:
        """Collects the newest GAL files that have not been seen yet.

        Unlike an RSS source, GAL has no single stable URL: each file is a minute of articles
        and disappears from the useful window as time passes. Incremental collection is
        therefore done with a cursor rather than with ETags - ``last_modified`` carries the
        newest filename stamp already collected, and anything at or below it is skipped.
        """
        stats = CollectionStats(source_id=source.source_id, attempted=True)
        started = time.monotonic()
        discovered_at = datetime.now(UTC)
        cursor = last_modified or ""

        candidates = [
            url for url in self.candidate_urls(discovered_at)
            if self.timestamp_of(url) > cursor
        ]
        if not candidates:
            stats.not_modified = True
            stats.duration_seconds = time.monotonic() - started
            return CollectionResult(
                source_id=source.source_id, stats=stats, last_modified=cursor,
            )

        articles: list[Article] = []
        seen: set[str] = set()
        newest_stamp = cursor
        files_read = 0
        misses = 0
        last_error: str | None = None

        for url in candidates:
            if files_read >= self._files_per_run:
                break
            try:
                response = await self._fetch(url, stats)
            except CollectorError as exc:
                # A 404 is the normal case: most minute-stamps have no file.
                if "404" in str(exc):
                    misses += 1
                    continue
                last_error = self._describe(exc)
                continue
            except Exception as exc:
                last_error = self._describe(exc)
                continue

            try:
                payload = self.decompress(response.content)
                batch = self.parse(payload, source, discovered_at, stats)
            except Exception as exc:
                last_error = f"parse failed for {url}: {self._describe(exc)}"
                logger.warning("gdelt.parse_failed url=%s error=%s", url, last_error)
                continue

            files_read += 1
            newest_stamp = max(newest_stamp, self.timestamp_of(url))
            for article in batch:
                if article.canonical_url in seen:
                    continue
                seen.add(article.canonical_url)
                articles.append(article)

        stats.parsed_items = len(articles)
        stats.duration_seconds = time.monotonic() - started

        if files_read == 0:
            # Two very different situations produce zero files, and conflating them would be
            # wrong in both directions.
            #
            # With a cursor, every candidate being a 404 is the *normal* state between
            # quarter-hour publications: there is simply nothing newer yet. Recording that as
            # a failure would increment the failure count every few minutes and eventually
            # back GDELT off for six hours over a feed that is working perfectly.
            #
            # Without a cursor - a first run, or after the window moved past everything we
            # had - zero files means GDELT is unreachable or has changed, and that is a real
            # failure that must be reported rather than hidden.
            if cursor and misses == len(candidates) and last_error is None:
                stats.not_modified = True
                logger.info(
                    "gdelt.nothing_new source=%s cursor=%s candidates=%d",
                    source.source_id, cursor, len(candidates),
                )
                return CollectionResult(
                    source_id=source.source_id, stats=stats, last_modified=cursor,
                )

            message = last_error or (
                f"no GAL file found in {len(candidates)} candidate timestamps "
                f"({misses} returned 404)"
            )
            logger.warning("gdelt.no_files source=%s reason=%s", source.source_id, message)
            return CollectionResult(source_id=source.source_id, stats=stats, error=message)

        logger.info(
            "gdelt.ok source=%s files=%d articles=%d cursor=%s",
            source.source_id, files_read, len(articles), newest_stamp,
        )
        return CollectionResult(
            source_id=source.source_id,
            articles=articles,
            stats=stats,
            last_modified=newest_stamp,
        )

    @staticmethod
    def decompress(payload: bytes) -> bytes:
        """GAL files are gzip served as ``.gz`` with no Content-Encoding, so httpx leaves them.

        Checks the magic number rather than the filename: an uncompressed payload (which is
        what a test fixture or a future format change would supply) passes through unchanged.
        """
        if payload[:2] == b"\x1f\x8b":
            try:
                return gzip.decompress(payload)
            except (OSError, EOFError) as exc:
                raise CollectorError(
                    f"GAL payload claimed gzip but did not decompress: {exc}"
                ) from exc
        return payload

    def parse(
        self,
        payload: bytes,
        source: NewsSource,
        discovered_at: datetime,
        stats: CollectionStats,
    ) -> list[Article]:
        text = payload.decode("utf-8", errors="replace")
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return []

        stats.raw_items = len(lines)
        keep_description = allows_description_display(source.license_type)
        summary_allowed = allows_summary_publication(source.license_type)

        articles: list[Article] = []
        seen: set[str] = set()
        per_domain: Counter[str] = Counter()
        decoded_any = False

        for line in lines[:MAX_RECORDS_PER_PAYLOAD]:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                stats.dropped_other += 1
                continue
            if not isinstance(record, dict):
                stats.dropped_other += 1
                continue
            decoded_any = True

            article = self._parse_record(
                record, source, discovered_at, stats,
                keep_description=keep_description,
                summary_allowed=summary_allowed,
            )
            if article is None or article.canonical_url in seen:
                continue
            if self._max_per_domain and per_domain[article.domain] >= self._max_per_domain:
                stats.capped_by_domain += 1
                continue
            per_domain[article.domain] += 1
            seen.add(article.canonical_url)
            articles.append(article)
            # Counted on kept articles only; see the same note in rss_collector.
            if article.offered_description_chars:
                stats.items_with_description += 1
            if article.description_withheld_reason:
                stats.descriptions_withheld_by_license += 1

        if not decoded_any:
            raise CollectorError(
                f"no line in the {len(lines)}-line payload decoded as a JSON object; the GAL "
                f"format is not what this parser targets. Run scripts/probe_gdelt.py and "
                f"update app/collectors/gdelt_collector.py against the real schema."
            )
        stats.parsed_items += len(articles)
        return articles

    def _parse_record(
        self,
        record: dict,
        source: NewsSource,
        discovered_at: datetime,
        stats: CollectionStats,
        *,
        keep_description: bool,
        summary_allowed: bool,
    ) -> Article | None:
        canonical = norm.canonicalise_url(_get(record, "url"))
        if not canonical:
            stats.dropped_invalid_url += 1
            return None
        domain = norm.domain_of(canonical)
        # GDELT indexes aggregators too. Their links redirect elsewhere, so storing one gives
        # a reader a URL that is not the article they were shown.
        if norm.is_aggregator_url(canonical):
            stats.dropped_other += 1
            return None

        language = norm.normalise_language(_get(record, "lang"), default="und")
        if self._languages and language not in self._languages:
            # Filtered, not failed: counted separately from malformed records so that a
            # mis-set filter shows up as "collected 3 of 1,791" rather than as a parse error.
            stats.filtered_by_language += 1
            return None

        outlet = _get(record, "outlet") or domain
        title = norm.clean_title(_get(record, "title"), outlet=outlet)
        if not title:
            stats.dropped_missing_title += 1
            return None

        description_raw = norm.strip_html(_get(record, "desc"))
        description: str | None = None
        withheld_reason: str | None = None
        if description_raw:
            if keep_description:
                description = description_raw
            else:
                withheld_reason = (
                    f"Source licence is {source.license_type.value}: GDELT indexes the "
                    f"publisher's description, it does not license it."
                )

        publisher = outlet or source.name

        return Article(
            id=article_id_for(canonical),
            url=_get(record, "url"),
            canonical_url=canonical,
            content_hash=content_hash_for(title, canonical),
            title=title,
            original_title=_get(record, "title"),
            publisher=publisher,
            domain=domain,
            # GAL records carry no country field; leaving it null is correct, and inferring one
            # from the TLD would be wrong for .com, .org and every global outlet.
            country=None,
            language=language,
            source_id=source.source_id,
            published_at=norm.parse_datetime(_get(record, "date"), discovered_at),
            discovered_at=discovered_at,
            author=_get(record, "author") or None,
            image_url=norm.canonicalise_url(_get(record, "image")) or None,
            original_description=description,
            description_withheld_reason=withheld_reason,
            offered_description_chars=len(description_raw),
            category=Category.OTHER,
            license_status=source.license_type,
            summary_reuse_allowed=summary_allowed,
            attribution_text=source.attribution_text or "GDELT Project",
        )


class GDELTRSSCollector(RSSCollector):
    """The GAL RSS feed. Identical parsing to any RSS source; separate class for the registry."""

    name = "gdelt_rss"

    def supports(self, source: NewsSource) -> bool:
        return source.source_type is SourceType.GDELT_GAL_RSS


def describe_payload(payload: bytes, sample_size: int = 500) -> dict:
    """Measures a real GAL payload's schema instead of assuming it.

    This is the function specification section 4.1 asks for: field presence, description
    coverage, language and domain spread, and invalid URLs, computed from data rather than
    from the announcement post. Used by ``scripts/probe_gdelt.py``; it does not require any
    registry entry and makes no network request itself.
    """
    text = payload.decode("utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]
    sample = lines[:sample_size]

    decoded: list[dict] = []
    malformed = 0
    for line in sample:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(record, dict):
            decoded.append(record)
        else:
            malformed += 1

    key_counts: Counter[str] = Counter()
    non_empty: Counter[str] = Counter()
    for record in decoded:
        for key, value in record.items():
            key_counts[key] += 1
            if value not in (None, "", [], {}):
                non_empty[key] += 1

    total = len(decoded)
    urls = [_get(r, "url") for r in decoded]
    canonical = [norm.canonicalise_url(u) for u in urls]
    descriptions = [norm.strip_html(_get(r, "desc")) for r in decoded]

    return {
        "lines_total": len(lines),
        "lines_sampled": len(sample),
        "records_decoded": total,
        "lines_malformed": malformed,
        "keys_seen": dict(key_counts),
        "keys_non_empty": dict(non_empty),
        "field_presence": {
            field: round(sum(1 for r in decoded if _get(r, field)) / total, 4) if total else 0.0
            for field in _FIELD_ALIASES
        },
        "invalid_urls": sum(1 for c in canonical if not c),
        "duplicate_canonical_urls": len(canonical) - len({c for c in canonical if c}),
        "description_coverage": round(sum(1 for d in descriptions if d) / total, 4) if total else 0.0,
        "description_median_chars": (
            sorted(len(d) for d in descriptions if d)[sum(1 for d in descriptions if d) // 2]
            if any(descriptions) else 0
        ),
        "distinct_domains": len({norm.domain_of(c) for c in canonical if c}),
        "top_domains": Counter(norm.domain_of(c) for c in canonical if c).most_common(15),
        "languages": Counter(norm.normalise_language(_get(r, "lang")) for r in decoded).most_common(15),
    }
