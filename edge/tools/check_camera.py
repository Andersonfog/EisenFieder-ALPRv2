"""Quick 'is my webcam working?' check for the trial.

Tries to open a webcam and grab one frame, then tells you what it found. It does
NOT save any image — it just confirms the camera can be opened and read.

    cd edge
    python -m tools.check_camera            # tries indexes 0 and 1
    python -m tools.check_camera --index 2   # try a specific camera
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether a webcam can be opened.")
    parser.add_argument("--index", type=int, help="Only try this camera index")
    args = parser.parse_args(argv)

    try:
        import cv2
    except Exception as exc:  # pragma: no cover
        print(f"Could not import OpenCV (cv2): {exc}")
        print("Install it with:  pip install opencv-python")
        return 2

    indexes = [args.index] if args.index is not None else [0, 1, 2]
    # On Windows, DirectShow (CAP_DSHOW) and Media Foundation (CAP_MSMF) are the
    # two backends that actually talk to webcams; CAP_ANY is the fallback.
    backends = [("DSHOW", getattr(cv2, "CAP_DSHOW", 0)),
                ("MSMF", getattr(cv2, "CAP_MSMF", 0)),
                ("ANY", getattr(cv2, "CAP_ANY", 0))]

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
                print("=" * 52)
                print(f"  WEBCAM WORKS")
                print(f"  index={idx}  backend={name}  resolution={w}x{h}")
                print("=" * 52)
                if idx != 0:
                    print(f"\nThis camera is index {idx}, not the default 0. Set it in")
                    print("config.yaml under  source:  usb_index: %d" % idx)
                print("\nYou're ready: double-click start-trial.cmd to run the trial.")
                return 0

    print("=" * 52)
    print("  NO WORKING WEBCAM FOUND")
    print("=" * 52)
    print("Checklist:")
    print("  1. Is a webcam plugged in (or the built-in one enabled)?")
    print("  2. Open the Windows 'Camera' app - does it show a picture?")
    print("     If the Camera app can't see it, this software can't either.")
    print("  3. Close apps that might be using the camera (Zoom, Teams, browser).")
    print("  4. Settings > Privacy & security > Camera:")
    print("     turn ON 'Camera access' and 'Let desktop apps access your camera'.")
    print("  5. Re-run this check:  python -m tools.check_camera")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
