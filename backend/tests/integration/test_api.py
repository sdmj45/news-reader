"""The REST API, against a real in-memory repository.

No HTTP mocking and no database stub: the app is built with its real dependency graph and a
repository seeded with real-shaped articles, because the bugs this layer produces are
integration bugs. The thread-safety defect that `test_the_api_serves_from_a_worker_thread`
guards against did not show up in any unit test and broke every endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core.config import Settings
from app.main import app
from app.models.article import Category
from app.repositories.sqlite_repository import SQLiteArticleRepository
from tests.conftest import make_article

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def seeded() -> SQLiteArticleRepository:
    repository = SQLiteArticleRepository(":memory:")
    articles = []
    for i in range(12):
        article = make_article(
            f"Dépêche française numéro {i}",
            f"https://lemonde.fr/a{i}",
            publisher="Le Monde" if i % 2 else "franceinfo",
            language="fr",
            published_at=NOW - timedelta(minutes=i),
            category=Category.FRANCE if i % 2 else Category.POLITICS,
        )
        if i < 4:
            article.translated_title = {"zh": f"法国新闻第{i}号"}
            article.provenance.translation_model = "mymemory@2026-11-14"
        articles.append(article)
    articles.append(
        make_article("An English headline", "https://bbc.co.uk/1",
                     publisher="BBC News", language="en", published_at=NOW,
                     category=Category.INTERNATIONAL)
    )
    repository.upsert_articles(articles)
    repository.save_collection_run(
        {"run_id": "r1", "started_at": NOW.isoformat(), "articles_collected": 13}
    )
    yield repository
    repository.close()


@pytest.fixture
def client(seeded, monkeypatch) -> TestClient:
    app.dependency_overrides[deps.get_repository] = lambda: seeded
    app.dependency_overrides[deps.settings_dep] = lambda: Settings(
        personal_use_mode=True, translator="mymemory", api_rate_limit_per_minute=0
    )
    # The rate limiter is a process singleton; disable it so one test's requests do not
    # exhaust another's budget.
    monkeypatch.setattr(deps, "rate_limit", lambda: None)
    app.dependency_overrides[deps.rate_limit] = lambda: None
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestHealth:
    def test_reports_real_state(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["articles"] == 13
        assert body["personal_use_mode"] is True
        assert body["last_collection"] is not None

    def test_the_api_serves_from_a_worker_thread(self, client):
        # TestClient runs the app on its own thread. A repository holding a single SQLite
        # connection raises ProgrammingError here and nowhere else.
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/articles").status_code == 200


class TestArticles:
    def test_returns_newest_first(self, client):
        articles = client.get("/api/v1/articles").json()["articles"]
        times = [a["published_at"] for a in articles]
        assert times == sorted(times, reverse=True)

    def test_cursor_walks_the_whole_set_once(self, client):
        seen, cursor = [], None
        while True:
            params = {"limit": 5, **({"cursor": cursor} if cursor else {})}
            page = client.get("/api/v1/articles", params=params).json()
            seen.extend(a["id"] for a in page["articles"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        assert len(seen) == 13 and len(set(seen)) == 13

    def test_filters_by_language(self, client):
        body = client.get("/api/v1/articles", params={"language": "en"}).json()
        assert [a["publisher"] for a in body["articles"]] == ["BBC News"]

    def test_filters_by_category(self, client):
        body = client.get("/api/v1/articles", params={"category": "POLITICS"}).json()
        assert body["articles"] and all(a["category"] == "POLITICS" for a in body["articles"])

    def test_repeatable_filters_are_an_or(self, client):
        body = client.get(
            "/api/v1/articles", params=[("category", "POLITICS"), ("category", "FRANCE")]
        ).json()
        assert len(body["articles"]) == 12

    def test_search_matches_the_headline(self, client):
        body = client.get("/api/v1/articles", params={"q": "numéro 3"}).json()
        assert len(body["articles"]) == 1

    def test_one_article_by_id(self, client):
        listed = client.get("/api/v1/articles").json()["articles"][0]
        fetched = client.get(f"/api/v1/articles/{listed['id']}").json()
        assert fetched["id"] == listed["id"] and fetched["title"] == listed["title"]

    def test_categories_endpoint_counts_only_non_empty(self, client):
        counts = {c["category"]: c["count"] for c in
                  client.get("/api/v1/articles/categories").json()}
        assert counts["FRANCE"] == 6 and counts["INTERNATIONAL"] == 1
        assert all(n > 0 for n in counts.values())

    def test_categories_can_be_scoped_to_a_language(self, client):
        counts = {c["category"]: c["count"] for c in
                  client.get("/api/v1/articles/categories", params={"language": "fr"}).json()}
        assert "INTERNATIONAL" not in counts


class TestTranslationIsLabelled:
    def test_translation_lives_in_its_own_object(self, client):
        article = next(a for a in client.get("/api/v1/articles").json()["articles"]
                       if a["translation"]["title"])
        # The publisher's headline and the machine's must never occupy the same field.
        assert article["title"] != article["translation"]["title"]["zh"]
        assert article["translation"]["provider"] == "mymemory@2026-11-14"

    def test_an_untranslated_article_says_so_by_omission_not_by_echoing_french(self, client):
        articles = client.get("/api/v1/articles").json()["articles"]
        untranslated = [a for a in articles if not a["translation"]["title"]]
        assert untranslated
        assert all(a["translation"]["title"] == {} for a in untranslated)


class TestErrors:
    def test_unknown_category_is_422_and_lists_the_valid_ones(self, client):
        response = client.get("/api/v1/articles", params={"category": "NOPE"})
        assert response.status_code == 422
        assert "POLITICS" in response.json()["detail"]

    def test_missing_article_is_404(self, client):
        assert client.get("/api/v1/articles/nope").status_code == 404

    def test_malformed_cursor_is_422_not_500(self, client):
        assert client.get("/api/v1/articles", params={"cursor": "zzz"}).status_code == 422

    def test_oversized_limit_is_rejected(self, client):
        assert client.get("/api/v1/articles", params={"limit": 9999}).status_code == 422

    def test_limit_zero_is_rejected(self, client):
        assert client.get("/api/v1/articles", params={"limit": 0}).status_code == 422


class TestMeta:
    def test_sources_carry_licence_and_translatability(self, client):
        sources = client.get("/api/v1/sources").json()
        assert sources
        gdelt = [s for s in sources if "gdelt" in s["source_id"]]
        assert not gdelt, "GDELT is disabled by default"
        assert any(s["license"] == "CC_BY" for s in sources)
        assert all("translation_permitted" in s for s in sources)

    def test_stats_report_the_unflattering_numbers_too(self, client):
        body = client.get("/api/v1/stats").json()
        assert body["articles_total"] == 13
        assert body["articles_by_language"]["fr"] == 12
        assert body["translated_counts"]["zh"] == 4
        assert body["recent_runs"][0]["run_id"] == "r1"


class TestWriteSurface:
    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_the_api_is_read_only(self, client, method):
        # Nothing a browser can reach writes. This is what lets the API be unauthenticated.
        response = getattr(client, method)("/api/v1/articles")
        assert response.status_code == 405
