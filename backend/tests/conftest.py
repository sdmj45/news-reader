"""Shared fixtures.

Fixture data under ``tests/fixtures/`` is **real**, captured from live providers on
2026-11-14, not hand-written. A hand-written RSS sample tests the parser against the author's
idea of RSS; a captured one tests it against what Le Monde and NPR actually send.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.article import Article, Category, article_id_for, content_hash_for
from app.models.licensing import LicenseType
from app.models.source import NewsSource, SourceType, VerificationState
from app.repositories.sqlite_repository import SQLiteArticleRepository

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def repo() -> SQLiteArticleRepository:
    repository = SQLiteArticleRepository(":memory:")
    yield repository
    repository.close()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_backend="sqlite",
        sqlite_path=":memory:",
        collector_max_attempts=1,
        collector_timeout_seconds=2.0,
        collector_min_host_interval=0.0,
    )


def make_source(
    source_id: str = "test-src",
    *,
    name: str | None = None,
    license_type: LicenseType = LicenseType.UNKNOWN,
    source_type: SourceType = SourceType.RSS,
    feed_url: str = "https://example.test/feed.xml",
    language: str = "fr",
    category: Category | None = None,
) -> NewsSource:
    return NewsSource(
        source_id=source_id,
        name=name or "Test Source",
        domain="example.test",
        country="FR",
        language=language,
        source_type=source_type,
        feed_url=feed_url,
        enabled=True,
        verification=VerificationState.FETCH_VERIFIED,
        verified_on="2026-11-14",
        license_type=license_type,
        license_evidence="Test fixture; not a real permission." ,
        modification_allowed=license_type in (LicenseType.CC_BY, LicenseType.PUBLIC_DOMAIN),
        summary_republication_allowed=license_type in (LicenseType.CC_BY, LicenseType.PUBLIC_DOMAIN),
        attribution_text=name or "Test Source",
        default_category=category.value if category else None,
    )


def make_article(
    title: str,
    url: str,
    *,
    publisher: str = "Test Source",
    source_id: str = "test-src",
    language: str = "fr",
    published_at: datetime | None = None,
    category: Category = Category.OTHER,
) -> Article:
    published = published_at or datetime.now(UTC) - timedelta(hours=1)
    return Article(
        id=article_id_for(url),
        url=url,
        canonical_url=url,
        content_hash=content_hash_for(title, url),
        title=title,
        publisher=publisher,
        domain=url.split("/")[2],
        language=language,
        source_id=source_id,
        published_at=published,
        discovered_at=datetime.now(UTC),
        category=category,
    )


@pytest.fixture
def source() -> NewsSource:
    return make_source()
