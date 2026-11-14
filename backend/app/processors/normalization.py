"""Turning whatever a provider sends into a uniform :class:`~app.models.article.Article`.

Three problems recur across every feed format and are solved here so no collector has to:

* **URLs carry tracking junk.** The same article arrives from two feeds with different campaign
  parameters and looks like two articles. :func:`canonicalise_url` strips them, which is the
  first and cheapest layer of deduplication.
* **Titles carry markup.** HTML entities, stray tags and non-breaking spaces, which would
  otherwise break both title similarity and the display layer.
* **Dates come in every format there is.** RFC 822, ISO 8601, no timezone, or absent.
  :func:`parse_datetime` always returns an aware UTC datetime, falling back to the discovery
  time rather than dropping the item: an article with an unparsable date is still an article.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dateutil import parser as _date_parser

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

#: Query parameters that identify a campaign or a referrer, never the article. Stripping them
#: is what lets the same story from a newsletter link and a homepage link collapse into one.
TRACKING_PARAMS = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
        "utm_name", "utm_reader", "utm_social", "utm_brand",
        "xtor", "xtref", "at_medium", "at_campaign", "at_custom1", "at_custom2",
        "at_custom3", "at_custom4", "at_link_origin",
        "ref", "referer", "referrer", "source", "src",
        "fbclid", "gclid", "dclid", "msclkid", "twclid", "igshid", "mc_cid", "mc_eid",
        "spm", "share_token", "ncid", "cmpid", "CMP", "ito", "smid",
    }
)

#: Hosts that wrap another publisher's URL. Their links are redirects, not canonical articles.
_AGGREGATOR_HOSTS = frozenset({"news.google.com", "t.co", "bit.ly", "ow.ly", "buff.ly"})


def strip_html(value: str | None) -> str:
    """Removes markup and entities and collapses all whitespace, including NBSP variants."""
    if not value:
        return ""
    text = _TAG_RE.sub(" ", value)
    text = html.unescape(text)
    # U+00A0 NBSP and U+202F narrow NBSP survive unescape and break token comparison.
    text = text.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    return _WHITESPACE_RE.sub(" ", text).strip()


#: Separators publishers put between a headline and their own name.
_SUFFIX_SEPARATORS = (" - ", " – ", " — ", " | ", " :: ")


def clean_title(value: str | None, outlet: str | None = None) -> str:
    """A display-ready headline: no markup, no doubled spaces, no trailing outlet name.

    Publishers routinely append their own name - "Les projets calent - La Depeche de
    Kabylie". Removing it is worth doing for two reasons beyond tidiness: the suffix repeats
    on every headline from that outlet, where the publisher is already shown next to it, and
    it is *paid for* when the headline is translated, which on a free quota of about 5,000
    characters a day is real money's worth of characters.

    Only removed when ``outlet`` is given and the tail actually matches it. Guessing from the
    separator alone would mangle "Proces Dupont - le verdict", and the outlet name is always
    available at the call site because the collector knows which source it is parsing.
    """
    text = strip_html(value)
    if outlet:
        text = _strip_outlet_suffix(text, outlet)
    return text.strip(" \t–—-|")


def _strip_outlet_suffix(text: str, outlet: str) -> str:
    """Removes a trailing ``<separator><outlet>``, case- and accent-insensitively."""
    folded_outlet = normalise_title(outlet)
    if not folded_outlet:
        return text
    for separator in _SUFFIX_SEPARATORS:
        index = text.rfind(separator)
        if index <= 0:
            continue
        tail = text[index + len(separator) :]
        # Folded comparison so "LA DEPECHE DE KABYLIE" matches "La Depeche de Kabylie". The
        # length bound keeps a long trailing clause - which is headline, not byline - intact.
        if len(tail) <= 60 and normalise_title(tail) == folded_outlet:
            return text[:index].rstrip(" -–—|")
    return text


def normalise_title(value: str | None) -> str:
    """Accent-folded, lowercase, punctuation-free form used for comparison, never for display."""
    text = strip_html(value).lower()
    decomposed = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))
    folded = re.sub(r"[^\w\s]", " ", folded, flags=re.UNICODE)
    return _WHITESPACE_RE.sub(" ", folded).strip()


def canonicalise_url(url: str | None) -> str:
    """Lowercases scheme and host, drops tracking parameters and fragments, trims trailing slash.

    Returns ``""`` for anything that is not an absolute http(s) URL, which the collectors treat
    as an invalid item rather than storing a link that cannot be opened.
    """
    if not url:
        return ""
    raw = url.strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return ""

    host = parts.netloc.lower()
    if "@" in host:  # credentials in a news URL are never meaningful
        host = host.rsplit("@", 1)[1]
    if host.startswith("www."):
        host = host[4:]
    # Default ports add a spurious difference between otherwise identical URLs.
    if host.endswith(":80") and parts.scheme.lower() == "http":
        host = host[:-3]
    if host.endswith(":443") and parts.scheme.lower() == "https":
        host = host[:-4]

    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k not in TRACKING_PARAMS and k.lower() not in {p.lower() for p in TRACKING_PARAMS}
    ]
    kept.sort()  # parameter order is not part of an article's identity
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(kept), ""))


def domain_of(url: str | None) -> str:
    """The registrable host, lowercased and without ``www.``. Empty for an unusable URL."""
    if not url:
        return ""
    host = urlsplit(url.strip()).netloc.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    host = host.split(":")[0]
    return host[4:] if host.startswith("www.") else host


def is_aggregator_url(url: str | None) -> bool:
    """Whether this URL points at a redirector rather than at a publisher's article."""
    return domain_of(url) in _AGGREGATOR_HOSTS


def parse_datetime(value: object, fallback: datetime) -> datetime:
    """Best-effort publication time, always timezone-aware UTC.

    Accepts a string, a ``time.struct_time`` (what feedparser produces), or a datetime. A time
    that cannot be parsed, or that is implausibly far in the future, falls back rather than
    being trusted: a feed claiming 2049 would otherwise pin itself to the top of every list.
    """
    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (tuple, list)) and len(value) >= 6:
        try:
            parsed = datetime(*[int(x) for x in value[:6]], tzinfo=UTC)
        except (ValueError, TypeError):
            parsed = None
    elif isinstance(value, str) and value.strip():
        try:
            parsed = _date_parser.parse(value.strip())
        except (ValueError, OverflowError, TypeError):
            parsed = None

    if parsed is None:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)

    # A timestamp more than a day ahead of discovery is a publisher error or a parsing error.
    if (parsed - fallback).total_seconds() > 86400:
        return fallback
    return parsed


_LANG_RE = re.compile(r"^([a-zA-Z]{2,3})(?:[-_].*)?$")


def normalise_language(value: str | None, default: str = "und") -> str:
    """Reduces ``fr-FR``, ``FR``, ``fra`` to a lowercase primary subtag. ``und`` when unknown.

    ``und`` is ISO 639-2's "undetermined" and is used rather than guessing, so that a language
    filter never silently claims an article is French because its publisher usually is.
    """
    if not value:
        return default
    match = _LANG_RE.match(value.strip())
    if not match:
        return default
    tag = match.group(1).lower()
    # Map the common three-letter forms GDELT and some feeds use onto ISO 639-1.
    three_to_two = {"fra": "fr", "fre": "fr", "eng": "en", "zho": "zh", "chi": "zh",
                    "deu": "de", "ger": "de", "spa": "es", "ita": "it", "por": "pt",
                    "rus": "ru", "ara": "ar", "jpn": "ja", "kor": "ko", "nld": "nl"}
    return three_to_two.get(tag, tag)
