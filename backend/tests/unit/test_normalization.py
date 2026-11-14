"""URL, title, date and language normalisation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.processors import normalization as norm


class TestCanonicaliseURL:
    def test_lowercases_scheme_and_host_but_not_path(self):
        # Paths are case-sensitive on most servers; hosts never are.
        assert norm.canonicalise_url("HTTPS://WWW.Example.COM/Path") == "https://example.com/Path"

    def test_strips_tracking_parameters_and_keeps_real_ones(self):
        url = "https://a.fr/x?utm_source=nl&id=7&fbclid=zz&page=2"
        assert norm.canonicalise_url(url) == "https://a.fr/x?id=7&page=2"

    def test_parameter_order_does_not_change_identity(self):
        assert norm.canonicalise_url("https://a.fr/x?b=2&a=1") == norm.canonicalise_url(
            "https://a.fr/x?a=1&b=2"
        )

    def test_drops_fragment_and_trailing_slash(self):
        assert norm.canonicalise_url("https://a.fr/x/#section") == "https://a.fr/x"

    def test_keeps_root_path_as_slash(self):
        assert norm.canonicalise_url("https://a.fr/") == "https://a.fr/"

    def test_removes_default_ports(self):
        assert norm.canonicalise_url("https://a.fr:443/x") == "https://a.fr/x"
        assert norm.canonicalise_url("http://a.fr:80/x") == "http://a.fr/x"

    @pytest.mark.parametrize(
        "bad", ["", "   ", None, "not a url", "ftp://a.fr/x", "javascript:alert(1)", "/relative"]
    )
    def test_rejects_anything_that_is_not_an_absolute_http_url(self, bad):
        # Returning "" rather than raising: the collectors count these and move on.
        assert norm.canonicalise_url(bad) == ""

    def test_two_feeds_linking_the_same_article_produce_one_url(self):
        a = "https://www.lemonde.fr/article/2026/x.html?utm_medium=Social&utm_source=Twitter"
        b = "http://lemonde.fr/article/2026/x.html"
        # Scheme still differs, which is correct - http and https are different URLs - but
        # everything the publisher added for tracking is gone.
        assert norm.canonicalise_url(a) == "https://lemonde.fr/article/2026/x.html"
        assert norm.canonicalise_url(b) == "http://lemonde.fr/article/2026/x.html"


class TestTitles:
    def test_strips_markup_entities_and_nbsp(self):
        assert norm.clean_title("L'État &amp; <b>l'Europe</b> : accord") == (
            "L'État & l'Europe : accord"
        )

    def test_normalise_folds_accents_and_punctuation_for_comparison(self):
        assert norm.normalise_title("L'État, demain !") == "l etat demain"

    def test_normalise_leaves_cjk_intact(self):
        assert "欧盟" in norm.normalise_title("欧盟就人工智能法案达成协议")

    def test_clean_title_of_nothing_is_empty(self):
        assert norm.clean_title(None) == "" and norm.clean_title("  ") == ""


class TestDates:
    @pytest.fixture
    def now(self):
        return datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

    def test_rfc822_with_offset(self, now):
        assert norm.parse_datetime("Tue, 10 Nov 2026 08:30:00 +0100", now) == datetime(
            2026, 11, 10, 7, 30, tzinfo=UTC
        )

    def test_iso8601_with_z(self, now):
        assert norm.parse_datetime("2026-11-13T22:15:00Z", now) == datetime(
            2026, 11, 13, 22, 15, tzinfo=UTC
        )

    def test_naive_timestamp_is_assumed_utc(self, now):
        assert norm.parse_datetime("2026-11-13 22:15:00", now).tzinfo is UTC

    def test_struct_time_from_feedparser(self, now):
        assert norm.parse_datetime((2026, 11, 12, 7, 0, 0, 0, 0, 0), now) == datetime(
            2026, 11, 12, 7, 0, tzinfo=UTC
        )

    def test_unparsable_falls_back_rather_than_dropping_the_item(self, now):
        assert norm.parse_datetime("sometime last week", now) == now
        assert norm.parse_datetime(None, now) == now

    def test_implausible_future_date_is_rejected(self, now):
        # A feed claiming 2049 would otherwise pin itself to the top of every list.
        assert norm.parse_datetime("2049-01-01", now) == now

    def test_slightly_future_date_is_accepted(self, now):
        # Clock skew of a few hours is normal and must not be discarded.
        soon = (now + timedelta(hours=3)).isoformat()
        assert norm.parse_datetime(soon, now) > now


class TestLanguage:
    @pytest.mark.parametrize(
        "raw,expected",
        [("fr-FR", "fr"), ("FR", "fr"), ("fra", "fr"), ("zh-Hans", "zh"), ("zho", "zh"),
         ("en_GB", "en"), ("eng", "en")],
    )
    def test_reduces_to_primary_subtag(self, raw, expected):
        assert norm.normalise_language(raw) == expected

    def test_unknown_is_undetermined_not_a_guess(self):
        assert norm.normalise_language(None) == "und"
        assert norm.normalise_language("") == "und"
        assert norm.normalise_language("!!") == "und"


class TestDomain:
    def test_strips_www_and_port(self):
        assert norm.domain_of("https://www.lemonde.fr:443/a") == "lemonde.fr"

    def test_recognises_redirectors(self):
        assert norm.is_aggregator_url("https://news.google.com/rss/articles/x")
        assert not norm.is_aggregator_url("https://www.bbc.co.uk/news/x")
