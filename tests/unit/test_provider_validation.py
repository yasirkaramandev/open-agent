"""Service-level credential validation for ``ProviderService.add`` (item 2).

The service is the single validation layer the CLI and both TUI flows share, so these tests pin the
behavior there: key-required presets can't be saved without a credential, 'no key' is only legal for
key-less/custom providers, env credentials need a variable name, and a rejected add writes nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openagent.app import OpenAgentApp
from openagent.config import Paths
from openagent.core.models import CredentialType
from openagent.services.provider_service import ProviderValidationError, resolve_credential


def _app(tmp_path: Path) -> OpenAgentApp:
    project = tmp_path / "proj"
    project.mkdir()
    paths = Paths(
        data_dir=tmp_path / "data", config_dir=tmp_path / "config",
        db_path=tmp_path / "data" / "openagent.db", project_root=project,
    )
    return OpenAgentApp(paths)


# --------------------------------------------------------------------------- resolve_credential

def test_keychain_requires_key_for_key_needing_preset() -> None:
    with pytest.raises(ProviderValidationError) as exc:
        resolve_credential(name="ds", provider_type="deepseek", api_key="", key_env=None,
                           credential_source="keychain")
    assert exc.value.field == "api_key"


def test_empty_whitespace_key_is_treated_as_missing() -> None:
    with pytest.raises(ProviderValidationError):
        resolve_credential(name="ds", provider_type="deepseek", api_key="   ", key_env=None,
                           credential_source="keychain")


def test_keychain_with_key_is_keychain_ref() -> None:
    ref = resolve_credential(name="ds", provider_type="deepseek", api_key="sk-x", key_env=None,
                             credential_source="keychain")
    assert ref.type is CredentialType.KEYCHAIN
    assert ref.account == "provider/ds"


def test_env_requires_variable_name() -> None:
    with pytest.raises(ProviderValidationError) as exc:
        resolve_credential(name="ds", provider_type="deepseek", api_key=None, key_env="",
                           credential_source="env")
    assert exc.value.field == "key_env"


def test_env_with_variable_is_env_ref() -> None:
    ref = resolve_credential(name="ds", provider_type="deepseek", api_key=None,
                             key_env="DEEPSEEK_API_KEY", credential_source="env")
    assert ref.type is CredentialType.ENV
    assert ref.env_var == "DEEPSEEK_API_KEY"


def test_none_rejected_for_key_needing_preset() -> None:
    for ptype in ("deepseek", "openai", "anthropic"):
        with pytest.raises(ProviderValidationError):
            resolve_credential(name="x", provider_type=ptype, api_key=None, key_env=None,
                               credential_source="none")


def test_none_allowed_for_local_and_custom() -> None:
    for ptype in ("ollama", "lmstudio", "custom"):
        ref = resolve_credential(name="x", provider_type=ptype, api_key=None, key_env=None,
                                 credential_source="none")
        assert ref.type is CredentialType.NONE


def test_local_provider_needs_no_key_on_keychain_source() -> None:
    ref = resolve_credential(name="ollama-local", provider_type="ollama", api_key=None,
                             key_env=None, credential_source="keychain")
    assert ref.type is CredentialType.NONE


def test_source_inferred_from_inputs_when_omitted() -> None:
    assert resolve_credential(name="x", provider_type="deepseek", api_key=None,
                              key_env="K", credential_source=None).type is CredentialType.ENV


# --------------------------------------------------------------------------- fail-closed add()

def test_add_does_not_persist_provider_on_missing_key(tmp_path: Path) -> None:
    oa = _app(tmp_path)
    with pytest.raises(ProviderValidationError):
        oa.providers.add(name="deepseek-main", provider_type="deepseek", api_key="",
                         credential_source="keychain")
    assert oa.providers.get("deepseek-main") is None


def test_add_does_not_persist_provider_on_illegal_none(tmp_path: Path) -> None:
    oa = _app(tmp_path)
    with pytest.raises(ProviderValidationError):
        oa.providers.add(name="oai", provider_type="openai", credential_source="none")
    assert oa.providers.get("oai") is None


def test_add_persists_env_provider_without_touching_keychain(tmp_path: Path) -> None:
    oa = _app(tmp_path)
    prov = oa.providers.add(name="ds", provider_type="deepseek", key_env="DS_KEY",
                            credential_source="env")
    assert prov.credential.type is CredentialType.ENV
    assert oa.providers.get("ds") is not None
