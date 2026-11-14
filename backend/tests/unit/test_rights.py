"""Personal-use mode: what the operator may assert, and what they may not."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.models.licensing import LicenseType, allows_derivatives, allows_full_text
from app.models.rights import effective_license, guard_personal_use
from tests.conftest import make_source

OFF = Settings(personal_use_mode=False)
ON = Settings(personal_use_mode=True)


class TestDefaultIsUnchanged:
    @pytest.mark.parametrize("licence", list(LicenseType))
    def test_with_the_flag_off_nothing_moves(self, licence):
        source = make_source(license_type=licence)
        assert effective_license(source, OFF) is licence


class TestPersonalUseMode:
    def test_unknown_becomes_personal_use(self):
        source = make_source(license_type=LicenseType.UNKNOWN)
        assert effective_license(source, ON) is LicenseType.PERSONAL_USE

    def test_personal_use_permits_derivatives_so_translation_is_possible(self):
        # This is the whole point of the flag: a private reader may translate a headline.
        assert allows_derivatives(LicenseType.PERSONAL_USE)

    def test_personal_use_does_not_unlock_full_article_bodies(self):
        # Reading a standfirst is one thing; warehousing whole articles is another, and
        # nothing in this product needs it.
        assert not allows_full_text(LicenseType.PERSONAL_USE)

    def test_an_explicit_no_derivatives_licence_is_not_overridden(self):
        # The Conversation forbids derivatives and says so in writing. Private use is not a
        # reason to read a published "no" as a "yes".
        source = make_source(license_type=LicenseType.CC_BY_ND)
        assert effective_license(source, ON) is LicenseType.CC_BY_ND
        assert not allows_derivatives(effective_license(source, ON))

    def test_an_already_open_licence_is_left_alone(self):
        source = make_source(license_type=LicenseType.CC_BY)
        assert effective_license(source, ON) is LicenseType.CC_BY

    def test_the_registry_object_is_never_mutated(self):
        source = make_source(license_type=LicenseType.UNKNOWN)
        effective_license(source, ON)
        assert source.license_type is LicenseType.UNKNOWN, (
            "the registry records what publishers grant; a deployment's assertion must not "
            "edit the evidence"
        )


class TestGuard:
    def test_personal_use_in_production_is_refused(self):
        with pytest.raises(RuntimeError, match="contradicts that assertion"):
            guard_personal_use(Settings(personal_use_mode=True, app_env="production"))

    def test_personal_use_locally_is_fine(self):
        guard_personal_use(Settings(personal_use_mode=True, app_env="local"))

    def test_production_without_the_flag_is_fine(self):
        guard_personal_use(Settings(personal_use_mode=False, app_env="production"))

    def test_personal_use_never_appears_in_the_registry(self):
        from app.services import source_registry

        assert all(s.license_type is not LicenseType.PERSONAL_USE
                   for s in source_registry.SOURCES), (
            "PERSONAL_USE is an operator assertion, not a publisher grant"
        )
