"""Runs one translation pass and prints what it did.

    python -m scripts.translate [--limit N] [--language zh] [--json]

Separate from ``scripts.ingest`` on purpose: collection is fast and free, translation is slow
and rationed, and a quota exhaustion must never cost an article.

Requires ``PERSONAL_USE_MODE=true`` for most sources — a translation is a derivative work and
27 of the registry's publishers have granted no such permission. See docs/COPYRIGHT_POLICY.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

import httpx

from app.core.config import get_settings
from app.repositories.factory import build_repository
from app.services.translation.factory import build_translator
from app.services.translation.runner import run_translation


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Articles per language. Overrides settings.")
    parser.add_argument("--language", help="Single target language. Overrides settings.")
    parser.add_argument("--max-characters", type=int,
                        help="Character ceiling for this run. Overrides settings.")
    parser.add_argument("--descriptions", action="store_true",
                        help="Also translate descriptions. Costs ~4x the quota per article.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )

    settings = get_settings()
    targets = (args.language,) if args.language else settings.target_languages
    limit = args.limit if args.limit is not None else settings.translate_max_per_run
    repository = build_repository(settings)

    async with httpx.AsyncClient() as client:
        translator = build_translator(settings, client)
        report = await run_translation(
            repository, translator,
            target_languages=targets,
            max_per_run=limit,
            max_characters=(
                args.max_characters if args.max_characters is not None
                else settings.translate_max_characters_per_run
            ),
            translate_descriptions=args.descriptions or settings.translate_descriptions,
            published_after=settings.retention_cutoff(),
        )

    if args.json:
        print(json.dumps(report.__dict__, indent=2, ensure_ascii=False))
        return 0

    print(f"provider          {report.provider}")
    print(f"considered        {report.articles_considered}")
    print(f"translated        {report.translated}")
    print(f"failed            {report.failed}  (success rate {report.success_rate:.0%})")
    budget = (args.max_characters if args.max_characters is not None
              else settings.translate_max_characters_per_run)
    print(f"characters sent   {report.characters_sent} of {budget or 'unlimited'} allowed this run")
    print("skipped:")
    print(f"  licence         {report.articles_skipped_license}")
    print(f"  already done    {report.articles_skipped_already_done}")
    print(f"  budget          {report.articles_skipped_budget}")
    print(f"  same language   {report.articles_skipped_same_language}")
    for error in report.errors[:10]:
        print(f"  ! {error}")
    for language in targets:
        print(f"\ntotal with a {language} headline: {repository.count_translated(language)}")

    if report.quota_exhausted:
        print("\n  The provider's daily allowance ran out and the pass stopped early.")
        print("  Everything translated before that point is stored and will not be redone.")
        print("  Set TRANSLATE_CONTACT_EMAIL in backend/.env to raise MyMemory's free")
        print("  allowance from about 5,000 to about 50,000 characters a day.")
    if report.provider == "null":
        print("\n  TRANSLATOR=null: nothing was translated and nothing was requested.")
    if report.articles_skipped_license and not report.translated:
        print("\n  Everything was skipped on licence grounds. Set PERSONAL_USE_MODE=true in")
        print("  backend/.env if this instance serves one private household; see")
        print("  docs/COPYRIGHT_POLICY.md for what that assertion means.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
