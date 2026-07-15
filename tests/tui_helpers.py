"""Small helpers for TUI tests.

Textual's ``Select`` exposes no public accessor for its current option list in the pinned 8.2.x
line, so reading it for assertions requires the private ``_options`` attribute. Centralize that one
version-coupled access here (item 12) so the whole suite has a single place to update if the pin
moves and a public API becomes available.
"""

from __future__ import annotations

from textual.widgets import Select


def select_option_labels(select: Select) -> list[str]:
    """The display labels currently offered by a Select."""

    return [opt[0] for opt in select._options]  # no public accessor in Textual 8.2


def select_option_values(select: Select) -> list[object]:
    """The internal values currently offered by a Select (blank/None entries excluded)."""

    return [opt[1] for opt in select._options if opt[1] is not None]


def select_all_option_values(select: Select) -> list[object]:
    """Every option value in overlay order, blanks included (for keyboard-navigation math)."""

    return [opt[1] for opt in select._options]
