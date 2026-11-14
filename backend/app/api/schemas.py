"""Wire format for the REST API.

Separate from the domain models on purpose. Two things the API must guarantee that the domain
objects do not:

* **The reader can always tell whose words they are reading.** ``title`` is the publisher's;
  ``title_translated`` is machine output, and it carries ``translation_provider`` so the
  distinction survives the network boundary rather than living only in a database column.
* **Nothing internal leaks.** ``content_hash``, ``discovered_at`` and the processing status
  are operational details; a public client has no use for them and shipping them makes them
  part of the contract.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.article import Article
from app.models.source import NewsSource


class TranslationInfo(BaseModel):
    """Machine translations, kept in their own object so they can never be mistaken for copy."""

    title: dict[str, str] = Field(default_factory=dict, description="Translated headline by language")
    summary: dict[str, str] = Field(default_factory=dict, description="Translated description by language")
    provider: str | None = Field(None, description="Model that produced these, with its version")
    generated_at: datetime | None = None


class ArticleOut(BaseModel):
    id: str
    title: str = Field(description="The publisher's headline, verbatim")
    url: str = Field(description="The original article, on the publisher's site")
    publisher: str
    domain: str
    language: str
    country: str | None = None
    category: str
    secondary_categories: list[str] = Field(default_factory=list)
    published_at: datetime
    author: str | None = None
    image_url: str | None = None

    description: str | None = Field(
        None, description="The publisher's own description. Null when the licence withholds it."
    )
    description_withheld_reason: str | None = Field(
        None, description="Why `description` is null although the feed supplied one."
    )

    translation: TranslationInfo = Field(default_factory=TranslationInfo)

    license: str = Field(description="Effective licence for this article in this deployment")
    attribution: str
    event_id: str | None = Field(
        None, description="Shared by articles covering the same event. Null when unique."
    )

    @classmethod
    def of(cls, article: Article) -> ArticleOut:
        return cls(
            id=article.id,
            title=article.title,
            url=article.url or article.canonical_url,
            publisher=article.publisher,
            domain=article.domain,
            language=article.language,
            country=article.country,
            category=article.category.value,
            secondary_categories=[c.value for c in article.secondary_categories],
            published_at=article.published_at,
            author=article.author,
            image_url=article.image_url,
            description=article.original_description,
            description_withheld_reason=article.description_withheld_reason,
            translation=TranslationInfo(
                title=article.translated_title,
                summary=article.translated_summary,
                provider=article.provenance.translation_model,
                generated_at=article.provenance.translation_generated_at,
            ),
            license=article.license_status.value,
            attribution=article.attribution_text,
            event_id=article.event_id,
        )


class ArticlePage(BaseModel):
    """A page of articles. ``next_cursor`` is opaque and must be passed back unmodified."""

    articles: list[ArticleOut]
    next_cursor: str | None = None
    has_more: bool = False


class SourceOut(BaseModel):
    """A source as the frontend needs it: enough to filter and to attribute, no more."""

    source_id: str
    name: str
    domain: str
    country: str
    language: str
    category: str | None = None
    license: str
    attribution: str
    translation_permitted: bool = Field(
        description="Whether this deployment may publish a translation of this source"
    )

    @classmethod
    def of(cls, source: NewsSource) -> SourceOut:
        return cls(
            source_id=source.source_id,
            name=source.name,
            domain=source.domain,
            country=source.country,
            language=source.language,
            category=source.default_category,
            license=source.license_type.value,
            attribution=source.attribution_text or source.name,
            translation_permitted=source.summary_republication_allowed,
        )


class CategoryCount(BaseModel):
    category: str
    count: int


class HealthOut(BaseModel):
    status: str
    articles: int
    sources_enabled: int
    last_collection: str | None = None
    personal_use_mode: bool
    translator: str


class StatsOut(BaseModel):
    """What the last runs measured. The honest view of whether the thing is working."""

    articles_total: int
    articles_by_language: dict[str, int]
    articles_by_category: dict[str, int]
    translated_counts: dict[str, int]
    publishers: int
    recent_runs: list[dict]
