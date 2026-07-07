"""Multi-frame license-plate fusion — the accuracy engine of the ALPR.

A car crossing the entrance is seen on many frames. Any single OCR read can be
wrong (motion blur, glare, a bug on the plate), but the *errors differ frame to
frame* while the truth stays the same. So instead of trusting one read, we:

  1. collect every read of the plate while the vehicle is tracked
     (:class:`PlateObservation`, produced by ``plate_reader``),
  2. vote character-by-character across all reads, weighting each vote by how
     much we trust that read (OCR confidence x how large/sharp the plate was),
  3. optionally repair classic OCR confusions (O<->0, I<->1, B<->8, S<->5 ...)
     — but ONLY on low-confidence characters, and ONLY when the repair makes
     the plate match a real-world plate pattern. A confident character is
     never altered, so we can't "correct" a plate into fiction.

This is the same idea commercial ALPR systems use ("plate grouping" /
"multi-frame consensus") and is worth far more accuracy than a bigger model.

Everything here is pure Python + arithmetic: deterministic and unit-testable
with no ML dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Observations (one per OCR read of one vehicle)
# --------------------------------------------------------------------------- #


@dataclass
class PlateObservation:
    """One OCR read of a plate, with everything needed to weight its vote."""

    text: str                                   # cleaned A-Z/0-9 text
    char_confidences: list[float] = field(default_factory=list)  # aligned to text
    confidence: float = 0.0                     # mean of char_confidences
    region: Optional[str] = None                # OCR's region/state guess
    region_confidence: Optional[float] = None
    plate_height: int = 0                       # plate box height in px (bigger = closer)
    sharpness: float = 0.0                      # Laplacian variance of the crop (higher = crisper)
    bbox: Optional[tuple] = None                # plate box in full-frame coords
    crop: Any = None                            # BGR ndarray of the plate pixels (optional)


@dataclass
class FusedPlate:
    """The consensus plate for one vehicle after voting across all reads."""

    text: str
    confidence: float                           # mean fused per-character confidence
    char_confidences: list[float] = field(default_factory=list)
    region: Optional[str] = None
    region_confidence: Optional[float] = None
    reads: int = 0                              # how many OCR reads voted
    corrected: bool = False                     # True if format repair changed a character
    raw_text: Optional[str] = None              # pre-repair consensus (when corrected)
    # Positions where the frames agreed on the GLYPH but split between its
    # letter and digit twin (B vs 8, O vs 0) — format repair may flip these
    # even when the glyph itself was read confidently.
    ambiguous_positions: list[int] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Vote weighting
# --------------------------------------------------------------------------- #

# A plate ~44px tall fills the OCR model's input nicely; sharpness ~120+ is a
# crisp crop on this camera class. Both saturate at 1.0 so a huge/crisp frame
# can't drown out everything else — it just votes a bit louder.
_FULL_HEIGHT_PX = 44.0
_FULL_SHARPNESS = 120.0


def _quality(obs: PlateObservation) -> float:
    """How much this read's votes count (0.5 .. 1.0)."""
    h = min(1.0, obs.plate_height / _FULL_HEIGHT_PX) if obs.plate_height > 0 else 0.5
    s = min(1.0, obs.sharpness / _FULL_SHARPNESS) if obs.sharpness > 0 else 0.5
    return 0.5 + 0.25 * h + 0.25 * s


def _char_conf(obs: PlateObservation, i: int) -> float:
    if i < len(obs.char_confidences):
        return max(0.0, min(1.0, obs.char_confidences[i]))
    return max(0.0, min(1.0, obs.confidence))


# --------------------------------------------------------------------------- #
# Consensus voting
# --------------------------------------------------------------------------- #


def fuse_observations(
    observations: list[PlateObservation],
    *,
    format_correction: bool = True,
) -> Optional[FusedPlate]:
    """Merge every read of one vehicle's plate into a single best answer.

    Returns None when there are no usable reads (honest blank, never a guess).
    """
    obs = [o for o in observations if o and o.text]
    if not obs:
        return None

    # 1) Agree on the plate LENGTH first. Each read votes for its length with
    #    its overall weight.
    length_votes: dict[int, float] = {}
    for o in obs:
        w = max(0.05, o.confidence) * _quality(o)
        length_votes[len(o.text)] = length_votes.get(len(o.text), 0.0) + w
    best_len = max(length_votes, key=lambda k: (length_votes[k], k))
    voters = [o for o in obs if len(o.text) == best_len]

    # 2) Character-by-character weighted vote among same-length reads.
    identity = list(range(best_len))
    participants: list[tuple[PlateObservation, list[Optional[int]]]] = [
        (o, identity) for o in voters
    ]
    fused_chars, fused_confs, ambiguous = _vote_positions(participants, best_len)

    # 3) A read that dropped or gained a character still saw MOST of the plate
    #    — align it to the consensus so its good characters vote too, instead
    #    of throwing the whole read away.
    anchor = "".join(fused_chars)
    extras: list[tuple[PlateObservation, list[Optional[int]]]] = []
    for o in obs:
        diff = len(o.text) - best_len
        if diff == 0 or abs(diff) > _ALIGN_MAX_LEN_DIFF:
            continue
        mapping = _align_to(o.text, anchor)
        if mapping is not None:
            extras.append((o, mapping))
    if extras:
        fused_chars, fused_confs, ambiguous = _vote_positions(
            participants + extras, best_len)

    text = "".join(fused_chars)

    # 4) Region (issuing state/country): same weighted vote across reads.
    region, region_conf = _fuse_region(obs)

    fused = FusedPlate(
        text=text,
        confidence=round(sum(fused_confs) / len(fused_confs), 4) if fused_confs else 0.0,
        char_confidences=fused_confs,
        region=region,
        region_confidence=region_conf,
        reads=len(obs),
        ambiguous_positions=ambiguous,
    )

    if format_correction:
        repaired = correct_format(fused.text, fused.char_confidences,
                                  swappable=set(ambiguous))
        if repaired != fused.text:
            fused.raw_text = fused.text
            fused.text = repaired
            fused.corrected = True

    return fused


def _vote_positions(
    participants: list[tuple[PlateObservation, list[Optional[int]]]],
    length: int,
) -> tuple[list[str], list[float], list[int]]:
    """The per-position weighted vote. Each participant is (read, mapping)
    where mapping[i] is the index into that read's text voting at position i
    (None = this read didn't see that position).

    Look-alike twins (B/8, O/0, S/5 ...) are pooled as ONE glyph vote: frames
    splitting between B and 8 AGREE about the shape on the plate — that's not
    disagreement, just letter-vs-digit ambiguity, which the plate-layout
    templates resolve later. Such positions are reported as ambiguous.
    """
    chars: list[str] = []
    confs: list[float] = []
    ambiguous: list[int] = []
    for i in range(length):
        votes: dict[str, float] = {}          # literal char -> total vote weight
        pairs_by_char: dict[str, list[tuple[float, float]]] = {}
        for o, mapping in participants:
            src = mapping[i]
            if src is None or src >= len(o.text):
                continue
            ch = o.text[src]
            c = _char_conf(o, src)
            q = _quality(o)
            votes[ch] = votes.get(ch, 0.0) + c * q
            pairs_by_char.setdefault(ch, []).append((c, q))
        if not votes:
            chars.append("?")
            confs.append(0.0)
            continue

        # Pool look-alike twins into one glyph class, vote on the class...
        class_votes: dict[str, float] = {}
        for ch, v in votes.items():
            cls = _glyph_class(ch)
            class_votes[cls] = class_votes.get(cls, 0.0) + v
        win_class = max(class_votes, key=lambda k: class_votes[k])
        members = [ch for ch in votes if _glyph_class(ch) == win_class]
        # ...then the literal spelling is the strongest member of the class.
        winner = max(members, key=lambda ch: votes[ch])

        total = sum(votes.values()) or 1.0
        share = class_votes[win_class] / total  # 1.0 when every read agrees

        # Weighted mean confidence of every vote for the winning GLYPH...
        pairs = [p for ch in members for p in pairs_by_char[ch]]
        wsum = sum(q for _, q in pairs) or 1.0
        mean_conf = sum(c * q for c, q in pairs) / wsum
        # ...boosted a little for independent agreement (three frames agreeing
        # at 0.9 is stronger evidence than one frame at 0.9)...
        agree_boost = 1.0 - (1.0 - mean_conf) * (0.6 ** (len(pairs) - 1))
        # ...and scaled down by disagreement (a contested character is suspect).
        chars.append(winner)
        confs.append(round(agree_boost * share, 4))

        # Letter-vs-digit twins genuinely split? Flag it so format repair may
        # flip within the class even though the glyph itself is confident.
        if len(members) > 1:
            minority = 1.0 - votes[winner] / (class_votes[win_class] or 1.0)
            if minority >= _AMBIGUITY_MIN_SHARE:
                ambiguous.append(i)
    return chars, confs, ambiguous


# Off-length reads within this many characters of the consensus length are
# aligned and vote; anything further off is a different plate or garbage.
_ALIGN_MAX_LEN_DIFF = 2
# A look-alike minority needs at least this share of the glyph vote to mark
# the position letter-vs-digit ambiguous.
_AMBIGUITY_MIN_SHARE = 0.2


def _align_to(text: str, anchor: str) -> Optional[list[Optional[int]]]:
    """Align a read of the wrong length to the consensus (edit-distance DP).

    Returns, for each anchor position, the index in ``text`` that voted there
    (None where the read missed a character), or None when the read is too
    different to be the same plate.
    """
    m, n = len(text), len(anchor)
    if m < 3 or n == 0:
        return None

    def sub_cost(a: str, b: str) -> float:
        if a == b:
            return 0.0
        # A look-alike twin (B/8, O/0) is nearly a match for alignment.
        return 0.4 if _glyph_class(a) == _glyph_class(b) else 1.0

    dp = [[0.0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        dp[i][0] = float(i)
    for j in range(1, n + 1):
        dp[0][j] = float(j)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = min(dp[i - 1][j - 1] + sub_cost(text[i - 1], anchor[j - 1]),
                           dp[i - 1][j] + 1.0,     # extra char in the read
                           dp[i][j - 1] + 1.0)     # read missed this position

    if dp[m][n] > 0.5 * n:
        return None  # mostly different characters — not this plate

    mapping: list[Optional[int]] = [None] * n
    i, j = m, n
    while i > 0 and j > 0:
        if dp[i][j] == dp[i - 1][j - 1] + sub_cost(text[i - 1], anchor[j - 1]):
            mapping[j - 1] = i - 1
            i -= 1
            j -= 1
        elif dp[i][j] == dp[i - 1][j] + 1.0:
            i -= 1
        else:
            j -= 1
    return mapping


def consensus_locked(observations: Optional[list],
                     *, min_agree: int = 3, min_conf: float = 0.92) -> bool:
    """True once enough confident reads agree EXACTLY on the plate text.

    At that point more OCR can't change the answer — the caller can stop
    paying for reads (a big CPU saving on a Pi).
    """
    counts: dict[str, int] = {}
    for o in observations or []:
        if o is None or not o.text or o.confidence < min_conf:
            continue
        counts[o.text] = counts.get(o.text, 0) + 1
        if counts[o.text] >= min_agree:
            return True
    return False


def _fuse_region(obs: list[PlateObservation]) -> tuple[Optional[str], Optional[float]]:
    votes: dict[str, float] = {}
    confs: dict[str, list[float]] = {}
    for o in obs:
        if not o.region:
            continue
        rc = o.region_confidence if o.region_confidence is not None else 0.5
        votes[o.region] = votes.get(o.region, 0.0) + rc * _quality(o)
        confs.setdefault(o.region, []).append(rc)
    if not votes:
        return None, None
    winner = max(votes, key=lambda k: votes[k])
    lst = confs[winner]
    return winner, round(sum(lst) / len(lst), 4)


# --------------------------------------------------------------------------- #
# Format-aware repair of classic OCR confusions
# --------------------------------------------------------------------------- #

# Common US plate layouts, as L(etter)/D(igit) patterns. A match is a BONUS
# used to repair doubtful characters — an unusual plate that matches nothing
# is left exactly as read.
DEFAULT_TEMPLATES = (
    "LLLDDDD",   # ABC1234  - TX, NY, FL, PA, NC, ...
    "DLLLDDD",   # 7ABC123  - California
    "LLLDDD",    # ABC123   - many states
    "DDDLLL",    # 123ABC
    "LLLLDDD",   # ABCD123
    "LLDDDDD",   # AB12345
    "LLDDDD",    # AB1234
    "DDDDLL",    # 1234AB
)

# Which characters OCR mixes up, per direction. Deliberately conservative —
# only pairs that genuinely look alike on a stamped plate.
_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
             "A": "4", "S": "5", "G": "6", "T": "7", "B": "8"}
_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G",
              "7": "T", "8": "B"}

# A character at or above this confidence is trusted as-is and never swapped.
_SWAP_BELOW_CONF = 0.90
# Never rewrite more than this many characters of one plate.
_MAX_SWAPS = 2

# Look-alike "glyph classes" built from the confusion maps: B and 8 are the
# same stamped shape, so votes for either are votes for the same glyph.
_GLYPH_CLASS: dict[str, str] = {}
for _l, _d in _TO_DIGIT.items():
    _GLYPH_CLASS[_l] = _d
    _GLYPH_CLASS[_d] = _d


def _glyph_class(ch: str) -> str:
    return _GLYPH_CLASS.get(ch, ch)


def matches_template(text: str, template: str) -> bool:
    if len(text) != len(template):
        return False
    for ch, t in zip(text, template):
        if t == "L" and not ch.isalpha():
            return False
        if t == "D" and not ch.isdigit():
            return False
    return True


def correct_format(
    text: str,
    char_confidences: list[float],
    templates: tuple[str, ...] = DEFAULT_TEMPLATES,
    swappable: Optional[set] = None,
) -> str:
    """Repair look-alike OCR mistakes using plate-layout knowledge.

    Example: consensus "7ABCI23" with a shaky "I" — no US plate is
    digit-letters-I-digits, but swapping the doubtful I->1 gives "7ABC123",
    a perfect California pattern, so the swap is applied. If the "I" had been
    read confidently, nothing is touched.

    ``swappable`` positions were flagged letter-vs-digit ambiguous by the vote
    (frames split between B and 8): those may be flipped within their glyph
    class even at high confidence — the glyph is certain, only its letter/digit
    reading isn't, and that's exactly what the layout decides.
    """
    if not text or not text.isalnum():
        return text
    swappable = swappable or set()

    # Already a clean match for a known layout -> leave it alone.
    if any(matches_template(text, t) for t in templates):
        return text

    best: Optional[tuple[float, str]] = None    # (total doubt of swapped chars, candidate)
    for template in templates:
        if len(template) != len(text):
            continue
        candidate = list(text)
        swaps = 0
        cost = 0.0
        ok = True
        for i, (ch, t) in enumerate(zip(text, template)):
            wants_digit = t == "D"
            fits = ch.isdigit() if wants_digit else ch.isalpha()
            if fits:
                continue
            conf = char_confidences[i] if i < len(char_confidences) else 0.0
            swap = (_TO_DIGIT if wants_digit else _TO_LETTER).get(ch.upper())
            if swap is None or (conf >= _SWAP_BELOW_CONF and i not in swappable):
                ok = False       # can't honestly reach this template
                break
            candidate[i] = swap
            swaps += 1
            # Prefer swapping the MOST doubtful characters; a vote-flagged
            # ambiguous position is the cheapest flip of all.
            cost += 0.0 if i in swappable else conf
            if swaps > _MAX_SWAPS:
                ok = False
                break
        if ok and swaps > 0:
            cand = "".join(candidate)
            if best is None or cost < best[0]:
                best = (cost, cand)

    return best[1] if best else text


# --------------------------------------------------------------------------- #
# Best-shot selection (which crop to save as the plate photo)
# --------------------------------------------------------------------------- #


def best_crop_observation(observations: list[PlateObservation]) -> Optional[PlateObservation]:
    """The read with the best plate PICTURE (sharpest + largest), for the saved
    close-up. Independent of the text vote — a blurry frame may still have won
    the vote, but we show the crispest photo we captured."""
    with_crop = [o for o in observations if o is not None and o.crop is not None]
    if not with_crop:
        return None
    return max(with_crop, key=lambda o: (o.sharpness + 1.0) * max(o.plate_height, 1))
