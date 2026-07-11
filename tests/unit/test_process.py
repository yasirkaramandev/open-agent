import os

from openagent.security.process import minimal_environment


def test_minimal_env_excludes_api_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin"))
    env = minimal_environment()
    assert "OPENAI_API_KEY" not in env
    assert "PATH" in env


def test_minimal_env_injects_extra():
    env = minimal_environment({"CODEX_API_KEY": "sk-run-scoped"})
    assert env["CODEX_API_KEY"] == "sk-run-scoped"
