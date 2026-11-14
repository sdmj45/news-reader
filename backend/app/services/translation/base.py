"""The translation interface.

Specification section 8 requires that the application not depend on a paid AI API, and that
summarisation and translation be pluggable. Both follow from one rule here: a `Translator` is
a small protocol, and every call site handles a provider returning nothing.

Three properties every implementation must have, because the alternative is a product that
quietly costs money or quietly lies:

* **A budget it cannot exceed.** Translation is the only outbound cost in this project.
  :class:`TranslationBudget` is enforced by the runner, not by the provider, so a provider
  cannot spend past it by being chatty.
* **No invention.** A provider that cannot translate returns ``None``. It never returns the
  source text pretending it is a translation, and never a partial result presented as
  complete.
* **Recorded provenance.** Every result carries the provider and a version, which the article
  stores. A reader, and a later audit, can always tell machine output from a publisher's own
  words.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TranslationRequest:
    text: str
    source_language: str
    target_language: str


@dataclass(frozen=True)
class TranslationResult:
    """One successful translation. Absence is represented by ``None``, never by an empty one."""

    text: str
    provider: str
    provider_version: str
    #: Provider's own confidence, 0-1, where it reports one. ``None`` when it does not.
    match: float | None = None
    characters_charged: int = 0


@dataclass
class TranslationBudget:
    """A hard character and call ceiling for one run. Enforced by the runner."""

    max_calls: int
    max_characters: int = 0
    calls_used: int = 0
    characters_used: int = 0
    #: Why the budget stopped, if it did. Surfaced in the report rather than only logged.
    exhausted_reason: str | None = None

    def can_afford(self, characters: int) -> bool:
        if self.calls_used >= self.max_calls:
            self.exhausted_reason = f"call budget reached ({self.max_calls})"
            return False
        if self.max_characters and self.characters_used + characters > self.max_characters:
            self.exhausted_reason = (
                f"character budget reached ({self.characters_used}/{self.max_characters})"
            )
            return False
        return True

    def charge(self, characters: int) -> None:
        self.calls_used += 1
        self.characters_used += characters


@dataclass
class TranslationReport:
    """What one translation pass did. Every number is measured, including the refusals."""

    articles_considered: int = 0
    articles_skipped_license: int = 0
    articles_skipped_already_done: int = 0
    articles_skipped_budget: int = 0
    articles_skipped_same_language: int = 0
    translated: int = 0
    failed: int = 0
    characters_sent: int = 0
    provider: str = "null"
    #: True when the pass stopped early because the provider's allowance ran out. Not an
    #: error: the articles already translated are kept, and the rest are retried next run.
    quota_exhausted: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        attempted = self.translated + self.failed
        return self.translated / attempted if attempted else 0.0


class TranslationError(Exception):
    """A provider could not translate. Carries a reason; never swallowed into silence."""


class TranslationQuotaExceeded(TranslationError):
    """The provider's allowance is gone until it resets.

    Distinct from an ordinary failure because the right response is different: one article
    failing means try the next one, the quota being gone means **stop**. Measured on
    2026-11-14 against MyMemory's free tier, the difference was eighty pointless requests to
    a service that had already said no, which is both slow and rude to a free provider.
    """


@runtime_checkable
class Translator(Protocol):
    """Translates short text. Implementations must be safe to call concurrently."""

    name: str
    version: str

    async def translate(self, request: TranslationRequest) -> TranslationResult | None:
        """Returns the translation, or ``None`` when this provider cannot produce one.

        Must not raise for an ordinary failure - a timeout, a quota, an unsupported language
        pair. Those return ``None`` and are counted. Raising is reserved for a misconfigured
        provider, which is a programming error rather than a runtime condition.
        """
        ...

    def supports(self, source_language: str, target_language: str) -> bool: ...
