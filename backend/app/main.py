"""The FastAPI application.

Read-only by design. Every endpoint is a GET; nothing a browser can reach writes to the
database. Collection and translation run as separate processes (``scripts/ingest.py``,
``scripts/translate.py``), which is what Phase 5 will schedule as Cloud Run Jobs. The API
therefore needs no authentication to be safe against writes, and the read surface is public
news metadata.

Favourites are deliberately **not** an endpoint. They live in the reader's browser until
there are user accounts to attach them to, because an unauthenticated favourites API is
either a shared mutable list or a tracking identifier, and neither is wanted here.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import articles, meta
from app.core.config import get_settings
from app.models.rights import guard_personal_use

logger = logging.getLogger(__name__)

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")

# Refuses at import time, not on the first request: a misconfigured instance should fail to
# start rather than serve for an hour and then be discovered.
guard_personal_use(settings)

app = FastAPI(
    title="News Reader API",
    version="0.2.0",
    summary="French news with Chinese translation, for a private household.",
    description=(
        "Read-only access to collected news metadata.\n\n"
        "**Attribution.** Every article carries its publisher, its licence and a link to the "
        "original. Headlines are the publishers' own words; anything under `translation` is "
        "machine output and is labelled with the model that produced it.\n\n"
        "**Licensing.** Most sources are registered as `UNKNOWN`, which means this service "
        "stores and serves the headline, publisher, timestamp and link only. See "
        "`docs/COPYRIGHT_POLICY.md`."
    ),
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    # An explicit list, never "*": the API is read-only today, but a wildcard origin is a
    # default that outlives the reason it was acceptable.
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
    max_age=600,
)

app.include_router(meta.router)
app.include_router(articles.router, prefix="/api/v1")
app.include_router(meta.router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"service": "news-reader", "docs": "/docs", "health": "/health"}
