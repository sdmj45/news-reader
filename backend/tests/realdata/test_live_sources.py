"""Live checks against real news providers.

Deselected by default. Run with::

    pytest -m realdata

Specification section 15 asks for these to be separate from mocked tests, and section 14.3
forbids pretending a provider works when it does not. So these tests **measure** rather than
assert optimistically: they check that the registry's claims about each endpoint still hold,
and a failure here means the world changed, not that the code is broken. Read a failure as a
report about a publisher.
"""

from __future__ import annotations

import pytest

from app.collectors.collector_manager import CollectorManager
from app.collectors.gdelt_collector import GDELTGALCollector, describe_payload
from app.models.source import SourceType
from app.services import source_registry

pytestmark = pytest.mark.realdata


@pytest.fixture
async def manager():
    async with CollectorManager(max_concurrency=4, min_host_interval=0.5) as m:
        yield m


class TestRegistryStillMatchesReality:
    @pytest.mark.parametrize(
        "source",
        [s for s in source_registry.active_sources() if s.source_type in
         (SourceType.RSS, SourceType.ATOM)],
        ids=lambda s: s.source_id,
    )
    async def test_each_rss_source_still_returns_articles(self, manager, source):
        result = await manager.collector_for(source).collect(source)

        assert result.succeeded, f"{source.source_id}: {result.error}"
        assert result.articles, f"{source.source_id} returned 0 articles"
        # The registry records a count measured on 2026-11-14. Feeds shrink and grow, so this
        # is a sanity floor, not an equality check.
        if source.verified_item_count:
            assert len(result.articles) >= max(1, source.verified_item_count // 4), (
                f"{source.source_id} returned {len(result.articles)}, registry recorded "
                f"{source.verified_item_count}"
            )
        assert all(a.canonical_url.startswith("http") for a in result.articles)
        assert all(a.title.strip() for a in result.articles)

    async def test_rejected_candidates_are_still_rejected(self, manager):
        """If a rejected endpoint starts working, the registry should be revisited.

        Reported rather than asserted: a publisher fixing their feed is good news, and
        failing the build over it would be perverse.

        "Working" means *parsable entries*, not bytes. Al Jazeera Chinese returns 352 kB that
        feedparser cannot read, and Liberation returns 13 kB with no items; counting those as
        recovered would make this check cry wolf every run. Endpoints rejected on provenance
        rather than reachability are excluded entirely - a mirror responding does not make it
        the publisher's feed.
        """
        import feedparser
        import httpx

        recovered = []
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            for url, reason in source_registry.REJECTED_CANDIDATES.items():
                if "provenance" in reason:
                    continue
                try:
                    response = await client.get(url, headers={"User-Agent": "NewsReaderBot/0.1"})
                except httpx.HTTPError:
                    continue
                if not response.is_success:
                    continue
                if feedparser.parse(response.content).entries:
                    recovered.append(url)
        if recovered:
            pytest.skip(
                "These previously rejected endpoints now respond and should be re-evaluated:\n"
                + "\n".join(f"  {url}" for url in recovered)
            )


class TestGDELTLive:
    async def test_a_gal_file_can_be_retrieved_and_parsed(self, manager):
        source = source_registry.by_id("gdelt-gal")
        collector = manager.collector_for(source)
        assert isinstance(collector, GDELTGALCollector)

        result = await collector.collect(source)

        if not result.succeeded:
            pytest.fail(
                f"GDELT GAL is not reachable from this host: {result.error}. "
                f"This is an environment limitation, not a code defect - see "
                f"docs/DATA_SOURCES.md."
            )
        assert len(result.articles) > 100, "a GAL file holds ~1,800 records"
        assert result.last_modified and result.last_modified.isdigit()

    async def test_the_measured_schema_still_holds(self):
        """Re-runs the measurement the parser was built on. The parser's own assumptions."""
        import httpx

        from scripts.probe_gdelt import UA, fetch_latest

        with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=60.0) as c:
            try:
                url, payload = fetch_latest(c)
            except SystemExit as exc:
                pytest.fail(f"no GAL file retrievable: {exc}")

        report = describe_payload(payload, sample_size=1000)

        # Measured on 2026-11-14: url and title 100%, desc 97.2%, lang 100%.
        assert report["field_presence"]["url"] > 0.99, report["field_presence"]
        assert report["field_presence"]["title"] > 0.95, report["field_presence"]
        assert report["description_coverage"] > 0.5, (
            f"description coverage fell to {report['description_coverage']:.1%} "
            f"(was 97.2% on 2026-11-14)"
        )
        assert report["distinct_domains"] > 50, "GAL should carry hundreds of domains"
        assert report["lines_malformed"] == 0


class TestDescriptionCoverageAcrossSources:
    async def test_report_description_coverage_per_source(self, manager):
        """Measures what section 4.1 asks for. Always passes; prints the measurement."""
        sources = [s for s in source_registry.active_sources()
                   if s.source_type in (SourceType.RSS, SourceType.ATOM)]
        results = await manager.collect_all(sources)

        print("\n  source                     items  desc-cov  status")
        for result in results:
            stats = result.stats
            status = "ok" if result.succeeded else (result.error or "")[:40]
            print(f"  {result.source_id:<26} {len(result.articles):>5}  "
                  f"{stats.description_coverage:>7.0%}  {status}")

        succeeded = sum(1 for r in results if r.succeeded)
        assert succeeded >= len(results) * 0.7, (
            f"only {succeeded}/{len(results)} sources responded; the registry may be stale"
        )
