"""Application settings, read from the environment.

Nothing in this file has a default that costs money or reaches a paid service. The database
defaults to a local SQLite file, the summariser defaults to the null implementation, and
Firestore is used only when ``DATABASE_BACKEND=firestore`` is set deliberately. Specification
section 12 requires that no paid service is ever activated silently, and a permissive default
is how that happens.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class DatabaseBackend(str, Enum):
    SQLITE = "sqlite"
    FIRESTORE = "firestore"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: AppEnv = AppEnv.LOCAL
    log_level: str = "INFO"

    # --- Storage -----------------------------------------------------------------
    database_backend: DatabaseBackend = DatabaseBackend.SQLITE
    sqlite_path: str = "data/news.db"
    #: Only read when the backend is Firestore. Empty means "use application default".
    gcp_project_id: str = ""
    firestore_database: str = "(default)"

    # --- Collection ----------------------------------------------------------------
    collector_timeout_seconds: float = 20.0
    collector_max_attempts: int = 3
    #: Concurrent feed fetches. Low on purpose: thirty simultaneous requests at a publisher is
    #: the behaviour that gets an aggregator blocked, and the run is not latency-critical.
    collector_max_concurrency: int = 6
    #: Minimum seconds between two requests to the same host.
    collector_min_host_interval: float = 1.0
    #: GAL files to read per run. Each is roughly 1,800 articles.
    gdelt_files_per_run: int = 2
    #: Sources to collect from. Empty means every enabled source in the registry.
    collector_only_sources: str = ""

    # --- Rights ---------------------------------------------------------------------
    #: Asserts that this instance serves one private household and republishes nothing.
    #: Off by default. See app/models/rights.py for what it does and does not unlock.
    #: Refused outright when APP_ENV=production.
    personal_use_mode: bool = False

    # --- Enrichment ------------------------------------------------------------------
    #: "null" generates nothing. Any other value must be an implemented provider.
    summariser: str = "null"
    #: Hard stop on enrichment spend. Zero means the summariser never runs.
    summary_daily_budget_calls: int = 0

    #: "null" or "mymemory". MyMemory is free and needs no key; see
    #: app/services/translation/mymemory.py for its measured quota.
    translator: str = "mymemory"
    #: Target languages for translation, comma-separated.
    translate_into: str = "zh"
    #: Articles attempted per run. The character budget below is the binding constraint;
    #: this just stops a single run walking the whole table.
    translate_max_per_run: int = 100

    #: Days of news kept, counted from publication. One window governs everything: older
    #: articles are not collected, are deleted after each collection, are not translated and
    #: are not exported. It has to be the same window for all four - an article deleted but
    #: still in a feed would be collected again as new and translated again, every run.
    #:
    #: 0 keeps everything, which is what the tests use: their fixtures are real feeds captured
    #: on a fixed date.
    retention_days: int = 2

    #: Sections this reader does not want, comma-separated category names. Articles whose
    #: primary category is one of these are dropped at collection, so they are never stored,
    #: translated or shown. Matched on the primary category only: a technology desk's story
    #: that mentions a football club is still a technology story.
    excluded_categories: str = "SPORTS,CULTURE,ENVIRONMENT,HEALTH"

    #: Hard character ceiling per run, enforced before each call. **This is the setting that
    #: matters**, because the provider's limit is in characters, not articles.
    #:
    #: Measured on real data: an average headline is 77 characters and an average
    #: description 260. MyMemory allows ~5,000 characters a day anonymously and ~50,000 with
    #: a contact address. At eight runs a day that is ~600 characters per run anonymously,
    #: or ~6,000 with the address. The default is the conservative one; raise it in the
    #: deployment once TRANSLATE_CONTACT_EMAIL is set.
    translate_max_characters_per_run: int = 600

    #: The provider's daily allowance in characters. When set (> 0), each run spends what is
    #: left of today's allowance, keeping TRANSLATE_MAX_CHARACTERS_PER_RUN in reserve for
    #: each run still to come today - so a backlog is cleared in one run instead of
    #: trickling through at a fixed slice per run. 0 keeps the fixed per-run budget.
    translate_daily_characters: int = 0
    #: How many times a day the pipeline runs; used to size that reserve.
    translate_runs_per_day: int = 8

    #: Whether to translate the publisher's description as well as the headline.
    #:
    #: Off by default, and that is a budget decision rather than a feature one. A
    #: description is 260 characters against a headline's 77, so translating both cuts the
    #: number of articles a day's quota covers by more than three quarters - from ~650
    #: headlines to ~150 pairs. The headline is what this product is for; a reader who wants
    #: more opens the article.
    translate_descriptions: bool = False
    #: Sent to MyMemory to raise the daily quota from 5,000 to 50,000 characters. Optional,
    #: not a credential - it is a contact address, and MyMemory documents it as such.
    translate_contact_email: str = ""

    #: Articles kept from one domain per GDELT run. Zero disables the cap. See
    #: MAX_ARTICLES_PER_DOMAIN for the measurement that produced the default.
    gdelt_max_per_domain: int = 5

    #: Restrict GDELT to these languages. GAL is a 40-language firehose and this product
    #: reads French news; without this, 94% of what it collects is noise.
    gdelt_languages: str = "fr"

    # --- API ---------------------------------------------------------------------------
    api_cors_origins: str = "http://localhost:5173"
    api_rate_limit_per_minute: int = 120

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @property
    def is_production(self) -> bool:
        return self.app_env is AppEnv.PRODUCTION

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def only_sources(self) -> tuple[str, ...]:
        return tuple(s.strip() for s in self.collector_only_sources.split(",") if s.strip())

    @property
    def gdelt_language_filter(self) -> frozenset[str]:
        """Empty means no filter - every language GAL supplies is kept."""
        return frozenset(s.strip().lower() for s in self.gdelt_languages.split(",") if s.strip())

    @property
    def target_languages(self) -> tuple[str, ...]:
        return tuple(s.strip().lower() for s in self.translate_into.split(",") if s.strip())

    @property
    def excluded_category_names(self) -> frozenset[str]:
        return frozenset(
            s.strip().upper() for s in self.excluded_categories.split(",") if s.strip()
        )

    def retention_cutoff(self, now: datetime | None = None) -> datetime | None:
        """The oldest publication time still kept, or None when retention is off."""
        if self.retention_days <= 0:
            return None
        return (now or datetime.now(UTC)) - timedelta(days=self.retention_days)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
