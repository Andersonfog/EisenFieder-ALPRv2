"""
Download a ready-made vehicle dataset from Roboflow Universe (free, no account needed
for public datasets). This gets you ~1000+ labeled vehicle images immediately so you
can train without any manual labeling.

After downloading, run:
  python scripts/train.py

For best results, ALSO collect your own entrance footage with collect_dataset.py
and add those images to the training set — they teach the model your specific
camera angle, lighting, and distance.

Usage:
  python scripts/download_public_dataset.py
"""

from __future__ import annotations

import sys
import shutil
from pathlib import Path

EDGE_DIR = Path(__file__).resolve().parent.parent
TRAINING_DIR = EDGE_DIR / "training"

# Maps Roboflow dataset class names -> our EFS class indices.
# This varies by dataset — adjust if you use a different one.
RF_CLASS_MAP: dict[str, int] = {
    "car": 0,
    "Car": 0,
    "SUV": 1,
    "suv": 1,
    "Truck": 2,
    "truck": 2,
    "Van": 3,
    "van": 3,
    "Pickup": 4,
    "pickup": 4,
    "Motorcycle": 5,
    "motorcycle": 5,
    "Bus": 6,
    "bus": 6,
    # Coarser fallbacks
    "vehicle": 0,
    "Vehicle": 0,
}


def remap_labels(src_labels: Path, dst_labels: Path, class_names: list[str]) -> int:
    """Rewrite label files mapping source class indices to EFS class indices."""
    dst_labels.mkdir(parents=True, exist_ok=True)
    remapped = 0
    for lbl_path in src_labels.glob("*.txt"):
        lines_out = []
        for line in lbl_path.read_text().splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            src_cls = int(parts[0])
            if src_cls >= len(class_names):
                continue
            src_name = class_names[src_cls]
            efs_idx = RF_CLASS_MAP.get(src_name)
            if efs_idx is None:
                continue  # skip classes we don't care about
            lines_out.append(f"{efs_idx} " + " ".join(parts[1:]))
        if lines_out:
            (dst_labels / lbl_path.name).write_text("\n".join(lines_out))
            remapped += 1
    return remapped


def download_via_roboflow():
    try:
        from roboflow import Roboflow
    except ImportError:
        print("Installing roboflow...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "roboflow", "-q"])
        from roboflow import Roboflow

    print("Downloading vehicle dataset from Roboflow Universe...")
    # Free public dataset — no API key needed for public downloads.
    rf = Roboflow(api_key="")
    project = rf.workspace("brad-dwyer").project("vehicle-detection-3mmwj")
    version = project.version(1)
    dataset = version.download("yolov8", location=str(TRAINING_DIR / "_rf_download"))
    return Path(dataset.location)


def download_via_kaggle_alternative():
    """Fallback: manual instructions if Roboflow fails."""
    print(
        "\nIf Roboflow download fails, get a free labeled dataset from:\n"
        "  https://universe.roboflow.com/brad-dwyer/vehicle-detection-3mmwj\n"
        "  -> Export as 'YOLOv8' -> Download zip\n"
        "\nThen run:\n"
        "  python scripts/download_public_dataset.py --local path/to/downloaded.zip\n"
    )


def import_local_zip(zip_path: Path):
    import zipfile
    extract_to = TRAINING_DIR / "_rf_download"
    extract_to.mkdir(parents=True, exist_ok=True)
    print(f"Extracting {zip_path}...")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(extract_to)
    return extract_to


def integrate_dataset(dataset_dir: Path):
    """Copy images/labels from the downloaded dataset into our training structure."""
    import yaml

    # Find data.yaml in the downloaded dataset
    data_yamls = list(dataset_dir.rglob("data.yaml"))
    if not data_yamls:
        sys.exit("Could not find data.yaml in the downloaded dataset.")
    data_yaml_path = data_yamls[0]
    with data_yaml_path.open() as f:
        ds_cfg = yaml.safe_load(f)
    class_names = ds_cfg.get("names", [])
    if isinstance(class_names, dict):
        class_names = [class_names[i] for i in sorted(class_names)]
    print(f"Source dataset classes: {class_names}")

    total_images = 0
    for split in ("train", "valid", "val", "test"):
        src_img = dataset_dir / split / "images"
        src_lbl = dataset_dir / split / "labels"
        if not src_img.exists():
            continue
        dst_split = "val" if split in ("valid", "val", "test") else "train"
        dst_img = TRAINING_DIR / "images" / dst_split
        dst_lbl = TRAINING_DIR / "labels" / dst_split
        dst_img.mkdir(parents=True, exist_ok=True)

        # Copy images
        imgs = list(src_img.glob("*.jpg")) + list(src_img.glob("*.png"))
        for img in imgs:
            shutil.copy2(img, dst_img / img.name)
        total_images += len(imgs)

        # Remap and copy labels
        n = remap_labels(src_lbl, dst_lbl, class_names)
        print(f"  {split}: {len(imgs)} images, {n} labeled -> {dst_split}/")

    print(f"\nIntegrated {total_images} images into training/")
    print("Run: python scripts/train.py")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", default=None,
                    help="Path to a locally downloaded dataset zip (skip download)")
    args = ap.parse_args()

    if args.local:
        dataset_dir = import_local_zip(Path(args.local))
    else:
        try:
            dataset_dir = download_via_roboflow()
        except Exception as e:
            print(f"Roboflow download failed: {e}")
            download_via_kaggle_alternative()
            return

    integrate_dataset(dataset_dir)


if __name__ == "__main__":
    main()
