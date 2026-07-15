"""Safe access to Textual ``Select`` values (root cause of the Add-Agent crash).

Textual signals "no option selected" with a sentinel object, but the *name* and *identity* of that
sentinel changed across versions:

* older Textual exposed it as ``Select.BLANK`` (a ``NoSelection`` instance);
* current Textual (8.x) exposes it as ``Select.NULL`` — and ``Select.BLANK`` now resolves to an
  unrelated ``Widget`` attribute whose value is ``False``.

Code that special-cased ``Select.BLANK`` therefore let the real ``Select.NULL`` sentinel pass
straight through into services, Pydantic models, SQLite and OPENAGENT.md — producing::

    ValidationError: cli — Input should be a valid string
    input_value=Select.NULL

The robust, version-independent rule used here does **not** depend on any sentinel name: a real
selection is always a non-empty ``str``. Anything else — ``Select.NULL``, ``Select.BLANK``, any
``NoSelection`` instance, ``None``, an empty/whitespace string — means "nothing selected".
"""

from __future__ import annotations

from textual.widgets import Select


def normalize_select_value(value: object) -> str | None:
    """Collapse any Textual Select value to a clean ``str`` or ``None``.

    ``None`` is returned for every "no selection" sentinel (regardless of Textual version) and for
    blank/whitespace strings. Only a non-empty string survives, stripped.
    """

    if not isinstance(value, str):
        # Covers Select.NULL / Select.BLANK / NoSelection / None / any non-string sentinel.
        return None
    value = value.strip()
    return value or None


def selected_string(select: Select) -> str | None:
    """Return the Select's current selection as a clean ``str``, or ``None`` if unselected."""

    return normalize_select_value(select.value)
