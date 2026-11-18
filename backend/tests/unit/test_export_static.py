"""The static snapshot: what gets published, and how it stays balanced.

The selection rule here is the whole reading experience. "The newest N" sounds neutral and
is not: it hands the page to whoever publishes most often, which on a real registry meant
every weekly source disappeared completely.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.article import Category
from app.models.licensing import LicenseType
from app.repositories.sqlite_repository import SQLiteArticleRepository
from scripts.export_static import article_json, collect
from tests.conftest import make_article

NOW = datetime.now(UTC)


def seed(repo, spec: dict[str, int], *, minutes_apart: int = 5):
    """spec maps publisher -> how many articles it published.

    Each publisher's articles are spaced by its own rate, so a prolific source genuinely
    occupies the recent end of the timeline and a weekly one genuinely sits further back -
    which is the situation the per-publisher cap exists for. Seeding each publisher as one
    contiguous block instead would make the test pass or fail on insertion order.
    """
    articles = []
    for publisher, count in spec.items():
        # 500 articles over the window means one every few minutes; 3 means one a day.
        spacing = max(1, (10 * 24 * 60) // max(count, 1))
        for i in range(count):
            articles.append(
                make_article(
                    f"{publisher} {i}",
                    f"https://{publisher.lower().replace(' ', '')}.test/{i}",
                    publisher=publisher,
                    published_at=NOW - timedelta(minutes=minutes_apart + i * spacing),
                )
            )
    repo.upsert_articles(articles)
    return articles


@pytest.fixture
def repo():
    repository = SQLiteArticleRepository(":memory:")
    yield repository
    repository.close()


class TestPerPublisherCap:
    def test_a_prolific_publisher_cannot_take_the_whole_snapshot(self, repo):
        # Enough publishers that the cap binds. When it cannot - too few publishers to
        # fill the page - the page wins; see
        # test_the_snapshot_is_filled_even_when_the_cap_would_leave_it_short.
        seed(repo, {"Chatty": 300, **{f"Quiet {n}": 6 for n in range(10)}})
        selected = collect(repo, limit=40, languages=(), max_age_days=0, max_per_publisher=5)

        counts: dict[str, int] = {}
        for article in selected:
            counts[article.publisher] = counts.get(article.publisher, 0) + 1
        assert counts["Chatty"] == 5
        assert len(counts) > 5, "the freed slots go to other publishers"

    def test_a_weekly_source_survives_a_prolific_one(self, repo):
        # The failure this exists for: across 53 real sources, "newest 400" left Google
        # DeepMind, OpenAI, LWN, the GitHub blog and MIT Technology Review with zero
        # articles each, while franceinfo took 54 slots.
        seed(repo, {"Chatty": 500, "Weekly": 3})
        selected = collect(repo, limit=50, languages=(), max_age_days=0, max_per_publisher=12)
        assert any(a.publisher == "Weekly" for a in selected)

    def test_the_cap_widens_the_time_window(self, repo):
        seed(repo, {"Chatty": 200, "Slow": 5})
        uncapped = collect(repo, limit=40, languages=(), max_age_days=0, max_per_publisher=0)
        capped = collect(repo, limit=40, languages=(), max_age_days=0, max_per_publisher=10)
        span = lambda xs: max(a.published_at for a in xs) - min(a.published_at for a in xs)  # noqa: E731
        assert span(capped) > span(uncapped)

    def test_results_stay_newest_first(self, repo):
        seed(repo, {"A": 30, "B": 30, "C": 30})
        selected = collect(repo, limit=40, languages=(), max_age_days=0, max_per_publisher=10)
        times = [a.published_at for a in selected]
        assert times == sorted(times, reverse=True)

    def test_the_snapshot_is_filled_even_when_the_cap_would_leave_it_short(self, repo):
        # Two publishers, cap of 5, asking for 20: capping alone yields 10, and publishing
        # a half-empty page because of an internal rule would be the wrong trade.
        seed(repo, {"A": 50, "B": 50})
        assert len(collect(repo, limit=20, languages=(), max_age_days=0, max_per_publisher=5)) == 20

    def test_zero_disables_the_cap(self, repo):
        seed(repo, {"Chatty": 300, **{f"Quiet {n}": 6 for n in range(10)}})
        uncapped = collect(repo, limit=40, languages=(), max_age_days=0, max_per_publisher=0)
        capped = collect(repo, limit=40, languages=(), max_age_days=0, max_per_publisher=5)

        chatty = lambda xs: sum(1 for a in xs if a.publisher == "Chatty")  # noqa: E731
        assert chatty(uncapped) > chatty(capped)
        assert chatty(uncapped) > 20, "without a cap the prolific source dominates"

    def test_asking_for_more_than_exists_returns_what_exists(self, repo):
        seed(repo, {"A": 3, "B": 2})
        assert len(collect(repo, limit=100, languages=(), max_age_days=0, max_per_publisher=12)) == 5


class TestAgeWindow:
    def test_articles_older_than_the_window_are_dropped(self, repo):
        old = make_article("Ancienne dépêche", "https://a.test/old",
                           published_at=NOW - timedelta(days=30))
        new = make_article("Dépêche du jour", "https://a.test/new", published_at=NOW)
        repo.upsert_articles([old, new])
        selected = collect(repo, limit=50, languages=())
        assert [a.title for a in selected] == ["Dépêche du jour"]


class TestPayloadShape:
    def test_empty_and_null_fields_are_omitted(self, repo):
        article = make_article("Titre", "https://a.test/1")
        payload = article_json(article)
        # Across 400 articles the absent keys are a third of the payload.
        assert "author" not in payload and "image_url" not in payload
        assert "translation" not in payload
        assert payload["title"] == "Titre"

    def test_a_long_description_is_cut_on_a_word_boundary(self, repo):
        article = make_article("Titre", "https://a.test/1")
        article.license_status = LicenseType.CC_BY
        article.original_description = "mot " * 200
        payload = article_json(article, max_description=50)
        assert len(payload["description"]) <= 51
        assert payload["description"].endswith("…")

    def test_translations_travel_in_their_own_object(self, repo):
        article = make_article("Titre français", "https://a.test/1")
        article.translated_title = {"zh": "法语标题"}
        payload = article_json(article)
        # The publisher's words and the machine's must not share a field on the wire either.
        assert payload["title"] == "Titre français"
        assert payload["translation"]["title"]["zh"] == "法语标题"

    def test_categories_are_carried_for_the_browser_to_filter_on(self, repo):
        article = make_article("Titre", "https://a.test/1", category=Category.TECHNOLOGY)
        article.secondary_categories = [Category.CHINA]
        payload = article_json(article)
        assert payload["category"] == "TECHNOLOGY"
        assert payload["secondary_categories"] == ["CHINA"]


class TestRetentionWindow:
    def test_the_default_window_is_two_days(self, repo):
        repo.upsert_articles([
            make_article("Avant-hier et plus", "https://a.test/3d",
                         published_at=NOW - timedelta(days=3)),
            make_article("Hier", "https://a.test/1d", published_at=NOW - timedelta(days=1)),
        ])
        assert [a.title for a in collect(repo, limit=50, languages=())] == ["Hier"]

    def test_zero_means_no_age_limit(self, repo):
        repo.upsert_articles([make_article("Ancienne", "https://a.test/old",
                                           published_at=NOW - timedelta(days=30))])
        assert len(collect(repo, limit=50, languages=(), max_age_days=0)) == 1


class TestPolicyOutsideTheCap:
    def test_a_policy_article_survives_a_crowded_publisher(self, repo):
        # Le Monde's money desk shares one cap with every other Le Monde section.
        crowd = [make_article(f"Une {i}", f"https://lemonde.test/{i}", publisher="Le Monde",
                              published_at=NOW - timedelta(minutes=i)) for i in range(5)]
        policy = make_article("Le SMIC augmentera au 1er janvier", "https://lemonde.test/smic",
                              publisher="Le Monde", published_at=NOW - timedelta(hours=10))
        policy.secondary_categories = [Category.FRANCE_POLICY]
        repo.upsert_articles([*crowd, policy])

        selected = collect(repo, limit=50, languages=(), max_per_publisher=3)
        assert "Le SMIC augmentera au 1er janvier" in [a.title for a in selected]

    def test_policy_articles_are_kept_when_the_limit_binds(self, repo):
        recent = [make_article(f"Flash {i}", f"https://a.test/{i}", publisher=f"P{i}",
                               published_at=NOW - timedelta(minutes=i)) for i in range(5)]
        policy = make_article("Titre de séjour : nouvelles règles", "https://b.test/p",
                              publisher="P0", published_at=NOW - timedelta(hours=20))
        policy.secondary_categories = [Category.FRANCE_POLICY]
        repo.upsert_articles([*recent, policy])

        selected = collect(repo, limit=3, languages=(), max_per_publisher=1)
        assert len(selected) == 3
        assert "Titre de séjour : nouvelles règles" in [a.title for a in selected]
