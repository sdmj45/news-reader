"""Chooses a repository implementation from configuration.

The only place in the application that knows which backend is in use. Importing Firestore is
deferred into the branch that needs it so that the default install - and therefore the whole
test suite - does not require ``google-cloud-firestore``.
"""

from __future__ import annotations

from app.core.config import DatabaseBackend, Settings
from app.repositories.base import ArticleRepository
from app.repositories.sqlite_repository import SQLiteArticleRepository


def build_repository(settings: Settings) -> ArticleRepository:
    if settings.database_backend is DatabaseBackend.SQLITE:
        return SQLiteArticleRepository(settings.sqlite_path)

    if settings.database_backend is DatabaseBackend.FIRESTORE:
        try:
            from app.repositories.firestore_repository import FirestoreArticleRepository
        except ImportError as exc:  # pragma: no cover - depends on an optional install
            raise RuntimeError(
                "DATABASE_BACKEND=firestore requires the optional cloud dependencies: "
                "pip install -r requirements-cloud.txt"
            ) from exc
        return FirestoreArticleRepository(
            project_id=settings.gcp_project_id or None,
            database=settings.firestore_database,
        )

    raise RuntimeError(f"unsupported database backend: {settings.database_backend}")
