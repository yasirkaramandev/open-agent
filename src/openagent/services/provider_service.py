"""Provider connection management (spec §12–§24, §30)."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..core.models import CredentialRef, CredentialType, Protocol, ProviderConnection, RemoteModel
from ..credentials.redaction import register_secret
from ..providers.base import HealthResult
from ..providers.factory import build_adapter, get_preset, resolve_base_url

if TYPE_CHECKING:
    from ..app import OpenAgentApp


class ProviderValidationError(ValueError):
    """A provider's credential configuration is invalid (missing key/env var, illegal 'none').

    Carries the offending form ``field`` so the TUI can surface the message inline under it.
    """

    def __init__(self, message: str, *, field: str = "") -> None:
        super().__init__(message)
        self.field = field


class ProviderInUseError(ValueError):
    """Raised when deleting a provider that one or more agents still bind to."""

    def __init__(self, provider: str, agents: Sequence[str]) -> None:
        self.provider = provider
        self.agents = list(agents)
        super().__init__(
            f"provider {provider!r} is used by agents: {', '.join(self.agents)}"
        )


@dataclass
class SecretRollback:
    """How to put the OS keychain back exactly as it was, if a transaction fails (item 17).

    The previous code only tracked *whether* it had written a secret where none existed. If a secret
    already existed under the same account, it was overwritten and — on failure — simply left there:
    the user's old key was destroyed and replaced by a key belonging to a provider that was never
    saved. Restoring correctly needs the previous **value**, not a boolean.
    """

    ref: CredentialRef | None = None
    previous: str | None = None
    wrote: bool = False

    def restore(self, credentials) -> None:
        """Undo the write: put the old secret back verbatim, or remove one that never existed."""

        if not self.wrote or self.ref is None:
            return
        if self.previous is None:
            credentials.delete_secret(self.ref)
        else:
            credentials.set_secret(self.ref, self.previous)


def resolve_credential(
    *,
    name: str,
    provider_type: str,
    api_key: str | None,
    key_env: str | None,
    credential_source: str | None = None,
) -> CredentialRef:
    """Validate the credential inputs and build a :class:`CredentialRef`, or fail closed.

    This is the single source of truth for "is this provider's credential acceptable" — the CLI,
    the Add Provider screen, and the Add Agent connect-new flow all go through
    :meth:`ProviderService.add`, which calls this. Nothing is persisted if it raises.
    """

    preset = get_preset(provider_type)
    needs_key = preset.needs_key if preset else True
    # An explicit "no key" is only legitimate for providers that don't need one (ollama, LM Studio)
    # or a bespoke endpoint the user is knowingly configuring (custom / unknown preset).
    none_allowed = (not needs_key) or provider_type == "custom" or preset is None

    source = credential_source or ("env" if key_env else "keychain")
    key = (api_key or "").strip()
    env_var = (key_env or "").strip()

    if source == "env":
        if not env_var:
            raise ProviderValidationError(
                "environment variable name is required for an env-var credential", field="key_env"
            )
        return CredentialRef(type=CredentialType.ENV, env_var=env_var)

    if source == "none":
        if not none_allowed:
            raise ProviderValidationError(
                f"provider type {provider_type!r} requires a key; 'no key' is only for local "
                "providers (ollama, lmstudio) or a custom endpoint",
                field="api_key",
            )
        return CredentialRef(type=CredentialType.NONE)

    # Default: OS keychain.
    if not key:
        if needs_key:
            raise ProviderValidationError(
                "an API key is required for this provider", field="api_key"
            )
        # A no-key provider configured via the keychain source but left blank: store nothing.
        return CredentialRef(type=CredentialType.NONE)
    return CredentialRef(type=CredentialType.KEYCHAIN, service="openagent", account=f"provider/{name}")


class ProviderService:
    def __init__(self, app: OpenAgentApp) -> None:
        self.app = app
        self.repos = app.repos
        self.credentials = app.credentials
        #: What :meth:`add` wrote to the keychain for each provider, so a later :meth:`rollback` in
        #: the same transaction can restore the previous value exactly (item 17).
        self._rollbacks: dict[str, SecretRollback] = {}

    def add(
        self,
        *,
        name: str,
        provider_type: str,
        protocol: Protocol | None = None,
        base_url: str | None = None,
        anthropic_base_url: str | None = None,
        api_key: str | None = None,
        key_env: str | None = None,
        credential_source: str | None = None,
        region: str | None = None,
        workspace_id: str | None = None,
        extra_headers: dict[str, str] | None = None,
        store_key: bool = True,
    ) -> ProviderConnection:
        """Register a provider and store its key in the OS keychain (spec §30).

        The credential is validated first (:func:`resolve_credential`) and this method **fails
        closed** and **atomically**:

        * a **duplicate name is rejected at the service layer** (item 6) — the CLI/TUI checks are a
          convenience, not the authority. ``upsert`` never silently overwrites an existing provider;
        * if the key/env-var is missing or 'no key' is illegal for this provider type, it raises
          :class:`ProviderValidationError` and writes nothing to the DB or keychain;
        * the keychain secret is written **before** the provider row, but if the row write fails the
          keychain is restored **exactly** as it was (item 17): a secret that existed before is put
          back verbatim, and one that did not is removed. A failed transaction can neither orphan a
          new key nor destroy an old one.

        ``key_env`` references an environment variable instead of storing a secret; ``api_key`` is
        written to the OS keychain. ``credential_source`` (``keychain``/``env``/``none``) makes the
        user's choice explicit; when omitted it is inferred from the inputs.
        """

        if self.get(name) is not None:
            raise ProviderValidationError(
                f"provider {name!r} already exists", field="name"
            )

        preset = get_preset(provider_type)
        resolved_protocol = protocol or (preset.protocol if preset else Protocol.OPENAI_CHAT)
        credential = resolve_credential(
            name=name, provider_type=provider_type, api_key=api_key, key_env=key_env,
            credential_source=credential_source,
        )

        provider = ProviderConnection(
            id=f"provider_{name}",
            name=name,
            provider_type=provider_type,
            protocol=resolved_protocol,
            base_url=base_url,
            anthropic_base_url=anthropic_base_url,
            credential=credential,
            region=region,
            workspace_id=workspace_id,
            extra_headers=extra_headers or {},
        )
        rollback = SecretRollback()
        if api_key and store_key and credential.type is CredentialType.KEYCHAIN:
            # Capture the *value* that was there before, not just whether one was: restoring needs it.
            rollback = SecretRollback(
                ref=credential, previous=self.credentials.resolve(credential), wrote=True,
            )
            self.credentials.set_secret(credential, api_key)
        try:
            self.repos.providers.upsert(provider)
        except Exception:
            rollback.restore(self.credentials)
            raise
        self._rollbacks[provider.name] = rollback
        return provider

    def list(self) -> Sequence[ProviderConnection]:
        return self.repos.providers.list()

    def get(self, name: str) -> ProviderConnection | None:
        return self.repos.providers.get_by_name(name)

    def rollback(self, provider: ProviderConnection) -> None:
        """Undo a just-created provider (row + keychain), restoring the keychain exactly (item 17).

        Used by the atomic create-provider-and-agent transaction (item 3); unlike :meth:`remove` it
        does **not** run the in-use guard, because the partner agent creation failed and the provider
        must be removed regardless.

        It follows the same rule as :meth:`add`: a secret this transaction wrote over is put back,
        and a secret that existed **before** the transaction is never deleted. Deleting it would
        destroy a key the user still has another use for, over a failure they did not cause.
        """

        rollback = self._rollbacks.pop(provider.name, None)
        if rollback is not None:
            rollback.restore(self.credentials)
        elif provider.credential.type is CredentialType.KEYCHAIN:
            # No recorded write (e.g. the provider was created elsewhere): nothing of ours to undo,
            # so leave the keychain alone rather than deleting a secret we did not write.
            pass
        self.repos.providers.delete(provider.id)

    def agents_using(self, name: str) -> Sequence[str]:
        """Names of agents whose runtime binds to the provider connection ``name``."""

        return [a.name for a in self.repos.agents.list() if a.runtime.provider == name]

    def remove(self, name: str) -> bool:
        """Delete a provider and its keychain secret.

        Refuses (raises :class:`ProviderInUseError`) when any agent still binds to it, so a
        dependent agent is never left pointing at a missing provider. Returns ``False`` when the
        provider does not exist.
        """

        provider = self.get(name)
        if not provider:
            return False
        dependents = self.agents_using(name)
        if dependents:
            raise ProviderInUseError(name, dependents)
        if provider.credential.type is CredentialType.KEYCHAIN:
            self.credentials.delete_secret(provider.credential)
        self.repos.providers.delete(provider.id)
        return True

    def adapter_for(self, provider: ProviderConnection):
        api_key = self.credentials.resolve(provider.credential)
        # Register the concrete key so it is scrubbed from every artifact/log even when its format
        # has no recognizable prefix (spec §30).
        register_secret(api_key)
        return build_adapter(provider, api_key)

    async def test_config(
        self,
        *,
        provider_type: str,
        protocol: Protocol | None = None,
        base_url: str | None = None,
        anthropic_base_url: str | None = None,
        region: str | None = None,
        workspace_id: str | None = None,
        api_key: str | None = None,
        key_env: str | None = None,
    ) -> HealthResult:
        """Test a would-be provider *before* saving it (spec §31 Test Connection).

        Builds a transient adapter from the supplied fields and key — nothing is persisted and the
        key is never stored or echoed back.
        """

        preset = get_preset(provider_type)
        resolved_protocol = protocol or (preset.protocol if preset else Protocol.OPENAI_CHAT)
        provider = ProviderConnection(
            id="provider__transient", name="__transient", provider_type=provider_type,
            protocol=resolved_protocol, base_url=base_url, anthropic_base_url=anthropic_base_url,
            region=region, workspace_id=workspace_id, credential=CredentialRef(type=CredentialType.NONE),
        )
        key = api_key or (os.environ.get(key_env) if key_env else None)
        register_secret(key)
        try:
            resolve_base_url(provider)
        except ValueError as exc:
            return HealthResult(ok=False, detail=str(exc))
        adapter = build_adapter(provider, key)
        try:
            return await adapter.test_connection()
        except Exception as exc:  # noqa: BLE001 - surface any failure as an unhealthy result
            return HealthResult(ok=False, detail=str(exc))
        finally:
            await _maybe_close(adapter)

    async def remote_models_config(
        self,
        *,
        provider_type: str,
        protocol: Protocol | None = None,
        base_url: str | None = None,
        anthropic_base_url: str | None = None,
        region: str | None = None,
        workspace_id: str | None = None,
        api_key: str | None = None,
        key_env: str | None = None,
    ) -> Sequence[RemoteModel]:
        """List models for a *would-be* provider before it is saved (Add-Agent new-connection flow).

        Mirrors :meth:`test_config`: builds a transient adapter from the supplied fields, persists
        nothing, and never stores or echoes the key. Best-effort — returns ``[]`` on any failure.
        """

        preset = get_preset(provider_type)
        resolved_protocol = protocol or (preset.protocol if preset else Protocol.OPENAI_CHAT)
        provider = ProviderConnection(
            id="provider__transient", name="__transient", provider_type=provider_type,
            protocol=resolved_protocol, base_url=base_url, anthropic_base_url=anthropic_base_url,
            region=region, workspace_id=workspace_id, credential=CredentialRef(type=CredentialType.NONE),
        )
        key = api_key or (os.environ.get(key_env) if key_env else None)
        register_secret(key)
        try:
            resolve_base_url(provider)
        except ValueError:
            return []
        adapter = build_adapter(provider, key)
        try:
            return await adapter.list_models()
        except Exception:  # noqa: BLE001 - discovery is best-effort
            return []
        finally:
            await _maybe_close(adapter)

    async def test(self, name: str) -> HealthResult:
        provider = self.get(name)
        if not provider:
            return HealthResult(ok=False, detail="provider not found")
        try:
            resolve_base_url(provider)
        except ValueError as exc:
            return HealthResult(ok=False, detail=str(exc))
        adapter = self.adapter_for(provider)
        try:
            return await adapter.test_connection()
        finally:
            await _maybe_close(adapter)

    async def remote_models(self, name: str) -> Sequence[RemoteModel]:
        provider = self.get(name)
        if not provider:
            return []
        adapter = self.adapter_for(provider)
        try:
            return await adapter.list_models()
        except Exception:  # noqa: BLE001 - discovery is best-effort
            return []
        finally:
            await _maybe_close(adapter)


async def _maybe_close(adapter: object) -> None:
    transport = getattr(adapter, "transport", None)
    if transport is not None and hasattr(transport, "aclose"):
        await transport.aclose()
