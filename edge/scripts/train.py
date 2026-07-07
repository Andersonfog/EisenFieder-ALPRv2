"""
Fine-tune the EisenFieder YOLO vehicle detector.

Starts from yolov8n.pt (pretrained on COCO) and adapts it to:
  - Your 7 fine-grained vehicle classes (car/suv/truck/van/pickup/motorcycle/bus)
  - Your specific entrance camera angle, lighting, and resolution

Requirements:
  - Run collect_dataset.py first to populate training/images/ and training/labels/
  - At least ~50 images per class for meaningful improvement (200+ is better)

Usage:
  # Quick run (CPU, 30 epochs — good to verify the pipeline works):
  python scripts/train.py --epochs 30 --batch 8

  # Full fine-tune:
  python scripts/train.py --epochs 100 --batch 16

  # If you have a GPU:
  python scripts/train.py --epochs 100 --batch 32 --device 0

After training, the best model is saved and config.yaml is updated automatically.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

EDGE_DIR = Path(__file__).resolve().parent.parent
TRAINING_DIR = EDGE_DIR / "training"
DATA_YAML = TRAINING_DIR / "data.yaml"
RUNS_DIR = TRAINING_DIR / "runs"


def check_dataset():
    n_train = len(list((TRAINING_DIR / "images" / "train").glob("*.jpg")))
    n_val   = len(list((TRAINING_DIR / "images" / "val").glob("*.jpg")))
    if n_train == 0:
        sys.exit(
            "No training images found. Run:\n"
            "  python scripts/collect_dataset.py --source usb\n"
            "or point --source folder at a directory of labeled vehicle images."
        )
    if n_val == 0:
        sys.exit("No validation images found. Re-run collect_dataset.py.")
    print(f"Dataset: {n_train} train / {n_val} val images")
    return n_train, n_val


def train(args):
    from ultralytics import YOLO

    base = EDGE_DIR / args.base_model
    if not base.exists():
        # Try downloading automatically via ultralytics
        print(f"Base model not found locally, will download: {args.base_model}")
        base = args.base_model

    print(f"\nFine-tuning {base} for {args.epochs} epochs "
          f"(batch={args.batch}, imgsz={args.imgsz}, device={args.device})")
    print(f"Output: {RUNS_DIR}\n")

    model = YOLO(str(base))
    results = model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=str(RUNS_DIR),
        name="efs_vehicle",
        exist_ok=True,
        pretrained=True,
        # Augmentation — helps with lighting/angle variation at entrances
        hsv_h=0.015,       # hue shift (handles different times of day)
        hsv_s=0.5,         # saturation (overcast vs sunny)
        hsv_v=0.4,         # brightness (dawn/dusk, headlights)
        degrees=5.0,       # slight rotation (camera not perfectly level)
        translate=0.1,
        scale=0.3,         # zoom variation (cars near/far from camera)
        fliplr=0.5,        # horizontal flip (in vs out lanes)
        mosaic=0.5,        # mosaic aug (helps with partial vehicles)
        # Regularization
        dropout=0.1,
        patience=20,       # early-stop if val mAP doesn't improve for 20 epochs
        # Saving
        save=True,
        save_period=10,    # checkpoint every 10 epochs
        verbose=True,
    )
    return results


def deploy_best_model(run_name: str = "efs_vehicle"):
    best = RUNS_DIR / run_name / "weights" / "best.pt"
    if not best.exists():
        print("best.pt not found — check training/runs/ for output.")
        return

    dest = EDGE_DIR / "efs_vehicle.pt"
    shutil.copy2(best, dest)
    print(f"\nBest model saved to: {dest}")

    # Update config.yaml to point at the new model
    cfg_path = EDGE_DIR / "config.yaml"
    if cfg_path.exists():
        text = cfg_path.read_text()
        if "model_path:" in text:
            import re
            text = re.sub(r"model_path:\s*\S+", "model_path: efs_vehicle.pt", text)
            cfg_path.write_text(text)
            print("config.yaml updated: detector.model_path = efs_vehicle.pt")
        else:
            print("NOTE: manually set detector.model_path: efs_vehicle.pt in config.yaml")
    else:
        print("NOTE: set EISENFIEDER_DETECTOR__MODEL_PATH=efs_vehicle.pt in .env")


def print_metrics(results):
    try:
        m = results.results_dict
        print("\n=== Training Results ===")
        print(f"  mAP50:     {m.get('metrics/mAP50(B)', 0):.4f}")
        print(f"  mAP50-95:  {m.get('metrics/mAP50-95(B)', 0):.4f}")
        print(f"  Precision: {m.get('metrics/precision(B)', 0):.4f}")
        print(f"  Recall:    {m.get('metrics/recall(B)', 0):.4f}")
    except Exception:
        print("(metrics unavailable — check training/runs/ for plots)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-model", default="yolov8n.pt",
                    help="Starting weights (yolov8n.pt / yolov8s.pt / yolov8m.pt)")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default="cpu",
                    help="'cpu' or GPU index e.g. '0'")
    ap.add_argument("--no-deploy", action="store_true",
                    help="Skip copying best.pt to edge/ and updating config.yaml")
    args = ap.parse_args()

    check_dataset()
    results = train(args)
    print_metrics(results)

    if not args.no_deploy:
        deploy_best_model()
        print("\nRestart the camera to load the new model.")


if __name__ == "__main__":
    main()
