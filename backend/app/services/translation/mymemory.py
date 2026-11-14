"""MyMemory translation: free, no API key, documented quota.

Chosen as the default because specification section 12 targets €0/month and section 8 forbids
making the application depend on a paid AI API. MyMemory is a translation-memory service with
a public API that needs no account.

**Measured on 2026-11-14** against real French headlines:

===================================================  ====================================
``Présidentielle 2027 : Gérard Larcher invite ...``  ``2027年总统大选：热拉尔·拉尔舍邀请右翼候选人``
``Grève à la SNCF : trafic perturbé lundi ...``      ``法国国家铁路公司罢工：周一法国全境交通受阻``
``L'Assemblée nationale rejette la motion ...``      ``国民议会否决不信任动议``
===================================================  ====================================

Proper nouns survive transliteration and "SNCF" is expanded rather than dropped, which is
better than this tier of service usually manages.

**The quota is the real constraint, and it is small.** MyMemory documents roughly 5,000
translated characters per day anonymously, rising to about 50,000 with a contact address in
the request. A French headline is 60-90 characters, so an anonymous instance gets on the
order of 60 headlines a day. Three consequences, all implemented:

* Translation is a **separate pass**, not part of collection, so a quota exhaustion never
  costs an article.
* A translation is **stored permanently** on the article and never requested twice. The cost
  of a headline is paid once in the product's lifetime.
* The runner enforces a per-run budget *before* calling, so the service is never asked for
  something that cannot be paid for.

``translate_contact_email`` is not a credential. MyMemory documents it as a contact address
used to raise the anonymous quota, and it is sent in the clear in the query string; it is
configuration, and it is stored as such.
"""

from __future__ import annotations

import logging

import httpx

from app.services.translation.base import TranslationRequest, TranslationResult

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.mymemory.translated.net/get"

#: MyMemory rejects long inputs. Headlines and standfirsts are well inside this; anything
#: longer is refused locally rather than sent and rejected remotely.
MAX_CHARACTERS = 500

#: Language codes MyMemory expects, where they differ from ISO 639-1.
_LANGUAGE_CODES = {"zh": "zh-CN", "pt": "pt-PT"}

#: Below this self-reported match, the result is more likely a mangled memory hit than a
#: translation. Measured: real headline translations came back at 0.85.
MIN_MATCH = 0.5

#: Phrases MyMemory returns in ``responseData.translatedText`` when it has failed. It uses
#: HTTP 200 for these, so the body is the only signal.
_ERROR_MARKERS = (
    "MYMEMORY WARNING",
    "QUERY LENGTH LIMIT",
    "INVALID LANGUAGE PAIR",
    "PLEASE SELECT TWO DISTINCT LANGUAGES",
    "AUTO-DETECTED LANGUAGE",
)


class MyMemoryTranslator:
    """Free translation through MyMemory's public API."""

    name = "mymemory"
    version = "2026-11-14"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        contact_email: str = "",
        timeout: float = 15.0,
    ) -> None:
        self._client = client
        self._contact_email = contact_email.strip()
        self._timeout = timeout

    def supports(self, source_language: str, target_language: str) -> bool:
        if not source_language or not target_language:
            return False
        if source_language == target_language:
            return False
        # "und" means the language was never determined. Asking a translator to guess is how
        # French headlines come back "translated" from Spanish.
        return source_language != "und" and target_language != "und"

    async def translate(self, request: TranslationRequest) -> TranslationResult | None:
        text = request.text.strip()
        if not text or len(text) > MAX_CHARACTERS:
            return None
        if not self.supports(request.source_language, request.target_language):
            return None

        source = _LANGUAGE_CODES.get(request.source_language, request.source_language)
        target = _LANGUAGE_CODES.get(request.target_language, request.target_language)
        params = {"q": text, "langpair": f"{source}|{target}"}
        if self._contact_email:
            params["de"] = self._contact_email

        try:
            response = await self._client.get(ENDPOINT, params=params, timeout=self._timeout)
        except httpx.HTTPError as exc:
            logger.warning("mymemory.request_failed error=%s", exc)
            return None

        if not response.is_success:
            logger.warning("mymemory.http_error status=%s", response.status_code)
            return None

        try:
            payload = response.json()
        except ValueError:
            logger.warning("mymemory.bad_json")
            return None

        data = payload.get("responseData") or {}
        translated = (data.get("translatedText") or "").strip()
        if not translated:
            return None

        # MyMemory signals failure in the body with HTTP 200. Returning this text as a
        # translation would put "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS"
        # on the front page in place of a headline.
        upper = translated.upper()
        if any(marker in upper for marker in _ERROR_MARKERS):
            logger.warning("mymemory.refused message=%s", translated[:120])
            return None

        if payload.get("quotaFinished"):
            logger.warning("mymemory.quota_finished")
            return None

        match = data.get("match")
        match = float(match) if isinstance(match, (int, float)) else None
        if match is not None and match < MIN_MATCH:
            logger.info("mymemory.low_match match=%.2f text=%s", match, text[:60])
            return None

        # An unchanged string is not a translation. It happens when MyMemory has no memory
        # for the pair and echoes the input, and it would show French text labelled Chinese.
        if translated == text:
            return None

        return TranslationResult(
            text=translated,
            provider=self.name,
            provider_version=self.version,
            match=match,
            characters_charged=len(text),
        )
