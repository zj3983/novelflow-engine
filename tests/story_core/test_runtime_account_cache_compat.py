"""Existing model discovery caches must not invalidate account configuration."""
import pytest
from pydantic import ValidationError

from packages.story_core.runtime_config import ProviderAccount


def test_existing_provider_model_cache_roundtrips_without_changing_account_settings():
    payload = {
        "base_url": "https://example.test/v1",
        "custom_models": ["example-model"],
        "model_capabilities": {"example-model": {"supports_tools": False}},
    }
    account = ProviderAccount.model_validate(payload)
    saved = account.model_dump()
    assert saved["model_capabilities"] == payload["model_capabilities"]
    assert saved["base_url"] == payload["base_url"]
    assert saved["custom_models"] == payload["custom_models"]


def test_unknown_provider_fields_still_fail_validation():
    with pytest.raises(ValidationError):
        ProviderAccount.model_validate({"unknown_setting": "invalid"})


def test_accounts_without_a_cache_expose_the_capability_configuration_field():
    assert ProviderAccount().model_dump()["model_capabilities"] == {}
