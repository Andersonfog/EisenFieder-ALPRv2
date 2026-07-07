"""Cosine similarity for vehicle appearance fingerprints.

The edge unit stores a compact "what this vehicle looks like" vector with each
event (see edge ``profiles.py``: colour histogram + shape gradients + geometry,
computed from the best side-view crop of the pass). Comparing two vectors says
"these two vehicles LOOK alike" — a suggestion for the owner, never an identity
claim; license plates do identity.

Vectors of different lengths or versions honestly compare as 0.
"""

from __future__ import annotations


def cosine(a, b) -> float:
    """Cosine similarity clamped to 0.0-1.0; 0.0 for anything malformed."""
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        dot = sum(float(x) * float(y) for x, y in zip(a, b))
        na = sum(float(x) * float(x) for x in a) ** 0.5
        nb = sum(float(y) * float(y) for y in b) ** 0.5
    except (TypeError, ValueError):
        return 0.0
    if not na or not nb:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))
