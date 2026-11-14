"""SQLite implementation of :class:`~app.repositories.base.ArticleRepository`.

Used for local development, for the whole test suite, and for the Cloud Run Job's dry runs.
Deliberately written with the standard-library ``sqlite3`` driver and no ORM: the schema is
nine columns of denormalised article plus two small tables, an ORM would add a dependency and
a mapping layer for no benefit, and the Firestore implementation will not share any of it
anyway.

The schema mirrors what Firestore will hold, including its awkward parts - list fields stored
as JSON, cursor pagination rather than OFFSET - so that behaviour measured here transfers.
Where SQLite would allow something Firestore will not, this class refuses it too; a local
backend that is more permissive than production is a way of discovering problems late.

Indexes follow specification section 6: ``published_at``, ``category``, ``language``,
``country``, ``publisher``, ``source_id`` and ``canonical_url``.
"""

from __future__ import annotations

import json
import sqlite3
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from pathlib import Path

from app.models.article import Article, Category, ProcessingStatus, Provenance
from app.models.licensing import LicenseType
from app.models.source import SourceHealth
from app.repositories.base import ArticleQuery, Page, UpsertReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id                          TEXT PRIMARY KEY,
    url                         TEXT NOT NULL,
    canonical_url               TEXT NOT NULL UNIQUE,
    content_hash                TEXT NOT NULL,
    title                       TEXT NOT NULL,
    original_title              TEXT NOT NULL DEFAULT '',
    publisher                   TEXT NOT NULL,
    domain                      TEXT NOT NULL,
    country                     TEXT,
    language                    TEXT NOT NULL,
    source_id                   TEXT NOT NULL,
    published_at                TEXT NOT NULL,
    discovered_at               TEXT NOT NULL,
    author                      TEXT,
    image_url                   TEXT,
    original_description        TEXT,
    description_withheld_reason TEXT,
    offered_description_chars   INTEGER NOT NULL DEFAULT 0,
    category                    TEXT NOT NULL,
    secondary_categories        TEXT NOT NULL DEFAULT '[]',
    license_status              TEXT NOT NULL,
    summary_reuse_allowed       INTEGER NOT NULL DEFAULT 0,
    attribution_text            TEXT NOT NULL DEFAULT '',
    generated_summary           TEXT,
    translated_summary          TEXT NOT NULL DEFAULT '{}',
    provenance                  TEXT NOT NULL DEFAULT '{}',
    body_paragraphs             TEXT NOT NULL DEFAULT '[]',
    processing_status           TEXT NOT NULL,
    duplicate_of                TEXT,
    event_id                    TEXT,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_articles_published  ON articles(published_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_articles_category   ON articles(category, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_language   ON articles(language, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_country    ON articles(country, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_publisher  ON articles(publisher, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_source     ON articles(source_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_canonical  ON articles(canonical_url);
CREATE INDEX IF NOT EXISTS idx_articles_event      ON articles(event_id);

CREATE TABLE IF NOT EXISTS source_health (
    source_id             TEXT PRIMARY KEY,
    last_successful_fetch TEXT,
    last_attempted_fetch  TEXT,
    last_error            TEXT,
    consecutive_failures  INTEGER NOT NULL DEFAULT 0,
    total_items_collected INTEGER NOT NULL DEFAULT 0,
    recent_outcomes       TEXT NOT NULL DEFAULT '[]',
    etag                  TEXT,
    last_modified         TEXT,
    cursor                TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_runs (
    run_id     TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    report     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON collection_runs(started_at DESC);
"""


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class SQLiteArticleRepository:
    """A file-backed or in-memory article store. Not thread-safe; one instance per worker."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        # WAL lets the API read while a collection job writes. Harmless in memory.
        if self._path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SQLiteArticleRepository:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ articles

    def upsert_articles(self, articles: list[Article]) -> UpsertReport:
        report = UpsertReport()
        if not articles:
            return report

        existing = {
            row["id"]: row["content_hash"]
            for row in self._conn.execute(
                f"SELECT id, content_hash FROM articles WHERE id IN "
                f"({','.join('?' * len(articles))})",
                [a.id for a in articles],
            )
        }

        now = _iso(datetime.now(UTC))
        for article in articles:
            previous = existing.get(article.id)
            if previous is None:
                report.inserted += 1
            elif previous == article.content_hash:
                report.unchanged += 1
                # Still written: enrichment fields may have changed even when the headline
                # and URL did not, and skipping the write would lose a new summary.
            else:
                report.updated += 1
            article.updated_at = datetime.now(UTC)
            self._conn.execute(_UPSERT_SQL, _row_of(article, now))

        self._conn.commit()
        return report

    def get_article(self, article_id: str) -> Article | None:
        row = self._conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return _article_of(row) if row else None

    def existing_ids(self, article_ids: list[str]) -> set[str]:
        if not article_ids:
            return set()
        found: set[str] = set()
        # SQLite's parameter limit is 999 by default; chunking keeps a large GDELT batch from
        # tripping it, and mirrors the 'in' limit Firestore imposes for the same query.
        for start in range(0, len(article_ids), 500):
            chunk = article_ids[start : start + 500]
            rows = self._conn.execute(
                f"SELECT id FROM articles WHERE id IN ({','.join('?' * len(chunk))})", chunk
            )
            found.update(row["id"] for row in rows)
        return found

    def count_articles(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM articles").fetchone()["n"]

    def list_articles(self, query: ArticleQuery) -> Page:
        where: list[str] = []
        params: list[object] = []

        def in_clause(column: str, values: tuple[str, ...]) -> None:
            if values:
                where.append(f"{column} IN ({','.join('?' * len(values))})")
                params.extend(values)

        in_clause("category", tuple(c.value for c in query.categories))
        in_clause("language", query.languages)
        in_clause("country", query.countries)
        in_clause("publisher", query.publishers)
        in_clause("source_id", query.source_ids)

        if query.published_after:
            where.append("published_at >= ?")
            params.append(_iso(query.published_after))
        if query.published_before:
            where.append("published_at <= ?")
            params.append(_iso(query.published_before))
        if query.exclude_duplicates:
            where.append("duplicate_of IS NULL")
        if query.search:
            # LIKE on the title only. Deliberately modest: Firestore cannot do substring search
            # at all, so anything richer here would be a local-only feature that disappears in
            # production. Full-text search is a separate decision, recorded in docs/.
            where.append("LOWER(title) LIKE ?")
            params.append(f"%{query.search.lower()}%")

        # Cursor pagination on (published_at, id): the tuple is unique, so no row is skipped or
        # repeated when several articles share a timestamp - which they constantly do.
        if query.cursor:
            cursor_published, cursor_id = _decode_cursor(query.cursor)
            where.append("(published_at < ? OR (published_at = ? AND id < ?))")
            params.extend([cursor_published, cursor_published, cursor_id])

        clause = f"WHERE {' AND '.join(where)}" if where else ""
        limit = max(1, min(query.limit, 200))
        rows = self._conn.execute(
            f"SELECT * FROM articles {clause} ORDER BY published_at DESC, id DESC LIMIT ?",
            [*params, limit + 1],
        ).fetchall()

        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            _encode_cursor(rows[-1]["published_at"], rows[-1]["id"]) if has_more and rows else None
        )
        return Page(articles=[_article_of(r) for r in rows], next_cursor=next_cursor)

    def distinct_publishers(self) -> list[str]:
        return [r["publisher"] for r in
                self._conn.execute("SELECT DISTINCT publisher FROM articles ORDER BY publisher")]

    # ------------------------------------------------------------------ source health

    def save_source_health(self, health: SourceHealth) -> None:
        now = _iso(datetime.now(UTC))
        self._conn.execute(
            """INSERT INTO source_health
               (source_id, last_successful_fetch, last_attempted_fetch, last_error,
                consecutive_failures, total_items_collected, recent_outcomes,
                etag, last_modified, cursor, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET
                 last_successful_fetch=excluded.last_successful_fetch,
                 last_attempted_fetch=excluded.last_attempted_fetch,
                 last_error=excluded.last_error,
                 consecutive_failures=excluded.consecutive_failures,
                 total_items_collected=excluded.total_items_collected,
                 recent_outcomes=excluded.recent_outcomes,
                 etag=excluded.etag,
                 last_modified=excluded.last_modified,
                 cursor=excluded.cursor,
                 updated_at=excluded.updated_at""",
            (
                health.source_id, _iso(health.last_successful_fetch),
                _iso(health.last_attempted_fetch), health.last_error,
                health.consecutive_failures, health.total_items_collected,
                json.dumps(health.recent_outcomes[:20]),
                health.etag, health.last_modified, health.cursor,
                _iso(health.created_at) or now, now,
            ),
        )
        self._conn.commit()

    def get_source_health(self, source_id: str) -> SourceHealth | None:
        row = self._conn.execute(
            "SELECT * FROM source_health WHERE source_id = ?", (source_id,)
        ).fetchone()
        return _health_of(row) if row else None

    def list_source_health(self) -> list[SourceHealth]:
        return [_health_of(r) for r in self._conn.execute("SELECT * FROM source_health")]

    # ------------------------------------------------------------------ run log

    def save_collection_run(self, run: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO collection_runs (run_id, started_at, report) VALUES (?,?,?)",
            (run["run_id"], run["started_at"], json.dumps(run, ensure_ascii=False, default=str)),
        )
        self._conn.commit()

    def list_collection_runs(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT report FROM collection_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        )
        return [json.loads(r["report"]) for r in rows]


# ---------------------------------------------------------------------- row mapping

_COLUMNS = ["id", "url", "canonical_url", "content_hash", "title", "original_title", "publisher", "domain", "country", "language", "source_id", "published_at", "discovered_at", "author", "image_url", "original_description", "description_withheld_reason", "offered_description_chars", "category", "secondary_categories", "license_status", "summary_reuse_allowed", "attribution_text", "generated_summary", "translated_summary", "provenance", "body_paragraphs", "processing_status", "duplicate_of", "event_id", "created_at", "updated_at"]

_UPSERT_SQL = (
    f"INSERT INTO articles ({','.join(_COLUMNS)}) VALUES ({','.join('?' * len(_COLUMNS))}) "
    f"ON CONFLICT(id) DO UPDATE SET "
    + ",".join(f"{c}=excluded.{c}" for c in _COLUMNS if c not in ("id", "created_at"))
)


def _row_of(article: Article, now: str) -> tuple:
    return (
        article.id, article.url, article.canonical_url, article.content_hash,
        article.title, article.original_title, article.publisher, article.domain,
        article.country, article.language, article.source_id,
        _iso(article.published_at), _iso(article.discovered_at),
        article.author, article.image_url, article.original_description,
        article.description_withheld_reason, article.offered_description_chars,
        article.category.value, json.dumps([c.value for c in article.secondary_categories]),
        article.license_status.value, int(article.summary_reuse_allowed),
        article.attribution_text, article.generated_summary,
        json.dumps(article.translated_summary, ensure_ascii=False),
        json.dumps(
            {k: _iso(v) if isinstance(v, datetime) else v
             for k, v in vars(article.provenance).items()}
        ),
        json.dumps(article.body_paragraphs, ensure_ascii=False),
        article.processing_status.value, article.duplicate_of, article.event_id,
        _iso(article.created_at) or now, _iso(article.updated_at) or now,
    )


def _article_of(row: sqlite3.Row) -> Article:
    provenance_data = json.loads(row["provenance"] or "{}")
    provenance = Provenance(
        summary_model=provenance_data.get("summary_model"),
        summary_prompt_version=provenance_data.get("summary_prompt_version"),
        summary_generated_at=_dt(provenance_data.get("summary_generated_at")),
        translation_model=provenance_data.get("translation_model"),
        translation_prompt_version=provenance_data.get("translation_prompt_version"),
        translation_generated_at=_dt(provenance_data.get("translation_generated_at")),
    )
    return Article(
        id=row["id"], url=row["url"], canonical_url=row["canonical_url"],
        content_hash=row["content_hash"], title=row["title"],
        original_title=row["original_title"], publisher=row["publisher"],
        domain=row["domain"], country=row["country"], language=row["language"],
        source_id=row["source_id"],
        published_at=_dt(row["published_at"]), discovered_at=_dt(row["discovered_at"]),
        author=row["author"], image_url=row["image_url"],
        original_description=row["original_description"],
        description_withheld_reason=row["description_withheld_reason"],
        offered_description_chars=row["offered_description_chars"],
        category=Category(row["category"]),
        secondary_categories=[Category(c) for c in json.loads(row["secondary_categories"])],
        license_status=LicenseType(row["license_status"]),
        summary_reuse_allowed=bool(row["summary_reuse_allowed"]),
        attribution_text=row["attribution_text"],
        generated_summary=row["generated_summary"],
        translated_summary=json.loads(row["translated_summary"]),
        provenance=provenance,
        body_paragraphs=json.loads(row["body_paragraphs"]),
        processing_status=ProcessingStatus(row["processing_status"]),
        duplicate_of=row["duplicate_of"], event_id=row["event_id"],
        created_at=_dt(row["created_at"]), updated_at=_dt(row["updated_at"]),
    )


def _health_of(row: sqlite3.Row) -> SourceHealth:
    return SourceHealth(
        source_id=row["source_id"],
        last_successful_fetch=_dt(row["last_successful_fetch"]),
        last_attempted_fetch=_dt(row["last_attempted_fetch"]),
        last_error=row["last_error"],
        consecutive_failures=row["consecutive_failures"],
        total_items_collected=row["total_items_collected"],
        recent_outcomes=json.loads(row["recent_outcomes"]),
        etag=row["etag"],
        last_modified=row["last_modified"],
        cursor=row["cursor"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _encode_cursor(published_at: str, article_id: str) -> str:
    return urlsafe_b64encode(f"{published_at}|{article_id}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        published_at, article_id = urlsafe_b64decode(padded).decode().split("|", 1)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"malformed pagination cursor: {cursor!r}") from exc
    return published_at, article_id
