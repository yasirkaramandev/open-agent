"""Command policy (spec §29).

Before any shell command runs (whether requested by an API agent's ``run_command`` tool or emitted
by a CLI runtime we control), it is screened here. Two outcomes beyond "allow":

* ``DENY`` — categorically forbidden (push, publish, sudo, credential reads, ``rm -rf`` outside the
  workspace…). Never runs.
* ``APPROVAL`` — high-risk but sometimes legitimate; requires an explicit approval event first.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    ALLOW = "allow"
    APPROVAL = "approval"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


# Categorically denied (spec §29 "Varsayılan yasaklar").
_DENY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bgit\s+push\b"), "git push is not allowed"),
    (re.compile(r"\bnpm\s+publish\b"), "npm publish is not allowed"),
    (re.compile(r"\b(pip|twine)\s+upload\b"), "package upload is not allowed"),
    (re.compile(r"\bdocker\s+login\b"), "docker login is not allowed"),
    (re.compile(r"\b(aws|gcloud|az)\s+.*\blogin\b"), "cloud CLI login is not allowed"),
    (re.compile(r"\bsudo\b"), "sudo is not allowed"),
    (re.compile(r"\bsecurity\s+find-generic-password\b"), "keychain access is not allowed"),
    (re.compile(r"(?i)\b(cat|less|more|head|tail|bat)\b[^\n|;&]*\.env\b"), "reading .env is not allowed"),
    (re.compile(r"(?i)id_rsa|id_ed25519|\.ssh/"), "SSH private key access is not allowed"),
    (re.compile(r"(?i)\b(cat|less|more)\b[^\n|;&]*(credentials|\.aws/)"), "reading credentials is not allowed"),
]

# High-risk: allowed only after approval.
_APPROVAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+-[rfRF]"), "recursive/forced delete"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "hard reset discards changes"),
    (re.compile(r"\bgit\s+clean\b"), "git clean removes untracked files"),
    (re.compile(r"\b(mkfs|dd)\b"), "disk-level operation"),
    (re.compile(r"\bchmod\s+-R\b"), "recursive permission change"),
    (re.compile(r">\s*/dev/sd"), "raw device write"),
]

# Commands that need network (blocked when the profile disallows network).
_NETWORK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(curl|wget|nc|ncat|telnet)\b"),
    re.compile(r"\b(pip|pip3)\s+install\b"),
    re.compile(r"\b(npm|pnpm|yarn)\s+(install|add|ci)\b"),
    re.compile(r"\b(apt|apt-get|brew|dnf|yum)\s+install\b"),
    re.compile(r"\bgit\s+(clone|fetch|pull)\b"),
]


def evaluate(command: str, *, network_allowed: bool = False) -> PolicyResult:
    """Screen a raw shell command string."""

    normalized = command.strip()
    if not normalized:
        return PolicyResult(Decision.DENY, "empty command")

    for pattern, reason in _DENY_PATTERNS:
        if pattern.search(normalized):
            return PolicyResult(Decision.DENY, reason)

    if not network_allowed:
        for pattern in _NETWORK_PATTERNS:
            if pattern.search(normalized):
                return PolicyResult(Decision.APPROVAL, "network access is disabled for this profile")

    for pattern, reason in _APPROVAL_PATTERNS:
        if pattern.search(normalized):
            return PolicyResult(Decision.APPROVAL, reason)

    return PolicyResult(Decision.ALLOW)


def split_command(command: str) -> list[str]:
    """Best-effort tokenization for logging/inspection (never used to bypass the policy)."""

    try:
        return shlex.split(command)
    except ValueError:
        return command.split()
