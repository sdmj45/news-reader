"""Effective rights: what the publisher licensed, versus what this deployment may do.

:mod:`app.models.licensing` records what a publisher has **licensed**. That is a legal fact
gathered from published reuse policies, and nothing here edits it — a deployment that wants
more text does not get to rewrite the evidence.

What a deployment *can* decide, for itself, is that it is not redistributing anything. A
private reader that fetches public feeds and shows them to one household is not republishing
journalism; in France and across the EU that sits under private-use and quotation exceptions,
and under Article 15(1) of Directive (EU) 2019/790, which explicitly excludes "individual
words or very short extracts" from press publishers' rights — a headline is such an extract.

That is a judgement about **how this instance is operated**, not about what a publisher
allows, so it lives in configuration and never in the registry. The split matters in both
directions:

* With ``PERSONAL_USE_MODE`` off — the default — behaviour is exactly as before: metadata
  only, except for the three sources with recorded permission.
* With it on, the operator has asserted that this instance serves one household and publishes
  nothing. The registry still records the truth, so turning the flag off restores conservative
  behaviour without a single source needing to be re-researched.

:func:`guard_personal_use` refuses the one combination that would turn a private reader into a
republisher, by raising rather than warning. A misconfiguration here is the difference between
reading the news and redistributing it, and that is not something to leave to a log line
nobody reads.
"""

from __future__ import annotations

from app.core.config import Settings
from app.models.licensing import LicenseType
from app.models.source import NewsSource


def effective_license(source: NewsSource, settings: Settings) -> LicenseType:
    """What this deployment may do with ``source``'s text, as opposed to what it is licensed.

    Returns the registry's own value unless personal-use mode is on, in which case the
    operator has taken responsibility for the private-use judgement in the module docstring.

    One exception is **not** overridden: ``CC_BY_ND`` stays as it is. The Conversation's
    licence forbids derivative works outright and their guidelines additionally prohibit use
    as AI training data. That is an explicit "no" from a publisher who took the trouble to
    publish one, and private use is not a reason to read it as a "yes".
    """
    if not settings.personal_use_mode:
        return source.license_type
    if source.license_type is LicenseType.CC_BY_ND:
        return LicenseType.CC_BY_ND
    if source.license_type in (LicenseType.UNKNOWN, LicenseType.METADATA_ONLY,
                               LicenseType.FEED_EXCERPT):
        return LicenseType.PERSONAL_USE
    return source.license_type


def guard_personal_use(settings: Settings) -> None:
    """Refuses personal-use mode on a production instance. Raises; never warns."""
    if settings.personal_use_mode and settings.is_production:
        raise RuntimeError(
            "PERSONAL_USE_MODE is enabled while APP_ENV=production. Personal-use mode asserts "
            "that this instance serves a single private household and republishes nothing; a "
            "production deployment contradicts that assertion. Disable one of the two."
        )
