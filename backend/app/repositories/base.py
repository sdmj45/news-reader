"""The storage interface.

Specification section 2.1 requires that the database can be replaced without rewriting
business logic, and names Firestore as the production target with SQLite acceptable locally.
That is only true if nothing above this layer knows which one is in use, so this module
defines the contract in terms the application cares about - "the newest articles in this
category" - and never in terms either backend's query language.

Two constraints come from Firestore and are therefore part of the contract even though SQLite
would not need them:

* **Pagination is cursor-based, not offset-based.** Firestore charges per document read and
  has no efficient OFFSET; an offset API would quietly cost a full scan per page.
* **Writes are upserts keyed on the article id.** Collection re-reads the same articles
  constantly, and an insert-or-fail API would make every run a conflict-handling exercise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.models.article import Article, Category
from app.models.source import SourceHealth


@dataclass(frozen=True)
class ArticleQuery:
    """Filters for a list of articles. Every field is optional; all supplied ones must match."""

    categories: tuple[Category, ...] = ()
    languages: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    publishers: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    published_after: datetime | None = None
    published_before: datetime | None = None
    #: Free-text search over the title. Matching is backend-specific and documented per class.
    search: str | None = None
    #: Exclude records already marked as duplicates of another article.
    exclude_duplicates: bool = True
    limit: int = 50
    #: Opaque token from a previous :class:`Page`. Never constructed by the caller.
    cursor: str | None = None


@dataclass
class Page:
    """One page of results plus the token for the next one."""

    articles: list[Article]
    next_cursor: str | None = None

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


@dataclass
class UpsertReport:
    """What a write actually changed, so a collection run can report new versus seen."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


@runtime_checkable
class ArticleRepository(Protocol):
    """Storage for articles and per-source collection health."""

    def upsert_articles(self, articles: list[Article]) -> UpsertReport:
        """Inserts or updates by ``Article.id``.

        ``unchanged`` counts records whose ``content_hash`` already matched, which is the
        common case on every run after the first and the reason this is worth measuring.
        """
        ...

    def get_article(self, article_id: str) -> Article | None: ...

    def list_articles(self, query: ArticleQuery) -> Page: ...

    def count_articles(self) -> int: ...

    def existing_ids(self, article_ids: list[str]) -> set[str]:
        """Which of these ids are already stored. Used to skip work before enrichment."""
        ...

    def list_untranslated(self, target_language: str, limit: int = 50) -> list[Article]:
        """Newest articles whose licence permits a translation and that lack one.

        A named operation rather than an :class:`ArticleQuery` flag: "does this JSON object
        have this key" is expressed very differently in SQLite and in Firestore, and
        pretending otherwise would push one backend's syntax into the contract.
        """
        ...

    def count_translated(self, target_language: str) -> int: ...

    def count_by_category(self, language: str | None = None) -> dict[str, int]: ...

    def count_by_language(self) -> dict[str, int]: ...

    def distinct_publishers(self) -> list[str]: ...

    def save_source_health(self, health: SourceHealth) -> None: ...

    def get_source_health(self, source_id: str) -> SourceHealth | None: ...

    def list_source_health(self) -> list[SourceHealth]: ...

    def save_collection_run(self, run: dict) -> None:
        """Appends one run's report. Kept as a plain dict: it is a log, not a domain object."""
        ...

    def list_collection_runs(self, limit: int = 20) -> list[dict]: ...
