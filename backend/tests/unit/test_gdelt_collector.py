"""GDELT GAL parsing, against a real captured JSON-NL slice.

The fixture is forty real records taken from ``20261114183100.gal.json.gz``. It is the only
honest way to test this parser: the schema was measured, not read off a blog post, and a
hand-written fixture would only confirm the author's assumptions.
"""

from __future__ import annotations

import gzip
from datetime import UTC, datetime

import pytest

from app.collectors.base import CollectionStats, CollectorError
from app.collectors.gdelt_collector import (
    GDELTGALCollector,
    GDELTRSSCollector,
    describe_payload,
)
from app.models.licensing import LicenseType
from app.models.source import SourceType
from tests.conftest import make_source

NOW = datetime(2026, 11, 14, 19, 0, tzinfo=UTC)


@pytest.fixture
def collector():
    return GDELTGALCollector(client=None)


@pytest.fixture
def gal_payload(fixtures):
    return (fixtures / "gdelt_gal_sample.jsonnl").read_bytes()


@pytest.fixture
def gal_source():
    return make_source(
        "gdelt-gal",
        source_type=SourceType.GDELT_GAL_JSONNL,
        feed_url="https://data.gdeltproject.org/gdeltv3/gal/",
        language="mul",
    )


def parse(collector, payload, source):
    stats = CollectionStats(source_id=source.source_id)
    return collector.parse(payload, source, NOW, stats), stats


class TestRealGALData:
    def test_parses_every_record_in_the_sample(self, collector, gal_payload, gal_source):
        articles, stats = parse(collector, gal_payload, gal_source)
        assert stats.raw_items == 40
        assert len(articles) >= 38, "at most a couple should be dropped"
        assert stats.dropped_other + stats.dropped_invalid_url + stats.dropped_missing_title < 3

    def test_extracts_the_documented_fields(self, collector, gal_payload, gal_source):
        articles, _ = parse(collector, gal_payload, gal_source)
        assert all(a.title for a in articles)
        assert all(a.canonical_url.startswith("http") for a in articles)
        assert all(a.domain for a in articles)
        assert all(a.publisher for a in articles)
        # lang was 100% present in the measured file; "und" would mean the mapping broke.
        assert all(a.language != "und" for a in articles)

    def test_outlet_name_is_preferred_over_the_bare_domain(
        self, collector, gal_payload, gal_source
    ):
        articles, _ = parse(collector, gal_payload, gal_source)
        named = [a for a in articles if a.publisher != a.domain]
        assert named, "GAL supplies outletName for most records"

    def test_the_sample_is_multilingual(self, collector, gal_payload, gal_source):
        articles, _ = parse(collector, gal_payload, gal_source)
        assert len({a.language for a in articles}) > 1
        assert "fr" in {a.language for a in articles}

    def test_dates_are_parsed_as_utc(self, collector, gal_payload, gal_source):
        articles, _ = parse(collector, gal_payload, gal_source)
        assert all(a.published_at.tzinfo is UTC for a in articles)
        # The sample was captured on 2026-11-14; nothing should be dated after the run.
        assert all(a.published_at <= NOW for a in articles)

    def test_country_is_left_null_rather_than_guessed_from_the_tld(
        self, collector, gal_payload, gal_source
    ):
        # GAL has no country field. Inferring one from .com or .org would be wrong.
        articles, _ = parse(collector, gal_payload, gal_source)
        assert all(a.country is None for a in articles)


class TestGDELTLicensing:
    def test_descriptions_are_measured_and_discarded(self, collector, gal_payload, gal_source):
        articles, stats = parse(collector, gal_payload, gal_source)
        assert stats.items_with_description > 30, "GAL desc coverage was measured at 97%"
        assert stats.descriptions_withheld_by_license == stats.items_with_description
        assert all(a.original_description is None for a in articles)
        assert any(a.offered_description_chars > 0 for a in articles)

    def test_no_gdelt_article_permits_summary_republication(
        self, collector, gal_payload, gal_source
    ):
        articles, _ = parse(collector, gal_payload, gal_source)
        assert not any(a.summary_reuse_allowed for a in articles)
        assert all(a.license_status is LicenseType.UNKNOWN for a in articles)


class TestMalformedGAL:
    def test_one_bad_line_costs_one_article_not_the_payload(self, collector, gal_source):
        payload = (
            b'{"url":"https://a.fr/1","title":"One","lang":"fr","date":"2026-11-14T10:00:00.000Z"}\n'
            b'not json at all\n'
            b'{"url":"https://a.fr/2","title":"Two","lang":"fr","date":"2026-11-14T10:00:00.000Z"}\n'
        )
        articles, stats = parse(collector, payload, gal_source)
        assert len(articles) == 2 and stats.dropped_other == 1

    def test_a_payload_where_nothing_decodes_raises(self, collector, gal_source):
        with pytest.raises(CollectorError, match="not what this parser targets"):
            parse(collector, b"<html>error</html>\nmore html\n", gal_source)

    def test_record_without_a_url_is_dropped(self, collector, gal_source):
        payload = b'{"title":"No URL","lang":"en"}\n{"url":"https://a.fr/1","title":"Ok"}\n'
        articles, stats = parse(collector, payload, gal_source)
        assert len(articles) == 1 and stats.dropped_invalid_url == 1

    def test_aggregator_links_are_dropped(self, collector, gal_source):
        # news.google.com links redirect; storing one gives the reader the wrong URL.
        payload = (
            b'{"url":"https://news.google.com/rss/articles/xyz","title":"Wrapped"}\n'
            b'{"url":"https://bbc.co.uk/news/1","title":"Direct"}\n'
        )
        articles, stats = parse(collector, payload, gal_source)
        assert len(articles) == 1 and articles[0].domain == "bbc.co.uk"
        assert stats.dropped_other == 1

    def test_empty_payload_is_not_an_error(self, collector, gal_source):
        assert parse(collector, b"", gal_source)[0] == []
        assert parse(collector, b"\n\n  \n", gal_source)[0] == []


class TestGzip:
    def test_gzip_payload_is_decompressed(self):
        assert GDELTGALCollector.decompress(gzip.compress(b"hello")) == b"hello"

    def test_plain_payload_passes_through(self):
        assert GDELTGALCollector.decompress(b'{"url":"x"}') == b'{"url":"x"}'

    def test_truncated_gzip_is_reported_not_swallowed(self):
        with pytest.raises(CollectorError, match="did not decompress"):
            GDELTGALCollector.decompress(gzip.compress(b"hello")[:8])


class TestFileDiscovery:
    def test_candidate_urls_are_newest_first(self):
        urls = GDELTGALCollector.candidate_urls(datetime(2026, 11, 14, 18, 37, tzinfo=UTC), 2)
        assert urls == sorted(urls, reverse=True)
        assert all(u.endswith(".gal.json.gz") for u in urls)

    def test_candidates_cluster_after_each_quarter_hour(self):
        urls = GDELTGALCollector.candidate_urls(datetime(2026, 11, 14, 18, 37, tzinfo=UTC), 1)
        minutes = sorted(int(GDELTGALCollector.timestamp_of(u)[10:12]) for u in urls)
        # 18:37 -> the quarter mark is 18:30, so 30..35 are probed.
        assert minutes == [30, 31, 32, 33, 34, 35]

    def test_timestamp_extraction(self):
        url = "https://data.gdeltproject.org/gdeltv3/gal/20261114183100.gal.json.gz"
        assert GDELTGALCollector.timestamp_of(url) == "20261114183100"

    def test_cursor_ordering_is_lexicographic_and_chronological(self):
        # The cursor comparison in collect() relies on these agreeing.
        assert "20261114183100" < "20261114184600" < "20261115000100"


class TestSchemaProbe:
    def test_describe_payload_measures_the_real_sample(self, gal_payload):
        report = describe_payload(gal_payload)
        assert report["records_decoded"] == 40
        assert report["lines_malformed"] == 0
        assert report["invalid_urls"] == 0
        assert report["field_presence"]["url"] == 1.0
        assert report["field_presence"]["title"] == 1.0
        assert report["distinct_domains"] > 10
        assert report["description_coverage"] > 0.5


class TestCollectorRouting:
    def test_gal_collector_claims_only_jsonnl_sources(self, collector, gal_source):
        assert collector.supports(gal_source)
        assert not collector.supports(make_source(source_type=SourceType.RSS))

    def test_rss_variant_claims_only_the_rss_source(self):
        rss = GDELTRSSCollector(client=None)
        assert rss.supports(make_source(source_type=SourceType.GDELT_GAL_RSS))
        assert not rss.supports(make_source(source_type=SourceType.GDELT_GAL_JSONNL))


class TestLanguageFilter:
    """GAL carries 40+ languages; this product reads French news."""

    def test_only_the_configured_languages_survive(self, gal_payload, gal_source):
        french_only = GDELTGALCollector(client=None, languages=frozenset({"fr"}))
        articles, stats = parse(french_only, gal_payload, gal_source)

        assert articles, "the fixture contains French records"
        assert {a.language for a in articles} == {"fr"}
        assert stats.filtered_by_language > 0

    def test_filtered_records_are_not_counted_as_defects(self, gal_payload, gal_source):
        french_only = GDELTGALCollector(client=None, languages=frozenset({"fr"}))
        _, stats = parse(french_only, gal_payload, gal_source)

        # A filter working as configured is not a quality problem. Folding it into drop_rate
        # would make a French-only run look like a 94% failure.
        assert stats.drop_rate < 0.2
        assert stats.dropped_other == 0

    def test_no_filter_keeps_everything(self, collector, gal_payload, gal_source):
        articles, stats = parse(collector, gal_payload, gal_source)
        assert stats.filtered_by_language == 0
        assert len({a.language for a in articles}) > 1

    def test_an_over_strict_filter_yields_nothing_rather_than_failing(
        self, gal_payload, gal_source
    ):
        impossible = GDELTGALCollector(client=None, languages=frozenset({"xx"}))
        articles, stats = parse(impossible, gal_payload, gal_source)
        assert articles == []
        assert stats.filtered_by_language == stats.raw_items
