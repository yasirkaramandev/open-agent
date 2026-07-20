#!/usr/bin/env python3
"""Per-module branch-coverage gate with a ratchet.

A single global coverage percentage is close to useless here. ``storage/repositories.py`` losing a
branch and ``tui/screens/lists.py`` losing a branch are not the same event: one of them can corrupt
a user's database. So the gate is per-module, and the modules that can leak a secret, lose a
credential, or corrupt persistent state are held to a much higher bar than the interface layer.

**Why a ratchet rather than a fixed threshold.** The spec sets 95% branch coverage for the critical
modules. The codebase is not there yet, and a gate that is red on day one is a gate that gets
``continue-on-error`` bolted onto it by week two — at which point it enforces nothing. Instead each
module carries two numbers:

* ``floor`` — measured, committed, and **enforced**. Coverage may not drop below it. This makes the
  gate meaningful immediately, on the real codebase.
* ``target`` — where the module needs to end up. Reported as a gap on every run so the distance
  stays visible instead of being quietly forgotten.

When a module's measured coverage exceeds its floor by more than ``RATCHET_SLACK``, the run fails
with an instruction to raise the floor. That is the ratchet: coverage that has been won cannot be
given back, and the floors converge on the targets without anyone having to remember.

Usage::

    coverage run -m pytest && coverage xml
    python scripts/check_critical_coverage.py [--coverage-xml coverage.xml] [--update-floors]
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FLOORS_PATH = REPO_ROOT / "scripts" / "coverage_floors.txt"

#: How far above its floor a module may drift before the floor must be raised. Without slack the
#: gate would fail on every incidental one-branch improvement, which trains people to ignore it.
RATCHET_SLACK = 3.0


@dataclass(frozen=True)
class ModuleGate:
    #: Path prefix relative to ``src/``. A prefix matches a whole package.
    prefix: str
    target: float
    rationale: str


#: The critical set. Membership is not about how much code a module has — it is about what a gap in
#: it costs. Each entry names the failure it is protecting against.
CRITICAL_MODULES: tuple[ModuleGate, ...] = (
    ModuleGate(
        "openagent/credentials",
        95.0,
        "an untested branch here leaks a secret or resolves the wrong one",
    ),
    ModuleGate(
        "openagent/security",
        95.0,
        "subprocess isolation, command policy, file locks and atomic writes",
    ),
    ModuleGate(
        "openagent/storage/repositories.py",
        95.0,
        "an untested CAS branch silently loses a concurrent write",
    ),
    ModuleGate(
        "openagent/storage/migrations.py",
        95.0,
        "a migration that half-applies corrupts the only copy of user data",
    ),
    ModuleGate(
        "openagent/services/provider_service.py",
        95.0,
        "the credential saga; a missed compensation orphans a keychain entry",
    ),
    ModuleGate(
        "openagent/services/agent_service.py",
        95.0,
        "agent/provider binding integrity",
    ),
    ModuleGate(
        "openagent/runtimes/cli/updates.py",
        95.0,
        "a wrong verdict here replaces a working CLI with a broken one",
    ),
    ModuleGate(
        "openagent/tui",
        75.0,
        "interface layer: failures are visible and recoverable, so the bar is lower",
    ),
)


def parse_floors(path: Path) -> dict[str, float]:
    floors: dict[str, float] = {}
    if not path.exists():
        return floors
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        prefix, _, value = line.partition("=")
        try:
            floors[prefix.strip()] = float(value.strip())
        except ValueError:
            print(f"warning: unparseable floor line: {raw!r}", file=sys.stderr)
    return floors


def write_floors(path: Path, floors: dict[str, float]) -> None:
    lines = [
        "# Measured branch-coverage floors, enforced by scripts/check_critical_coverage.py.",
        "# Regenerate with: python scripts/check_critical_coverage.py --update-floors",
        "# Never lower a value by hand to make CI pass — that is the one thing this file exists",
        "# to prevent. If coverage legitimately drops (a module was deleted, a branch became",
        "# unreachable), say so in the pull request description.",
        "",
    ]
    lines += [f"{prefix} = {value:.1f}" for prefix, value in sorted(floors.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def measure(coverage_xml: Path) -> dict[str, tuple[int, int, int, int]]:
    """Return ``{source_path: (lines_covered, lines_total, branches_covered, branches_total)}``."""

    tree = ET.parse(coverage_xml)
    root = tree.getroot()
    per_file: dict[str, tuple[int, int, int, int]] = {}

    for class_element in root.iter("class"):
        filename = class_element.get("filename")
        if not filename:
            continue
        normalized = filename.replace("\\", "/")
        # coverage.xml paths are relative to a <source> root; strip a leading src/ if present.
        normalized = re.sub(r"^.*?(?=openagent/)", "", normalized)
        if not normalized.startswith("openagent/"):
            continue

        lines_covered = lines_total = branches_covered = branches_total = 0
        for line in class_element.iter("line"):
            lines_total += 1
            if int(line.get("hits", "0")) > 0:
                lines_covered += 1
            if line.get("branch") == "true":
                # condition-coverage looks like: "50% (1/2)"
                match = re.search(r"\((\d+)/(\d+)\)", line.get("condition-coverage", ""))
                if match:
                    branches_covered += int(match.group(1))
                    branches_total += int(match.group(2))

        previous = per_file.get(normalized, (0, 0, 0, 0))
        per_file[normalized] = (
            previous[0] + lines_covered,
            previous[1] + lines_total,
            previous[2] + branches_covered,
            previous[3] + branches_total,
        )

    return per_file


def aggregate(per_file: dict[str, tuple[int, int, int, int]], prefix: str) -> float | None:
    """Branch coverage across every file under ``prefix``, or None when nothing matched."""

    covered = total = 0
    matched = False
    for path, (_, _, branch_covered, branch_total) in per_file.items():
        if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
            matched = True
            covered += branch_covered
            total += branch_total
    if not matched:
        return None
    if total == 0:
        # A module with no branches at all is vacuously fully covered.
        return 100.0
    return 100.0 * covered / total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-xml", default="coverage.xml", type=Path)
    parser.add_argument(
        "--update-floors",
        action="store_true",
        help="rewrite the floors file from the current measurement instead of checking it",
    )
    args = parser.parse_args()

    if not args.coverage_xml.exists():
        print(
            f"error: {args.coverage_xml} not found — run `coverage run -m pytest && coverage xml`",
            file=sys.stderr,
        )
        return 2

    per_file = measure(args.coverage_xml)
    if not per_file:
        print(f"error: {args.coverage_xml} contained no openagent/ files", file=sys.stderr)
        return 2

    floors = parse_floors(FLOORS_PATH)
    measured: dict[str, float] = {}
    failures: list[str] = []
    ratchets: list[str] = []
    missing: list[str] = []

    width = max(len(gate.prefix) for gate in CRITICAL_MODULES)
    print(f"{'module'.ljust(width)}   branch    floor   target   status")
    print("-" * (width + 40))

    for gate in CRITICAL_MODULES:
        value = aggregate(per_file, gate.prefix)
        if value is None:
            missing.append(gate.prefix)
            print(f"{gate.prefix.ljust(width)}        -        -        -   NOT MEASURED")
            continue
        measured[gate.prefix] = value
        floor = floors.get(gate.prefix)

        if floor is None:
            status = "no floor recorded"
            missing.append(gate.prefix)
        elif value + 0.05 < floor:
            status = f"REGRESSED (-{floor - value:.1f})"
            failures.append(
                f"{gate.prefix}: branch coverage {value:.1f}% fell below the recorded floor "
                f"{floor:.1f}%.\n    Why this module matters: {gate.rationale}."
            )
        elif value > floor + RATCHET_SLACK and floor < gate.target:
            status = f"RAISE FLOOR (+{value - floor:.1f})"
            ratchets.append(
                f"{gate.prefix}: now at {value:.1f}%, floor still {floor:.1f}%. "
                f"Run `python scripts/check_critical_coverage.py --update-floors`."
            )
        elif value + 0.05 >= gate.target:
            status = "at target"
        else:
            status = f"gap to target: {gate.target - value:.1f}"

        floor_text = f"{floor:.1f}" if floor is not None else "-"
        print(
            f"{gate.prefix.ljust(width)}   {value:6.1f}   {floor_text:>6}   "
            f"{gate.target:6.1f}   {status}"
        )

    if args.update_floors:
        # Never lower a floor automatically — that would defeat the ratchet. Only raise.
        updated = dict(floors)
        for prefix, value in measured.items():
            updated[prefix] = max(updated.get(prefix, 0.0), round(value, 1))
        write_floors(FLOORS_PATH, updated)
        print(f"\nWrote {FLOORS_PATH.relative_to(REPO_ROOT)}")
        return 0

    print()
    if missing:
        print(
            "error: no floor recorded for: "
            + ", ".join(missing)
            + "\n       run `python scripts/check_critical_coverage.py --update-floors` "
            "and commit the result.",
            file=sys.stderr,
        )
    for failure in failures:
        print(f"error: {failure}", file=sys.stderr)
    for ratchet in ratchets:
        print(f"error: {ratchet}", file=sys.stderr)

    if failures or ratchets or missing:
        return 1

    remaining = [
        f"{gate.prefix} ({measured[gate.prefix]:.1f}% → {gate.target:.1f}%)"
        for gate in CRITICAL_MODULES
        if gate.prefix in measured and measured[gate.prefix] + 0.05 < gate.target
    ]
    if remaining:
        print("Coverage held. Still below target (not a failure): " + ", ".join(remaining))
    else:
        print("Coverage held; every critical module is at target.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
