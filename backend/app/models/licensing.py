"""What may be done with a publisher's content, and what may not.

This module is the project's answer to specification section 1.3: *technical accessibility does
not imply permission to republish*. Every other part of the pipeline asks this module before it
stores, displays, summarises or translates anything, and the answer defaults to "no".

Two axes are kept separate because real licences separate them:

* **How much may be shown** - :class:`LicenseType` ordered from metadata only to fully open.
* **Whether derivative works are allowed** - summarising and translating are derivative works.
  CC BY-ND permits verbatim republication of an entire article while forbidding translation,
  so a single "how open is this" scale would be wrong in both directions.

An unknown licence is not a permissive licence. :data:`DEFAULT_LICENSE` is
:attr:`LicenseType.UNKNOWN`, which grants exactly what the specification allows for unknown
sources: title, publisher, timestamp and the original URL.
"""

from __future__ import annotations

from enum import Enum


class LicenseType(str, Enum):
    """The reuse permission recorded for a source, as a legal fact.

    This records what the *publisher* has granted. It is never adjusted to suit what the
    application would like to display; that decision belongs to :mod:`app.core.config`.
    """

    UNKNOWN = "UNKNOWN"
    """No reuse permission has been researched or recorded. Conservative default."""

    METADATA_ONLY = "METADATA_ONLY"
    """Headline, publisher, timestamp and link may be shown. Nothing else."""

    FEED_EXCERPT = "FEED_EXCERPT"
    """The feed's own short description may be shown, attributed. No full text, no derivatives.

    Recorded only where the publisher's terms permit reproducing the feed's description - a
    feed *containing* a description is not a licence to republish it.
    """

    CC_BY_ND = "CC_BY_ND"
    """Full text may be republished verbatim with attribution. Translation and summary forbidden."""

    CC_BY = "CC_BY"
    """Full text may be republished and modified with attribution. Derivatives permitted."""

    CC_BY_SA = "CC_BY_SA"
    """As CC_BY, with share-alike obligations on the derivative."""

    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    """No restriction. In practice: some public-institution output."""

    EXPLICIT_AGREEMENT = "EXPLICIT_AGREEMENT"
    """A publisher-specific written permission exists. Its terms live in ``license_evidence``."""


#: Licences under which the feed's own description text may be stored and displayed.
_DESCRIPTION_OK = frozenset(
    {
        LicenseType.FEED_EXCERPT,
        LicenseType.CC_BY_ND,
        LicenseType.CC_BY,
        LicenseType.CC_BY_SA,
        LicenseType.PUBLIC_DOMAIN,
        LicenseType.EXPLICIT_AGREEMENT,
    }
)

#: Licences that permit a derivative work - which is what a summary and a translation are.
_DERIVATIVES_OK = frozenset(
    {
        LicenseType.CC_BY,
        LicenseType.CC_BY_SA,
        LicenseType.PUBLIC_DOMAIN,
        LicenseType.EXPLICIT_AGREEMENT,
    }
)

#: Licences that permit storing and displaying the full article body.
_FULL_TEXT_OK = frozenset(
    {
        LicenseType.CC_BY_ND,
        LicenseType.CC_BY,
        LicenseType.CC_BY_SA,
        LicenseType.PUBLIC_DOMAIN,
        LicenseType.EXPLICIT_AGREEMENT,
    }
)

#: Applied to any source whose licence has not been researched.
DEFAULT_LICENSE = LicenseType.UNKNOWN


def allows_metadata(_license: LicenseType) -> bool:
    """Title, publisher, timestamp and original URL.

    True for every licence including ``UNKNOWN``. Short factual metadata plus a link is the
    conservative baseline the specification describes, and it is what a link aggregator does.
    """
    return True


def allows_description_display(license_type: LicenseType) -> bool:
    """Whether the publisher's own description/standfirst may be stored and shown."""
    return license_type in _DESCRIPTION_OK


def allows_full_text(license_type: LicenseType) -> bool:
    """Whether the article body may be stored and shown."""
    return license_type in _FULL_TEXT_OK


def allows_derivatives(license_type: LicenseType) -> bool:
    """Whether a summary or translation may be *produced* from this source's text."""
    return license_type in _DERIVATIVES_OK


def allows_summary_publication(license_type: LicenseType) -> bool:
    """Whether a generated summary may be *displayed to users*.

    Deliberately identical to :func:`allows_derivatives` today, and deliberately a separate
    function: producing a summary for internal classification and publishing it to readers are
    different acts, and a future explicit agreement may permit one and not the other.
    """
    return allows_derivatives(license_type)
