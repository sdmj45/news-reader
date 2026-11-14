"""The news source record.

Fields follow specification section 4.3. Two of them carry more weight than the rest:

* ``license_type`` - see :mod:`app.models.licensing`. Defaults to ``UNKNOWN``, which means
  metadata only.
* ``verification`` - whether anyone has actually fetched this URL. A source that has not been
  fetched from a real host is not allowed to be enabled, enforced in ``__post_init__`` rather
  than by convention, so the registry table below cannot quietly acquire a guessed URL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.models.licensing import DEFAULT_LICENSE, LicenseType


class SourceType(str, Enum):
    RSS = "RSS"
    ATOM = "ATOM"
    GDELT_GAL_RSS = "GDELT_GAL_RSS"
    GDELT_GAL_JSONNL = "GDELT_GAL_JSONNL"
    PUBLIC_API = "PUBLIC_API"


class VerificationState(str, Enum):
    """How thoroughly this registry entry has been checked against the real endpoint."""

    FETCH_VERIFIED = "FETCH_VERIFIED"
    """Returned HTTP 200 and parsable content from a real host on ``verified_on``."""

    UNREACHABLE = "UNREACHABLE"
    """Probed and did not respond. The reason is in ``verification_note``."""

    UNVERIFIED = "UNVERIFIED"
    """Not probed. Must never be enabled."""


@dataclass(frozen=True)
class NewsSource:
    """One configured source. Frozen: the registry is a declaration, not mutable state.

    Runtime state (``last_successful_fetch``, ``last_error``) lives on the persisted source
    document in the repository layer, not here - see :class:`SourceHealth`.
    """

    source_id: str
    name: str
    domain: str
    country: str
    language: str
    source_type: SourceType
    feed_url: str
    enabled: bool
    verification: VerificationState
    license_type: LicenseType = DEFAULT_LICENSE
    attribution_required: bool = True
    commercial_reuse_allowed: bool = False
    modification_allowed: bool = False
    summary_republication_allowed: bool = False
    #: What the project considers permitted for this source's *metadata*, in prose, for the
    #: licence audit in docs/COPYRIGHT_POLICY.md.
    metadata_reuse_policy: str = "Title, publisher, publication time and original URL only."
    #: Where the licence claim comes from. Must cite something for any licence above UNKNOWN.
    license_evidence: str = "None recorded. Treated as UNKNOWN: metadata and link only."
    attribution_text: str = ""
    #: Default category applied to items from a section feed, e.g. a politics-only feed.
    default_category: str | None = None
    verified_on: str | None = None
    verified_item_count: int | None = None
    verification_note: str = ""
    fetch_interval_minutes: int = 30
    notes: str = ""

    def __post_init__(self) -> None:
        if self.enabled and self.verification is not VerificationState.FETCH_VERIFIED:
            raise ValueError(
                f"source {self.source_id!r} is enabled but its verification state is "
                f"{self.verification.value}. Only endpoints that have actually been fetched "
                f"may be enabled."
            )
        if self.license_type is not LicenseType.UNKNOWN and not self.license_evidence.strip():
            raise ValueError(
                f"source {self.source_id!r} claims licence {self.license_type.value} with no "
                f"evidence. Record where the permission comes from."
            )
        if self.summary_republication_allowed and not self.modification_allowed:
            raise ValueError(
                f"source {self.source_id!r} allows summary republication but not modification. "
                f"A summary is a derivative work; the two cannot disagree."
            )


@dataclass
class SourceHealth:
    """Mutable per-source collection state, persisted alongside the registry entry."""

    source_id: str
    last_successful_fetch: datetime | None = None
    last_attempted_fetch: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    total_items_collected: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    #: Rolling record of recent outcomes, newest first, for the retry policy.
    recent_outcomes: list[str] = field(default_factory=list)
    #: HTTP validators, sent back as If-None-Match / If-Modified-Since so an unchanged feed
    #: costs a 304 instead of a download. Set from the previous run's response headers.
    etag: str | None = None
    last_modified: str | None = None
    #: Provider-specific position marker for sources that are not a single stable URL. GDELT
    #: uses it to hold the newest GAL filename already read; RSS sources leave it null.
    cursor: str | None = None
