"""Canonical name comparison for uniqueness constraints.

Provider and agent names are user-facing labels, so "the same name" has to mean what a person means
by it: ``OpenAI`` and ``openai`` are the same connection, and so are ``café`` typed with a composed
``é`` and with a combining accent. Uniqueness that only catches byte-identical strings lets a user
create two providers they cannot tell apart, and then wonder which one their agent is using.

**Why this is computed in Python and stored, rather than done in SQL.** SQLite's ``NOCASE``
collation folds only ASCII A–Z. It would consider ``CAFÉ`` and ``café`` distinct while considering
``CAFE`` and ``cafe`` the same — a rule no user would predict. ``LOWER()`` has the same limitation.
So the canonical form is derived here, with full Unicode semantics, and written to a
``normalized_name`` column that carries the ``UNIQUE`` constraint. The database enforces the
invariant; this module defines it.

The three steps are not interchangeable and the order matters:

* **NFKC** unifies characters that render identically but differ in code points — combining accents
  versus precomposed forms, and compatibility characters such as the fullwidth ``Ａ``. Without it,
  two names that look identical on screen are distinct keys.
* **strip** removes leading and trailing whitespace, which is almost always a paste artefact rather
  than intent. Interior whitespace is preserved: ``my provider`` and ``myprovider`` are genuinely
  different names.
* **casefold**, not ``lower``. ``lower`` is a display transformation; ``casefold`` is designed for
  caseless matching and handles cases ``lower`` does not, notably German ``ß`` folding to ``ss``.
"""

from __future__ import annotations

import unicodedata


def normalize_name(value: str) -> str:
    """The canonical form of ``value`` for uniqueness comparison.

    Returns the empty string for input that is only whitespace — callers validate non-emptiness
    separately, since "this name is blank" is a different error from "this name is taken".
    """

    return unicodedata.normalize("NFKC", value).strip().casefold()


def names_collide(left: str, right: str) -> bool:
    """Whether two user-supplied names refer to the same thing."""

    return normalize_name(left) == normalize_name(right)
