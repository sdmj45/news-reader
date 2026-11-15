"""The SQLite repository: upserts, filtering, and cursor pagination."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.article import Category, ProcessingStatus
from app.models.licensing import LicenseType
from app.models.source import SourceHealth
from app.repositories.base import ArticleQuery, ArticleRepository
from tests.conftest import make_article

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def seed(repo, count=10, **kwargs):
    articles = [
        make_article(f"Dépêche {i}", f"https://a.fr/{i}", published_at=NOW - timedelta(minutes=i),
                     **kwargs)
        for i in range(count)
    ]
    repo.upsert_articles(articles)
    return articles


class TestContract:
    def test_satisfies_the_repository_protocol(self, repo):
        assert isinstance(repo, ArticleRepository)


class TestUpsert:
    def test_insert_then_unchanged_then_updated(self, repo):
        articles = seed(repo, 3)
        assert repo.upsert_articles(articles) == type(repo.upsert_articles(articles))(
            inserted=0, updated=0, unchanged=3
        )

        articles[0].title = "Titre corrigé"
        articles[0].content_hash = "different"
        report = repo.upsert_articles(articles)
        assert (report.inserted, report.updated, report.unchanged) == (0, 1, 2)
        assert repo.get_article(articles[0].id).title == "Titre corrigé"

    def test_re_running_a_collection_does_not_duplicate(self, repo):
        seed(repo, 5)
        seed(repo, 5)
        assert repo.count_articles() == 5

    def test_round_trips_every_field(self, repo):
        article = make_article("Titre", "https://a.fr/1", published_at=NOW)
        article.secondary_categories = [Category.EUROPE, Category.POLITICS]
        article.license_status = LicenseType.CC_BY
        article.summary_reuse_allowed = True
        article.generated_summary = "Un résumé."
        article.translated_summary = {"zh": "摘要", "en": "A summary."}
        article.body_paragraphs = ["Un paragraphe."]
        article.processing_status = ProcessingStatus.TRANSLATED
        article.provenance.summary_model = "test-model"
        article.provenance.summary_generated_at = NOW
        article.event_id = "evt_1"
        repo.upsert_articles([article])

        stored = repo.get_article(article.id)
        assert stored.secondary_categories == [Category.EUROPE, Category.POLITICS]
        assert stored.license_status is LicenseType.CC_BY
        assert stored.translated_summary == {"zh": "摘要", "en": "A summary."}
        assert stored.body_paragraphs == ["Un paragraphe."]
        assert stored.processing_status is ProcessingStatus.TRANSLATED
        assert stored.provenance.summary_model == "test-model"
        assert stored.provenance.summary_generated_at == NOW
        assert stored.event_id == "evt_1"

    def test_empty_batch_is_a_no_op(self, repo):
        assert repo.upsert_articles([]).total == 0

    def test_existing_ids_handles_a_batch_larger_than_the_parameter_limit(self, repo):
        articles = seed(repo, 600)
        found = repo.existing_ids([a.id for a in articles])
        assert len(found) == 600


class TestPagination:
    def test_cursor_walks_every_article_exactly_once(self, repo):
        seed(repo, 25)
        seen, cursor = [], None
        for _ in range(10):
            page = repo.list_articles(ArticleQuery(limit=7, cursor=cursor))
            seen.extend(a.id for a in page.articles)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert len(seen) == 25 and len(set(seen)) == 25

    def test_articles_sharing_a_timestamp_are_not_skipped(self, repo):
        # The reason the cursor is (published_at, id) rather than published_at alone.
        articles = [make_article(f"T{i}", f"https://a.fr/{i}", published_at=NOW) for i in range(9)]
        repo.upsert_articles(articles)
        seen, cursor = [], None
        while True:
            page = repo.list_articles(ArticleQuery(limit=4, cursor=cursor))
            seen.extend(a.id for a in page.articles)
            cursor = page.next_cursor
            if not cursor:
                break
        assert len(set(seen)) == 9

    def test_results_are_newest_first(self, repo):
        seed(repo, 5)
        page = repo.list_articles(ArticleQuery(limit=5))
        assert [a.published_at for a in page.articles] == sorted(
            (a.published_at for a in page.articles), reverse=True
        )

    def test_last_page_has_no_cursor(self, repo):
        seed(repo, 3)
        assert repo.list_articles(ArticleQuery(limit=10)).next_cursor is None

    def test_malformed_cursor_is_rejected_clearly(self, repo):
        with pytest.raises(ValueError, match="malformed pagination cursor"):
            repo.list_articles(ArticleQuery(cursor="!!!not-base64!!!"))

    def test_limit_is_clamped(self, repo):
        seed(repo, 5)
        assert len(repo.list_articles(ArticleQuery(limit=10_000)).articles) == 5


class TestFiltering:
    def test_by_category(self, repo):
        repo.upsert_articles([
            make_article("A", "https://a.fr/1", category=Category.POLITICS),
            make_article("B", "https://a.fr/2", category=Category.SPORTS),
        ])
        page = repo.list_articles(ArticleQuery(categories=(Category.SPORTS,)))
        assert [a.title for a in page.articles] == ["B"]

    def test_by_language_and_publisher(self, repo):
        repo.upsert_articles([
            make_article("A", "https://a.fr/1", language="fr", publisher="Le Monde"),
            make_article("B", "https://b.cn/2", language="zh", publisher="德国之声"),
        ])
        assert len(repo.list_articles(ArticleQuery(languages=("zh",))).articles) == 1
        assert len(repo.list_articles(ArticleQuery(publishers=("Le Monde",))).articles) == 1

    def test_by_date_range(self, repo):
        seed(repo, 10)
        page = repo.list_articles(ArticleQuery(published_after=NOW - timedelta(minutes=4)))
        assert len(page.articles) == 5

    def test_search_matches_the_title_case_insensitively(self, repo):
        repo.upsert_articles([make_article("Grève à la SNCF", "https://a.fr/1")])
        assert len(repo.list_articles(ArticleQuery(search="grève")).articles) == 1
        assert len(repo.list_articles(ArticleQuery(search="SNCF")).articles) == 1
        assert len(repo.list_articles(ArticleQuery(search="rien")).articles) == 0

    def test_duplicates_are_excluded_by_default(self, repo):
        duplicate = make_article("Copie", "https://a.fr/2")
        duplicate.duplicate_of = "other-id"
        repo.upsert_articles([make_article("Original", "https://a.fr/1"), duplicate])
        assert len(repo.list_articles(ArticleQuery()).articles) == 1
        assert len(repo.list_articles(ArticleQuery(exclude_duplicates=False)).articles) == 2

    def test_filters_combine(self, repo):
        repo.upsert_articles([
            make_article("A", "https://a.fr/1", language="fr", category=Category.SPORTS),
            make_article("B", "https://a.fr/2", language="en", category=Category.SPORTS),
            make_article("C", "https://a.fr/3", language="fr", category=Category.POLITICS),
        ])
        page = repo.list_articles(
            ArticleQuery(languages=("fr",), categories=(Category.SPORTS,))
        )
        assert [a.title for a in page.articles] == ["A"]


class TestSourceHealth:
    def test_round_trip_and_update(self, repo):
        repo.save_source_health(SourceHealth(
            source_id="s1", consecutive_failures=2, last_error="HTTP 503",
            last_attempted_fetch=NOW, cursor="20261114183100", etag='"abc"',
        ))
        stored = repo.get_source_health("s1")
        assert stored.consecutive_failures == 2
        assert stored.cursor == "20261114183100" and stored.etag == '"abc"'

        stored.consecutive_failures = 0
        stored.last_error = None
        repo.save_source_health(stored)
        assert repo.get_source_health("s1").last_error is None

    def test_missing_source_is_none(self, repo):
        assert repo.get_source_health("nope") is None

    def test_recent_outcomes_are_capped(self, repo):
        repo.save_source_health(SourceHealth(
            source_id="s1", recent_outcomes=[f"outcome {i}" for i in range(100)]
        ))
        assert len(repo.get_source_health("s1").recent_outcomes) == 20


class TestRunLog:
    def test_runs_are_stored_newest_first(self, repo):
        for i in range(3):
            repo.save_collection_run({
                "run_id": f"r{i}", "started_at": (NOW + timedelta(minutes=i)).isoformat(),
                "articles_collected": i,
            })
        runs = repo.list_collection_runs()
        assert [r["run_id"] for r in runs] == ["r2", "r1", "r0"]


class TestSecondaryCategoryFiltering:
    """A chip shows everything tagged with its category, not only what is filed under it."""

    def _seed(self, repo):
        tagged = make_article("Xi Jinping et Macron", "https://a.fr/1", category=Category.POLITICS)
        tagged.secondary_categories = [Category.CHINA]
        filed = make_article("Pékin dévoile un plan", "https://a.fr/2", category=Category.CHINA)
        other = make_article("Grève SNCF", "https://a.fr/3", category=Category.FRANCE)
        repo.upsert_articles([tagged, filed, other])

    def test_the_filter_matches_primary_or_secondary(self, repo):
        self._seed(repo)
        found = repo.list_articles(ArticleQuery(categories=(Category.CHINA,))).articles
        assert {a.title for a in found} == {"Xi Jinping et Macron", "Pékin dévoile un plan"}

    def test_unrelated_articles_are_not_matched(self, repo):
        self._seed(repo)
        found = repo.list_articles(ArticleQuery(categories=(Category.CHINA,))).articles
        assert "Grève SNCF" not in {a.title for a in found}

    def test_counts_agree_with_what_the_chip_will_show(self, repo):
        # A count that disagreed with the list behind it would be worse than no count.
        self._seed(repo)
        counts = repo.count_by_category()
        for category, expected in counts.items():
            listed = repo.list_articles(
                ArticleQuery(categories=(Category(category),), limit=100)
            ).articles
            assert len(listed) == expected, category

    def test_several_categories_are_an_or(self, repo):
        self._seed(repo)
        found = repo.list_articles(
            ArticleQuery(categories=(Category.CHINA, Category.FRANCE))
        ).articles
        assert len(found) == 3
