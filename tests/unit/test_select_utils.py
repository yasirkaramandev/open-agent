"""Unit coverage for Textual Select empty-value normalisation (root cause of the Add-Agent crash).

Directly exercises every empty/sentinel state a ``Select`` can hold in the installed Textual, plus
synthetic sentinels, so a regression in sentinel handling is caught without a full pilot run.
"""

from __future__ import annotations

from textual.widgets import Select

from openagent.tui.select_utils import normalize_select_value, selected_string


class _FakeNoSelection:
    """Stand-in for a hypothetical future/other Textual no-selection sentinel object."""

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "Select.NULL"


def test_null_sentinel_is_none():
    # The exact sentinel that leaked into AgentRuntime(cli=Select.NULL) in the crash report.
    assert normalize_select_value(Select.NULL) is None


def test_blank_alias_is_none():
    # In current Textual, Select.BLANK resolves to an unrelated Widget attribute (== False).
    assert normalize_select_value(Select.BLANK) is None


def test_synthetic_noselection_object_is_none():
    assert normalize_select_value(_FakeNoSelection()) is None


def test_none_is_none():
    assert normalize_select_value(None) is None


def test_empty_and_whitespace_strings_are_none():
    assert normalize_select_value("") is None
    assert normalize_select_value("   ") is None


def test_normal_string_survives_stripped():
    assert normalize_select_value("codex") == "codex"
    assert normalize_select_value("  claude  ") == "claude"


def test_non_string_values_are_none():
    assert normalize_select_value(False) is None
    assert normalize_select_value(0) is None
    assert normalize_select_value(object()) is None


def test_selected_string_reads_widget_value():
    # An unmounted Select with nothing selected holds Select.NULL -> normalises to None.
    empty = Select([("A", "a"), ("B", "b")], allow_blank=True)
    assert selected_string(empty) is None
    # selected_string simply reads .value and normalises it (mounting is not needed to prove that).
    empty.value = "a"
    assert selected_string(empty) == "a"
