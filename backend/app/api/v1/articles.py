"""Article endpoints: list, filter, search, and fetch one."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_repository, rate_limit
from app.api.schemas import ArticleOut, ArticlePage, CategoryCount
from app.models.article import Category
from app.repositories.base import ArticleQuery, ArticleRepository

router = APIRouter(prefix="/articles", tags=["articles"], dependencies=[Depends(rate_limit)])

#: Hard ceiling regardless of what a client asks for. Every page is a billed read in
#: Firestore, and an unbounded limit is how a client turns a free tier into a bill.
MAX_PAGE_SIZE = 100


@router.get("", response_model=ArticlePage, summary="List articles, newest first")
async def list_articles(
    repository: Annotated[ArticleRepository, Depends(get_repository)],
    category: Annotated[list[str] | None, Query(description="Repeatable.")] = None,
    language: Annotated[list[str] | None, Query(description="Repeatable. ISO 639-1.")] = None,
    country: Annotated[list[str] | None, Query(description="Repeatable.")] = None,
    publisher: Annotated[list[str] | None, Query(description="Repeatable.")] = None,
    source_id: Annotated[list[str] | None, Query(description="Repeatable.")] = None,
    q: Annotated[str | None, Query(description="Substring of the headline.", max_length=120)] = None,
    published_after: datetime | None = None,
    published_before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 30,
    cursor: Annotated[str | None, Query(description="From a previous page. Opaque.")] = None,
) -> ArticlePage:
    try:
        categories = tuple(Category(c.upper()) for c in (category or []))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown category. Valid values: {', '.join(c.value for c in Category)}",
        ) from exc

    query = ArticleQuery(
        categories=categories,
        languages=tuple(lang.lower() for lang in (language or [])),
        countries=tuple(country or []),
        publishers=tuple(publisher or []),
        source_ids=tuple(source_id or []),
        search=q,
        published_after=published_after,
        published_before=published_before,
        limit=limit,
        cursor=cursor,
    )
    try:
        page = repository.list_articles(query)
    except ValueError as exc:
        # A malformed cursor is the client's mistake, not a server fault.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return ArticlePage(
        articles=[ArticleOut.of(a) for a in page.articles],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get("/categories", response_model=list[CategoryCount], summary="Categories with counts")
async def list_categories(
    repository: Annotated[ArticleRepository, Depends(get_repository)],
    language: Annotated[str | None, Query(description="Count within one language only.")] = None,
) -> list[CategoryCount]:
    """Counts per category, so the navigation can hide sections that hold nothing."""
    counts = repository.count_by_category(language=language)
    return [CategoryCount(category=c, count=n) for c, n in counts.items()]


@router.get("/{article_id}", response_model=ArticleOut, summary="One article")
async def get_article(
    article_id: str,
    repository: Annotated[ArticleRepository, Depends(get_repository)],
) -> ArticleOut:
    article = repository.get_article(article_id)
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such article.")
    return ArticleOut.of(article)
