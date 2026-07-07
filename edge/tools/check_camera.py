"""Quick USB webcam check.

Tries to open a webcam and grab one frame, then prints the camera index and
backend that worked. It does not save an image.

    cd edge
    python -m tools.check_camera
    python -m tools.check_camera --index 1
"""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether a USB webcam can be opened.")
    parser.add_argument("--index", type=int, help="Only try this camera index")
    parser.add_argument("--max-index", type=int, default=4, help="Highest camera index to scan")
    args = parser.parse_args(argv)

    try:
        import cv2
    except Exception as exc:  # pragma: no cover
        print(f"Could not import OpenCV (cv2): {exc}")
        print("Install USB dependencies with: install-usb.cmd")
        return 2

    indexes = [args.index] if args.index is not None else list(range(max(0, args.max_index) + 1))
    backends = [
        ("DSHOW", getattr(cv2, "CAP_DSHOW", 0)),
        ("MSMF", getattr(cv2, "CAP_MSMF", 0)),
        ("ANY", getattr(cv2, "CAP_ANY", 0)),
    ]

    for idx in indexes:
        for name, backend in backends:
            cap = cv2.VideoCapture(idx, backend)
            if not cap.isOpened():
                cap.release()
                continue
            ok, frame = cap.read()
            cap.release()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                print("=" * 56)
                print("  USB CAMERA WORKS")
                print(f"  index={idx}  backend={name}  resolution={w}x{h}")
                print("=" * 56)
                print()
                print("Run it with:")
                print(f"  .\\run-camera.cmd {idx}")
                print()
                print("Or start the whole local stack from the repo root:")
                print(f"  start-usb-camera.cmd {idx}")
                return 0

    print("=" * 56)
    print("  NO WORKING USB CAMERA FOUND")
    print("=" * 56)
    print("Checklist:")
    print("  1. Plug in the webcam or enable the built-in camera.")
    print("  2. Open the Windows Camera app and confirm it shows video.")
    print("  3. Close apps that might be using the camera, like Zoom or Teams.")
    print("  4. Settings > Privacy & security > Camera:")
    print("     turn on Camera access and Let desktop apps access your camera.")
    print("  5. Try another index: python -m tools.check_camera --index 1")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
