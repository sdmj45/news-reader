"""Deduplication and event clustering.

The two failure modes under test are opposite and both bad:

* Treating two publishers' independent coverage as one article, and deleting one of them.
* Storing the same article twice because a URL carried a campaign parameter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.processors import dedup
from app.processors.normalization import canonicalise_url
from tests.conftest import make_article

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def article(title, url, *, publisher="P", hours_ago=1, language="fr"):
    canonical = canonicalise_url(url)
    a = make_article(title, canonical, publisher=publisher, language=language,
                     published_at=NOW - timedelta(hours=hours_ago))
    a.url = url
    return a


class TestDeduplicate:
    def test_same_url_with_different_tracking_parameters_is_one_article(self):
        items = [
            article("Grève à la SNCF", "https://a.fr/greve?utm_source=twitter"),
            article("Grève à la SNCF", "https://a.fr/greve"),
        ]
        kept, report = dedup.deduplicate(items)
        assert len(kept) == 1
        assert report.duplicate_canonical_url == 1
        assert report.duplicate_rate == 0.5

    def test_identical_headlines_from_different_publishers_are_both_kept(self):
        # Wire copy guarantees this. Deleting one would discard a publisher's work.
        items = [
            article("Accord trouvé à Bruxelles", "https://a.fr/x", publisher="Le Monde"),
            article("Accord trouvé à Bruxelles", "https://b.fr/y", publisher="franceinfo"),
        ]
        kept, report = dedup.deduplicate(items)
        assert len(kept) == 2 and report.duplicate_canonical_url == 0

    def test_merge_fills_gaps_without_overwriting(self):
        first = article("A", "https://a.fr/x", hours_ago=2)
        first.image_url = None
        second = article("A", "https://a.fr/x?ref=nl", hours_ago=1)
        second.image_url = "https://a.fr/img.jpg"
        second.author = "Jane"
        kept, _ = dedup.deduplicate([first, second])
        assert len(kept) == 1
        assert kept[0].image_url == "https://a.fr/img.jpg"
        assert kept[0].author == "Jane"

    def test_merge_keeps_the_earlier_publication_time(self):
        # A feed re-stamping an article on update must not make it look newer than it is.
        early = article("A", "https://a.fr/x", hours_ago=5)
        late = article("A", "https://a.fr/x", hours_ago=1)
        kept, _ = dedup.deduplicate([late, early])
        assert kept[0].published_at == NOW - timedelta(hours=5)

    def test_empty_input(self):
        kept, report = dedup.deduplicate([])
        assert kept == [] and report.duplicate_rate == 0.0


class TestEventClustering:
    def test_same_story_from_two_publishers_is_grouped_and_both_survive(self):
        items = [
            article("Emmanuel Macron reçoit Friedrich Merz à l'Élysée",
                    "https://a.fr/1", publisher="Le Monde"),
            article("Friedrich Merz reçu par Emmanuel Macron à l'Élysée",
                    "https://b.fr/2", publisher="franceinfo"),
        ]
        clusters = dedup.cluster_events(items)
        assert len(clusters) == 1
        assert clusters[0].is_multi_publisher
        assert len(items) == 2, "clustering must never delete an article"
        assert items[0].event_id == items[1].event_id

    def test_a_shared_generic_place_name_is_not_an_event(self):
        # The failure the specification calls out: both mention France and nothing else.
        items = [
            article("La France enregistre une baisse du chômage", "https://a.fr/1"),
            article("La France accueille un sommet sur le climat", "https://b.fr/2"),
        ]
        assert dedup.cluster_events(items) == []

    def test_unrelated_headlines_are_not_grouped(self):
        items = [
            article("Grève des transports à Paris lundi", "https://a.fr/1"),
            article("Le prix du gaz augmente en janvier", "https://b.fr/2"),
            article("Nouvelle exposition au Louvre", "https://c.fr/3"),
        ]
        assert dedup.cluster_events(items) == []
        assert all(a.event_id is None for a in items)

    def test_articles_far_apart_in_time_are_not_grouped(self):
        items = [
            article("Emmanuel Macron reçoit Friedrich Merz", "https://a.fr/1", hours_ago=1),
            article("Emmanuel Macron reçoit Friedrich Merz", "https://b.fr/2", hours_ago=100),
        ]
        assert dedup.cluster_events(items) == []

    def test_entity_component_matching(self):
        # Publishers alternate between the full name and the surname.
        items = [
            article("Gadi Eisenkot quitte le gouvernement israélien", "https://a.fr/1"),
            article("Eisenkot quitte le gouvernement israélien", "https://b.fr/2"),
        ]
        assert len(dedup.cluster_events(items)) == 1

    def test_single_article_gets_no_event_id(self):
        items = [article("Une seule dépêche", "https://a.fr/1")]
        assert dedup.cluster_events(items) == []
        assert items[0].event_id is None

    def test_cross_script_articles_are_not_grouped(self):
        # Grouping across scripts needs translation, which is a later phase and a licence
        # question. Declining is the honest answer.
        items = [
            article("欧盟就人工智能法案达成协议", "https://a.cn/1", language="zh"),
            article("EU reaches agreement on the AI act", "https://b.eu/2", language="en"),
        ]
        assert dedup.cluster_events(items) == []

    def test_chinese_headlines_group_on_bigram_overlap(self):
        items = [
            article("欧盟就人工智能法案达成最终协议", "https://a.cn/1", language="zh"),
            article("欧盟就人工智能法案达成协议", "https://b.cn/2", language="zh"),
        ]
        assert len(dedup.cluster_events(items)) == 1

    def test_different_chinese_stories_are_not_grouped(self):
        items = [
            article("上海举办国际电影节开幕式", "https://a.cn/1", language="zh"),
            article("北京地铁新线路今日开通运营", "https://b.cn/2", language="zh"),
        ]
        assert dedup.cluster_events(items) == []


class TestTokenisation:
    def test_stopwords_are_removed(self):
        tokens = dedup.content_tokens("Le gouvernement de la France et les régions")
        assert "gouvernement" in tokens and "regions" in tokens
        assert "les" not in tokens and "the" not in dedup.content_tokens("the budget")

    def test_cjk_produces_bigrams(self):
        tokens = dedup.content_tokens("人工智能")
        assert tokens == frozenset({"人工", "工智", "智能"})

    def test_jaccard_of_disjoint_sets_is_zero(self):
        assert dedup.jaccard(frozenset("ab"), frozenset("cd")) == 0.0
        assert dedup.jaccard(frozenset(), frozenset("a")) == 0.0

    def test_entities_ignores_generic_capitalised_words(self):
        multi, single = dedup.entities("La France et l'Europe discutent")
        assert "France" not in single and "Europe" not in single

    def test_title_case_headline_does_not_become_all_entities(self):
        # English headlines in Title Case would otherwise yield an entity per word.
        _, single = dedup.entities("Markets Fall Again As Traders Weigh New Tariff Rules Today")
        assert single == frozenset()


class TestClusteringScale:
    def test_clustering_a_thousand_articles_stays_fast(self):
        # GDELT supplies thousands per run; the naive pairwise version is minutes, not seconds.
        import time

        items = [article(f"Dépêche numéro {i} sur un sujet distinct", f"https://a.fr/{i}")
                 for i in range(1000)]
        started = time.monotonic()
        dedup.cluster_events(items)
        assert time.monotonic() - started < 5.0
