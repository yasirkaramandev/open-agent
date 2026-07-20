"""The single authority for version parsing and comparison (spec §4, §12).

Every version decision in OpenAgent — "is this update newer?", "does the installed CLI meet the
minimum?", "is the version I detected the one the adapter was validated against?", "did the
self-update actually land the version I expected?" — must agree on what a version *is* and how two
versions order. When that logic is copied by hand into each call site, the copies drift: one uses
PEP 440 ordering, another a regex-and-integer-tuple that silently discards prerelease and build
metadata, so ``1.2.0rc1`` and ``1.2.0`` compare **equal** and a release candidate is reported as
already current. That exact bug shipped more than once (spec §4). It is fixed once, here, and never
re-derived.

Everything routes through :func:`parse_version`, which extracts a version from a noisy ``--version``
line and parses it with :class:`packaging.version.Version` — PEP 440 ordering, not a local
approximation of it. Only a small, explicit set of mechanical normalisations is applied (a leading
``v``/``rust-v`` prefix, SemVer's ``-rc.2`` separator). Anything that cannot be parsed is reported
as ``None`` / *unknown* and never silently treated as equal to, newer than, or at-least some other
version. Callers that gate on a version must treat ``None`` as fail-closed, not as "supported".
"""

from __future__ import annotations

import re

from packaging.version import InvalidVersion, Version

#: A version as it appears inside a ``--version`` line, which is rarely just the version:
#: "claude 1.2.3 (Claude Code)", "codex-cli 0.5.0-rc.2", "1.2.0rc1", "openagent 0.1.6rc2".
#:
#: The trailing group must accept a suffix attached with **no separator at all** (``1.2.0rc1``, PEP
#: 440's own spelling) as well as one introduced by ``-``/``+``/``.`` (``0.5.0-rc.2``, SemVer's).
#: An earlier version of this pattern required the separator, so ``1.2.0rc1`` matched only its
#: ``1.2.0`` prefix — silently reintroducing the exact "a prerelease equals its release" bug this
#: module exists to prevent. Requiring the suffix to start with an alphanumeric is what keeps the
#: match from running into " (Claude Code)".
_VERSION_PATTERN = re.compile(r"\d+(?:\.\d+)*(?:[-+.]?[0-9A-Za-z][0-9A-Za-z.+-]*)?")


def parse_version(value: str | None) -> Version | None:
    """Extract and parse a version, or ``None`` when there is nothing comparable.

    PEP 440 ordering (via ``packaging``) is not something to re-derive locally: it has to know that
    ``1.2.0rc1 < 1.2.0``, that ``1.2.0.post1 > 1.2.0``, that ``1.2.0.dev1 < 1.2.0a1``, and that
    build metadata does not affect ordering. Versions that are not PEP 440 (some CLIs ship SemVer
    with a ``-rc.2`` suffix) are normalised where the translation is mechanical and unambiguous, and
    reported as unparseable otherwise — never silently equal.
    """

    if not value:
        return None
    match = _VERSION_PATTERN.search(value)
    if not match:
        return None
    raw = match.group(0).rstrip(".-+")
    try:
        return Version(raw)
    except InvalidVersion:
        # SemVer prerelease syntax ("0.5.0-rc.2") is not PEP 440 but is unambiguous; normalising the
        # separator is a mechanical translation, not a guess about intent.
        try:
            return Version(raw.replace("-", ""))
        except InvalidVersion:
            return None


def canonical_version(value: str | None) -> str | None:
    """The PEP 440 canonical spelling of ``value``, or ``None`` when it cannot be parsed.

    ``canonical_version("openagent 0.1.6rc1")`` is ``"0.1.6rc1"`` — crucially **not** ``"0.1.6"``.
    Comparing two canonical strings for equality is safe because ``Version`` collapses spellings that
    order the same (``1.2.0-rc.1`` and ``1.2.0rc1``) onto one canonical form.
    """

    parsed = parse_version(value)
    return str(parsed) if parsed is not None else None


def compare_versions(left: str | None, right: str | None) -> int | None:
    """``-1``/``0``/``1`` for ``left`` <, ==, > ``right``; ``None`` when either is unparseable."""

    a, b = parse_version(left), parse_version(right)
    if a is None or b is None:
        return None
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def is_newer(candidate: str | None, installed: str | None) -> bool | None:
    """Whether ``candidate`` is strictly newer than ``installed``.

    The three-valued return matters: callers must not treat "unparseable" as "up to date". That
    conflation is what let a failed update report success (spec §4).
    """

    result = compare_versions(candidate, installed)
    return None if result is None else result > 0


def version_at_least(installed: str | None, minimum: str | None) -> bool | None:
    """Whether ``installed`` satisfies the ``minimum`` version, or ``None`` when not comparable.

    Returning ``None`` — rather than ``False`` or ``True`` — for an unparseable input is deliberate:
    a minimum-version *policy* that cannot be evaluated has not been satisfied and has not been
    violated. The caller decides, and a mandatory policy treats ``None`` as fail-closed (spec §12),
    never as "supported".
    """

    result = compare_versions(installed, minimum)
    return None if result is None else result >= 0
