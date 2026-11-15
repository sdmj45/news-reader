"""The normalised article record.

Fields follow specification section 6. The design rule that shapes this class: **publisher
metadata and machine-generated content never share a field.** ``original_description`` is what
the publisher wrote; ``generated_summary`` is what a model produced; ``translated_summary`` is
a machine translation of that. A reader, and a later copyright audit, can always tell which is
which, and ``provenance`` records the model and prompt version that produced the generated
parts.

No field here holds a full copyrighted article. ``body_paragraphs`` exists but is only ever
populated for sources whose licence permits full text (:func:`app.models.licensing.allows_full_text`),
and the ingestion pipeline checks that independently of the parser.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from app.models.licensing import LicenseType


class ProcessingStatus(str, Enum):
    """Where this article is in the enrichment pipeline."""

    COLLECTED = "COLLECTED"
    """Normalised and stored. No enrichment attempted."""

    CLASSIFIED = "CLASSIFIED"
    """A category has been assigned."""

    SUMMARY_SKIPPED_LICENSE = "SUMMARY_SKIPPED_LICENSE"
    """Deliberately not summarised: the source licence does not permit a derivative work."""

    SUMMARY_SKIPPED_NO_INPUT = "SUMMARY_SKIPPED_NO_INPUT"
    """Licence permits it, but there was no text to summarise beyond the headline."""

    SUMMARISED = "SUMMARISED"

    TRANSLATED = "TRANSLATED"
    """At least the headline has been translated into every configured target language."""

    TRANSLATION_SKIPPED_LICENSE = "TRANSLATION_SKIPPED_LICENSE"
    """Deliberately not translated: a translation is a derivative work and the licence forbids it."""

    TRANSLATION_FAILED = "TRANSLATION_FAILED"
    """The provider was asked and could not. Distinct from "we chose not to ask"."""

    FAILED = "FAILED"


class Category(str, Enum):
    """Specification section 9. ``OTHER`` is used when classification abstains."""

    FRANCE = "FRANCE"
    CHINA = "CHINA"
    """China, as a desk rather than a language: a Le Monde piece about Beijing belongs here
    as much as a BBC Chinese one. Separate from INTERNATIONAL because a reader who wants
    China news does not want it diluted by everything else that is not France."""
    INTERNATIONAL = "INTERNATIONAL"
    EUROPE = "EUROPE"
    POLITICS = "POLITICS"
    ECONOMY = "ECONOMY"
    TECHNOLOGY = "TECHNOLOGY"
    ARTIFICIAL_INTELLIGENCE = "ARTIFICIAL_INTELLIGENCE"
    SCIENCE = "SCIENCE"
    HEALTH = "HEALTH"
    ENVIRONMENT = "ENVIRONMENT"
    BUSINESS = "BUSINESS"
    FINANCE = "FINANCE"
    SPORTS = "SPORTS"
    CULTURE = "CULTURE"
    EDUCATION = "EDUCATION"
    OTHER = "OTHER"


@dataclass
class Provenance:
    """Which model and prompt produced the generated fields, so output stays traceable."""

    summary_model: str | None = None
    summary_prompt_version: str | None = None
    summary_generated_at: datetime | None = None
    translation_model: str | None = None
    translation_prompt_version: str | None = None
    translation_generated_at: datetime | None = None


@dataclass
class Article:
    """One article, normalised from whatever the collector found."""

    # --- Identity -----------------------------------------------------------------
    id: str
    url: str
    canonical_url: str
    content_hash: str

    # --- Publisher metadata (never machine-generated) -----------------------------
    title: str
    publisher: str
    domain: str
    language: str
    source_id: str
    published_at: datetime
    discovered_at: datetime
    #: The headline exactly as received, before whitespace and entity normalisation.
    original_title: str = ""
    country: str | None = None
    author: str | None = None
    image_url: str | None = None
    #: The publisher's own description. Stored only when the licence permits it; see
    #: ``description_withheld_reason`` when it does not.
    original_description: str | None = None
    #: Why a description that the feed *did* supply was not kept. Null when none was offered.
    description_withheld_reason: str | None = None
    #: Length of the description the feed offered, kept even when the text is discarded, so
    #: description coverage can be measured without storing the text.
    offered_description_chars: int = 0

    # --- Classification -----------------------------------------------------------
    category: Category = Category.OTHER
    secondary_categories: list[Category] = field(default_factory=list)

    # --- Licensing ------------------------------------------------------------------
    license_status: LicenseType = LicenseType.UNKNOWN
    summary_reuse_allowed: bool = False
    attribution_text: str = ""

    # --- Generated content (never publisher metadata) -------------------------------
    generated_summary: str | None = None
    #: Machine translations of ``title``, keyed by target language. Separate from ``title``
    #: so a reader always knows which words are the publisher's.
    translated_title: dict[str, str] = field(default_factory=dict)
    #: Machine translations of ``original_description`` (not of ``generated_summary``, which
    #: this product does not produce), keyed by target language.
    translated_summary: dict[str, str] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)
    body_paragraphs: list[str] = field(default_factory=list)

    # --- Pipeline state ---------------------------------------------------------------
    processing_status: ProcessingStatus = ProcessingStatus.COLLECTED
    #: Set when this article was judged a duplicate of another; points at the kept one.
    duplicate_of: str | None = None
    #: Shared id for articles covering the same event across publishers. Never merges rows.
    event_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.original_title:
            self.original_title = self.title
        now = datetime.now(UTC)
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now


def article_id_for(canonical_url: str) -> str:
    """Stable id derived from the canonical URL.

    Re-collecting the same article therefore updates the existing record rather than creating a
    second one, which makes the whole pipeline idempotent and a crashed run simply re-runnable.
    """
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:24]


def content_hash_for(title: str, canonical_url: str) -> str:
    """Hash over the fields that identify the *content*, used for change detection.

    Separate from :func:`article_id_for` so that a publisher editing a headline in place is
    detectable (same id, different hash) rather than invisible.
    """
    payload = f"{title}\x00{canonical_url}".encode()
    return hashlib.sha256(payload).hexdigest()
