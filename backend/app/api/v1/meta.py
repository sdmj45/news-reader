"""Health, sources and statistics.

These exist so that "is it working?" has an answer that is not "look at the logs". The stats
endpoint deliberately reports the unflattering numbers too - how many articles have no
translation, which sources last failed - because a dashboard that only shows successes is a
dashboard nobody checks.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_repository, rate_limit, settings_dep
from app.api.schemas import HealthOut, SourceOut, StatsOut
from app.core.config import Settings
from app.repositories.base import ArticleRepository
from app.services import source_registry

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthOut, summary="Liveness and basic state")
async def health(
    repository: Annotated[ArticleRepository, Depends(get_repository)],
    settings: Annotated[Settings, Depends(settings_dep)],
) -> HealthOut:
    runs = repository.list_collection_runs(limit=1)
    return HealthOut(
        status="ok",
        articles=repository.count_articles(),
        sources_enabled=len(source_registry.active_sources()),
        last_collection=runs[0]["started_at"] if runs else None,
        personal_use_mode=settings.personal_use_mode,
        translator=settings.translator,
    )


@router.get("/sources", response_model=list[SourceOut], summary="Configured sources")
async def list_sources(
    _: Annotated[None, Depends(rate_limit)],
    enabled_only: bool = True,
) -> list[SourceOut]:
    """The registry, as the frontend needs it: enough to filter by and to attribute with.

    Licence and ``translation_permitted`` are included because the interface shows them. A
    reader who sees a French headline and no Chinese one is owed the reason.
    """
    sources = source_registry.active_sources() if enabled_only else source_registry.SOURCES
    return [SourceOut.of(s) for s in sources]


@router.get("/stats", response_model=StatsOut, summary="What the last runs measured")
async def stats(
    repository: Annotated[ArticleRepository, Depends(get_repository)],
    settings: Annotated[Settings, Depends(settings_dep)],
    _: Annotated[None, Depends(rate_limit)] = None,
) -> StatsOut:
    return StatsOut(
        articles_total=repository.count_articles(),
        articles_by_language=repository.count_by_language(),
        articles_by_category=repository.count_by_category(),
        translated_counts={
            language: repository.count_translated(language)
            for language in settings.target_languages
        },
        publishers=len(repository.distinct_publishers()),
        recent_runs=[
            {
                key: run.get(key)
                for key in (
                    "run_id", "started_at", "duration_seconds", "sources_attempted",
                    "sources_succeeded", "articles_collected", "articles_inserted",
                    "duplicate_rate", "collection_success_rate",
                )
            }
            for run in repository.list_collection_runs(limit=10)
        ],
    )
