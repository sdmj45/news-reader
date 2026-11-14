"""The default translator: produces nothing, costs nothing.

Exists so that the default configuration of this application makes no outbound request to any
language service at all, and so that every call site is exercised against a provider that
declines. A pipeline that only works when a provider answers is a pipeline that breaks the
first time one does not.
"""

from __future__ import annotations

from app.services.translation.base import TranslationRequest, TranslationResult


class NullTranslator:
    name = "null"
    version = "1"

    def supports(self, source_language: str, target_language: str) -> bool:
        return False

    async def translate(self, request: TranslationRequest) -> TranslationResult | None:
        return None
