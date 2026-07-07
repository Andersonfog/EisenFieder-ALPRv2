"""
Collect training data for fine-tuning the EisenFieder YOLO model.

Two modes:
  --source video    : capture frames from a video file or USB camera
  --source folder   : use an existing folder of clean JPEG images

YOLO auto-labels each frame with bounding boxes. You assign the vehicle type
(car/suv/truck/van/pickup/motorcycle/bus) at capture time or during review.

Output goes to edge/training/ in YOLO format (images/ + labels/ split 80/20).

Usage examples:
  # Capture 200 frames from USB camera index 0:
  python scripts/collect_dataset.py --source usb --device 0 --frames 200

  # Label a folder of existing clean images:
  python scripts/collect_dataset.py --source folder --input data/raw_frames/

  # Use a video file:
  python scripts/collect_dataset.py --source video --input data/footage.mp4

After collecting, run:
  python scripts/train.py
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path

EDGE_DIR = Path(__file__).resolve().parent.parent
TRAINING_DIR = EDGE_DIR / "training"
IMG_TRAIN = TRAINING_DIR / "images" / "train"
IMG_VAL   = TRAINING_DIR / "images" / "val"
LBL_TRAIN = TRAINING_DIR / "labels" / "train"
LBL_VAL   = TRAINING_DIR / "labels" / "val"

for d in [IMG_TRAIN, IMG_VAL, LBL_TRAIN, LBL_VAL]:
    d.mkdir(parents=True, exist_ok=True)

# COCO class id -> our fine-grained class index
# (yolov8n is trained on COCO; we map its coarse vehicle classes to ours)
COCO_TO_EFS = {
    2: 0,   # car -> car
    3: 5,   # motorcycle -> motorcycle
    5: 6,   # bus -> bus
    7: 2,   # truck -> truck
    # suv/van/pickup have no COCO equivalent — you manually label those
}

EFS_CLASSES = ["car", "suv", "truck", "van", "pickup", "motorcycle", "bus"]


def _yolo_label_line(cls_idx: int, box_xyxy, img_w: int, img_h: int) -> str:
    x1, y1, x2, y2 = box_xyxy
    cx = ((x1 + x2) / 2) / img_w
    cy = ((y1 + y2) / 2) / img_h
    bw = (x2 - x1) / img_w
    bh = (y2 - y1) / img_h
    return f"{cls_idx} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"


def _prompt_type(default_idx: int) -> int:
    print("\nVehicle types:")
    for i, name in enumerate(EFS_CLASSES):
        marker = " <--" if i == default_idx else ""
        print(f"  {i}: {name}{marker}")
    choice = input(f"Type index [{default_idx}]: ").strip()
    if choice == "":
        return default_idx
    try:
        idx = int(choice)
        if 0 <= idx < len(EFS_CLASSES):
            return idx
    except ValueError:
        pass
    return default_idx


def label_image(img_path: Path, model, split: str, interactive: bool) -> bool:
    import cv2
    img = cv2.imread(str(img_path))
    if img is None:
        print(f"  skip (unreadable): {img_path.name}")
        return False
    h, w = img.shape[:2]

    results = model.predict(img, classes=list(COCO_TO_EFS.keys()),
                            conf=0.3, verbose=False)
    lines = []
    for result in results:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue
        for box in boxes:
            coco_cls = int(box.cls[0])
            efs_idx = COCO_TO_EFS.get(coco_cls, 0)
            xyxy = [int(v) for v in box.xyxy[0].tolist()]

            if interactive:
                # Show the crop so the user can confirm the vehicle type
                x1, y1, x2, y2 = xyxy
                crop = img[max(0,y1):y2, max(0,x1):x2]
                if crop.size > 0:
                    cv2.imshow("Vehicle (press any key)", crop)
                    cv2.waitKey(800)
                efs_idx = _prompt_type(efs_idx)

            lines.append(_yolo_label_line(efs_idx, xyxy, w, h))

    if not lines:
        return False  # no vehicles detected, skip this frame

    img_dir = IMG_TRAIN if split == "train" else IMG_VAL
    lbl_dir = LBL_TRAIN if split == "train" else LBL_VAL
    stem = img_path.stem
    shutil.copy2(img_path, img_dir / f"{stem}.jpg")
    (lbl_dir / f"{stem}.txt").write_text("\n".join(lines))
    return True


def collect_from_folder(folder: Path, model, interactive: bool, val_frac: float):
    images = sorted(folder.glob("*.jpg")) + sorted(folder.glob("*.png"))
    random.shuffle(images)
    print(f"Found {len(images)} images in {folder}")
    saved = 0
    for i, img_path in enumerate(images):
        split = "val" if i < int(len(images) * val_frac) else "train"
        if label_image(img_path, model, split, interactive):
            saved += 1
            print(f"  [{saved}] {img_path.name} -> {split}")
    print(f"\nSaved {saved} labeled images to training/")


def collect_from_video(source, model, n_frames: int, interactive: bool,
                       val_frac: float, skip: int = 15):
    import cv2
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        sys.exit(f"Cannot open video source: {source}")
    print(f"Capturing up to {n_frames} frames from {source} (skip={skip})")
    saved, frame_no = 0, 0
    tmp = TRAINING_DIR / "_tmp_frames"
    tmp.mkdir(exist_ok=True)
    try:
        while saved < n_frames:
            ok, frame = cap.read()
            if not ok:
                break
            frame_no += 1
            if frame_no % skip != 0:
                continue
            stem = f"frame_{frame_no:06d}"
            img_path = tmp / f"{stem}.jpg"
            cv2.imwrite(str(img_path), frame)
            split = "val" if random.random() < val_frac else "train"
            if label_image(img_path, model, split, interactive):
                saved += 1
                print(f"  [{saved}/{n_frames}] frame {frame_no} -> {split}")
            img_path.unlink(missing_ok=True)
    finally:
        cap.release()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nSaved {saved} labeled frames to training/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["folder", "video", "usb"], default="folder")
    ap.add_argument("--input", default="data/raw_frames",
                    help="Folder path or video file path")
    ap.add_argument("--device", type=int, default=0, help="USB camera index")
    ap.add_argument("--frames", type=int, default=300,
                    help="Max frames to capture (video/usb mode)")
    ap.add_argument("--skip", type=int, default=15,
                    help="Capture 1 frame every N (video/usb mode)")
    ap.add_argument("--val-frac", type=float, default=0.2,
                    help="Fraction of images for validation set")
    ap.add_argument("--interactive", action="store_true",
                    help="Prompt for vehicle type for each detection (slow but accurate)")
    ap.add_argument("--model", default=str(EDGE_DIR / "yolov8n.pt"),
                    help="Base YOLO model weights")
    args = ap.parse_args()

    from ultralytics import YOLO
    print(f"Loading model: {args.model}")
    model = YOLO(args.model)

    if args.source == "folder":
        collect_from_folder(Path(args.input), model, args.interactive, args.val_frac)
    elif args.source in ("video", "usb"):
        src = args.device if args.source == "usb" else args.input
        collect_from_video(src, model, args.frames, args.interactive,
                           args.val_frac, args.skip)

    # Print dataset summary
    n_train = len(list(IMG_TRAIN.glob("*.jpg")))
    n_val   = len(list(IMG_VAL.glob("*.jpg")))
    print(f"\nDataset ready: {n_train} train / {n_val} val")
    print("Run: python scripts/train.py")


if __name__ == "__main__":
    main()
