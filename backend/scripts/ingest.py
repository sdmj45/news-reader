"""Runs one collection pass and prints a verification report.

    python -m scripts.ingest [--sources id,id] [--dry-run] [--json]

This is the Phase 1 deliverable's entry point and the body of the Cloud Run Job added in
Phase 5. It writes to whatever ``DATABASE_BACKEND`` points at - SQLite by default, which
needs no cloud project and costs nothing.

``--dry-run`` collects and reports without writing, for checking a new source.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from app.core.config import get_settings
from app.repositories.factory import build_repository
from app.repositories.sqlite_repository import SQLiteArticleRepository
from app.services import source_registry
from app.services.ingestion import run_ingestion


def _format(report) -> str:
    lines = [
        f"run {report.run_id}  {report.duration_seconds:.1f}s",
        "",
        f"  sources          {report.sources_succeeded}/{report.sources_attempted} succeeded"
        f"  ({report.sources_skipped} skipped, "
        f"{report.collection_success_rate:.0%} success rate)",
        f"  collected        {report.articles_collected}",
        f"  after dedup      {report.articles_after_dedup}"
        f"  (duplicate rate {report.duplicate_rate:.1%})",
        f"  written          {report.articles_inserted} new, "
        f"{report.articles_updated} updated, {report.articles_unchanged} unchanged",
        f"  events           {report.events_formed} "
        f"({report.multi_publisher_events} across publishers)",
        f"  descriptions     {report.descriptions_withheld_by_license} withheld by licence",
        "",
        "  categories       " + ", ".join(
            f"{k}={v}" for k, v in sorted(report.categories.items(), key=lambda kv: -kv[1])[:8]
        ),
        "  languages        " + ", ".join(
            f"{k}={v}" for k, v in sorted(report.languages.items(), key=lambda kv: -kv[1])[:8]
        ),
        "",
        "  per source:",
    ]
    for outcome in sorted(report.outcomes, key=lambda o: (-o.articles_collected, o.source_id)):
        if outcome.succeeded:
            detail = (
                f"{outcome.articles_collected:>5} articles  "
                f"desc {outcome.description_coverage:>4.0%}  {outcome.duration_seconds:>5.1f}s"
            )
            if outcome.not_modified:
                detail = "    not modified (304)"
        else:
            detail = f"    FAILED  {outcome.error}"
        lines.append(f"    {outcome.source_id:<26} {detail}")
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", help="Comma-separated source ids. Default: all enabled.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Collect and report without writing to the database.")
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )

    settings = get_settings()
    if args.sources:
        settings = settings.model_copy(update={"collector_only_sources": args.sources})

    repository = SQLiteArticleRepository(":memory:") if args.dry_run else build_repository(settings)

    selected = list(source_registry.active_sources())
    if settings.only_sources:
        unknown = set(settings.only_sources) - {s.source_id for s in source_registry.SOURCES}
        if unknown:
            print(f"unknown source ids: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2

    report = await run_ingestion(repository, settings, sources=selected)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(_format(report))
        if args.dry_run:
            print("\n  (dry run: nothing was written)")
        else:
            print(f"\n  database now holds {repository.count_articles()} articles")

    # A run in which every source failed is a failure, even though no exception was raised.
    return 0 if report.sources_succeeded > 0 or report.sources_attempted == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
