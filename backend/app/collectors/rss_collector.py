"""RSS and Atom collection.

``feedparser`` absorbs most of the format variation; what this module adds is the project's
rules about what may be *kept*:

* An entry with no usable absolute http(s) URL is dropped and counted, not stored with a broken
  link.
* An entry with no title is dropped: the title is the one field the conservative licence
  baseline permits showing, so an item without one has nothing displayable.
* The description a feed supplies is **measured always and stored only when the source's licence
  permits it**. That is the distinction specification section 1.3 insists on - a feed carrying
  a description is not a publisher licensing its republication - and it is why
  ``offered_description_chars`` exists separately from ``original_description``.
"""

from __future__ import annotations

from datetime import datetime

import feedparser

from app.collectors.base import BaseCollector, CollectionStats, CollectorError
from app.models.article import Article, Category, article_id_for, content_hash_for
from app.models.licensing import allows_description_display, allows_summary_publication
from app.models.source import NewsSource, SourceType
from app.processors import normalization as norm

#: Feed description fields, in the order they are preferred. ``content`` can hold an entire
#: article, which is why it is read last and never kept for a metadata-only source.
_DESCRIPTION_KEYS = ("summary", "description", "subtitle")


class RSSCollector(BaseCollector):
    """Collects from any RSS 0.9x/1.0/2.0 or Atom feed."""

    name = "rss"

    def supports(self, source: NewsSource) -> bool:
        return source.source_type in (SourceType.RSS, SourceType.ATOM)

    def parse(
        self,
        payload: bytes,
        source: NewsSource,
        discovered_at: datetime,
        stats: CollectionStats,
    ) -> list[Article]:
        feed = feedparser.parse(payload)

        # An empty *feed* and a payload that is not a feed must not look the same. A publisher
        # serving an HTML error page with HTTP 200 is the common case, and feedparser reports
        # it as zero entries with `bozo` unset - which would be recorded as a healthy source
        # that happened to publish nothing. `version` is the reliable signal: feedparser sets
        # it only when it recognised a feed format, so an empty RSS channel keeps "rss20"
        # while an HTML page gets "".
        if not feed.entries:
            if not getattr(feed, "version", ""):
                reason = getattr(feed, "bozo_exception", None)
                raise CollectorError(
                    "payload is not a recognised feed format"
                    + (f": {reason}" if reason else " (no entries, no feed version)")
                )
            return []

        # feedparser sets `bozo` for anything it had to repair. That alone is not an error - a
        # great many live feeds have stray entities and parse fine - so it is not checked once
        # entries came out.

        stats.raw_items = len(feed.entries)
        keep_description = allows_description_display(source.license_type)
        summary_allowed = allows_summary_publication(source.license_type)
        articles: list[Article] = []
        seen_in_payload: set[str] = set()

        for entry in feed.entries:
            article = self._parse_entry(
                entry, source, discovered_at, stats,
                keep_description=keep_description,
                summary_allowed=summary_allowed,
            )
            if article is None:
                continue
            # A feed that lists the same article twice is common around an update. Collapse it
            # here so the per-run statistics are not inflated by the provider's own duplicates.
            if article.canonical_url in seen_in_payload:
                continue
            seen_in_payload.add(article.canonical_url)
            articles.append(article)
            # Counted here rather than at parse time so that an entry which was dropped, or
            # collapsed into one already seen, cannot push coverage above 100%.
            if article.offered_description_chars:
                stats.items_with_description += 1
            if article.description_withheld_reason:
                stats.descriptions_withheld_by_license += 1

        if source.max_items_per_fetch:
            # Newest first, then truncate. Feed order is not reliably chronological - some
            # publishers put a sticky item at the top - so the cap sorts rather than slicing
            # whatever happened to come first.
            articles.sort(key=lambda a: a.published_at, reverse=True)
            dropped = len(articles) - source.max_items_per_fetch
            if dropped > 0:
                articles = articles[: source.max_items_per_fetch]
                stats.capped_by_domain += dropped

        # Set here as well as in collect() so that the coverage ratio is meaningful when
        # parse() is called on its own - which is how the parser is unit-tested.
        stats.parsed_items += len(articles)
        return articles

    def _parse_entry(
        self,
        entry: dict,
        source: NewsSource,
        discovered_at: datetime,
        stats: CollectionStats,
        *,
        keep_description: bool,
        summary_allowed: bool,
    ) -> Article | None:
        title = norm.clean_title(entry.get("title"), outlet=source.name)
        if not title:
            stats.dropped_missing_title += 1
            return None

        raw_url = entry.get("link") or ""
        if not raw_url and entry.get("links"):
            raw_url = next(
                (link.get("href", "") for link in entry["links"] if link.get("rel") == "alternate"),
                entry["links"][0].get("href", ""),
            )
        canonical = norm.canonicalise_url(raw_url)
        if not canonical:
            stats.dropped_invalid_url += 1
            return None

        description_raw = ""
        for key in _DESCRIPTION_KEYS:
            description_raw = norm.strip_html(entry.get(key))
            if description_raw:
                break
        description: str | None = None
        withheld_reason: str | None = None
        if description_raw:
            if keep_description:
                description = description_raw
            else:
                withheld_reason = (
                    f"Source licence is {source.license_type.value}: the publisher's description "
                    f"is measured but not stored."
                )

        published_at = norm.parse_datetime(
            entry.get("published_parsed") or entry.get("updated_parsed")
            or entry.get("published") or entry.get("updated"),
            discovered_at,
        )

        language = norm.normalise_language(
            entry.get("language") or source.language, default=source.language or "und"
        )

        category = Category.OTHER
        if source.default_category:
            try:
                category = Category(source.default_category)
            except ValueError:
                category = Category.OTHER

        return Article(
            id=article_id_for(canonical),
            url=raw_url.strip(),
            canonical_url=canonical,
            content_hash=content_hash_for(title, canonical),
            title=title,
            original_title=norm.strip_html(entry.get("title")),
            publisher=source.name,
            domain=norm.domain_of(canonical) or source.domain,
            country=source.country,
            language=language,
            source_id=source.source_id,
            published_at=published_at,
            discovered_at=discovered_at,
            author=norm.strip_html(entry.get("author")) or None,
            image_url=_extract_image(entry),
            original_description=description,
            description_withheld_reason=withheld_reason,
            offered_description_chars=len(description_raw),
            category=category,
            license_status=source.license_type,
            summary_reuse_allowed=summary_allowed,
            attribution_text=source.attribution_text or source.name,
        )


def _extract_image(entry: dict) -> str | None:
    """The entry's lead image, from whichever of the four common places it is in.

    Only the URL is kept. The image itself is never downloaded or re-hosted: hotlinking the
    publisher's own URL keeps the request, and the copyright question, with the publisher.
    """
    media = entry.get("media_content") or entry.get("media_thumbnail")
    if isinstance(media, list) and media:
        url = norm.canonicalise_url(media[0].get("url"))
        if url:
            return url
    for link in entry.get("links", []) or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image/"):
            url = norm.canonicalise_url(link.get("href"))
            if url:
                return url
    for enclosure in entry.get("enclosures", []) or []:
        if str(enclosure.get("type", "")).startswith("image/"):
            url = norm.canonicalise_url(enclosure.get("href") or enclosure.get("url"))
            if url:
                return url
    return None
