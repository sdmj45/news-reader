"""One collection run: fetch, normalise, deduplicate, classify, cluster, persist.

The stage order is not arbitrary:

1. **Collect** every source concurrently and independently (:mod:`app.collectors.collector_manager`).
2. **Deduplicate within the run**, before any write. Two feeds from the same publisher
   routinely carry the same article, and GDELT overlaps with everything; collapsing them here
   means one write instead of several and makes the "new articles" figure honest.
3. **Classify**, which is local keyword work and costs nothing.
4. **Cluster** into events. After deduplication, so that genuine duplicates are not mistaken
   for independent coverage of one story.
5. **Persist**, as an upsert keyed on article id, so a re-run updates rather than duplicating
   and a crashed run can simply be run again.
6. **Record health**, per source, including the failures - which is what makes the backoff in
   the manager work on the next run.

Two guarantees this module is responsible for:

* **No fabricated data.** A source that fails contributes zero articles and one recorded
  error. There is no cache fallback, no sample data and no placeholder article anywhere.
* **No licence violation by accident.** The parser already withheld descriptions it had no
  right to keep; :func:`_enforce_license` checks again before the write, against the registry
  rather than against whatever the article object claims. A field can only survive if two
  independent checks agree.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from app.collectors.base import CollectionResult
from app.collectors.collector_manager import CollectorManager
from app.core.config import Settings
from app.models.article import Article, Category, ProcessingStatus
from app.models.licensing import allows_description_display, allows_summary_publication
from app.models.source import NewsSource, SourceHealth
from app.processors import classifier, dedup
from app.repositories.base import ArticleRepository
from app.services import source_registry

logger = logging.getLogger(__name__)


@dataclass
class SourceOutcome:
    """One source's contribution to the run, successful or not."""

    source_id: str
    succeeded: bool
    articles_collected: int = 0
    error: str | None = None
    http_status: int | None = None
    duration_seconds: float = 0.0
    raw_items: int = 0
    description_coverage: float = 0.0
    descriptions_withheld: int = 0
    not_modified: bool = False


@dataclass
class IngestionReport:
    """The measurable outcome of a run - specification section 14.5's metric list.

    Serialised straight into the ``collection_runs`` log, so every number a later optimisation
    might want is captured at the time rather than reconstructed afterwards.
    """

    run_id: str
    started_at: str
    finished_at: str = ""
    duration_seconds: float = 0.0
    sources_attempted: int = 0
    sources_succeeded: int = 0
    sources_skipped: int = 0
    articles_collected: int = 0
    articles_after_dedup: int = 0
    articles_inserted: int = 0
    articles_updated: int = 0
    articles_unchanged: int = 0
    duplicate_rate: float = 0.0
    events_formed: int = 0
    multi_publisher_events: int = 0
    descriptions_withheld_by_license: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    languages: dict[str, int] = field(default_factory=dict)
    outcomes: list[SourceOutcome] = field(default_factory=list)

    @property
    def collection_success_rate(self) -> float:
        attempted = self.sources_attempted - self.sources_skipped
        return self.sources_succeeded / attempted if attempted else 0.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["collection_success_rate"] = round(self.collection_success_rate, 4)
        return data


def _enforce_license(article: Article, source: NewsSource) -> Article:
    """Second, independent licence check, made against the registry rather than the article.

    The parser already applied the rule. This exists because the parser takes its answer from
    the ``NewsSource`` it was handed, and a bug - or a future collector - could hand it the
    wrong one. Two checks against the same registry entry is cheap; publishing text the
    project has no right to publish is not.
    """
    if article.original_description and not allows_description_display(source.license_type):
        article.original_description = None
        article.description_withheld_reason = (
            f"Withheld at persistence: source licence is {source.license_type.value}."
        )
    article.license_status = source.license_type
    article.summary_reuse_allowed = allows_summary_publication(source.license_type)
    if not article.summary_reuse_allowed:
        article.processing_status = ProcessingStatus.SUMMARY_SKIPPED_LICENSE
    if article.body_paragraphs and source.license_type.value in ("UNKNOWN", "METADATA_ONLY",
                                                                 "FEED_EXCERPT"):
        article.body_paragraphs = []
    return article


async def run_ingestion(
    repository: ArticleRepository,
    settings: Settings,
    *,
    sources: list[NewsSource] | None = None,
    manager: CollectorManager | None = None,
) -> IngestionReport:
    """Executes one full collection run and returns its measured report."""
    started = datetime.now(UTC)
    report = IngestionReport(run_id=uuid.uuid4().hex[:16], started_at=started.isoformat())

    selected = list(sources if sources is not None else source_registry.active_sources())
    if settings.only_sources:
        wanted = set(settings.only_sources)
        selected = [s for s in selected if s.source_id in wanted]
    report.sources_attempted = len(selected)
    if not selected:
        report.finished_at = datetime.now(UTC).isoformat()
        return report

    health_by_id = {h.source_id: h for h in repository.list_source_health()}

    owns_manager = manager is None
    manager = manager or CollectorManager(
        timeout=settings.collector_timeout_seconds,
        max_concurrency=settings.collector_max_concurrency,
        min_host_interval=settings.collector_min_host_interval,
        max_attempts=settings.collector_max_attempts,
        gdelt_files_per_run=settings.gdelt_files_per_run,
    )
    try:
        results = await manager.collect_all(selected, health_by_id)
    finally:
        if owns_manager:
            await manager.aclose()

    sources_by_id = {s.source_id: s for s in selected}
    collected: list[Article] = []

    for result in results:
        source = sources_by_id[result.source_id]
        outcome = _record(result, source, repository, health_by_id)
        report.outcomes.append(outcome)
        if outcome.not_modified:
            report.sources_succeeded += 1
            continue
        if result.error and result.error.startswith("skipped:"):
            report.sources_skipped += 1
            continue
        if not result.succeeded:
            continue
        report.sources_succeeded += 1
        report.descriptions_withheld_by_license += outcome.descriptions_withheld
        for article in result.articles:
            collected.append(_enforce_license(article, source))

    report.articles_collected = len(collected)

    unique, dedup_report = dedup.deduplicate(collected)
    report.articles_after_dedup = len(unique)
    report.duplicate_rate = round(dedup_report.duplicate_rate, 4)

    for article in unique:
        source = sources_by_id[article.source_id]
        default = Category(source.default_category) if source.default_category else None
        classifier.classify(article, default)
        if article.processing_status is ProcessingStatus.COLLECTED:
            article.processing_status = ProcessingStatus.CLASSIFIED

    clusters = dedup.cluster_events(unique)
    report.events_formed = len(clusters)
    report.multi_publisher_events = sum(1 for c in clusters if c.is_multi_publisher)

    upsert = repository.upsert_articles(unique)
    report.articles_inserted = upsert.inserted
    report.articles_updated = upsert.updated
    report.articles_unchanged = upsert.unchanged

    for article in unique:
        report.categories[article.category.value] = report.categories.get(article.category.value, 0) + 1
        report.languages[article.language] = report.languages.get(article.language, 0) + 1

    finished = datetime.now(UTC)
    report.finished_at = finished.isoformat()
    report.duration_seconds = round((finished - started).total_seconds(), 2)

    repository.save_collection_run(report.to_dict())
    logger.info(
        "ingestion.done run=%s sources=%d/%d articles=%d new=%d duplicates=%.1f%% in %.1fs",
        report.run_id, report.sources_succeeded, report.sources_attempted,
        report.articles_after_dedup, report.articles_inserted,
        report.duplicate_rate * 100, report.duration_seconds,
    )
    return report


def _record(
    result: CollectionResult,
    source: NewsSource,
    repository: ArticleRepository,
    health_by_id: dict[str, SourceHealth],
) -> SourceOutcome:
    """Updates the source's persisted health from one result and summarises it for the report."""
    stats = result.stats
    now = datetime.now(UTC)
    health = health_by_id.get(source.source_id) or SourceHealth(
        source_id=source.source_id, created_at=now
    )

    skipped = bool(result.error and result.error.startswith("skipped:"))
    if not skipped:
        health.last_attempted_fetch = now

    if result.succeeded:
        health.last_successful_fetch = now
        health.last_error = None
        health.consecutive_failures = 0
        health.total_items_collected += len(result.articles)
        health.etag = result.etag
        health.last_modified = result.last_modified
        # GDELT returns a filename stamp here rather than an HTTP date; keeping it in `cursor`
        # as well means the manager can read one field without knowing which kind it is.
        if result.last_modified and result.last_modified.isdigit():
            health.cursor = result.last_modified
        health.recent_outcomes.insert(0, f"{now.isoformat()} ok {len(result.articles)}")
    elif not skipped:
        health.last_error = result.error
        health.consecutive_failures += 1
        health.recent_outcomes.insert(0, f"{now.isoformat()} error {result.error}")

    health.recent_outcomes = health.recent_outcomes[:20]
    if not skipped:
        repository.save_source_health(health)
        health_by_id[source.source_id] = health

    return SourceOutcome(
        source_id=source.source_id,
        succeeded=result.succeeded,
        articles_collected=len(result.articles),
        error=result.error,
        http_status=stats.http_status if stats else None,
        duration_seconds=round(stats.duration_seconds, 2) if stats else 0.0,
        raw_items=stats.raw_items if stats else 0,
        description_coverage=round(stats.description_coverage, 4) if stats else 0.0,
        descriptions_withheld=stats.descriptions_withheld_by_license if stats else 0,
        not_modified=bool(stats and stats.not_modified),
    )
