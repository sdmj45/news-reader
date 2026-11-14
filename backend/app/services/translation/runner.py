"""The translation pass.

Deliberately a **separate pass over stored articles**, not a stage of collection. Three
reasons, all of which came out of how the collector actually behaves:

* Collection is fast (30 seconds for 4,400 articles) and free. Translation is slow and
  rationed. Coupling them would make every collection run as slow as the slowest quota.
* A quota exhaustion must never cost an article. If translation fails, the news is still
  collected and still readable in French.
* Specification section 8 requires the enrichment engine to be independent of the collector.

What it translates: **the headline**, into each configured target language, and the
publisher's description where one was legally stored. The headline is the point - this is a
French news reader for a Chinese-speaking household - and it is also short, which matters when
the free tier allows roughly 5,000 characters a day.

What it never does:

* Translate when the effective licence forbids derivative works. A translation is a derivative
  work; see :mod:`app.models.rights`.
* Translate the same article twice. Results are stored permanently, so a headline costs its
  characters once in the product's lifetime.
* Overwrite a publisher's words. Translations live in ``translated_title`` and
  ``translated_summary``, never in ``title``.
* Exceed its budget. The budget is checked *before* each call, by this runner, so a provider
  cannot spend past it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.models.article import Article, ProcessingStatus
from app.models.licensing import LicenseType, allows_summary_publication
from app.repositories.base import ArticleRepository
from app.services.translation.base import (
    TranslationBudget,
    TranslationReport,
    TranslationRequest,
    Translator,
)

logger = logging.getLogger(__name__)

#: Concurrent provider requests. One at a time would be slow; many at once is how a free
#: service decides you are abusing it. Three is polite and fast enough for a 60-item budget.
MAX_CONCURRENT_TRANSLATIONS = 3


async def translate_article(
    article: Article,
    translator: Translator,
    target_language: str,
    budget: TranslationBudget,
    report: TranslationReport,
) -> bool:
    """Translates one article's headline, and its description when one is stored.

    Returns True when the headline was translated. The description is best-effort: a reader
    with a Chinese headline and a French standfirst is better served than one with neither,
    so a failed description does not fail the article.
    """
    if article.language == target_language:
        report.articles_skipped_same_language += 1
        return False
    if target_language in article.translated_title:
        report.articles_skipped_already_done += 1
        return False
    if not article.summary_reuse_allowed:
        report.articles_skipped_license += 1
        article.processing_status = ProcessingStatus.TRANSLATION_SKIPPED_LICENSE
        return False

    if not budget.can_afford(len(article.title)):
        report.articles_skipped_budget += 1
        return False

    budget.charge(len(article.title))
    report.characters_sent += len(article.title)
    result = await translator.translate(
        TranslationRequest(article.title, article.language, target_language)
    )
    if result is None:
        report.failed += 1
        article.processing_status = ProcessingStatus.TRANSLATION_FAILED
        return False

    article.translated_title[target_language] = result.text
    article.provenance.translation_model = f"{result.provider}@{result.provider_version}"
    article.provenance.translation_prompt_version = "headline-v1"
    article.provenance.translation_generated_at = datetime.now(UTC)
    article.processing_status = ProcessingStatus.TRANSLATED
    report.translated += 1

    description = article.original_description
    if description and budget.can_afford(len(description)):
        budget.charge(len(description))
        report.characters_sent += len(description)
        summary = await translator.translate(
            TranslationRequest(description, article.language, target_language)
        )
        if summary is not None:
            article.translated_summary[target_language] = summary.text

    return True


async def run_translation(
    repository: ArticleRepository,
    translator: Translator,
    *,
    target_languages: tuple[str, ...],
    max_per_run: int,
    max_characters: int = 0,
) -> TranslationReport:
    """One translation pass over the newest articles that still need one."""
    report = TranslationReport(provider=translator.name)
    if max_per_run <= 0 or translator.name == "null":
        logger.info("translation.disabled provider=%s budget=%d", translator.name, max_per_run)
        return report

    budget = TranslationBudget(max_calls=max_per_run * 2, max_characters=max_characters)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TRANSLATIONS)

    for target in target_languages:
        pending = repository.list_untranslated(target, limit=max_per_run)
        report.articles_considered += len(pending)
        if not pending:
            continue

        async def one(article: Article, target: str = target) -> None:
            async with semaphore:
                try:
                    await translate_article(article, translator, target, budget, report)
                except Exception as exc:
                    logger.exception("translation.unexpected article=%s", article.id)
                    report.errors.append(f"{article.id}: {type(exc).__name__}: {exc}")
                    report.failed += 1

        await asyncio.gather(*(one(a) for a in pending))
        # Written once per language rather than once per article: the pass is rationed to a
        # few dozen records, and one batched write is cheaper than sixty.
        repository.upsert_articles(pending)

    if budget.exhausted_reason:
        report.errors.append(f"budget stopped the pass: {budget.exhausted_reason}")

    logger.info(
        "translation.done provider=%s translated=%d failed=%d chars=%d",
        translator.name, report.translated, report.failed, report.characters_sent,
    )
    return report


def mark_untranslatable(article: Article) -> Article:
    """Records *why* an article has no translation, so absence is never ambiguous."""
    if not allows_summary_publication(article.license_status):
        article.processing_status = ProcessingStatus.TRANSLATION_SKIPPED_LICENSE
    elif article.license_status is LicenseType.UNKNOWN:
        article.processing_status = ProcessingStatus.SUMMARY_SKIPPED_LICENSE
    return article
