"""Request-scoped dependencies: settings, repository, and a rate limiter.

The rate limiter is written here rather than pulled in as a package. It is forty lines, it has
no dependencies, and the alternative (``slowapi``) brings in ``limits`` and a middleware stack
to do the same job. Its limitation is stated plainly in the docstring: it is per-process, so
on Cloud Run with N instances the effective limit is N times the configured one. For a family
instance that is irrelevant; before public launch it should be replaced with something backed
by shared state, and that is recorded in docs/OPERATIONS.md rather than left to be discovered.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.repositories.base import ArticleRepository
from app.repositories.factory import build_repository


@lru_cache(maxsize=1)
def _repository() -> ArticleRepository:
    """One repository per process.

    SQLite connections are not thread-safe, and FastAPI's sync endpoints run in a thread
    pool, so every endpoint in this application is ``async def`` and therefore runs on the
    event loop thread. If a sync endpoint is ever added, this needs a connection per thread.
    """
    return build_repository(get_settings())


def get_repository() -> ArticleRepository:
    return _repository()


def settings_dep() -> Settings:
    return get_settings()


class RateLimiter:
    """A fixed-window-per-client limiter. Per-process; see the module docstring."""

    def __init__(self, requests_per_minute: int) -> None:
        self._limit = requests_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, client: str) -> None:
        if self._limit <= 0:
            return
        now = time.monotonic()
        window = self._hits[client]
        while window and now - window[0] > 60.0:
            window.popleft()
        if len(window) >= self._limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit of {self._limit} requests per minute exceeded.",
                headers={"Retry-After": "60"},
            )
        window.append(now)
        # Clients that stopped calling would otherwise accumulate forever in a long-lived
        # process. Cheap to prune here; there is no background task to do it elsewhere.
        if len(self._hits) > 10_000:
            for key in [k for k, v in self._hits.items() if not v or now - v[-1] > 300]:
                del self._hits[key]


@lru_cache(maxsize=1)
def _limiter() -> RateLimiter:
    return RateLimiter(get_settings().api_rate_limit_per_minute)


async def rate_limit(request: Request) -> None:
    """Keys on the client address, or on X-Forwarded-For behind Cloud Run's proxy."""
    forwarded = request.headers.get("x-forwarded-for", "")
    client = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else "unknown"
    )
    _limiter().check(client)


RepositoryDep = Depends(get_repository)
SettingsDep = Depends(settings_dep)
RateLimited = Depends(rate_limit)
