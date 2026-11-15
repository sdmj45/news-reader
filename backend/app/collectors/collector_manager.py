"""Runs every source's collector, concurrently and independently.

The one rule this module exists to enforce is specification section 5's: *do not allow one
failed source to stop all other collectors*. Every fetch is isolated, every failure is
recorded against its own source, and the run's result is always a complete list of outcomes -
one per attempted source, successful or not.

A second rule follows from operating politely: concurrency is bounded, and a per-host rate
limiter is shared across all collectors so that six feeds from ``lemonde.fr`` do not become
six simultaneous requests to ``lemonde.fr``.

Failing sources are **backed off, not disabled**. A source that has failed repeatedly is
skipped for a while and then retried, because the common cause is a publisher's temporary
outage and a permanently disabled source needs a human to notice it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx

from app.collectors.base import (
    DEFAULT_TIMEOUT_SECONDS,
    USER_AGENT,
    BaseCollector,
    CollectionResult,
    RateLimiter,
)
from app.collectors.gdelt_collector import GDELTGALCollector, GDELTRSSCollector
from app.collectors.rss_collector import RSSCollector
from app.models.source import NewsSource, SourceHealth

logger = logging.getLogger(__name__)

#: Backoff schedule by consecutive failure count, in minutes. The last value repeats.
#:
#: Index 1 is zero on purpose: **a single failure is forgiven.** Publishers return a 503 for a
#: few seconds all the time, and the source's own ``fetch_interval_minutes`` already spaces
#: runs out, so skipping a source after one blip would turn a momentary outage into a gap of
#: several scheduled runs. Backoff starts at the second consecutive failure, which is the
#: point at which the problem looks real.
#:
#: Capped at six hours: beyond that a source is effectively dead and needs a human, not a
#: longer timer.
FAILURE_BACKOFF_MINUTES = (0, 0, 15, 60, 180, 360)


def backoff_minutes(consecutive_failures: int) -> int:
    if consecutive_failures <= 0:
        return 0
    index = min(consecutive_failures, len(FAILURE_BACKOFF_MINUTES) - 1)
    return FAILURE_BACKOFF_MINUTES[index]


class CollectorManager:
    """Owns the HTTP client, the collector instances and the concurrency budget."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_concurrency: int = 6,
        min_host_interval: float = 1.0,
        max_attempts: int = 3,
        gdelt_files_per_run: int = 2,
        gdelt_languages: frozenset[str] | None = None,
        gdelt_max_per_domain: int = 5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            # A connection pool smaller than the concurrency limit would serialise the run.
            limits=httpx.Limits(max_connections=max_concurrency * 2),
        )
        rate_limiter = RateLimiter(min_host_interval)
        shared = {"rate_limiter": rate_limiter, "max_attempts": max_attempts}
        self._collectors: list[BaseCollector] = [
            RSSCollector(self._client, **shared),
            GDELTRSSCollector(self._client, **shared),
            GDELTGALCollector(
                self._client,
                files_per_run=gdelt_files_per_run,
                languages=gdelt_languages,
                max_per_domain=gdelt_max_per_domain,
                **shared,
            ),
        ]
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def __aenter__(self) -> CollectorManager:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def collector_for(self, source: NewsSource) -> BaseCollector | None:
        return next((c for c in self._collectors if c.supports(source)), None)

    def should_skip(
        self, source: NewsSource, health: SourceHealth | None, now: datetime
    ) -> str | None:
        """Why this source is being skipped this run, or ``None`` to collect it."""
        if health is None:
            return None

        # The source's own polling interval. This field was declared on NewsSource and
        # documented from the first commit and read by nothing, which made every entry's
        # `interval=` a comment rather than a setting: a 360-minute feed and a 20-minute one
        # were both fetched on every run. It matters now that the registry carries feeds
        # publishing their whole archive - one is 12 MB - and the scheduled job runs eight
        # times a day.
        #
        # A tolerance of one minute, because a run that starts a few seconds early should
        # not push a source to the next cycle and halve its effective rate.
        if health.last_successful_fetch and source.fetch_interval_minutes:
            due_at = health.last_successful_fetch + timedelta(
                minutes=source.fetch_interval_minutes - 1
            )
            if now < due_at:
                return (
                    f"polled {source.fetch_interval_minutes} min apart; "
                    f"next due at {due_at.isoformat(timespec='minutes')}"
                )

        if health.consecutive_failures == 0:
            return None
        wait = backoff_minutes(health.consecutive_failures)
        if not wait or health.last_attempted_fetch is None:
            return None
        ready_at = health.last_attempted_fetch + timedelta(minutes=wait)
        if now < ready_at:
            return (
                f"backing off after {health.consecutive_failures} consecutive failures; "
                f"next attempt at {ready_at.isoformat()}"
            )
        return None

    async def collect_all(
        self,
        sources: list[NewsSource],
        health_by_id: dict[str, SourceHealth] | None = None,
    ) -> list[CollectionResult]:
        """Collects every source concurrently. Returns one result per source, in input order.

        A source that is backed off, or that has no collector, still gets a result - with an
        error explaining which - so the caller's report never silently omits a source.
        """
        health_by_id = health_by_id or {}
        now = datetime.now(UTC)

        async def run_one(source: NewsSource) -> CollectionResult:
            health = health_by_id.get(source.source_id)
            skip_reason = self.should_skip(source, health, now)
            if skip_reason:
                logger.info("collector.skipped source=%s reason=%s", source.source_id, skip_reason)
                return CollectionResult(source_id=source.source_id, error=f"skipped: {skip_reason}")

            collector = self.collector_for(source)
            if collector is None:
                return CollectionResult(
                    source_id=source.source_id,
                    error=f"no collector supports source_type {source.source_type.value}",
                )

            async with self._semaphore:
                # collect() is documented never to raise, but a bug there must not take the
                # whole run down with it - that is exactly the failure mode this guards.
                try:
                    # GDELT reads last_modified as its filename cursor; RSS reads it as the
                    # HTTP header. Both are "where the last run got to", so one field serves.
                    return await collector.collect(
                        source,
                        etag=health.etag if health else None,
                        last_modified=(
                            (health.cursor or health.last_modified) if health else None
                        ),
                    )
                except Exception as exc:
                    logger.exception("collector.unexpected source=%s", source.source_id)
                    return CollectionResult(
                        source_id=source.source_id,
                        error=f"unexpected {type(exc).__name__}: {exc}",
                    )

        return list(await asyncio.gather(*(run_one(s) for s in sources)))
