"""An untested capability is not a supported capability (spec §20).

``ModelCapabilities.text`` defaulted to ``True`` while every other field defaulted to ``None``. So
``ModelCapabilities()`` — which is what ``ModelService.register()`` stores for a model the user adds
without probing — asserted "this model does text" on the basis of nothing at all. The model's mere
presence in a provider's catalog was being read as a capability proof.

The three states must stay distinct, because they carry different information and the UI renders them
differently:

* ``None``  — not tested
* ``True``  — actually observed
* ``False`` — tested, and not supported

Collapsing None into False via ``bool(caps.text)`` is the same class of error in the other direction:
it reports an untested model as *known unsupported*.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openagent.app import OpenAgentApp
from openagent.config import Paths
from openagent.core.models import ModelCapabilities


@pytest.fixture()
def oa_app(tmp_path: Path) -> OpenAgentApp:
    project = tmp_path / "proj"
    project.mkdir()
    return OpenAgentApp(
        Paths(
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            db_path=tmp_path / "data" / "openagent.db",
            project_root=project,
        )
    )


# --------------------------------------------------------------------- the default


def test_an_unprobed_capability_set_asserts_nothing():
    """The headline: a bare ModelCapabilities() has observed nothing, so it must claim nothing."""

    caps = ModelCapabilities()
    assert caps.text is None, "text defaulted to True — an untested capability claimed as supported"
    assert caps.streaming is None
    assert caps.tool_calling is None
    assert caps.system_prompt is None


def test_every_capability_field_defaults_the_same_way():
    """text was the odd one out; that asymmetry is what made the bug easy to miss."""

    caps = ModelCapabilities()
    assert all(
        getattr(caps, f) is None
        for f in (
            "text",
            "streaming",
            "tool_calling",
            "parallel_tool_calling",
            "structured_output",
            "vision",
            "system_prompt",
        )
    )


def test_the_three_states_are_representable():
    assert ModelCapabilities(text=True).text is True
    assert ModelCapabilities(text=False).text is False
    assert ModelCapabilities(text=None).text is None


# --------------------------------------------------------------------- registration


def test_registering_a_model_without_a_probe_claims_no_capabilities(oa_app):
    """`openagent model add` on a catalog entry proves nothing about the model."""

    oa_app.providers.add(
        name="p1",
        provider_type="custom",
        base_url="https://api.test/v1",
        key_env="P1_KEY",
        credential_source="env",
    )
    model = oa_app.models.add(provider_name="p1", remote_model_id="some-model")
    assert model.capabilities.text is None, (
        "an unprobed model was recorded as text-capable — being in the catalog is not a probe"
    )


def test_registering_with_a_real_probe_keeps_the_observed_values(oa_app):
    oa_app.providers.add(
        name="p1",
        provider_type="custom",
        base_url="https://api.test/v1",
        key_env="P1_KEY",
        credential_source="env",
    )
    model = oa_app.models.add(
        provider_name="p1",
        remote_model_id="some-model",
        capabilities=ModelCapabilities(text=True, streaming=True),
    )
    assert model.capabilities.text is True
    assert model.capabilities.streaming is True
    assert model.capabilities.tool_calling is None


def test_a_capability_survives_a_round_trip_through_the_db(oa_app):
    """None must persist as None, not be coerced back to a default of True."""

    oa_app.providers.add(
        name="p1",
        provider_type="custom",
        base_url="https://api.test/v1",
        key_env="P1_KEY",
        credential_source="env",
    )
    oa_app.models.add(provider_name="p1", remote_model_id="m")
    stored = oa_app.models.list_for_provider("p1")[0]
    assert stored.capabilities.text is None


# --------------------------------------------------------------------- merge


def test_merge_does_not_invent_a_true():
    probed = ModelCapabilities(text=True)
    merged = ModelCapabilities().merge(probed)
    assert merged.text is True
    assert merged.tool_calling is None, "merge invented a capability nothing observed"


# --------------------------------------------------------------------- reporting


def test_probe_json_reports_untested_as_null_not_false():
    """`bool(caps.text)` told a --json consumer "tested, unsupported" about an untested model."""

    from openagent.providers.discovery import AgentModelProbe

    probe = AgentModelProbe(
        model="m", capabilities=ModelCapabilities(), agent_compatible=False, category="unknown"
    )
    assert probe.to_dict()["text"] is None, "untested was serialized as false"


def test_probe_json_still_reports_a_real_false():
    from openagent.providers.discovery import AgentModelProbe

    probe = AgentModelProbe(
        model="m",
        capabilities=ModelCapabilities(text=False),
        agent_compatible=False,
        category="incompatible",
    )
    assert probe.to_dict()["text"] is False


def test_probe_json_reports_a_real_true():
    from openagent.providers.discovery import AgentModelProbe

    probe = AgentModelProbe(
        model="m",
        capabilities=ModelCapabilities(text=True),
        agent_compatible=False,
        category="partial",
    )
    assert probe.to_dict()["text"] is True


def test_an_untested_model_is_never_agent_compatible():
    """Unknown must fail closed: absence of a probe is not evidence of support."""

    from openagent.providers.discovery import AgentModelProbe

    probe = AgentModelProbe(
        model="m", capabilities=ModelCapabilities(), agent_compatible=False, category="unknown"
    )
    assert probe.agent_compatible is False
