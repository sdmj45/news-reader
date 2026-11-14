"""The translation pass: licence gating, budgets, and what happens when the quota runs out."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core.config import Settings
from app.models.article import ProcessingStatus
from app.models.licensing import LicenseType
from app.repositories.base import ArticleQuery
from app.repositories.sqlite_repository import SQLiteArticleRepository
from app.services.translation.base import (
    TranslationBudget,
    TranslationRequest,
)
from app.services.translation.factory import build_translator
from app.services.translation.mymemory import ENDPOINT, MyMemoryTranslator
from app.services.translation.null_translator import NullTranslator
from app.services.translation.runner import run_translation
from tests.conftest import make_article


def ok_body(text: str, match: float = 0.85) -> dict:
    return {"responseData": {"translatedText": text, "match": match}, "quotaFinished": False}


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c


@pytest.fixture
def seeded():
    repository = SQLiteArticleRepository(":memory:")
    articles = []
    for i in range(4):
        article = make_article(f"Dépêche française {i}", f"https://lemonde.fr/{i}", language="fr")
        article.summary_reuse_allowed = True
        article.license_status = LicenseType.PERSONAL_USE
        articles.append(article)
    repository.upsert_articles(articles)
    yield repository
    repository.close()


class TestNullProvider:
    async def test_the_default_makes_no_request_and_produces_nothing(self, seeded):
        report = await run_translation(
            seeded, NullTranslator(), target_languages=("zh",), max_per_run=10
        )
        assert report.translated == 0 and report.failed == 0
        assert seeded.count_translated("zh") == 0

    def test_the_factory_defaults_to_a_real_provider_only_when_asked(self, client):
        assert build_translator(Settings(translator="null"), client).name == "null"
        assert build_translator(Settings(translator="mymemory"), client).name == "mymemory"

    def test_an_unknown_provider_raises_rather_than_falling_back(self, client):
        # A silent fallback is how a deployment ends up using a service nobody chose.
        with pytest.raises(RuntimeError, match="unknown TRANSLATOR"):
            build_translator(Settings(translator="deepl"), client)


class TestMyMemory:
    @respx.mock
    async def test_a_good_response_is_stored_with_provenance(self, client, seeded):
        respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=ok_body("法国新闻")))
        report = await run_translation(
            seeded, MyMemoryTranslator(client), target_languages=("zh",), max_per_run=4
        )
        assert report.translated == 4
        assert seeded.list_untranslated("zh", limit=10) == []

        article = seeded.list_articles(ArticleQuery()).articles[0]
        assert article.translated_title["zh"] == "法国新闻"
        # The publisher's headline is untouched; the translation sits beside it.
        assert article.title.startswith("Dépêche française")
        assert article.provenance.translation_model.startswith("mymemory@")
        assert article.processing_status is ProcessingStatus.TRANSLATED

    @respx.mock
    async def test_an_echoed_input_is_not_a_translation(self, client):
        # MyMemory echoes the input when it has no memory for the pair. Storing that would
        # label French text as Chinese.
        respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=ok_body("Bonjour")))
        result = await MyMemoryTranslator(client).translate(
            TranslationRequest("Bonjour", "fr", "zh")
        )
        assert result is None

    @respx.mock
    async def test_a_warning_in_the_body_is_not_a_translation(self, client):
        # MyMemory signals failure in the body with HTTP 200. Returning it would put
        # "MYMEMORY WARNING: ..." on the front page where a headline should be.
        respx.get(ENDPOINT).mock(
            return_value=httpx.Response(200, json=ok_body("MYMEMORY WARNING: INVALID LANGUAGE PAIR"))
        )
        assert await MyMemoryTranslator(client).translate(
            TranslationRequest("Bonjour le monde", "fr", "xx")
        ) is None

    @respx.mock
    async def test_a_low_confidence_match_is_refused(self, client):
        respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=ok_body("乱码", match=0.1)))
        assert await MyMemoryTranslator(client).translate(
            TranslationRequest("Une dépêche", "fr", "zh")
        ) is None

    @respx.mock
    async def test_a_network_failure_is_not_an_exception(self, client):
        respx.get(ENDPOINT).mock(side_effect=httpx.ConnectError("down"))
        assert await MyMemoryTranslator(client).translate(
            TranslationRequest("Une dépêche", "fr", "zh")
        ) is None

    def test_it_declines_pairs_it_cannot_serve(self, client):
        translator = MyMemoryTranslator(client)
        assert not translator.supports("fr", "fr")
        assert not translator.supports("und", "zh"), "guessing the source produces nonsense"
        assert translator.supports("fr", "zh")


class TestQuotaExhaustion:
    """The behaviour that matters on a free tier, found by actually running out."""

    @respx.mock
    async def test_http_429_stops_the_pass_instead_of_retrying_everything(self, client, seeded):
        route = respx.get(ENDPOINT).mock(return_value=httpx.Response(429))
        report = await run_translation(
            seeded, MyMemoryTranslator(client), target_languages=("zh",), max_per_run=4
        )
        assert report.quota_exhausted
        # The real defect this guards: eighty pointless requests to a service that already
        # said no. One article may be in flight concurrently; eighty must not be.
        assert route.call_count <= 3, f"{route.call_count} requests after a 429"
        assert report.translated == 0

    @respx.mock
    async def test_quota_finished_in_the_body_also_stops_the_pass(self, client, seeded):
        respx.get(ENDPOINT).mock(
            return_value=httpx.Response(
                200, json={"responseData": {"translatedText": "x"}, "quotaFinished": True}
            )
        )
        report = await run_translation(
            seeded, MyMemoryTranslator(client), target_languages=("zh",), max_per_run=4
        )
        assert report.quota_exhausted and report.translated == 0

    @respx.mock
    async def test_work_already_paid_for_survives_the_quota_running_out(self, client, seeded):
        responses = [
            httpx.Response(200, json=ok_body("第一条")),
            httpx.Response(429),
            httpx.Response(429),
            httpx.Response(429),
        ]
        respx.get(ENDPOINT).mock(side_effect=responses)
        report = await run_translation(
            seeded, MyMemoryTranslator(client), target_languages=("zh",), max_per_run=4,
        )
        assert report.quota_exhausted
        # Whatever got through is stored, so the next run does not pay for it again.
        assert seeded.count_translated("zh") == report.translated

    @respx.mock
    async def test_the_reason_is_reported_not_just_logged(self, client, seeded):
        respx.get(ENDPOINT).mock(return_value=httpx.Response(429))
        report = await run_translation(
            seeded, MyMemoryTranslator(client), target_languages=("zh",), max_per_run=4
        )
        assert any("TRANSLATE_CONTACT_EMAIL" in e for e in report.errors), report.errors


class TestLicenceGating:
    @respx.mock
    async def test_an_article_whose_licence_forbids_derivatives_is_never_sent(self, client):
        route = respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=ok_body("x")))
        repository = SQLiteArticleRepository(":memory:")
        article = make_article("Un titre", "https://theconversation.com/1", language="fr")
        article.summary_reuse_allowed = False
        article.license_status = LicenseType.CC_BY_ND
        repository.upsert_articles([article])

        report = await run_translation(
            repository, MyMemoryTranslator(client), target_languages=("zh",), max_per_run=10
        )
        assert route.call_count == 0, "a no-derivatives licence must not reach the provider"
        assert report.translated == 0
        repository.close()

    @respx.mock
    async def test_an_article_already_in_the_target_language_is_skipped(self, client):
        route = respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=ok_body("x")))
        repository = SQLiteArticleRepository(":memory:")
        article = make_article("中文标题", "https://dw.com/1", language="zh")
        article.summary_reuse_allowed = True
        repository.upsert_articles([article])

        await run_translation(
            repository, MyMemoryTranslator(client), target_languages=("zh",), max_per_run=10
        )
        assert route.call_count == 0
        repository.close()


class TestBudget:
    def test_a_call_budget_is_enforced_before_spending(self):
        budget = TranslationBudget(max_calls=2)
        assert budget.can_afford(10)
        budget.charge(10)
        assert budget.can_afford(10)
        budget.charge(10)
        assert not budget.can_afford(10)
        assert "call budget" in budget.exhausted_reason

    def test_a_character_budget_is_enforced_before_spending(self):
        budget = TranslationBudget(max_calls=100, max_characters=50)
        assert budget.can_afford(40)
        budget.charge(40)
        assert not budget.can_afford(40), "40 + 40 exceeds 50 and must be refused in advance"
        assert "character budget" in budget.exhausted_reason

    @respx.mock
    async def test_a_zero_budget_makes_no_request(self, client, seeded):
        route = respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=ok_body("x")))
        report = await run_translation(
            seeded, MyMemoryTranslator(client), target_languages=("zh",), max_per_run=0
        )
        assert route.call_count == 0 and report.translated == 0

    @respx.mock
    async def test_a_second_run_does_not_pay_for_the_same_headline(self, client, seeded):
        route = respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=ok_body("法国新闻")))
        await run_translation(
            seeded, MyMemoryTranslator(client), target_languages=("zh",), max_per_run=4
        )
        first = route.call_count
        await run_translation(
            seeded, MyMemoryTranslator(client), target_languages=("zh",), max_per_run=4
        )
        assert route.call_count == first, "a stored translation must never be requested again"


class TestCharacterBudget:
    """The provider's limit is in characters, so that is what has to be enforced."""

    @respx.mock
    async def test_the_run_stops_at_the_character_ceiling(self, client, seeded):
        route = respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=ok_body("标题")))
        # Each fixture headline is ~20 characters, so 50 pays for two and refuses the third.
        report = await run_translation(
            seeded, MyMemoryTranslator(client),
            target_languages=("zh",), max_per_run=4, max_characters=50,
        )
        assert report.characters_sent <= 50
        assert report.articles_skipped_budget > 0
        assert route.call_count < 4

    @respx.mock
    async def test_descriptions_are_not_translated_unless_asked(self, client):
        route = respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=ok_body("标题")))
        repository = SQLiteArticleRepository(":memory:")
        article = make_article("Un titre français", "https://lemonde.fr/1", language="fr")
        article.summary_reuse_allowed = True
        article.original_description = "Une description assez longue " * 5
        repository.upsert_articles([article])

        await run_translation(
            repository, MyMemoryTranslator(client), target_languages=("zh",), max_per_run=4
        )
        # One call, for the headline. A description is 260 characters against a headline's
        # 77, so including it by default would cut a day's quota by three quarters.
        assert route.call_count == 1
        stored = repository.list_articles(ArticleQuery()).articles[0]
        assert stored.translated_title["zh"] == "标题"
        assert stored.translated_summary == {}
        repository.close()

    @respx.mock
    async def test_descriptions_are_translated_when_asked(self, client):
        route = respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=ok_body("中文")))
        repository = SQLiteArticleRepository(":memory:")
        article = make_article("Un titre français", "https://lemonde.fr/1", language="fr")
        article.summary_reuse_allowed = True
        article.original_description = "Une description."
        repository.upsert_articles([article])

        await run_translation(
            repository, MyMemoryTranslator(client), target_languages=("zh",),
            max_per_run=4, translate_descriptions=True,
        )
        assert route.call_count == 2
        stored = repository.list_articles(ArticleQuery()).articles[0]
        assert stored.translated_summary["zh"] == "中文"
        repository.close()

    def test_the_default_budget_fits_the_free_anonymous_quota(self):
        # MyMemory allows ~5,000 characters a day anonymously. The workflow runs eight times
        # a day, so a default above ~625 per run guarantees a 429 every day.
        from app.core.config import Settings

        assert Settings().translate_max_characters_per_run <= 625
        assert Settings().translate_descriptions is False
