"""Measure license-plate reading accuracy on YOUR labelled photos.

Marketing numbers don't matter; what matters is accuracy on plates from *your*
camera, at *your* mounting angle and light. This tool gives you that number.

How to use it
=============
1. Make a folder of test images. Name each file after the TRUE plate::

       plates/
         7ABC123.jpg          <- the whole image, or a vehicle crop
         8XYZ456_1.jpg        <- anything after an underscore is ignored,
         8XYZ456_2.jpg           so you can have several photos of one plate

   (Tip: the camera already saves plate close-ups in data/events/ — copy a
   bunch out and rename them to their true plates.)

2. Run::

       cd edge
       python -m tools.measure_alpr --data plates

3. Read the report:
   * exact-match rate — the number that matters (whole plate right),
   * character accuracy — how close the misses were,
   * a confidence table — pick a confidence gate: e.g. "at >=0.85 the system
     answers 90% of the time and is right 98% of the time".

``compute_metrics`` is pure (no ML, no files) so it is unit-tested.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class Sample:
    truth: str                    # the real plate (from the filename)
    predicted: Optional[str]      # what the ALPR read (None = no read)
    confidence: float = 0.0


def levenshtein(a: str, b: str) -> int:
    """Edit distance — how many single-character fixes turn a into b."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1,           # delete
                           cur[j - 1] + 1,        # insert
                           prev[j - 1] + (ca != cb)))  # substitute
        prev = cur
    return prev[-1]


def _norm(text: Optional[str]) -> str:
    return "".join(ch for ch in (text or "") if ch.isalnum()).upper()


def compute_metrics(samples: list[Sample],
                    thresholds: Optional[list[float]] = None) -> dict:
    """Accuracy numbers from (truth, predicted, confidence) triples. Pure."""
    if thresholds is None:
        thresholds = [0.0, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95]

    total = len(samples)
    exact = 0
    read = 0
    char_scores: list[float] = []
    confusions: dict[str, int] = {}   # "truth->read" -> count, for tuning
    for s in samples:
        truth, pred = _norm(s.truth), _norm(s.predicted)
        if pred:
            read += 1
        if truth and truth == pred:
            exact += 1
        span = max(len(truth), len(pred), 1)
        char_scores.append(1.0 - levenshtein(truth, pred) / span if pred else 0.0)
        # Which characters get mixed up (same-length misses, position-wise)?
        if pred and truth and pred != truth and len(pred) == len(truth):
            for tc, pc in zip(truth, pred):
                if tc != pc:
                    key = f"{tc}->{pc}"
                    confusions[key] = confusions.get(key, 0) + 1

    table = []
    for t in thresholds:
        answered = [s for s in samples if _norm(s.predicted) and s.confidence >= t]
        correct = sum(1 for s in answered if _norm(s.predicted) == _norm(s.truth))
        table.append({
            "threshold": t,
            "answered": len(answered),
            "coverage": round(len(answered) / total, 4) if total else 0.0,
            "correct": correct,
            "accuracy": round(correct / len(answered), 4) if answered else None,
        })

    return {
        "total_images": total,
        "read_rate": round(read / total, 4) if total else 0.0,
        "exact_match_rate": round(exact / total, 4) if total else 0.0,
        "char_accuracy": round(sum(char_scores) / total, 4) if total else 0.0,
        "threshold_table": table,
        "confusions": dict(sorted(confusions.items(),
                                  key=lambda kv: (-kv[1], kv[0]))),
    }


# --------------------------------------------------------------------------- #
# CLI — runs the REAL reader over a labelled folder
# --------------------------------------------------------------------------- #


def _truth_from_name(path: Path) -> str:
    stem = path.stem
    if "_" in stem:
        stem = stem.split("_", 1)[0]
    return _norm(stem)


def _collect(data_dir: Path, reader, fuse: bool) -> list[Sample]:
    import cv2

    from efsurveillance.plate_fusion import fuse_observations

    samples: list[Sample] = []
    files = sorted(p for p in data_dir.rglob("*") if p.suffix.lower() in _IMAGE_EXTS)
    groups: dict[str, list[Path]] = {}
    for p in files:
        groups.setdefault(_truth_from_name(p), []).append(p)

    for truth, paths in groups.items():
        if not truth:
            continue
        obs = []
        singles = []
        for p in paths:
            img = cv2.imread(str(p))
            if img is None:
                print(f"  ! unreadable image skipped: {p.name}")
                continue
            h, w = img.shape[:2]
            res = reader.read(img, (0, 0, w, h))
            singles.append(res)
            o = res.to_observation() if res else None
            if o is not None:
                obs.append(o)

        if fuse and obs:
            fused = fuse_observations(obs)
            samples.append(Sample(truth, fused.text if fused else None,
                                  fused.confidence if fused else 0.0))
        else:
            best = max((r for r in singles if r and r.text),
                       key=lambda r: r.confidence, default=None)
            samples.append(Sample(truth, best.text if best else None,
                                  best.confidence if best else 0.0))
    return samples


def _print_report(m: dict) -> None:
    print()
    print("=" * 62)
    print("ALPR ACCURACY REPORT")
    print("=" * 62)
    print(f"Plates tested       : {m['total_images']}")
    print(f"Read rate           : {m['read_rate'] * 100:5.1f}%   (a text came back)")
    print(f"Exact-match rate    : {m['exact_match_rate'] * 100:5.1f}%   (whole plate right)")
    print(f"Character accuracy  : {m['char_accuracy'] * 100:5.1f}%   (how close misses were)")
    print()
    print("Confidence gate     answers      right    accuracy")
    print("-" * 52)
    for row in m["threshold_table"]:
        acc = f"{row['accuracy'] * 100:5.1f}%" if row["accuracy"] is not None else "   -  "
        print(f"  >= {row['threshold']:.2f}          {row['answered']:4d} "
              f"({row['coverage'] * 100:5.1f}%)   {row['correct']:4d}     {acc}")
    print("-" * 52)
    print("Pick the gate where accuracy is high enough for you and coverage")
    print("is still useful; watchlist alerts should use a high gate.")
    if m.get("confusions"):
        top = list(m["confusions"].items())[:8]
        print()
        print("Top character mixups (true->read):",
              ", ".join(f"{k} x{n}" for k, n in top))
        print("(If one pair dominates, tell us — the repair maps can learn it.)")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="measure_alpr",
        description="Measure plate-reading accuracy on a folder of labelled photos.",
    )
    parser.add_argument("--data", required=True,
                        help="Folder of images named after their true plate")
    parser.add_argument("--no-fuse", action="store_true",
                        help="Score each image alone instead of fusing multiple "
                             "photos of the same plate (fusing = how the live "
                             "pipeline behaves)")
    args = parser.parse_args(argv)

    data_dir = Path(args.data)
    if not data_dir.is_dir():
        print(f"Not a folder: {data_dir}")
        return 2

    from efsurveillance.plate_reader import RealPlateReader

    print("Loading the plate reader (first run downloads models)...")
    reader = RealPlateReader()
    if reader._alpr is None:
        print("fast-alpr is not installed - run: pip install fast-alpr")
        return 2

    samples = _collect(data_dir, reader, fuse=not args.no_fuse)
    if not samples:
        print("No labelled images found (name files after the true plate).")
        return 2
    _print_report(compute_metrics(samples))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
