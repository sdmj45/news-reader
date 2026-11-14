"""RSS and Atom parsing, against real captured feeds."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.collectors.base import CollectionStats, CollectorError
from app.collectors.rss_collector import RSSCollector
from app.models.article import Category
from app.models.licensing import LicenseType
from tests.conftest import make_source

NOW = datetime(2026, 11, 14, 19, 0, tzinfo=UTC)


@pytest.fixture
def collector():
    # The parser never touches the client, so None is honest about what is under test.
    return RSSCollector(client=None)


def parse(collector, payload, source):
    stats = CollectionStats(source_id=source.source_id)
    return collector.parse(payload, source, NOW, stats), stats


class TestRealFeeds:
    def test_lemonde_front_page(self, collector, fixtures):
        source = make_source("lemonde-une", category=Category.FRANCE)
        articles, stats = parse(collector, (fixtures / "lemonde_une.xml").read_bytes(), source)

        assert len(articles) == 16
        assert stats.raw_items == 16
        assert all(a.canonical_url.startswith("https://") for a in articles)
        assert all(a.title for a in articles)
        assert all(a.publisher == "Test Source" for a in articles)
        assert all(a.language == "fr" for a in articles)
        assert all(a.category is Category.FRANCE for a in articles)

    def test_npr_feed(self, collector, fixtures):
        source = make_source("npr", language="en")
        articles, stats = parse(collector, (fixtures / "npr_rss.xml").read_bytes(), source)

        assert len(articles) == 10
        assert all(a.language == "en" for a in articles)
        assert all(a.published_at.tzinfo is UTC for a in articles)

    def test_every_article_has_a_stable_id_derived_from_its_url(self, collector, fixtures):
        source = make_source()
        articles, _ = parse(collector, (fixtures / "lemonde_une.xml").read_bytes(), source)
        again, _ = parse(collector, (fixtures / "lemonde_une.xml").read_bytes(), source)
        assert [a.id for a in articles] == [a.id for a in again]
        assert len({a.id for a in articles}) == len(articles)


class TestLicenceEnforcement:
    """The behaviour specification section 1.3 is about, at the point where it is decided."""

    def test_unknown_licence_measures_the_description_but_does_not_store_it(
        self, collector, fixtures
    ):
        source = make_source(license_type=LicenseType.UNKNOWN)
        articles, stats = parse(collector, (fixtures / "lemonde_une.xml").read_bytes(), source)

        assert stats.items_with_description == 16, "the feed does supply descriptions"
        assert stats.descriptions_withheld_by_license == 16
        assert all(a.original_description is None for a in articles)
        # Measured, not stored: coverage stays reportable without keeping the text.
        assert all(a.offered_description_chars > 0 for a in articles)
        assert all("UNKNOWN" in a.description_withheld_reason for a in articles)

    def test_cc_by_licence_stores_the_description(self, collector, fixtures):
        source = make_source(license_type=LicenseType.CC_BY)
        articles, stats = parse(collector, (fixtures / "lemonde_une.xml").read_bytes(), source)

        assert stats.descriptions_withheld_by_license == 0
        assert all(a.original_description for a in articles)
        assert all(a.description_withheld_reason is None for a in articles)

    def test_summary_permission_is_copied_onto_every_article(self, collector, fixtures):
        payload = (fixtures / "lemonde_une.xml").read_bytes()
        strict, _ = parse(collector, payload, make_source(license_type=LicenseType.CC_BY_ND))
        open_, _ = parse(collector, payload, make_source(license_type=LicenseType.CC_BY))
        assert not any(a.summary_reuse_allowed for a in strict)
        assert all(a.summary_reuse_allowed for a in open_)


class TestMalformedInput:
    def test_entry_without_a_title_is_dropped_and_counted(self, collector, source):
        payload = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
        <item><link>https://a.fr/1</link></item>
        <item><title>Real</title><link>https://a.fr/2</link></item>
        </channel></rss>"""
        articles, stats = parse(collector, payload, source)
        assert len(articles) == 1 and stats.dropped_missing_title == 1

    def test_entry_without_a_usable_url_is_dropped_and_counted(self, collector, source):
        payload = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
        <item><title>No link</title></item>
        <item><title>Relative</title><link>/not-absolute</link></item>
        <item><title>Real</title><link>https://a.fr/2</link></item>
        </channel></rss>"""
        articles, stats = parse(collector, payload, source)
        assert len(articles) == 1 and stats.dropped_invalid_url == 2

    def test_duplicate_urls_within_one_payload_collapse(self, collector, source):
        payload = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
        <item><title>A</title><link>https://a.fr/1?utm_source=x</link></item>
        <item><title>A updated</title><link>https://a.fr/1</link></item>
        </channel></rss>"""
        articles, stats = parse(collector, payload, source)
        assert len(articles) == 1 and stats.raw_items == 2

    def test_empty_feed_is_not_an_error(self, collector, source):
        payload = b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title></channel></rss>'
        articles, _ = parse(collector, payload, source)
        assert articles == []

    def test_html_error_page_raises_rather_than_looking_like_an_empty_feed(
        self, collector, source
    ):
        # A publisher serving an HTML error page with HTTP 200 is common. feedparser reports
        # it as zero entries with no error, which would be recorded as a healthy source that
        # published nothing - a silent success for a broken feed.
        with pytest.raises(CollectorError, match="not a recognised feed format"):
            parse(collector, b"<html><body>404 Not Found</body></html>", source)

    def test_json_payload_raises(self, collector, source):
        with pytest.raises(CollectorError, match="not a recognised feed format"):
            parse(collector, b'{"articles": []}', source)

    def test_an_empty_but_valid_feed_is_distinguished_from_a_broken_one(
        self, collector, source
    ):
        # The contrast that makes the test above meaningful: valid RSS with no items is a
        # quiet source, not a failure, and must not be recorded as an error.
        payload = b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title></channel></rss>'
        assert parse(collector, payload, source)[0] == []

    def test_html_in_a_title_is_stripped(self, collector, source):
        payload = b"""<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>T</title>
        <item><title>L'&#201;tat &amp; &lt;b&gt;l'Europe&lt;/b&gt;</title>
        <link>https://a.fr/1</link></item></channel></rss>"""
        articles, _ = parse(collector, payload, source)
        assert articles[0].title == "L'État & l'Europe"


class TestStatisticsAreConsistent:
    """Counters must be over the same population, or coverage exceeds 100%."""

    def test_description_coverage_never_exceeds_one(self, collector, fixtures):
        for name in ("lemonde_une.xml", "npr_rss.xml"):
            _, stats = parse(collector, (fixtures / name).read_bytes(), make_source())
            assert 0.0 <= stats.description_coverage <= 1.0, name

    def test_a_duplicate_entry_does_not_inflate_the_description_count(
        self, collector, source
    ):
        # The BBC feed listed one article twice; the counter was incremented per entry while
        # items were counted per kept article, giving 103%.
        payload = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
        <item><title>A</title><link>https://a.fr/1</link><description>d</description></item>
        <item><title>A again</title><link>https://a.fr/1</link><description>d</description></item>
        </channel></rss>"""
        articles, stats = parse(collector, payload, source)
        assert len(articles) == 1
        assert stats.items_with_description == 1
        assert stats.description_coverage == 1.0

    def test_withheld_count_matches_the_articles_that_withheld(self, collector, fixtures):
        articles, stats = parse(
            collector, (fixtures / "lemonde_une.xml").read_bytes(),
            make_source(license_type=LicenseType.UNKNOWN),
        )
        withheld = sum(1 for a in articles if a.description_withheld_reason)
        assert stats.descriptions_withheld_by_license == withheld
