"""Measure a make/model classifier's accuracy BEFORE you trust it.

Why this exists
---------------
A make/model classifier is only worth turning on if it's actually right often
enough on YOUR camera's view. Models are usually trained on clean, straight-on
catalog photos; an entrance camera sees cars at an angle, partly cropped, in bad
light. So the honest workflow is: measure first, then decide the confidence
threshold at which the answer is trustworthy — and leave make/model blank below
it. This tool does the measuring.

What you need
-------------
1. A folder of labelled crops, one sub-folder per make/model, folder name == the
   label as it appears in your labels file::

       testset/
         Ford F-150/       img1.jpg img2.jpg ...
         Toyota Camry/     ...
         Honda Civic/      ...

2. The classifier itself (``--model model.onnx --labels labels.txt``).

Run it
------
    cd edge
    python -m tools.measure_make_model --data testset --model model.onnx \
        --labels labels.txt

Read the output
---------------
* **Overall top-1 accuracy** — right answers over ALL images.
* **Coverage/accuracy by confidence threshold** — the important table. For each
  threshold it shows how many images the model was that sure about (coverage)
  and how often it was RIGHT on those. Pick the lowest threshold whose accuracy
  you'd trust, then set ``detector.makemodel_min_confidence`` to it and turn the
  classifier on. Below that confidence the field stays blank (no fake data).

The metric math lives in :func:`compute_metrics` so it can be unit-tested
without a model or any images.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

DEFAULT_THRESHOLDS = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9]
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class Sample:
    """One evaluated image."""

    truth: str                 # ground-truth label (the folder name)
    pred: Optional[str]        # predicted label, or None if the model abstained
    confidence: float          # 0..1 (0.0 when pred is None)


def _norm(label: Optional[str]) -> str:
    """Loose label comparison: case-insensitive, whitespace-collapsed."""
    return " ".join((label or "").split()).casefold()


def compute_metrics(
    samples: Iterable[Sample],
    thresholds: Optional[list[float]] = None,
) -> dict:
    """Turn evaluated samples into accuracy metrics (pure, no I/O).

    Returns overall top-1 accuracy, a coverage/accuracy table across confidence
    thresholds, and per-class accuracy. "Coverage" = fraction of all images the
    model answered (pred set AND confidence >= threshold); "accuracy" on that
    slice = correct / answered.
    """
    thresholds = thresholds if thresholds is not None else list(DEFAULT_THRESHOLDS)
    samples = list(samples)
    total = len(samples)

    correct_overall = sum(
        1 for s in samples if s.pred is not None and _norm(s.pred) == _norm(s.truth)
    )

    table = []
    for t in thresholds:
        answered = [s for s in samples if s.pred is not None and s.confidence >= t]
        n_ans = len(answered)
        n_correct = sum(1 for s in answered if _norm(s.pred) == _norm(s.truth))
        table.append({
            "threshold": round(t, 3),
            "coverage": round(n_ans / total, 4) if total else 0.0,
            "answered": n_ans,
            "correct": n_correct,
            "accuracy": round(n_correct / n_ans, 4) if n_ans else 0.0,
        })

    per_class: dict[str, dict] = {}
    for s in samples:
        c = per_class.setdefault(s.truth, {"total": 0, "correct": 0})
        c["total"] += 1
        if s.pred is not None and _norm(s.pred) == _norm(s.truth):
            c["correct"] += 1
    for c in per_class.values():
        c["accuracy"] = round(c["correct"] / c["total"], 4) if c["total"] else 0.0

    return {
        "total_images": total,
        "overall_top1_accuracy": round(correct_overall / total, 4) if total else 0.0,
        "threshold_table": table,
        "per_class": per_class,
    }


def format_report(metrics: dict) -> str:
    """Human-readable version of :func:`compute_metrics` output."""
    lines = []
    lines.append(f"Images evaluated : {metrics['total_images']}")
    lines.append(f"Overall top-1    : {metrics['overall_top1_accuracy'] * 100:.1f}%")
    lines.append("")
    lines.append("Confidence gate -> what you'd get if you set min_confidence there:")
    lines.append(f"  {'min_conf':>9}  {'coverage':>9}  {'answered':>9}  {'accuracy':>9}")
    for row in metrics["threshold_table"]:
        lines.append(
            f"  {row['threshold']:>9.2f}  {row['coverage'] * 100:>8.1f}%  "
            f"{row['answered']:>9}  {row['accuracy'] * 100:>8.1f}%"
        )
    lines.append("")
    lines.append("Per-class accuracy:")
    for label, c in sorted(metrics["per_class"].items()):
        lines.append(f"  {label:<28} {c['correct']:>4}/{c['total']:<4} "
                     f"{c['accuracy'] * 100:>6.1f}%")
    return "\n".join(lines)


def _iter_labelled_images(data_dir: Path) -> Iterable[tuple[str, Path]]:
    for sub in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        for img in sorted(sub.iterdir()):
            if img.suffix.lower() in _IMAGE_EXTS:
                yield sub.name, img


def _evaluate_dataset(data_dir: Path, classifier, limit: Optional[int]) -> list[Sample]:
    import cv2  # imported here so the metric math stays importable without OpenCV

    samples: list[Sample] = []
    for truth, img_path in _iter_labelled_images(data_dir):
        frame = cv2.imread(str(img_path))
        if frame is None:
            print(f"  ! could not read {img_path}", file=sys.stderr)
            continue
        h, w = frame.shape[:2]
        res = classifier.classify(frame, (0, 0, w, h))  # whole crop = the vehicle
        if res is None:
            samples.append(Sample(truth=truth, pred=None, confidence=0.0))
        else:
            label = " ".join(p for p in [res.make, res.model] if p)
            samples.append(Sample(truth=truth, pred=label, confidence=res.confidence))
        if limit and len(samples) >= limit:
            break
    return samples


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="measure_make_model",
        description="Measure a make/model classifier's accuracy on a labelled test set.",
    )
    parser.add_argument("--data", required=True, help="Folder of labelled crops (sub-folder per label)")
    parser.add_argument("--model", required=True, help="Path to the .onnx classifier")
    parser.add_argument("--labels", required=True, help="Labels file (one label per line, order = class index)")
    parser.add_argument("--input-size", type=int, default=224)
    parser.add_argument("--limit", type=int, default=0, help="Evaluate at most N images (0 = all)")
    parser.add_argument("--report", help="Write the metrics JSON to this path")
    args = parser.parse_args(argv)

    # Imported lazily so importing this module (for its metric functions) never
    # requires the recognizer's optional deps.
    from efsurveillance.recognizer import MakeModelClassifier

    data_dir = Path(args.data)
    if not data_dir.is_dir():
        print(f"error: --data folder not found: {data_dir}", file=sys.stderr)
        return 2

    classifier = MakeModelClassifier(
        backend="onnx", model_path=args.model, labels_path=args.labels,
        min_confidence=0.0,          # measure the RAW model; the gate is what we're choosing
        input_size=args.input_size,
    )
    if not classifier.enabled:
        print("error: classifier failed to load (see the warning above).", file=sys.stderr)
        return 2

    samples = _evaluate_dataset(data_dir, classifier, args.limit or None)
    if not samples:
        print(f"error: no images found under {data_dir}", file=sys.stderr)
        return 2

    metrics = compute_metrics(samples)
    print(format_report(metrics))
    if args.report:
        Path(args.report).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        print(f"\nWrote {args.report}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
