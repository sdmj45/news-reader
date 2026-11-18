"""The collection script's exit code, which decides whether the publish run goes on."""

from __future__ import annotations

from app.services.ingestion import IngestionReport
from scripts.ingest import exit_code


def report(attempted: int, succeeded: int, skipped: int) -> IngestionReport:
    r = IngestionReport(run_id="r", started_at="2026-11-18T10:15:00+00:00")
    r.sources_attempted, r.sources_succeeded, r.sources_skipped = attempted, succeeded, skipped
    return r


def test_every_fetched_source_failing_is_a_failure():
    assert exit_code(report(attempted=5, succeeded=0, skipped=0)) == 1


def test_every_source_skipped_as_not_yet_due_is_not():
    # A run twenty minutes after the previous one: nothing is due, nothing is wrong.
    assert exit_code(report(attempted=62, succeeded=0, skipped=62)) == 0


def test_some_skipped_and_the_rest_failed_is_a_failure():
    assert exit_code(report(attempted=62, succeeded=0, skipped=60)) == 1


def test_one_success_is_enough():
    assert exit_code(report(attempted=62, succeeded=1, skipped=10)) == 0
