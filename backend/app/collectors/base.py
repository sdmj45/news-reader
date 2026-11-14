"""The collector interface and the HTTP behaviour every collector shares.

Specification section 5 lists seven responsibilities per collector and six cross-cutting
concerns (timeouts, backoff, rate limiting, user-agent, logging, incremental collection). The
cross-cutting half lives here so that writing a new collector means writing a parser, not
another retry loop.

Two rules are enforced rather than documented:

* **A collector never raises into the manager.** :meth:`BaseCollector.collect` catches
  everything and returns a :class:`CollectionResult` carrying the error, because specification
  section 5 requires that one failed source not stop the others.
* **A collector never invents an item.** On failure the result has an empty item list and a
  populated ``error``. There is no fallback to cached, sample or placeholder articles anywhere
  in this package.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app.models.article import Article
from app.models.source import NewsSource

logger = logging.getLogger(__name__)

#: Sent on every outbound request. A contactable identity is the minimum courtesy owed to a
#: publisher whose feed is being polled, and several publishers block unidentified clients.
USER_AGENT = (
    "NewsReaderBot/0.1 (+https://github.com/; personal news aggregator; contact: operator)"
)

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_ATTEMPTS = 3
#: Base for exponential backoff; actual sleep is base * 2**attempt plus jitter.
DEFAULT_BACKOFF_BASE_SECONDS = 1.0
#: Status codes worth retrying. 429 and 5xx are transient; 4xx otherwise is not.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class CollectorError(Exception):
    """A collector could not produce items. Carries a human-readable reason, never swallowed."""


@dataclass
class CollectionStats:
    """What actually happened during one source's collection, measured not assumed.

    These are the numbers specification section 14.5 asks the system to monitor. They are
    produced on every run whether or not anyone is watching, because a metric computed only
    when something looks wrong is a metric nobody has a baseline for.
    """

    source_id: str
    attempted: bool = False
    http_status: int | None = None
    attempts: int = 0
    duration_seconds: float = 0.0
    bytes_downloaded: int = 0
    raw_items: int = 0
    """Entries the provider returned, before any validation."""
    parsed_items: int = 0
    """Entries that produced a usable article."""
    dropped_invalid_url: int = 0
    dropped_missing_title: int = 0
    dropped_other: int = 0
    items_with_description: int = 0
    """How many entries offered a description - the coverage measure section 4.1 requires."""
    descriptions_withheld_by_license: int = 0
    not_modified: bool = False
    """True when the server answered 304, so nothing needed parsing."""

    @property
    def description_coverage(self) -> float:
        """Share of *kept* articles that came with any description text.

        Both counters must be over the same population. Counting descriptions at parse time
        while counting items after in-payload deduplication once produced 103% for the BBC
        feed, which is how this invariant acquired its assertion-shaped docstring: the
        collectors increment ``items_with_description`` only for articles they keep.
        """
        if not self.parsed_items:
            return 0.0
        return min(self.items_with_description / self.parsed_items, 1.0)

    @property
    def drop_rate(self) -> float:
        dropped = self.dropped_invalid_url + self.dropped_missing_title + self.dropped_other
        return dropped / self.raw_items if self.raw_items else 0.0


@dataclass
class CollectionResult:
    """One source's outcome. ``error`` and a non-empty ``articles`` are mutually exclusive."""

    source_id: str
    articles: list[Article] = field(default_factory=list)
    stats: CollectionStats | None = None
    error: str | None = None
    #: Returned by the server, stored by the caller, and sent back next run as If-None-Match /
    #: If-Modified-Since. This is what makes collection incremental and cheap.
    etag: str | None = None
    last_modified: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None

    def __post_init__(self) -> None:
        if self.stats is None:
            self.stats = CollectionStats(source_id=self.source_id)


class RateLimiter:
    """A per-host minimum interval between requests.

    Deliberately simple: one timestamp per host, awaited before each request. A token bucket
    would allow bursts, and bursting at a publisher's feed is the behaviour that gets an
    aggregator blocked.
    """

    def __init__(self, min_interval_seconds: float = 1.0) -> None:
        self._min_interval = min_interval_seconds
        self._last: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, host: str) -> None:
        async with self._lock:
            now = time.monotonic()
            previous = self._last.get(host)
            if previous is not None:
                wait = self._min_interval - (now - previous)
                if wait > 0:
                    await asyncio.sleep(wait)
                    now = time.monotonic()
            self._last[host] = now


class BaseCollector(abc.ABC):
    """Common interface for every collector. Subclasses implement :meth:`parse` only."""

    #: Short name used in logs and in the collection report.
    name: str = "base"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        rate_limiter: RateLimiter | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS,
    ) -> None:
        self._client = client
        self._rate_limiter = rate_limiter or RateLimiter()
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base

    # --- Subclass contract ------------------------------------------------------------

    @abc.abstractmethod
    def parse(
        self,
        payload: bytes,
        source: NewsSource,
        discovered_at: datetime,
        stats: CollectionStats,
    ) -> list[Article]:
        """Turns one fetched payload into normalised articles, updating ``stats`` as it goes.

        Must not raise for a malformed *item*: skip it and count it in ``stats``. Raising is
        reserved for a payload that is not of the expected format at all.
        """

    def supports(self, source: NewsSource) -> bool:
        """Whether this collector can handle ``source``. Overridden by each implementation."""
        return False

    # --- Shared behaviour -------------------------------------------------------------

    async def collect(
        self,
        source: NewsSource,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> CollectionResult:
        """Fetch and parse one source. Never raises; failures come back in the result."""
        stats = CollectionStats(source_id=source.source_id, attempted=True)
        started = time.monotonic()
        discovered_at = datetime.now(UTC)

        try:
            response = await self._fetch(source.feed_url, stats, etag=etag, last_modified=last_modified)
        except Exception as exc:
            stats.duration_seconds = time.monotonic() - started
            message = self._describe(exc)
            logger.warning("collector.fetch_failed source=%s error=%s", source.source_id, message)
            return CollectionResult(source_id=source.source_id, stats=stats, error=message)

        if response.status_code == 304:
            stats.not_modified = True
            stats.duration_seconds = time.monotonic() - started
            logger.info("collector.not_modified source=%s", source.source_id)
            return CollectionResult(
                source_id=source.source_id, stats=stats,
                etag=etag, last_modified=last_modified,
            )

        try:
            articles = self.parse(response.content, source, discovered_at, stats)
        except Exception as exc:
            stats.duration_seconds = time.monotonic() - started
            message = f"parse failed: {self._describe(exc)}"
            logger.warning("collector.parse_failed source=%s error=%s", source.source_id, message)
            return CollectionResult(source_id=source.source_id, stats=stats, error=message)

        stats.parsed_items = len(articles)
        stats.duration_seconds = time.monotonic() - started
        logger.info(
            "collector.ok source=%s items=%d raw=%d duration=%.2fs",
            source.source_id, len(articles), stats.raw_items, stats.duration_seconds,
        )
        return CollectionResult(
            source_id=source.source_id,
            articles=articles,
            stats=stats,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )

    async def _fetch(
        self,
        url: str,
        stats: CollectionStats,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> httpx.Response:
        """GET with rate limiting, conditional headers, and retry with exponential backoff."""
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        host = httpx.URL(url).host
        last_error: Exception | None = None

        for attempt in range(self._max_attempts):
            stats.attempts = attempt + 1
            await self._rate_limiter.acquire(host)
            try:
                response = await self._client.get(url, headers=headers, follow_redirects=True)
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                stats.http_status = response.status_code
                stats.bytes_downloaded = len(response.content)
                if response.status_code == 304 or response.is_success:
                    return response
                if response.status_code not in RETRYABLE_STATUS:
                    raise CollectorError(
                        f"HTTP {response.status_code} {response.reason_phrase}".strip()
                    )
                last_error = CollectorError(f"HTTP {response.status_code}")

            if attempt < self._max_attempts - 1:
                # Full jitter: without it, several sources failing together retry in lockstep.
                delay = self._backoff_base * (2**attempt)
                await asyncio.sleep(delay * (0.5 + random.random() * 0.5))

        raise last_error or CollectorError("request failed with no further detail")

    @staticmethod
    def _describe(exc: Exception) -> str:
        """A log line that names the failure without dumping a stack trace into the database."""
        if isinstance(exc, httpx.TimeoutException):
            return f"timeout after waiting for {exc.request.url.host if exc.request else 'host'}"
        if isinstance(exc, httpx.ConnectError):
            return f"connection failed: {exc}"
        if isinstance(exc, CollectorError):
            return str(exc)
        return f"{type(exc).__name__}: {exc}"
