"""License-plate text helpers.

We store two forms of a plate: the human-readable ``plate_text`` (what the
console shows) and a ``plate_normalized`` form (letters+digits only, uppercased)
that we match and search on — so "ABC-1234", "abc 1234" and "ABC1234" all line up.
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def normalize_plate(text: str | None) -> str:
    """Uppercase and strip everything except letters and digits."""
    if not text:
        return ""
    return _NON_ALNUM.sub("", text.upper())
