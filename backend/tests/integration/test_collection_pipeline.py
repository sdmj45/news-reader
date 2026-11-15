"""The collection pipeline end to end, with HTTP mocked at the transport layer.

These tests use ``respx`` rather than real feeds so they are deterministic and offline. They
test *this code's* behaviour - isolation, backoff, licence enforcement, idempotency. They say
nothing about whether real providers work; that is what ``tests/realdata/`` is for, and the
distinction is specification section 15's "real data validation" requirement.
"""

from __future__ import annotations

import gzip
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.collectors.collector_manager import CollectorManager, backoff_minutes
from app.core.config import Settings
from app.models.licensing import LicenseType
from app.models.source import SourceHealth, SourceType
from app.repositories.base import ArticleQuery
from app.services.ingestion import run_ingestion
from tests.conftest import make_source

FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Test</title>
  <item><title>Emmanuel Macron reçoit Friedrich Merz à l'Élysée</title>
    <link>https://a.test/macron-merz</link>
    <description>Le président a reçu le chancelier allemand.</description>
    <pubDate>Fri, 14 Nov 2026 10:00:00 +0000</pubDate></item>
  <item><title>Le chômage recule de 0,2 point</title>
    <link>https://a.test/chomage</link>
    <description>Les chiffres du trimestre.</description>
    <pubDate>Fri, 14 Nov 2026 09:00:00 +0000</pubDate></item>
</channel></rss>"""

OTHER_FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Other</title>
  <item><title>Friedrich Merz reçu par Emmanuel Macron à l'Élysée</title>
    <link>https://b.test/merz-macron</link>
    <pubDate>Fri, 14 Nov 2026 10:30:00 +0000</pubDate></item>
</channel></rss>"""


@pytest.fixture
def mem_settings():
    return Settings(
        sqlite_path=":memory:", collector_max_attempts=1,
        collector_min_host_interval=0.0, collector_timeout_seconds=2.0,
    )


async def ingest(repo, settings, sources, **kwargs):
    async with httpx.AsyncClient() as client:
        manager = CollectorManager(client=client, min_host_interval=0.0, max_attempts=1, **kwargs)
        return await run_ingestion(repo, settings, sources=sources, manager=manager)


class TestHappyPath:
    @respx.mock
    async def test_collects_classifies_and_stores(self, repo, mem_settings):
        respx.get("https://a.test/feed.xml").mock(return_value=httpx.Response(200, text=FEED))
        source = make_source(feed_url="https://a.test/feed.xml")

        report = await ingest(repo, mem_settings, [source])

        assert report.sources_succeeded == 1
        assert report.articles_collected == 2
        assert report.articles_inserted == 2
        assert repo.count_articles() == 2
        categories = {a.category.value for a in repo.list_articles(ArticleQuery()).articles}
        assert categories == {"POLITICS", "ECONOMY"}

    @respx.mock
    async def test_a_second_run_inserts_nothing_new(self, repo, mem_settings):
        respx.get("https://a.test/feed.xml").mock(return_value=httpx.Response(200, text=FEED))
        # Interval zero so this exercises write idempotency rather than the polling
        # interval, which is what TestPollingInterval is for. Before intervals were
        # enforced, this test passed for the wrong reason: the second run refetched.
        source = replace(make_source(feed_url="https://a.test/feed.xml"),
                         fetch_interval_minutes=0)

        await ingest(repo, mem_settings, [source])
        second = await ingest(repo, mem_settings, [source])

        assert second.articles_inserted == 0
        assert second.articles_unchanged == 2
        assert repo.count_articles() == 2

    @respx.mock
    async def test_health_is_recorded_on_success(self, repo, mem_settings):
        respx.get("https://a.test/feed.xml").mock(
            return_value=httpx.Response(200, text=FEED, headers={"ETag": '"v1"'})
        )
        await ingest(repo, mem_settings, [make_source(feed_url="https://a.test/feed.xml")])

        health = repo.get_source_health("test-src")
        assert health.consecutive_failures == 0
        assert health.last_successful_fetch is not None
        assert health.total_items_collected == 2
        assert health.etag == '"v1"'

    @respx.mock
    async def test_the_run_is_logged_with_its_metrics(self, repo, mem_settings):
        respx.get("https://a.test/feed.xml").mock(return_value=httpx.Response(200, text=FEED))
        await ingest(repo, mem_settings, [make_source(feed_url="https://a.test/feed.xml")])

        logged = repo.list_collection_runs()
        assert len(logged) == 1
        assert logged[0]["articles_collected"] == 2
        assert logged[0]["collection_success_rate"] == 1.0
        assert "POLITICS" in logged[0]["categories"]


class TestFailureIsolation:
    """Specification section 5: one failed source must not stop the others."""

    @respx.mock
    async def test_one_failing_source_does_not_stop_the_rest(self, repo, mem_settings):
        respx.get("https://broken.test/feed.xml").mock(return_value=httpx.Response(500))
        respx.get("https://a.test/feed.xml").mock(return_value=httpx.Response(200, text=FEED))
        sources = [
            make_source("broken", feed_url="https://broken.test/feed.xml"),
            make_source("working", feed_url="https://a.test/feed.xml"),
        ]

        report = await ingest(repo, mem_settings, sources)

        assert report.sources_attempted == 2
        assert report.sources_succeeded == 1
        assert repo.count_articles() == 2
        failed = next(o for o in report.outcomes if o.source_id == "broken")
        assert not failed.succeeded and "500" in failed.error

    @respx.mock
    async def test_a_timeout_is_recorded_not_raised(self, repo, mem_settings):
        respx.get("https://slow.test/feed.xml").mock(side_effect=httpx.ConnectTimeout("too slow"))
        report = await ingest(
            repo, mem_settings, [make_source("slow", feed_url="https://slow.test/feed.xml")]
        )
        assert report.sources_succeeded == 0
        assert "timeout" in report.outcomes[0].error.lower()
        assert repo.get_source_health("slow").consecutive_failures == 1

    @respx.mock
    async def test_an_html_error_page_is_a_failure_not_an_empty_success(
        self, repo, mem_settings
    ):
        # The failure mode that matters: HTTP 200 with a maintenance page. Recording it as a
        # healthy source with no news would hide a broken feed indefinitely.
        respx.get("https://a.test/feed.xml").mock(
            return_value=httpx.Response(200, text="<html><body>Maintenance</body></html>")
        )
        report = await ingest(repo, mem_settings, [make_source(feed_url="https://a.test/feed.xml")])
        assert report.sources_succeeded == 0
        assert "not a recognised feed format" in report.outcomes[0].error

    @respx.mock
    async def test_no_articles_are_invented_when_everything_fails(self, repo, mem_settings):
        respx.get("https://a.test/feed.xml").mock(return_value=httpx.Response(503))
        report = await ingest(repo, mem_settings, [make_source(feed_url="https://a.test/feed.xml")])
        assert report.articles_collected == 0
        assert repo.count_articles() == 0

    @respx.mock
    async def test_failures_accumulate_and_then_back_off(self, repo, mem_settings):
        respx.get("https://a.test/feed.xml").mock(return_value=httpx.Response(500))
        source = make_source(feed_url="https://a.test/feed.xml")

        await ingest(repo, mem_settings, [source])
        await ingest(repo, mem_settings, [source])
        assert repo.get_source_health("test-src").consecutive_failures == 2

        # Third run: the source is now inside its backoff window and is skipped, not fetched.
        third = await ingest(repo, mem_settings, [source])
        assert third.sources_skipped == 1
        assert "backing off" in third.outcomes[0].error

    def test_a_single_failure_is_forgiven(self):
        # A publisher returning one 503 must not cost several scheduled runs.
        assert backoff_minutes(1) == 0

    def test_backoff_schedule_is_bounded(self):
        assert backoff_minutes(0) == 0
        assert backoff_minutes(2) < backoff_minutes(3) < backoff_minutes(5)
        assert backoff_minutes(50) == backoff_minutes(5) == 360

    @respx.mock
    async def test_recovery_clears_the_failure_count(self, repo, mem_settings):
        route = respx.get("https://a.test/feed.xml")
        route.mock(return_value=httpx.Response(500))
        source = make_source(feed_url="https://a.test/feed.xml")
        await ingest(repo, mem_settings, [source])

        # Rewind the attempt time so the backoff window has passed.
        health = repo.get_source_health("test-src")
        health.last_attempted_fetch = datetime.now(UTC) - timedelta(hours=2)
        repo.save_source_health(health)

        route.mock(return_value=httpx.Response(200, text=FEED))
        await ingest(repo, mem_settings, [source])
        assert repo.get_source_health("test-src").consecutive_failures == 0


class TestLicenceEnforcementEndToEnd:
    @respx.mock
    async def test_unknown_licence_never_reaches_the_database_with_a_description(
        self, repo, mem_settings
    ):
        respx.get("https://a.test/feed.xml").mock(return_value=httpx.Response(200, text=FEED))
        source = make_source(feed_url="https://a.test/feed.xml",
                             license_type=LicenseType.UNKNOWN)

        report = await ingest(repo, mem_settings, [source])

        stored = repo.list_articles(ArticleQuery()).articles
        assert all(a.original_description is None for a in stored)
        assert all(not a.summary_reuse_allowed for a in stored)
        assert all(a.processing_status.value == "SUMMARY_SKIPPED_LICENSE" for a in stored)
        assert report.descriptions_withheld_by_license == 2

    @respx.mock
    async def test_cc_by_licence_stores_the_description(self, repo, mem_settings):
        respx.get("https://a.test/feed.xml").mock(return_value=httpx.Response(200, text=FEED))
        source = make_source(feed_url="https://a.test/feed.xml", license_type=LicenseType.CC_BY)

        await ingest(repo, mem_settings, [source])

        stored = repo.list_articles(ArticleQuery()).articles
        assert all(a.original_description for a in stored)
        assert all(a.summary_reuse_allowed for a in stored)


class TestDeduplicationAcrossSources:
    @respx.mock
    async def test_the_same_article_from_two_feeds_is_stored_once(self, repo, mem_settings):
        respx.get("https://a.test/feed.xml").mock(return_value=httpx.Response(200, text=FEED))
        respx.get("https://a.test/feed2.xml").mock(
            return_value=httpx.Response(200, text=FEED.replace(
                "https://a.test/macron-merz", "https://a.test/macron-merz?utm_source=nl"
            ))
        )
        sources = [
            make_source("one", feed_url="https://a.test/feed.xml"),
            make_source("two", feed_url="https://a.test/feed2.xml"),
        ]

        report = await ingest(repo, mem_settings, sources)

        assert report.articles_collected == 4
        assert report.articles_after_dedup == 2
        assert report.duplicate_rate == 0.5
        assert repo.count_articles() == 2

    @respx.mock
    async def test_two_publishers_covering_one_event_are_both_kept_and_linked(
        self, repo, mem_settings
    ):
        respx.get("https://a.test/feed.xml").mock(return_value=httpx.Response(200, text=FEED))
        respx.get("https://b.test/feed.xml").mock(
            return_value=httpx.Response(200, text=OTHER_FEED)
        )
        sources = [
            make_source("a", name="Le Monde", feed_url="https://a.test/feed.xml"),
            make_source("b", name="franceinfo", feed_url="https://b.test/feed.xml"),
        ]

        report = await ingest(repo, mem_settings, sources)

        assert repo.count_articles() == 3, "no article is deleted"
        assert report.multi_publisher_events == 1
        linked = [a for a in repo.list_articles(ArticleQuery()).articles if a.event_id]
        assert len(linked) == 2 and len({a.event_id for a in linked}) == 1


class TestGDELTCollection:
    def _gal(self, *records):
        import json
        return gzip.compress("\n".join(json.dumps(r) for r in records).encode())

    @respx.mock
    async def test_reads_the_newest_available_gal_file(self, repo, mem_settings):
        payload = self._gal(
            {"date": "2026-11-14T10:00:00.000Z", "url": "https://x.test/1",
             "domain": "x.test", "outletName": "X Times", "title": "A real headline",
             "desc": "Something.", "lang": "en"},
        )
        # Every candidate 404s except one, which is exactly how GAL behaves.
        respx.get(url__regex=r".*gal/\d+\.gal\.json\.gz").mock(
            side_effect=lambda request: httpx.Response(
                200, content=payload
            ) if request.url.path.endswith("00.gal.json.gz") else httpx.Response(404)
        )
        source = make_source(
            "gdelt-gal", source_type=SourceType.GDELT_GAL_JSONNL,
            feed_url="https://data.gdeltproject.org/gdeltv3/gal/", language="mul",
        )

        report = await ingest(repo, mem_settings, [source], gdelt_files_per_run=1)

        assert report.sources_succeeded == 1
        assert report.articles_inserted == 1
        stored = repo.list_articles(ArticleQuery()).articles[0]
        assert stored.publisher == "X Times" and stored.original_description is None

    @respx.mock
    async def test_all_404s_is_a_recorded_failure_not_a_silent_success(
        self, repo, mem_settings
    ):
        respx.get(url__regex=r".*gal/.*").mock(return_value=httpx.Response(404))
        source = make_source(
            "gdelt-gal", source_type=SourceType.GDELT_GAL_JSONNL,
            feed_url="https://data.gdeltproject.org/gdeltv3/gal/", language="mul",
        )

        report = await ingest(repo, mem_settings, [source])

        assert report.sources_succeeded == 0
        assert "no GAL file found" in report.outcomes[0].error
        assert repo.count_articles() == 0

    @respx.mock
    async def test_the_cursor_stops_a_second_run_re_reading_the_same_file(
        self, repo, mem_settings
    ):
        payload = self._gal({"url": "https://x.test/1", "title": "Headline", "lang": "en",
                             "date": "2026-11-14T10:00:00.000Z"})
        respx.get(url__regex=r".*gal/\d+\.gal\.json\.gz").mock(
            return_value=httpx.Response(200, content=payload)
        )
        source = make_source(
            "gdelt-gal", source_type=SourceType.GDELT_GAL_JSONNL,
            feed_url="https://data.gdeltproject.org/gdeltv3/gal/", language="mul",
        )

        await ingest(repo, mem_settings, [source], gdelt_files_per_run=1)
        cursor = repo.get_source_health("gdelt-gal").cursor
        assert cursor and cursor.isdigit()

        second = await ingest(repo, mem_settings, [source], gdelt_files_per_run=1)
        # Either nothing newer exists (304-equivalent) or only newer files were read.
        assert second.articles_inserted == 0


class TestSelection:
    @respx.mock
    async def test_only_sources_setting_restricts_the_run(self, repo):
        respx.get("https://a.test/feed.xml").mock(return_value=httpx.Response(200, text=FEED))
        settings = Settings(sqlite_path=":memory:", collector_only_sources="wanted")
        sources = [
            make_source("wanted", feed_url="https://a.test/feed.xml"),
            make_source("ignored", feed_url="https://b.test/feed.xml"),
        ]
        report = await ingest(repo, settings, sources)
        assert report.sources_attempted == 1

    async def test_no_sources_is_an_empty_run_not_a_crash(self, repo, mem_settings):
        report = await ingest(repo, mem_settings, [])
        assert report.sources_attempted == 0 and report.articles_collected == 0


class TestGDELTQuietPeriods:
    """Between quarter-hour publications there is nothing new. That is not a failure."""

    @respx.mock
    async def test_nothing_newer_than_the_cursor_is_not_an_error(self, repo, mem_settings):
        respx.get(url__regex=r".*gal/.*").mock(return_value=httpx.Response(404))
        source = make_source(
            "gdelt-gal", source_type=SourceType.GDELT_GAL_JSONNL,
            feed_url="https://data.gdeltproject.org/gdeltv3/gal/", language="mul",
        )
        # A cursor from a previous successful run, far enough back that candidates remain.
        repo.save_source_health(SourceHealth(source_id="gdelt-gal", cursor="20200101000100"))

        report = await ingest(repo, mem_settings, [source])

        assert report.sources_succeeded == 1
        assert report.outcomes[0].not_modified
        assert report.outcomes[0].error is None
        assert repo.get_source_health("gdelt-gal").consecutive_failures == 0

    @respx.mock
    async def test_a_first_run_finding_nothing_is_still_a_failure(self, repo, mem_settings):
        # No cursor means this is the first attempt; zero files means GDELT is unreachable or
        # has changed shape, and that must be reported, not hidden behind "nothing new".
        respx.get(url__regex=r".*gal/.*").mock(return_value=httpx.Response(404))
        source = make_source(
            "gdelt-gal", source_type=SourceType.GDELT_GAL_JSONNL,
            feed_url="https://data.gdeltproject.org/gdeltv3/gal/", language="mul",
        )

        report = await ingest(repo, mem_settings, [source])

        assert report.sources_succeeded == 0
        assert "no GAL file found" in report.outcomes[0].error

    @respx.mock
    async def test_a_server_error_is_still_a_failure_even_with_a_cursor(
        self, repo, mem_settings
    ):
        respx.get(url__regex=r".*gal/.*").mock(return_value=httpx.Response(503))
        source = make_source(
            "gdelt-gal", source_type=SourceType.GDELT_GAL_JSONNL,
            feed_url="https://data.gdeltproject.org/gdeltv3/gal/", language="mul",
        )
        repo.save_source_health(SourceHealth(source_id="gdelt-gal", cursor="20200101000100"))

        report = await ingest(repo, mem_settings, [source])

        assert report.sources_succeeded == 0
        assert repo.get_source_health("gdelt-gal").consecutive_failures == 1


class TestPollingInterval:
    """`fetch_interval_minutes` was declared, documented, and read by nothing."""

    @respx.mock
    async def test_a_source_is_not_refetched_before_its_interval(self, repo, mem_settings):
        route = respx.get("https://a.test/feed.xml").mock(
            return_value=httpx.Response(200, text=FEED)
        )
        source = make_source(feed_url="https://a.test/feed.xml")
        source = replace(source, fetch_interval_minutes=180)

        await ingest(repo, mem_settings, [source])
        assert route.call_count == 1

        second = await ingest(repo, mem_settings, [source])
        assert route.call_count == 1, "a 180-minute feed must not be fetched twice in a row"
        assert second.sources_skipped == 1
        assert "180 min apart" in second.outcomes[0].error

    @respx.mock
    async def test_it_is_refetched_once_the_interval_has_passed(self, repo, mem_settings):
        route = respx.get("https://a.test/feed.xml").mock(
            return_value=httpx.Response(200, text=FEED)
        )
        source = replace(make_source(feed_url="https://a.test/feed.xml"),
                         fetch_interval_minutes=180)
        await ingest(repo, mem_settings, [source])

        health = repo.get_source_health("test-src")
        health.last_successful_fetch = datetime.now(UTC) - timedelta(hours=4)
        repo.save_source_health(health)

        await ingest(repo, mem_settings, [source])
        assert route.call_count == 2

    @respx.mock
    async def test_a_frequent_source_is_fetched_every_run(self, repo, mem_settings):
        route = respx.get("https://a.test/feed.xml").mock(
            return_value=httpx.Response(200, text=FEED)
        )
        # The scheduled job runs every three hours; a 20-minute feed is always due.
        source = replace(make_source(feed_url="https://a.test/feed.xml"),
                         fetch_interval_minutes=20)
        await ingest(repo, mem_settings, [source])
        health = repo.get_source_health("test-src")
        health.last_successful_fetch = datetime.now(UTC) - timedelta(hours=3)
        repo.save_source_health(health)
        await ingest(repo, mem_settings, [source])
        assert route.call_count == 2

    @respx.mock
    async def test_a_skipped_source_is_not_counted_as_a_failure(self, repo, mem_settings):
        respx.get("https://a.test/feed.xml").mock(return_value=httpx.Response(200, text=FEED))
        source = replace(make_source(feed_url="https://a.test/feed.xml"),
                         fetch_interval_minutes=180)
        await ingest(repo, mem_settings, [source])
        second = await ingest(repo, mem_settings, [source])
        assert repo.get_source_health("test-src").consecutive_failures == 0
        assert second.sources_succeeded == 0 and second.sources_skipped == 1
