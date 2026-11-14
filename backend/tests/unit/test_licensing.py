"""The licence rules, and the registry invariants that depend on them.

These are the tests that matter most for specification section 1.3: if the conservative
default ever stops being conservative, the application starts republishing other people's
journalism and nothing else in the test suite would notice.
"""

from __future__ import annotations

import pytest

from app.models import licensing as lic
from app.models.licensing import LicenseType
from app.models.source import NewsSource, SourceType, VerificationState
from app.services import source_registry


class TestDefaults:
    def test_unknown_is_the_default(self):
        assert lic.DEFAULT_LICENSE is LicenseType.UNKNOWN

    def test_unknown_permits_metadata_and_nothing_else(self):
        unknown = LicenseType.UNKNOWN
        assert lic.allows_metadata(unknown)
        assert not lic.allows_description_display(unknown)
        assert not lic.allows_full_text(unknown)
        assert not lic.allows_derivatives(unknown)
        assert not lic.allows_summary_publication(unknown)

    def test_metadata_only_withholds_the_feed_description(self):
        # A feed carrying a description is not a publisher licensing it.
        assert not lic.allows_description_display(LicenseType.METADATA_ONLY)

    def test_every_licence_permits_metadata(self):
        assert all(lic.allows_metadata(licence) for licence in LicenseType)


class TestNoDerivatives:
    """CC BY-ND is the case that a single 'how open is it' scale would get wrong."""

    def test_nd_allows_verbatim_full_text(self):
        assert lic.allows_full_text(LicenseType.CC_BY_ND)
        assert lic.allows_description_display(LicenseType.CC_BY_ND)

    def test_nd_forbids_summary_and_translation(self):
        assert not lic.allows_derivatives(LicenseType.CC_BY_ND)
        assert not lic.allows_summary_publication(LicenseType.CC_BY_ND)

    def test_by_allows_both(self):
        assert lic.allows_full_text(LicenseType.CC_BY)
        assert lic.allows_derivatives(LicenseType.CC_BY)


class TestSourceInvariants:
    def _source(self, **overrides):
        base = {
            "source_id": "x", "name": "X", "domain": "x.fr", "country": "FR",
            "language": "fr", "source_type": SourceType.RSS,
            "feed_url": "https://x.fr/f.xml", "enabled": True,
            "verification": VerificationState.FETCH_VERIFIED,
        }
        base.update(overrides)
        return NewsSource(**base)

    def test_unverified_source_cannot_be_enabled(self):
        with pytest.raises(ValueError, match="verification state"):
            self._source(verification=VerificationState.UNVERIFIED)

    def test_unreachable_source_cannot_be_enabled(self):
        with pytest.raises(ValueError, match="verification state"):
            self._source(verification=VerificationState.UNREACHABLE)

    def test_unverified_source_may_exist_while_disabled(self):
        # Recording a dead endpoint is how the registry remembers not to retry it.
        self._source(enabled=False, verification=VerificationState.UNREACHABLE)

    def test_elevated_licence_requires_evidence(self):
        with pytest.raises(ValueError, match="with no evidence"):
            self._source(license_type=LicenseType.CC_BY, license_evidence="   ")

    def test_summary_republication_cannot_outrun_modification(self):
        with pytest.raises(ValueError, match="derivative work"):
            self._source(
                license_type=LicenseType.CC_BY,
                license_evidence="test",
                modification_allowed=False,
                summary_republication_allowed=True,
            )


class TestRegistryIsConsistent:
    """The registry is data, so these assertions are the only thing checking it."""

    def test_every_active_source_is_fetch_verified(self):
        for s in source_registry.active_sources():
            assert s.verification is VerificationState.FETCH_VERIFIED, s.source_id
            assert s.verified_on, s.source_id

    def test_source_ids_are_unique(self):
        ids = [s.source_id for s in source_registry.SOURCES]
        assert len(ids) == len(set(ids))

    def test_feed_urls_are_absolute_https_or_http(self):
        for s in source_registry.SOURCES:
            assert s.feed_url.startswith(("https://", "http://")), s.source_id

    def test_every_elevated_licence_cites_a_url(self):
        for s in source_registry.SOURCES:
            if s.license_type is not LicenseType.UNKNOWN:
                assert "http" in s.license_evidence, (
                    f"{s.source_id} claims {s.license_type.value} without citing a source"
                )

    def test_flags_agree_with_the_licence_enum(self):
        # The boolean fields exist because the specification asks for them; they must not
        # drift away from the enum they duplicate.
        for s in source_registry.SOURCES:
            assert s.modification_allowed == lic.allows_derivatives(s.license_type), s.source_id
            assert s.summary_republication_allowed == lic.allows_summary_publication(
                s.license_type
            ), s.source_id

    def test_gdelt_is_never_treated_as_licensed(self):
        # GDELT indexes 545 domains per file; no per-publisher permission can exist.
        for s in source_registry.SOURCES:
            if "gdelt" in s.source_id:
                assert s.license_type is LicenseType.UNKNOWN
                assert not s.summary_republication_allowed

    def test_rejected_candidates_each_record_a_reason(self):
        for url, reason in source_registry.REJECTED_CANDIDATES.items():
            assert len(reason) > 20, url
            assert "2026-" in reason, f"{url} does not say when it was probed"

    def test_rejected_candidates_are_not_also_active(self):
        active = {s.feed_url for s in source_registry.active_sources()}
        assert not (active & set(source_registry.REJECTED_CANDIDATES))
