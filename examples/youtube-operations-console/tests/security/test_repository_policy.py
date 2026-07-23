from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Constructed to ensure the scanner test itself does not contain a prohibited literal.
FORBIDDEN = [
    "_".join(("gmail", "password")),
    "_".join(("google", "password")),
    "_".join(("youtube", "password")),
    "_".join(("raw", "cookie")),
    "_".join(("session", "cookie")),
    "captcha " + "bypass",
    "proxy " + "rotation",
    "fingerprint " + "spoof",
    "bulk " + "like",
    "bulk " + "subscribe",
    "bulk " + "comment",
]


def project_text() -> str:
    chunks: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(
            part in {"node_modules", ".git", ".openagent-local", ".venv", "__pycache__", "dist"}
            for part in path.parts
        ):
            continue
        if path.suffix.lower() not in {".py", ".ts", ".tsx", ".json", ".yml", ".yaml", ".toml"}:
            continue
        chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks).lower()


def test_repository_has_no_password_cookie_or_bulk_engagement_surface() -> None:
    text = project_text()
    assert [term for term in FORBIDDEN if term in text] == []


def test_no_multi_account_write_contract() -> None:
    api = (ROOT / "apps/api/src/signal_api/main.py").read_text(encoding="utf-8")
    assert not re.search(r"account_ids|all_accounts|selected_accounts", api, re.IGNORECASE)
    assert "youtube_account_id" in api
    assert "payload_hash" in api
    assert "idempotency" in api
