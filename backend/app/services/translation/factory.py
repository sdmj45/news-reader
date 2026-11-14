"""Chooses a translator from configuration.

Defaults matter here more than anywhere else in the project: this is the only component that
makes an outbound request to a third party. An unknown provider name raises rather than
falling back to something that works, because a silent fallback is how a deployment ends up
using a service nobody chose.
"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.services.translation.base import Translator
from app.services.translation.mymemory import MyMemoryTranslator
from app.services.translation.null_translator import NullTranslator


def build_translator(settings: Settings, client: httpx.AsyncClient) -> Translator:
    name = (settings.translator or "null").strip().lower()
    if name in ("null", "none", "off", ""):
        return NullTranslator()
    if name == "mymemory":
        return MyMemoryTranslator(client, contact_email=settings.translate_contact_email)
    raise RuntimeError(
        f"unknown TRANSLATOR {settings.translator!r}. Implemented: null, mymemory. "
        f"Add a provider in app/services/translation/ rather than falling back silently."
    )
