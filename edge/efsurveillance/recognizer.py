"""Vehicle attribute recognizer: make, color, occupant count, and any company
branding on the side of the vehicle.

    * :class:`MockRecognizer` — invents plausible attributes, no dependencies.
    * :class:`RealRecognizer` — real measurements from the actual pixels:
        - color: sampled from the vehicle body region (HSV heuristic),
        - company: REAL text detection + OCR on the vehicle crop (EasyOCR),
        - make/model: left blank until a classifier model is wired (not guessed),
        - occupants: left blank until person-in-vehicle counting is wired.
      Anything not actually measured is returned as ``None`` — no fake data.

The ``capture_*`` toggles come from the camera's settings (set in the console):
a business may not want occupant counting, or may not care about company names.
"""

from __future__ import annotations

import difflib
import logging
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

MAKES = ["Ford", "Toyota", "Chevrolet", "Honda", "Tesla", "RAM", "Nissan", "GMC",
         "Jeep", "Subaru", "Hyundai", "Kia"]
# Plausible models per make, so make+model line up (Ford F-150, not Ford Camry).
MODELS_BY_MAKE = {
    "Ford": ["F-150", "Explorer", "Escape", "Transit", "Mustang"],
    "Toyota": ["Camry", "Corolla", "RAV4", "Tacoma", "Highlander"],
    "Chevrolet": ["Silverado", "Equinox", "Malibu", "Tahoe", "Colorado"],
    "Honda": ["Civic", "Accord", "CR-V", "Pilot", "Odyssey"],
    "Tesla": ["Model 3", "Model Y", "Model S", "Cybertruck"],
    "RAM": ["1500", "2500", "ProMaster"],
    "Nissan": ["Altima", "Rogue", "Frontier", "Titan"],
    "GMC": ["Sierra", "Yukon", "Acadia", "Savana"],
    "Jeep": ["Wrangler", "Grand Cherokee", "Gladiator"],
    "Subaru": ["Outback", "Forester", "Crosstrek"],
    "Hyundai": ["Elantra", "Tucson", "Santa Fe"],
    "Kia": ["Sorento", "Sportage", "Telluride"],
}
COLORS = ["black", "white", "silver", "gray", "red", "blue", "green", "tan"]
# Companies whose branded vehicles commonly show up at a business entrance.
COMPANIES = ["FedEx", "UPS", "Amazon", "USPS", "DHL", "Sysco", "Coca-Cola",
             "PepsiCo", "Comcast", "Waste Management"]

# Canonical spellings for big fleets, keyed by the name we want to store.
# OCR output varies ("FEDEX", "FedEx Ground", "fedex freight") — any alias below
# maps to ONE canonical spelling so the analytics "top fleets" grouping works.
KNOWN_FLEETS: dict[str, tuple[str, ...]] = {
    "FedEx": ("FEDEX", "FEDEX GROUND", "FEDEX EXPRESS", "FEDEX FREIGHT"),
    "UPS": ("UPS", "UNITED PARCEL SERVICE"),
    "USPS": ("USPS", "UNITED STATES POSTAL SERVICE", "US MAIL", "POSTAL SERVICE"),
    "Amazon": ("AMAZON", "AMAZON PRIME"),
    "DHL": ("DHL", "DHL EXPRESS"),
    "Sysco": ("SYSCO",),
    "Coca-Cola": ("COCA COLA", "COCACOLA", "COKE"),
    "PepsiCo": ("PEPSI", "PEPSICO"),
    "Comcast": ("COMCAST", "XFINITY"),
    "Waste Management": ("WASTE MANAGEMENT",),
}

# Flattened (canonical, cleaned-alias) pairs, computed once at import.
_FLEET_ALIASES: list[tuple[str, str]] = [
    (canonical, re.sub(r"[^A-Za-z0-9]", "", alias).upper())
    for canonical, aliases in KNOWN_FLEETS.items()
    for alias in aliases
]


@dataclass
class VehicleAttributes:
    make: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    occupant_count: Optional[int] = None
    is_commercial: bool = False
    company_name: Optional[str] = None


@dataclass
class MakeModelResult:
    make: Optional[str]
    model: Optional[str]
    confidence: float


def parse_make_model(label: str) -> tuple[Optional[str], Optional[str]]:
    """Split a classifier label into (make, model).

    Accepts either ``"Make|Model"`` (explicit) or ``"Make Model words"`` (the
    first token is the make, the rest is the model). Empty parts become None.
    """
    label = (label or "").strip()
    if not label:
        return None, None
    if "|" in label:
        make, _, model = label.partition("|")
    else:
        make, _, model = label.partition(" ")
    make = make.strip() or None
    model = model.strip() or None
    return make, model


class BaseRecognizer(ABC):
    name = "base"

    @abstractmethod
    def recognize(self, frame, bbox, *, occupants: bool, company: bool,
                  plate_text: Optional[str] = None) -> VehicleAttributes:
        ...


class MockRecognizer(BaseRecognizer):
    name = "mock"

    def recognize(self, frame, bbox, *, occupants: bool, company: bool,
                  plate_text: Optional[str] = None) -> VehicleAttributes:
        commercial = company and random.random() < 0.25
        make = random.choice(MAKES)
        return VehicleAttributes(
            make=make,
            model=random.choice(MODELS_BY_MAKE.get(make, ["—"])),
            color=random.choice(COLORS),
            occupant_count=random.randint(1, 4) if occupants else None,
            is_commercial=commercial,
            company_name=random.choice(COMPANIES) if commercial else None,
        )


# --------------------------------------------------------------------------- #
# Real company-name reader (EasyOCR)
# --------------------------------------------------------------------------- #
@dataclass
class _OcrToken:
    """One accepted OCR detection, in crop coordinates."""

    text: str
    score: float    # area × confidence — bigger, surer text ranks higher
    cx: float
    cy: float
    height: float
    x1: float
    x2: float


class CompanyReader:
    """Reads company branding off a vehicle crop with real OCR.

    Uses EasyOCR (optional dependency). If it isn't installed, the reader stays
    disabled and every call returns ``None`` — the pipeline still runs, company
    names are just left blank rather than faked.

    Pipeline: upscale small crops so the text has enough pixels → OCR → drop
    plates / phone numbers / fleet boilerplate ("HOW'S MY DRIVING", DOT numbers)
    → assemble the strongest text line, merging a stacked second line ("WASTE"
    over "MANAGEMENT") → canonicalize known fleets so "FEDEX GROUND" and
    "fedex" both store as "FedEx". If the first OCR pass saw text but none of
    it read cleanly (shade, low-contrast paint), one contrast-enhanced retry
    (CLAHE) is made before giving up.
    """

    # Only trust text the OCR is reasonably sure about.
    MIN_CONF = 0.45
    # Below this the first pass "saw something"; worth a contrast-enhanced retry.
    RETRY_CONF = 0.20
    # Branding needs pixels; skip crops too small to read reliably.
    MIN_CROP_W = 80
    MIN_CROP_H = 45
    # EasyOCR reads best when letters are ~30+ px tall. Small (distant) crops
    # are upscaled toward this width first, capped so the Pi isn't overworked.
    TARGET_W = 640
    MAX_UPSCALE = 3.0
    _NON_ALNUM = re.compile(r"[^A-Za-z0-9]")
    # "www."/"http://" cruft on a painted URL — the domain is the useful part.
    _URL_PREFIX = re.compile(r"^(?:https?://)?www\.", re.IGNORECASE)
    # Fleet boilerplate painted on trucks that is NOT the company name.
    _JUNK = re.compile(
        r"HOW.?S\s+MY\s+DRIVING"            # fleet-safety sticker
        r"|\bUS\s?DOT\b|\bMC\s?\d|\bGVWR?\b"  # regulatory numbers
        r"|\bTOLL\s?FREE\b|\bCALL\b|\bFOLLOW\s+US\b"
        r"|\bFREE\s+ESTIMATES?\b|\bLICENSED\b|\bINSURED\b|\bBONDED\b"
        r"|\bSINCE\s+\d{4}\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self._reader = None
        self._enabled = True   # flips to False if EasyOCR can't be loaded

    def _ensure_reader(self):
        if self._reader is not None or not self._enabled:
            return self._reader
        try:
            import easyocr  # heavy; imported lazily on first use

            self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            logger.info("CompanyReader: EasyOCR ready — reading real side branding.")
        except Exception as exc:
            self._enabled = False
            logger.warning(
                "CompanyReader: EasyOCR unavailable (%s); company names left blank "
                "(install easyocr to enable).", exc,
            )
        return self._reader

    # -- image preparation --------------------------------------------------- #
    def _prepare(self, crop):
        """Upscale small crops so EasyOCR has enough pixels to find the text."""
        try:
            scale = min(self.MAX_UPSCALE, self.TARGET_W / float(crop.shape[1]))
            if scale < 1.25:
                return crop            # already big enough; skip the resize
            import cv2

            return cv2.resize(crop, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_CUBIC)
        except Exception:
            return crop

    @staticmethod
    def _enhance(crop):
        """Boost local contrast (CLAHE) for branding in shade or low light."""
        try:
            import cv2

            lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            l = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(l)
            return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
        except Exception:
            return None

    # -- text filtering -------------------------------------------------------#
    def _looks_like_company(self, text: str, plate_norm: Optional[str]) -> bool:
        cleaned = self._NON_ALNUM.sub("", text)
        if len(cleaned) < 3:
            return False
        letters = sum(c.isalpha() for c in cleaned)
        if letters < 3 or letters / len(cleaned) < 0.5:
            return False              # mostly digits/symbols → phone#, plate, etc.
        if plate_norm and cleaned.upper() == plate_norm:
            return False              # that's the license plate, not a company
        if self._JUNK.search(text):
            return False              # painted on the truck, but not the name
        return True

    def _filter(self, results, plate_norm: Optional[str]) -> list[_OcrToken]:
        """OCR detections → tokens that plausibly belong to the company name."""
        kept: list[_OcrToken] = []
        for box, text, conf in results:
            if conf < self.MIN_CONF:
                continue
            text = " ".join(str(text).split())
            text = self._URL_PREFIX.sub("", text).strip(" .,:;|/\\-")
            if not self._looks_like_company(text, plate_norm):
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            w, h = max(xs) - min(xs), max(ys) - min(ys)
            kept.append(_OcrToken(
                text=text, score=w * h * conf, cx=sum(xs) / 4.0, cy=sum(ys) / 4.0,
                height=float(h), x1=float(min(xs)), x2=float(max(xs)),
            ))
        return kept

    # -- assembly -------------------------------------------------------------#
    @staticmethod
    def _assemble(kept: list[_OcrToken]) -> str:
        """Join the strongest text line; merge one stacked companion line."""
        # 1. Cluster tokens into horizontal lines of text.
        lines: list[list[_OcrToken]] = []
        for tok in sorted(kept, key=lambda t: t.cy):
            for line in lines:
                line_cy = sum(t.cy for t in line) / len(line)
                line_h = max(t.height for t in line)
                if abs(tok.cy - line_cy) <= 0.6 * max(line_h, tok.height):
                    line.append(tok)
                    break
            else:
                lines.append([tok])

        def score(line: list[_OcrToken]) -> float:
            return sum(t.score for t in line)

        # 2. The strongest line is the branding anchor.
        anchor = max(lines, key=score)
        a_cy = sum(t.cy for t in anchor) / len(anchor)
        a_h = max(t.height for t in anchor)
        a_x1 = min(t.x1 for t in anchor)
        a_x2 = max(t.x2 for t in anchor)

        # 3. Stacked logos ("WASTE" over "MANAGEMENT"): merge in ONE neighbour
        #    line that is close vertically, overlaps horizontally, and has text
        #    of comparable size (much smaller text = slogan/phone strip).
        best = None
        for line in lines:
            if line is anchor:
                continue
            cy = sum(t.cy for t in line) / len(line)
            if abs(cy - a_cy) > 2.0 * a_h or max(t.height for t in line) < 0.4 * a_h:
                continue
            x1, x2 = min(t.x1 for t in line), max(t.x2 for t in line)
            overlap = min(a_x2, x2) - max(a_x1, x1)
            if overlap / max(1.0, min(a_x2 - a_x1, x2 - x1)) < 0.35:
                continue
            if best is None or score(line) > score(best):
                best = line

        picked = [anchor] + ([best] if best else [])
        picked.sort(key=lambda ln: sum(t.cy for t in ln) / len(ln))  # top → bottom
        words: list[str] = []
        for line in picked:
            words.extend(t.text for t in sorted(line, key=lambda t: t.cx))
        return " ".join(words).strip()

    def _canonicalize(self, name: str) -> Optional[str]:
        """Map OCR spelling variants of known fleets to one canonical name."""
        flat = self._NON_ALNUM.sub("", name).upper()
        if not flat:
            return None
        for canonical, alias in _FLEET_ALIASES:
            if flat == alias:
                return canonical
            if len(alias) >= 5:            # short brands (UPS, DHL) match exactly only
                if alias in flat:
                    return canonical       # "FEDEXGROUND" contains "FEDEX"
                # Fuzzy: a one-letter OCR slip ("FEOEX"). Requiring the same
                # first letter guards against sound-alike different brands.
                if flat[0] == alias[0] and \
                        difflib.SequenceMatcher(None, alias, flat).ratio() >= 0.8:
                    return canonical
        return name

    def read(self, frame, bbox, plate_text: Optional[str] = None) -> Optional[str]:
        reader = self._ensure_reader()
        if reader is None:
            return None
        if getattr(frame, "shape", None) is None:
            return None
        try:
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = (int(v) for v in bbox)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            # Trim the bottom (wheels/road) where branding rarely lives.
            y2 = y1 + int((y2 - y1) * 0.82)
            if (x2 - x1) < self.MIN_CROP_W or (y2 - y1) < self.MIN_CROP_H:
                return None
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                return None

            plate_norm = self._NON_ALNUM.sub("", plate_text).upper() if plate_text else None
            proc = self._prepare(crop)
            results = reader.readtext(proc)  # list[(box, text, conf)]
            kept = self._filter(results, plate_norm)

            # Nothing readable, but the OCR *saw* text (low confidence)? The
            # paint may just be low-contrast — retry once, contrast-enhanced.
            # A plain unmarked car yields no detections at all and skips this.
            if not kept and any(conf >= self.RETRY_CONF for _, _, conf in results):
                enhanced = self._enhance(proc)
                if enhanced is not None:
                    kept = self._filter(reader.readtext(enhanced), plate_norm)
            if not kept:
                return None

            name = self._assemble(kept)
            if not name:
                return None
            name = self._canonicalize(name[:128])
            return name or None
        except Exception as exc:
            logger.debug("CompanyReader: OCR failed on crop: %s", exc)
            return None


# --------------------------------------------------------------------------- #
# Make/model classifier (optional, ONNX)
# --------------------------------------------------------------------------- #
class MakeModelClassifier:
    """Classifies a vehicle crop into make/model with a real ONNX model.

    Deliberately conservative and honest:

    * It stays **disabled** unless a backend, model file and labels file are all
      configured and load cleanly. When disabled, every call returns ``None`` —
      make/model are left blank, never guessed.
    * Even when enabled, a prediction below ``min_confidence`` returns ``None``.
      A classifier trained on clean catalog photos is unreliable on angled
      entrance-cam crops, so the confidence gate (tuned with
      ``tools/measure_make_model.py``) is what earns the right to fill the field.

    Preprocessing is the standard ImageNet pipeline (resize to a square, BGR→RGB,
    scale to 0..1, normalise by ImageNet mean/std, NCHW float32). Swap it if your
    model was trained differently.
    """

    _IMAGENET_MEAN = (0.485, 0.456, 0.406)
    _IMAGENET_STD = (0.229, 0.224, 0.225)

    def __init__(self, *, backend: str = "off", model_path: str = "",
                 labels_path: str = "", min_confidence: float = 0.60,
                 input_size: int = 224) -> None:
        self.backend = (backend or "off").lower()
        self.model_path = model_path
        self.labels_path = labels_path
        self.min_confidence = float(min_confidence)
        self.input_size = int(input_size)
        self._labels: list[str] = []
        self._session = None        # onnxruntime InferenceSession
        self._input_name = None
        self._ready = False
        if self.backend != "off":
            self._load()

    # -- loading ----------------------------------------------------------- #
    def _load(self) -> None:
        try:
            self._labels = self._read_labels(self.labels_path)
            if not self._labels:
                raise ValueError(f"no labels found in {self.labels_path!r}")
            if self.backend == "onnx":
                import onnxruntime as ort  # heavy; imported only when enabled

                self._session = ort.InferenceSession(
                    self.model_path, providers=["CPUExecutionProvider"])
                self._input_name = self._session.get_inputs()[0].name
            else:
                raise ValueError(f"unknown makemodel backend {self.backend!r}")
            self._ready = True
            logger.info(
                "MakeModelClassifier: %s model ready (%d classes, gate>=%.2f).",
                self.backend, len(self._labels), self.min_confidence,
            )
        except Exception as exc:
            self._ready = False
            logger.warning(
                "MakeModelClassifier: disabled (%s); make/model left blank. "
                "See edge/MAKEMODEL.md to enable.", exc,
            )

    @staticmethod
    def _read_labels(path: str) -> list[str]:
        if not path:
            return []
        with open(path, "r", encoding="utf-8") as fh:
            return [ln.strip() for ln in fh if ln.strip()]

    @property
    def enabled(self) -> bool:
        return self._ready

    # -- inference --------------------------------------------------------- #
    def _infer(self, crop_bgr) -> Optional[tuple[int, float]]:
        """Run the model on a BGR crop → (class_index, confidence). None on error.

        Overridable / monkeypatchable in tests so the gate + label logic can be
        exercised without a real model.
        """
        if not self._ready or self._session is None:
            return None
        try:
            import numpy as np

            x = self._preprocess(crop_bgr, np)
            outputs = self._session.run(None, {self._input_name: x})
            logits = np.asarray(outputs[0]).reshape(-1).astype("float64")
            probs = self._softmax(logits, np)
            idx = int(probs.argmax())
            return idx, float(probs[idx])
        except Exception as exc:
            logger.debug("MakeModelClassifier: inference failed: %s", exc)
            return None

    def _preprocess(self, crop_bgr, np):
        import cv2

        img = cv2.resize(crop_bgr, (self.input_size, self.input_size))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype("float32") / 255.0
        mean = np.array(self._IMAGENET_MEAN, dtype="float32")
        std = np.array(self._IMAGENET_STD, dtype="float32")
        img = (img - mean) / std
        img = np.transpose(img, (2, 0, 1))[None, ...]  # NCHW
        return img.astype("float32")

    @staticmethod
    def _softmax(logits, np):
        e = np.exp(logits - logits.max())
        return e / e.sum()

    def classify(self, frame, bbox) -> Optional[MakeModelResult]:
        """Return a make/model result, or None if disabled/low-confidence."""
        if not self._ready:
            return None
        crop = self._crop(frame, bbox)
        if crop is None:
            return None
        out = self._infer(crop)
        if out is None:
            return None
        idx, conf = out
        if conf < self.min_confidence:
            return None                      # not sure enough → leave blank
        if not (0 <= idx < len(self._labels)):
            return None
        make, model = parse_make_model(self._labels[idx])
        return MakeModelResult(make=make, model=model, confidence=conf)

    @staticmethod
    def _crop(frame, bbox):
        if getattr(frame, "shape", None) is None:
            return None
        try:
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = (int(v) for v in bbox)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 - x1 < 8 or y2 - y1 < 8:
                return None
            crop = frame[y1:y2, x1:x2]
            return crop if getattr(crop, "size", 0) else None
        except Exception:
            return None


class RealRecognizer(BaseRecognizer):  # pragma: no cover - needs real frames
    """Real measurements only.

    Color is measured from the vehicle's body pixels; company branding is read
    with real OCR off the vehicle crop. Make/model come from a classifier ONLY
    when one is configured and confident enough (see MakeModelClassifier); left
    blank otherwise. Occupant count is filled by the detector's person counting,
    not here. Anything not actually measured stays ``None`` — no fake data.
    """

    name = "real"

    def __init__(self, makemodel: Optional["MakeModelClassifier"] = None) -> None:
        self._company = CompanyReader()
        self._makemodel = makemodel or MakeModelClassifier(backend="off")
        mm = "enabled" if self._makemodel.enabled else "blank (no model)"
        logger.info(
            "Recognizer: REAL backend — colour measured from pixels, company "
            "branding read with OCR. Make/model: %s. Occupant count not guessed "
            "here.", mm,
        )

    def recognize(self, frame, bbox, *, occupants: bool, company: bool,
                  plate_text: Optional[str] = None) -> VehicleAttributes:
        attrs = VehicleAttributes(color=self._estimate_color(frame, bbox))
        if company:
            name = self._company.read(frame, bbox, plate_text)
            if name:
                attrs.company_name = name
                attrs.is_commercial = True  # branding was actually read off it
        if self._makemodel.enabled:
            mm = self._makemodel.classify(frame, bbox)
            if mm is not None:
                attrs.make = mm.make
                attrs.model = mm.model
        return attrs

    @staticmethod
    def _estimate_color(frame, bbox) -> Optional[str]:
        if getattr(frame, "shape", None) is None:
            return None
        try:
            import cv2
            import numpy as np

            h, w = frame.shape[:2]
            x1, y1, x2, y2 = bbox
            bw, bh = x2 - x1, y2 - y1
            # Sample an upper-central body panel (avoid windshield, wheels, road).
            sx1, sx2 = max(0, x1 + int(bw * 0.28)), min(w, x1 + int(bw * 0.72))
            sy1, sy2 = max(0, y1 + int(bh * 0.30)), min(h, y1 + int(bh * 0.55))
            crop = frame[sy1:sy2, sx1:sx2]
            if crop.size == 0:
                return None
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            hue = float(np.median(hsv[..., 0]))
            sat = float(np.median(hsv[..., 1]))
            val = float(np.median(hsv[..., 2]))
            # Low-saturation = greyscale family (black/gray/silver/white).
            if val < 55:
                return "black"
            if sat < 45:
                if val > 175:
                    return "white"
                if val > 110:
                    return "silver"
                return "gray"
            # Coloured: map OpenCV hue (0-179).
            if hue < 10 or hue >= 170:
                return "red"
            if hue < 35:
                return "tan"
            if hue < 85:
                return "green"
            if hue < 135:
                return "blue"
            return "red"
        except Exception:
            return None


def create_recognizer(backend: str = "auto", detector_cfg=None) -> BaseRecognizer:
    backend = (backend or "auto").lower()
    if backend == "mock":
        return MockRecognizer()
    # Real for everything else (yolo / real / auto). Build the optional make/model
    # classifier from the detector config when one is supplied.
    makemodel = None
    if detector_cfg is not None:
        makemodel = MakeModelClassifier(
            backend=getattr(detector_cfg, "makemodel_backend", "off"),
            model_path=getattr(detector_cfg, "makemodel_model_path", ""),
            labels_path=getattr(detector_cfg, "makemodel_labels_path", ""),
            min_confidence=getattr(detector_cfg, "makemodel_min_confidence", 0.60),
            input_size=getattr(detector_cfg, "makemodel_input_size", 224),
        )
    return RealRecognizer(makemodel=makemodel)
