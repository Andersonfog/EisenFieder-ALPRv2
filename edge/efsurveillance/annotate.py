"""Draw YOLO-style annotated stills for the saved/log view.

Produces a JPEG with a bright detection box around the vehicle (labelled with
make/model/color) and a box around the license plate (labelled with the plate
text) — the same look as a YOLO demo frame.

Works in two situations:
  * Real frame (numpy BGR array, on the Pi): boxes are drawn over the photo.
  * Synthetic/mock (laptop demo): a stand-in scene is drawn so the boxes and
    labels are still visible to click through in the console.

Pillow does the drawing. If Pillow isn't installed it degrades to a tiny
placeholder so the pipeline never breaks.
"""

from __future__ import annotations

import io
import logging
from typing import Optional, Sequence

from .camera import SyntheticFrame, frame_size

logger = logging.getLogger(__name__)

# Box / accent colour (YOLO-ish cyan-green).
_BOX = (34, 211, 153)
_PLATE_BOX = (250, 204, 21)

# Vehicle paint colours for the synthetic stand-in scene.
_COLOR_RGB = {
    "white": (235, 235, 235), "black": (40, 40, 44), "silver": (192, 198, 204),
    "gray": (120, 126, 134), "grey": (120, 126, 134), "red": (200, 60, 55),
    "blue": (60, 110, 200), "green": (70, 150, 95), "tan": (200, 180, 140),
}


def _have_pil() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


def _font(size: int):
    from PIL import ImageFont

    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_w_h(draw, text: str, font) -> tuple[int, int]:
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return r - l, b - t
    except Exception:
        return (len(text) * 7, 12)


def _label(draw, xy, text, font, *, fg=(10, 14, 20), bg=_BOX) -> None:
    """Draw a filled label chip with text at the top-left of xy=(x,y)."""
    x, y = xy
    tw, th = _text_w_h(draw, text, font)
    pad = 5
    draw.rectangle([x, y, x + tw + pad * 2, y + th + pad * 2], fill=bg)
    draw.text((x + pad, y + pad), text, fill=fg, font=font)


def _base_image(frame, width: int, height: int, vehicle_color: Optional[str], bbox):
    """Return a PIL RGB image to draw on (the photo, or a synthetic scene)."""
    from PIL import Image, ImageDraw

    # Real camera frame (numpy BGR) -> RGB PIL image.
    if not isinstance(frame, SyntheticFrame) and getattr(frame, "shape", None) is not None:
        try:
            return Image.fromarray(frame[:, :, ::-1].copy())
        except Exception:
            pass

    # Synthetic stand-in scene: dark ground + a car-ish block in its colour.
    img = Image.new("RGB", (width, height), (24, 30, 40))
    draw = ImageDraw.Draw(img)
    for i in range(height):  # subtle vertical gradient = "ground"
        shade = 24 + int(18 * (i / max(height, 1)))
        draw.line([(0, i), (width, i)], fill=(shade, shade + 4, shade + 10))
    x1, y1, x2, y2 = bbox
    car = _COLOR_RGB.get((vehicle_color or "").lower(), (150, 156, 164))
    inset = int((x2 - x1) * 0.06)
    draw.rounded_rectangle([x1 + inset, y1 + inset, x2 - inset, y2 - inset],
                           radius=18, fill=car, outline=(15, 18, 24), width=2)
    # windshield + two wheels for a touch of realism
    draw.rounded_rectangle([x1 + inset * 3, y1 + inset * 2,
                            x2 - inset * 3, y1 + int((y2 - y1) * 0.42)],
                           radius=10, fill=(70, 90, 110))
    wheel_y = y2 - inset
    r = max(8, int((x2 - x1) * 0.07))
    for wx in (x1 + int((x2 - x1) * 0.26), x1 + int((x2 - x1) * 0.74)):
        draw.ellipse([wx - r, wheel_y - r, wx + r, wheel_y + r], fill=(20, 22, 26))
    return img


def render_event_image(
    frame, *, vehicle_bbox, plate_bbox=None, vehicle_label: str = "",
    plate_label: Optional[str] = None, vehicle_color: Optional[str] = None,
) -> bytes:
    """Render the annotated scene and return JPEG bytes."""
    width, height = frame_size(frame)
    if not _have_pil():
        from .main import _PLACEHOLDER_JPEG  # late import to avoid cycle at import time
        return _PLACEHOLDER_JPEG

    from PIL import ImageDraw

    img = _base_image(frame, width, height, vehicle_color, vehicle_bbox)
    draw = ImageDraw.Draw(img)
    font = _font(max(16, height // 30))
    small = _font(max(13, height // 42))

    # Vehicle detection box + label above it.
    x1, y1, x2, y2 = vehicle_bbox
    draw.rectangle([x1, y1, x2, y2], outline=_BOX, width=3)
    if vehicle_label:
        ly = max(0, y1 - (height // 24) - 10)
        _label(draw, (x1, ly), vehicle_label, font, bg=_BOX)

    # Plate box + label.
    if plate_bbox is not None:
        px1, py1, px2, py2 = plate_bbox
        draw.rectangle([px1, py1, px2, py2], outline=_PLATE_BOX, width=3)
        if plate_label:
            _label(draw, (px1, min(height - 24, py2 + 4)), f"PLATE {plate_label}",
                   small, fg=(20, 16, 0), bg=_PLATE_BOX)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def render_plate_crop(frame, plate_bbox, plate_text: str, region: Optional[str] = None) -> bytes:
    """Close-up of the plate for the detail view.

    With a real camera frame + plate box, returns the ACTUAL plate pixels with
    the OCR text captioned beneath. In mock mode (no real pixels) it draws a
    clean stand-in plate showing the text.
    """
    if not _have_pil() or not plate_text:
        from .main import _PLACEHOLDER_JPEG
        return _PLACEHOLDER_JPEG
    from PIL import Image, ImageDraw

    # Real plate pixels, when we have a real frame and a plate box.
    if (not isinstance(frame, SyntheticFrame) and getattr(frame, "shape", None) is not None
            and plate_bbox is not None):
        try:
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = (int(v) for v in plate_bbox)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 > x1 and y2 > y1:
                crop = frame[y1:y2, x1:x2][:, :, ::-1].copy()  # BGR -> RGB
                im = Image.fromarray(crop)
                if im.width < 420:  # upscale small plates for readability
                    scale = 420 / max(im.width, 1)
                    im = im.resize((420, max(1, int(im.height * scale))))
                cap_h = 48
                canvas = Image.new("RGB", (im.width, im.height + cap_h), (20, 20, 24))
                canvas.paste(im, (0, 0))
                d = ImageDraw.Draw(canvas)
                caption = plate_text + (f"   {region}" if region else "")
                d.text((12, im.height + 9), caption, fill=_PLATE_BOX, font=_font(30))
                buf = io.BytesIO()
                canvas.save(buf, format="JPEG", quality=88)
                return buf.getvalue()
        except Exception:
            pass

    W, H = 420, 200
    img = Image.new("RGB", (W, H), (245, 245, 245))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([10, 10, W - 10, H - 10], radius=16,
                           fill=(252, 252, 250), outline=(30, 30, 30), width=4)
    if region:
        _label(draw, (24, 22), region, _font(22), fg=(255, 255, 255), bg=(30, 60, 130))
    big = _font(88)
    tw, th = _text_w_h(draw, plate_text, big)
    draw.text(((W - tw) / 2, (H - th) / 2 + 6), plate_text, fill=(20, 20, 24), font=big)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def render_live_frame(width: int, height: int, *, camera_id: str = "", tick: int = 0) -> bytes:
    """A stand-in 'live' preview for mock mode.

    Draws an entrance-driveway scene with a moving scan line, a LIVE chip and a
    ticking clock, so the console's repeated fetches show a visibly changing
    image (it looks alive). On the Pi the real camera frame is sent instead.
    """
    if not _have_pil():
        from .main import _PLACEHOLDER_JPEG
        return _PLACEHOLDER_JPEG
    import time as _time

    from PIL import Image, ImageDraw

    width = max(160, int(width))
    height = max(120, int(height))
    img = Image.new("RGB", (width, height), (18, 23, 32))
    draw = ImageDraw.Draw(img)
    for i in range(height):  # sky/ground gradient
        shade = 16 + int(22 * (i / max(height, 1)))
        draw.line([(0, i), (width, i)], fill=(shade, shade + 4, shade + 9))
    horizon = int(height * 0.55)
    draw.line([(0, horizon), (width, horizon)], fill=(70, 80, 95), width=2)
    # a driveway narrowing toward the horizon (perspective)
    draw.polygon(
        [(width * 0.44, horizon), (width * 0.56, horizon),
         (width * 0.84, height), (width * 0.16, height)],
        fill=(38, 44, 54),
    )
    # moving scan line — its position depends on tick, so the frame changes
    sx = int((tick * 24) % (width + 80)) - 40
    draw.line([(sx, 0), (sx, height)], fill=_BOX, width=3)
    draw.ellipse([sx - 6, horizon - 6, sx + 6, horizon + 6], fill=_BOX)

    font = _font(max(15, height // 22))
    _label(draw, (12, 12), f"● LIVE  {camera_id}", font, fg=(255, 255, 255), bg=(200, 40, 45))
    stamp = _time.strftime("%H:%M:%S")
    tw, _h = _text_w_h(draw, stamp, font)
    _label(draw, (width - tw - 34, 12), stamp, font, fg=(10, 14, 20), bg=_BOX)
    small = _font(max(11, height // 36))
    draw.text((14, height - 22), "Mock preview — real camera shows live video on the Pi",
              fill=(150, 160, 175), font=small)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=72)
    return buf.getvalue()


def synth_plate_bbox(vehicle_bbox) -> Sequence[int]:
    """A plausible plate rectangle in the lower-centre of the vehicle box
    (used for the annotation when a real ALPR plate box isn't available)."""
    x1, y1, x2, y2 = vehicle_bbox
    w, h = x2 - x1, y2 - y1
    pw, ph = int(w * 0.30), int(h * 0.14)
    cx = x1 + w // 2
    py2 = y2 - int(h * 0.12)
    return [cx - pw // 2, py2 - ph, cx + pw // 2, py2]
