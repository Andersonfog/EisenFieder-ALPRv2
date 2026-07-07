"""Edge unit tests (no network, no ML deps).

    cd edge
    python tests/test_edge.py     # self-runner

Exercises the mock pipeline end-to-end: synthetic frames -> mock detection ->
mock plate + attributes -> SQLite buffer, plus the uploader's metadata mapping.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

EDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EDGE_DIR))

from efsurveillance.camera import SyntheticFrame, SyntheticSource, frame_size  # noqa: E402
from efsurveillance.config import Config  # noqa: E402
from efsurveillance.detector import MockVehicleDetector, create_detector  # noqa: E402
from efsurveillance.event_logger import EventLogger  # noqa: E402
from efsurveillance.main import SurveillanceApp  # noqa: E402
from efsurveillance.plate_reader import create_plate_reader  # noqa: E402
from efsurveillance.recognizer import create_recognizer  # noqa: E402
from efsurveillance.uploader import Uploader  # noqa: E402


def test_synthetic_source_and_size():
    src = SyntheticSource(640, 480)
    frame = src.read()
    assert isinstance(frame, SyntheticFrame)
    assert frame_size(frame) == (640, 480)


def test_mock_detector_emits_after_interval():
    det = MockVehicleDetector(interval_seconds=0.0)
    frame = SyntheticFrame(1280, 720)
    dets = det.detect(frame)
    assert len(dets) == 1
    d = dets[0]
    assert d.vehicle_type and 0.0 <= d.confidence <= 1.0
    assert len(d.bbox) == 4


def test_mock_plate_and_attributes():
    reader = create_plate_reader("mock")
    # Read enough times to get at least one successful (non-None) plate.
    plates = [reader.read(None, (0, 0, 10, 10)).text for _ in range(50)]
    assert any(p for p in plates)

    rec = create_recognizer("mock")
    attrs = rec.recognize(None, (0, 0, 10, 10), occupants=True, company=True)
    assert attrs.make and attrs.color and attrs.occupant_count is not None


class _FakeOCR:
    """Stand-in for easyocr.Reader.readtext with canned detections."""

    def readtext(self, crop):
        # (polygon, text, confidence)
        return [
            ([[40, 30], [160, 30], [160, 80], [40, 80]], "ACME", 0.95),      # branding
            ([[200, 32], [420, 32], [420, 78], [200, 78]], "PLUMBING", 0.80),  # branding
            ([[60, 140], [180, 140], [180, 175], [60, 175]], "ABC1234", 0.90),  # the plate
            ([[300, 150], [430, 150], [430, 180], [300, 180]], "555-1234", 0.92),  # phone#
            ([[10, 10], [30, 10], [30, 20], [10, 20]], "zz", 0.20),          # low-conf noise
        ]


def test_company_reader_extracts_real_branding():
    import numpy as np

    from efsurveillance.recognizer import CompanyReader

    cr = CompanyReader()
    cr._reader = _FakeOCR()   # bypass easyocr; test the filtering/assembly logic
    frame = np.zeros((200, 600, 3), dtype=np.uint8)

    # Company words are merged left→right; the plate and the phone number are
    # rejected (plate matches plate_text; phone is mostly digits).
    name = cr.read(frame, (0, 0, 600, 200), plate_text="ABC-1234")
    assert name == "ACME PLUMBING", name

    # No company-like text -> None (honest blank, never fabricated).
    class _JustANumber:
        def readtext(self, crop):
            return [([[0, 0], [9, 0], [9, 9], [0, 9]], "42", 0.99)]

    cr._reader = _JustANumber()
    assert cr.read(frame, (0, 0, 600, 200), plate_text=None) is None


def test_company_reader_merges_stacked_logo():
    import numpy as np

    from efsurveillance.recognizer import CompanyReader

    class _StackedLogo:
        """Two-line logo plus a much smaller slogan strip below it."""

        def readtext(self, crop):
            return [
                ([[100, 30], [260, 30], [260, 80], [100, 80]], "WASTE", 0.90),
                ([[60, 95], [420, 95], [420, 145], [60, 145]], "MANAGEMENT", 0.88),
                ([[300, 300], [420, 300], [420, 318], [300, 318]], "THINK GREEN", 0.70),
            ]

    cr = CompanyReader()
    cr._reader = _StackedLogo()
    frame = np.zeros((500, 600, 3), dtype=np.uint8)

    # Stacked lines merge top->bottom; the small far-away slogan is ignored;
    # the result canonicalizes to the known fleet spelling.
    assert cr.read(frame, (0, 0, 600, 500)) == "Waste Management"


def test_company_reader_rejects_fleet_boilerplate_and_cleans_urls():
    import numpy as np

    from efsurveillance.recognizer import CompanyReader

    cr = CompanyReader()
    frame = np.zeros((500, 600, 3), dtype=np.uint8)

    class _NoisyTruck:
        def readtext(self, crop):
            return [
                ([[50, 40], [400, 40], [400, 95], [50, 95]], "JOE'S PLUMBING", 0.90),
                ([[60, 300], [300, 300], [300, 330], [60, 330]], "HOW'S MY DRIVING?", 0.90),
                ([[320, 300], [430, 300], [430, 330], [320, 330]], "US DOT 2231144", 0.85),
                ([[60, 350], [280, 350], [280, 380], [60, 380]], "LICENSED & INSURED", 0.88),
            ]

    cr._reader = _NoisyTruck()
    assert cr.read(frame, (0, 0, 600, 500)) == "JOE'S PLUMBING"

    class _UrlVan:
        def readtext(self, crop):
            return [([[50, 40], [400, 40], [400, 90], [50, 90]],
                     "www.acmeplumbing.com", 0.86)]

    cr._reader = _UrlVan()
    assert cr.read(frame, (0, 0, 600, 500)) == "acmeplumbing.com"


def test_company_reader_canonicalizes_known_fleets():
    from efsurveillance.recognizer import CompanyReader

    cr = CompanyReader()
    assert cr._canonicalize("FEDEX GROUND") == "FedEx"
    assert cr._canonicalize("fedex") == "FedEx"
    assert cr._canonicalize("FEOEX") == "FedEx"                  # one-letter OCR slip
    assert cr._canonicalize("UNITED PARCEL SERVICE") == "UPS"
    assert cr._canonicalize("XFINITY") == "Comcast"
    # Unknown companies pass through exactly as read — never force-matched.
    assert cr._canonicalize("Bob's Welding") == "Bob's Welding"
    # Short brand names need an exact match ("PUPS GROOMING" is not UPS).
    assert cr._canonicalize("PUPS GROOMING") == "PUPS GROOMING"


def test_occupant_counting():
    from efsurveillance.occupancy import count_occupants

    veh = (100, 100, 300, 260)
    persons = [
        (150, 150, 190, 230),   # centre inside -> occupant
        (250, 140, 290, 220),   # centre inside -> occupant
        (400, 100, 440, 180),   # centre outside -> not counted
        (80, 80, 360, 300),     # bigger than the vehicle -> foreground, ignored
    ]
    assert count_occupants(veh, persons) == 2
    assert count_occupants(veh, []) == 0


def test_track_carries_occupant_count():
    from efsurveillance.detector import VehicleDetection
    from efsurveillance.tracking import TrackManager

    frame = SyntheticFrame(1000, 500)
    tm = TrackManager(axis="x", miss_grace=1, min_frames=2, move_frac=0.1)
    # Two sightings of one car; the closest (largest-box) frame has 2 occupants,
    # and that is the value the finalized track should carry.
    tm.update(frame, [VehicleDetection("car", 0.9, (100, 200, 180, 300),
                                       track_id=5, occupant_count=1)], seq=0)
    tm.update(frame, [VehicleDetection("car", 0.9, (300, 180, 520, 360),
                                       track_id=5, occupant_count=2)], seq=1)
    out = tm.flush()
    assert len(out) == 1 and out[0].occupant_count == 2


def test_make_model_classifier_gate():
    import numpy as np

    from efsurveillance.recognizer import MakeModelClassifier, parse_make_model

    # Label parsing: "Make Model" or explicit "Make|Model".
    assert parse_make_model("Ford F-150") == ("Ford", "F-150")
    assert parse_make_model("Mercedes-Benz|C-Class") == ("Mercedes-Benz", "C-Class")
    assert parse_make_model("") == (None, None)

    frame = np.zeros((120, 160, 3), dtype=np.uint8)

    # Off by default → disabled, always blank (never guesses).
    off = MakeModelClassifier(backend="off")
    assert not off.enabled
    assert off.classify(frame, (0, 0, 160, 120)) is None

    # Pretend a model loaded; inject inference to exercise the confidence gate.
    c = MakeModelClassifier(backend="off")
    c._labels = ["Ford F-150", "Toyota Camry"]
    c._ready = True
    c.min_confidence = 0.6

    c._infer = lambda crop: (0, 0.92)     # confident → fills make/model
    res = c.classify(frame, (0, 0, 160, 120))
    assert res is not None and res.make == "Ford" and res.model == "F-150"

    c._infer = lambda crop: (1, 0.41)     # below the gate → blank (honest)
    assert c.classify(frame, (0, 0, 160, 120)) is None

    c._infer = lambda crop: None          # inference failed → blank, no crash
    assert c.classify(frame, (0, 0, 160, 120)) is None


def test_make_model_accuracy_metrics():
    from tools.measure_make_model import Sample, compute_metrics

    samples = [
        Sample("Ford F-150", "Ford F-150", 0.95),    # correct, very confident
        Sample("Ford F-150", "Toyota Camry", 0.55),  # wrong, low confidence
        Sample("Toyota Camry", "Toyota Camry", 0.80),  # correct
        Sample("Honda Civic", None, 0.0),            # model abstained
    ]
    m = compute_metrics(samples, thresholds=[0.0, 0.6, 0.9])
    assert m["total_images"] == 4
    assert m["overall_top1_accuracy"] == 0.5     # 2 of 4 right

    rows = {r["threshold"]: r for r in m["threshold_table"]}
    # No gate: 3 answered (the None abstains), 2 correct.
    assert rows[0.0]["answered"] == 3 and rows[0.0]["correct"] == 2
    assert rows[0.0]["accuracy"] == round(2 / 3, 4)
    # Gate 0.6: only the two confident preds, both correct → 100%.
    assert rows[0.6]["answered"] == 2 and rows[0.6]["accuracy"] == 1.0
    # Gate 0.9: just the 0.95 one.
    assert rows[0.9]["answered"] == 1 and rows[0.9]["accuracy"] == 1.0

    assert m["per_class"]["Toyota Camry"]["accuracy"] == 1.0
    assert m["per_class"]["Honda Civic"]["accuracy"] == 0.0


def test_plate_fusion_consensus_voting():
    from efsurveillance.plate_fusion import PlateObservation, fuse_observations

    # Three reads of the same California plate; frame 2 misread B as 8 (with
    # low confidence on that character). The vote recovers the true plate.
    good = [0.92] * 7
    shaky = [0.92, 0.92, 0.35, 0.92, 0.92, 0.92, 0.92]   # pos 2 doubtful
    o1 = PlateObservation("7ABC123", good, 0.92, region="CA",
                          region_confidence=0.8, plate_height=40, sharpness=100)
    o2 = PlateObservation("7A8C123", shaky, 0.84, region="CA",
                          region_confidence=0.7, plate_height=30, sharpness=60)
    o3 = PlateObservation("7ABC123", [0.88] * 7, 0.88, region="TX",
                          region_confidence=0.4, plate_height=42, sharpness=110)

    fused = fuse_observations([o1, o2, o3])
    assert fused is not None
    assert fused.text == "7ABC123"
    assert fused.reads == 3
    assert fused.region == "CA"           # weighted region vote
    assert not fused.corrected
    # Agreement across frames makes the fused plate MORE confident than one read.
    assert fused.char_confidences[0] > 0.92

    # A minority short read can't drag the length vote down.
    o4 = PlateObservation("7ABC12", [0.5] * 6, 0.5, plate_height=20, sharpness=20)
    fused2 = fuse_observations([o1, o3, o4])
    assert fused2.text == "7ABC123"

    # No reads -> honest None.
    assert fuse_observations([]) is None


def test_plate_fusion_format_correction():
    from efsurveillance.plate_fusion import (PlateObservation, correct_format,
                                             fuse_observations)

    # "I" misread on a California-layout plate: no US layout is D-LLL-I-DD,
    # and the I was doubtful, so I -> 1 gives a perfect DLLLDDD match.
    confs = [0.95, 0.95, 0.95, 0.95, 0.40, 0.95, 0.95]
    assert correct_format("7ABCI23", confs) == "7ABC123"

    # Same text but the I was read CONFIDENTLY -> never touched.
    sure = [0.95] * 7
    assert correct_format("7ABCI23", sure) == "7ABCI23"

    # Already matches a layout -> untouched.
    assert correct_format("ABC1234", sure) == "ABC1234"

    # End-to-end through fusion: doubtful I is repaired and flagged.
    obs = [PlateObservation("7ABCI23", confs, 0.87, plate_height=40, sharpness=100)]
    fused = fuse_observations(obs)
    assert fused.text == "7ABC123" and fused.corrected and fused.raw_text == "7ABCI23"

    # Correction can be turned off.
    fused_off = fuse_observations(obs, format_correction=False)
    assert fused_off.text == "7ABCI23" and not fused_off.corrected


def test_plate_fusion_aligns_off_length_reads():
    """A read that dropped a character used to be thrown away entirely. Now it
    is ALIGNED to the consensus so the characters it did see still vote —
    here the 6-char read breaks a tie the full-length reads left open."""
    from efsurveillance.plate_fusion import PlateObservation, fuse_observations

    same = dict(plate_height=40, sharpness=100)
    # Position 3 is contested between the full-length reads: C@0.55 vs Q@0.60.
    o1 = PlateObservation("7ABC123", [0.9, 0.9, 0.9, 0.55, 0.9, 0.9, 0.9], 0.85, **same)
    o2 = PlateObservation("7ABQ123", [0.9, 0.9, 0.9, 0.60, 0.9, 0.9, 0.9], 0.86, **same)
    # The short read missed the final '3' but saw the C clearly.
    o3 = PlateObservation("7ABC12", [0.9] * 6, 0.9, **same)

    fused = fuse_observations([o1, o2, o3])
    assert fused.text == "7ABC123", fused.text
    assert fused.reads == 3

    # A garbage read of a similar length is rejected by the alignment, not voted.
    o4 = PlateObservation("XYZ99", [0.9] * 5, 0.9, **same)
    fused2 = fuse_observations([o1, o1, o4])
    assert fused2.text == "7ABC123"


def test_plate_fusion_pools_lookalike_votes():
    """Frames splitting between B and 8 AGREE about the glyph on the plate.
    The vote pools the twins (confidence stays high instead of cratering) and
    the plate-layout template decides letter-vs-digit — even though every
    individual read was confident."""
    from efsurveillance.plate_fusion import PlateObservation, fuse_observations

    same = dict(plate_height=40, sharpness=100)
    reads = [
        PlateObservation("ABC123B", [0.92] * 7, 0.92, **same),
        PlateObservation("ABC123B", [0.92] * 7, 0.92, **same),
        PlateObservation("ABC1238", [0.90] * 7, 0.90, **same),
        PlateObservation("ABC1238", [0.90] * 7, 0.90, **same),
    ]
    fused = fuse_observations(reads)
    # LLLDDDD wants a digit last -> the pooled glyph resolves to '8'.
    assert fused.text == "ABC1238", fused.text
    assert fused.corrected and fused.raw_text == "ABC123B"
    assert 6 in fused.ambiguous_positions
    # Pooled twins are agreement, not conflict: last-char confidence stays high.
    assert fused.char_confidences[6] > 0.9, fused.char_confidences


def test_consensus_lock_stops_paying_for_ocr():
    from efsurveillance.detector import VehicleDetection
    from efsurveillance.plate_fusion import PlateObservation, consensus_locked
    from efsurveillance.tracking import TrackManager

    ob = lambda text, conf: PlateObservation(text, [conf] * len(text), conf)  # noqa: E731

    # Two agreeing reads aren't enough; the third locks it.
    reads = [ob("ABC1234", 0.95), ob("ABC1234", 0.96)]
    assert not consensus_locked(reads, min_agree=3)
    assert consensus_locked(reads + [ob("ABC1234", 0.94)], min_agree=3)
    # Weak or disagreeing reads never lock.
    assert not consensus_locked([ob("ABC1234", 0.5)] * 5, min_agree=3)
    assert not consensus_locked(
        [ob("ABC1234", 0.95), ob("ABC1239", 0.95), ob("ABC1230", 0.95)], min_agree=3)

    tm = TrackManager(axis="x", miss_grace=2, min_frames=2)
    frame = SyntheticFrame(1000, 500)
    tm.update(frame, [VehicleDetection("car", 0.9, (100, 200, 220, 300),
                                       track_id=7)], seq=0)
    assert not tm.plate_locked(7)
    for _ in range(3):
        tm.add_plate(7, ob("XYZ7890", 0.95))
    assert tm.plate_locked(7)
    assert not tm.plate_locked(7, min_agree=4)
    assert not tm.plate_locked(99)  # unknown track


def test_deskew_levels_tilted_plate():
    try:
        import cv2
        import numpy as np
    except Exception:
        print("        (cv2 not installed - deskew test skipped)")
        return
    from efsurveillance.plate_reader import RealPlateReader

    # A synthetic plate: white background, black frame + characters...
    img = np.full((90, 260, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (10, 15), (250, 75), (0, 0, 0), 3)
    cv2.putText(img, "ABC123", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    # ...tilted 10 degrees, like a plate seen from an angled camera mount.
    m = cv2.getRotationMatrix2D((130, 45), -10, 1.0)
    tilted = cv2.warpAffine(img, m, (260, 90), borderValue=(255, 255, 255))

    tilt = RealPlateReader._estimate_tilt(tilted)
    assert 5.0 <= abs(tilt) <= 15.0, f"tilt estimate off: {tilt}"

    level = RealPlateReader._rotated_level(tilted, tilt)
    residual = RealPlateReader._estimate_tilt(level)
    assert abs(residual) <= 3.5, f"still tilted after deskew: {residual}"

    # The enhancement pipeline picks the deskew up automatically.
    assert RealPlateReader._enhanced_variants(tilted)


def test_retry_merges_variant_reads():
    """When the first read is doubtful the enhanced variants are re-OCR'd and
    ALL reads of the frame merge character-by-character — one variant can fix
    the character another got wrong, even if neither read was perfect."""
    from types import SimpleNamespace

    import numpy as np

    from efsurveillance.plate_reader import RealPlateReader

    def _base_predict(crop):
        det = SimpleNamespace(
            bounding_box=SimpleNamespace(x1=40, y1=80, x2=200, y2=130))
        ocr = SimpleNamespace(text="ABC7234", region=None, region_confidence=None,
                              confidence=[0.95, 0.95, 0.95, 0.20, 0.95, 0.95, 0.98])
        return [SimpleNamespace(detection=det, ocr=ocr)]

    def _variant_predict(_v):
        return SimpleNamespace(text="ABC1230", region=None, region_confidence=None,
                               confidence=[0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.20])

    reader = RealPlateReader.__new__(RealPlateReader)
    reader.retry_below_conf = 0.95
    reader.min_read_conf = 0.5
    reader._alpr = SimpleNamespace(predict=_base_predict,
                                   ocr=SimpleNamespace(predict=_variant_predict))
    reader._enhanced_variants = lambda pc: [pc]     # exactly one variant, no cv2

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    res = reader.read(frame, (0, 0, 320, 240))
    # pos 3: base '7'@0.20 vs variant '1'@0.95 -> 1;  pos 6: base '4'@0.98
    # vs variant '0'@0.20 -> 4. Neither single read was ABC1234; the merge is.
    assert res.text == "ABC1234", res.text
    assert res.confidence > 0.85


def test_alpr_confusion_report():
    from tools.measure_alpr import Sample, compute_metrics

    m = compute_metrics([
        Sample("ABC1234", "ABC1234", 0.95),
        Sample("XYZ8888", "XYZ888B", 0.80),
        Sample("XYZ8888", "XYZ88B8", 0.75),
        Sample("PQR5555", None, 0.0),
    ])
    assert m["confusions"] == {"8->B": 2}


def test_track_manager_collects_plate_reads():
    from efsurveillance.detector import VehicleDetection
    from efsurveillance.plate_fusion import PlateObservation
    from efsurveillance.tracking import TrackManager

    frame = SyntheticFrame(1000, 500)
    tm = TrackManager(axis="x", miss_grace=1, min_frames=2, move_frac=0.1)
    tm.update(frame, [VehicleDetection("car", 0.9, (100, 200, 220, 300),
                                       track_id=3)], seq=0)

    ob = lambda conf: PlateObservation("ABC1234", [conf] * 7, conf)  # noqa: E731
    assert tm.add_plate(3, ob(0.9)) is True
    assert tm.add_plate(99, ob(0.9)) is False       # unknown track
    assert tm.plate_read_count(3) == 1

    # The budget caps stored reads; a better read replaces the weakest.
    assert tm.add_plate(3, ob(0.5), max_reads=2) is True
    assert tm.add_plate(3, ob(0.4), max_reads=2) is False    # weaker than both
    assert tm.add_plate(3, ob(0.95), max_reads=2) is True    # replaces the 0.5
    assert tm.plate_read_count(3) == 2

    tm.update(frame, [VehicleDetection("car", 0.9, (400, 200, 540, 300),
                                       track_id=3)], seq=1)
    out = tm.flush()
    assert len(out) == 1
    confs = sorted(o.confidence for o in out[0].plate_observations)
    assert confs == [0.9, 0.95]


def test_event_logger_upserts_live_event():
    """The instant 'vehicle in view' row and the final enriched commit share
    an event_uuid -> ONE row that updates in place and re-queues for upload."""
    with tempfile.TemporaryDirectory() as tmp:
        log = EventLogger(Path(tmp) / "events.db")
        # Provisional: vehicle just confirmed, no plate yet.
        first = log.log_vehicle(camera_id="EFS-L", vehicle_type="car",
                                confidence=0.8, event_uuid="pass-1", pending=True)
        assert log.count() == 1
        log.mark_synced([first["id"]])
        assert log.count_unsynced() == 0

        # Finalize: same uuid -> same row, enriched, and queued for upload again.
        log.log_vehicle(camera_id="EFS-L", vehicle_type="car", confidence=0.9,
                        plate_text="ABC1234", direction="in",
                        event_uuid="pass-1", pending=False)
        assert log.count() == 1                      # updated, not duplicated
        rows = log.get_unsynced()
        assert len(rows) == 1
        row = rows[0]
        assert row["plate_text"] == "ABC1234" and row["direction"] == "in"
        assert row["pending"] == 0 and row["synced"] == 0
        assert row["id"] == first["id"]              # same local row
        # Uploader metadata carries the pending flag to the backend.
        up = Uploader(_uploader_cfg(), log, camera_id="EFS-L")
        assert up.build_metadata(row)["pending"] is False
        log.close()


def test_tracker_announces_new_vehicles_once():
    from efsurveillance.detector import VehicleDetection
    from efsurveillance.tracking import TrackManager

    frame = SyntheticFrame(1000, 500)
    tm = TrackManager(axis="x", miss_grace=2, min_frames=2, move_frac=0.1)
    det = lambda cx, tid: VehicleDetection(  # noqa: E731
        "car", 0.9, (cx - 40, 200, cx + 40, 300), track_id=tid)

    tm.update(frame, [det(100, 5)], seq=0)
    assert tm.pop_new_confirmed() == []        # one frame: not real yet
    tm.update(frame, [det(160, 5)], seq=1)
    confirmed = tm.pop_new_confirmed()
    assert len(confirmed) == 1
    snap = confirmed[0]
    assert snap.track_id == 5 and snap.direction == "unknown"
    assert snap.event_uuid
    assert tm.pop_new_confirmed() == []        # announced exactly once

    # The final event carries the SAME uuid -> one log row for the pass.
    for i, cx in enumerate([300, 500, 700, 900], start=2):
        tm.update(frame, [det(cx, 5)], seq=i)
    out = tm.update(frame, [], seq=10)
    assert len(out) == 1 and out[0].event_uuid == snap.event_uuid
    assert out[0].direction == "in"


def test_real_reader_confidence_alignment():
    """The OCR returns one confidence per model SLOT (fixed width) while the
    text is pad-stripped — the reader must align them, and non-alphanumeric
    characters must drop their confidences too."""
    import numpy as np
    from types import SimpleNamespace

    from efsurveillance.plate_reader import RealPlateReader

    class _FakeALPR:
        ocr = SimpleNamespace(predict=lambda v: None)

        def predict(self, crop):
            det = SimpleNamespace(
                bounding_box=SimpleNamespace(x1=50, y1=100, x2=150, y2=140))
            # 7 real chars + a stray '_' the model left in, 9 slot confidences.
            ocr = SimpleNamespace(text="ABC_1234", region="TX", region_confidence=0.7,
                                  confidence=[0.99, 0.98, 0.97, 0.10, 0.96,
                                              0.95, 0.94, 0.93, 0.05])
            return [SimpleNamespace(detection=det, ocr=ocr)]

    reader = RealPlateReader.__new__(RealPlateReader)
    reader.retry_below_conf = 0.0      # skip the enhance-and-retry pass
    reader.min_read_conf = 0.5
    reader._alpr = _FakeALPR()

    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    res = reader.read(frame, (10, 10, 290, 190))
    assert res.text == "ABC1234"
    # 8 raw chars -> slot conf trimmed to 8, then the '_' slot (0.10) dropped.
    assert len(res.char_confidences) == 7
    assert 0.10 not in res.char_confidences
    assert res.region == "TX" and res.bbox is not None and res.crop is not None

    obs = res.to_observation()
    assert obs.text == "ABC1234" and len(obs.char_confidences) == 7
    assert obs.plate_height == res.bbox[3] - res.bbox[1]


def test_alpr_accuracy_metrics():
    from tools.measure_alpr import Sample, compute_metrics, levenshtein

    assert levenshtein("ABC1234", "ABC1234") == 0
    assert levenshtein("ABC1234", "A8C1234") == 1
    assert levenshtein("ABC", "") == 3

    samples = [
        Sample("ABC1234", "ABC1234", 0.95),   # right, confident
        Sample("XYZ789", "XYZ780", 0.60),     # one character off
        Sample("DEF456", None, 0.0),          # no read
        Sample("GHI111", "GHI111", 0.70),     # right
    ]
    m = compute_metrics(samples, thresholds=[0.0, 0.7, 0.9])
    assert m["total_images"] == 4
    assert m["read_rate"] == 0.75
    assert m["exact_match_rate"] == 0.5
    assert m["char_accuracy"] == round((1.0 + (1 - 1 / 6) + 0.0 + 1.0) / 4, 4)

    rows = {r["threshold"]: r for r in m["threshold_table"]}
    assert rows[0.0]["answered"] == 3 and rows[0.0]["correct"] == 2
    # Gate 0.7: only the two confident answers remain, both right -> 100%.
    assert rows[0.7]["answered"] == 2 and rows[0.7]["accuracy"] == 1.0
    assert rows[0.9]["answered"] == 1 and rows[0.9]["accuracy"] == 1.0


def test_event_logger_store_and_forward():
    with tempfile.TemporaryDirectory() as tmp:
        log = EventLogger(Path(tmp) / "events.db")
        row = log.log_vehicle(
            camera_id="EFS-T", plate_text="ABC-1234", vehicle_type="truck",
            vehicle_color="white", confidence=0.9, is_commercial=True, company_name="FedEx",
        )
        assert row["id"] >= 1
        assert log.count() == 1 and log.count_unsynced() == 1
        pending = log.get_unsynced()
        assert pending[0]["plate_text"] == "ABC-1234"
        log.mark_synced([row["id"]])
        assert log.count_unsynced() == 0
        assert log.count_by_type().get("truck") == 1
        log.close()


def test_uploader_metadata_mapping():
    with tempfile.TemporaryDirectory() as tmp:
        log = EventLogger(Path(tmp) / "events.db")
        row = log.log_vehicle(camera_id="EFS-T", plate_text="XYZ-1", vehicle_type="van",
                              confidence=0.7, occupant_count=2)
        up = Uploader(_uploader_cfg(), log, camera_id="EFS-T")
        meta = up.build_metadata(log.get_unsynced()[0])
        assert meta["event_uuid"] == row["event_uuid"]
        assert meta["camera_id"] == "EFS-T" and meta["plate_text"] == "XYZ-1"
        assert meta["vehicle_type"] == "van" and meta["occupant_count"] == 2
        # Must match the backend's required keys.
        for k in ("event_uuid", "camera_id", "captured_at", "direction", "confidence"):
            assert k in meta
        log.close()


def test_track_manager_logs_once_with_direction():
    from efsurveillance.detector import VehicleDetection
    from efsurveillance.tracking import TrackManager

    frame = SyntheticFrame(1000, 500)

    # Car #1 crosses left -> right; should log once, direction "in".
    tm = TrackManager(axis="x", invert=False, miss_grace=2, min_frames=2, move_frac=0.1)
    finals = []
    for i, cx in enumerate([100, 300, 500, 700, 900]):
        det = VehicleDetection("car", 0.9, (cx - 40, 200, cx + 40, 300), track_id=1)
        finals += tm.update(frame, [det], seq=i)
    assert finals == []  # still in frame, not finalized yet
    out = tm.update(frame, [], seq=10)  # vanished -> finalize after miss_grace
    assert len(out) == 1 and out[0].track_id == 1 and out[0].direction == "in"

    # Car #2 crosses right -> left; direction "out".
    tm2 = TrackManager(axis="x", miss_grace=2, min_frames=2, move_frac=0.1)
    for i, cx in enumerate([900, 700, 500, 300, 100]):
        tm2.update(frame, [VehicleDetection("truck", 0.8, (cx - 40, 200, cx + 40, 300),
                                            track_id=7)], seq=i)
    out2 = tm2.flush()
    assert len(out2) == 1 and out2[0].direction == "out"

    # A single-frame blip is ignored (likely a false positive).
    tm3 = TrackManager(min_frames=2)
    tm3.update(frame, [VehicleDetection("car", 0.5, (10, 10, 50, 50), track_id=99)], seq=0)
    assert tm3.flush() == []


def test_track_stabilizer_bridges_tracker_id_churn():
    from efsurveillance.detector import VehicleDetection
    from efsurveillance.tracking import TrackStabilizer

    stabilizer = TrackStabilizer(max_missing=4)
    first = stabilizer.stabilize(
        [VehicleDetection("car", 0.9, (100, 120, 260, 260), track_id=10)],
        seq=1,
        frame_wh=(1000, 600),
    )[0]
    assert first.track_id == 1

    # ByteTrack may restart with a new external id after a flicker. A nearby
    # box is still the same vehicle locally.
    second = stabilizer.stabilize(
        [VehicleDetection("car", 0.9, (120, 122, 280, 262), track_id=99)],
        seq=2,
        frame_wh=(1000, 600),
    )[0]
    assert second.track_id == first.track_id

    jumped = stabilizer.stabilize(
        [VehicleDetection("car", 0.9, (180, 125, 340, 265), track_id=101)],
        seq=5,
        frame_wh=(1000, 600),
    )[0]
    assert jumped.track_id == first.track_id
    assert stabilizer.overlay_items(seq=6, frame_wh=(1000, 600))

    far = stabilizer.stabilize(
        [VehicleDetection("car", 0.9, (720, 120, 900, 260), track_id=202)],
        seq=6,
        frame_wh=(1000, 600),
    )[0]
    assert far.track_id != first.track_id


def test_parked_vehicle_is_never_logged():
    """A car that sits still the whole time is scenery, not an event — no
    provisional announcement, no finalized event, no matter how the track ends."""
    from efsurveillance.detector import VehicleDetection
    from efsurveillance.tracking import TrackManager

    frame = SyntheticFrame(1000, 500)
    tm = TrackManager(axis="x", miss_grace=2, min_frames=2, min_move_frac=0.05)
    parked = lambda tid: VehicleDetection(  # noqa: E731
        "car", 0.9, (400, 200, 520, 300), track_id=tid)

    for i in range(12):
        assert tm.update(frame, [parked(4)], seq=i) == []
        assert tm.pop_new_confirmed() == []      # never announced
        assert not tm.has_moved(4)
    # Track ends (occluded / aged out) -> still nothing.
    assert tm.update(frame, [], seq=20) == []
    assert tm.flush() == []

    # The classic failure: a passing car breaks the track and the parked car
    # comes back with a FRESH id. Still stationary -> still not an event.
    for i in range(21, 27):
        tm.update(frame, [parked(9)], seq=i)
    assert tm.pop_new_confirmed() == []
    assert tm.update(frame, [], seq=40) == []


def test_arriving_car_logs_once_then_parks_silently():
    """A car that drives in and parks is ONE event (it moved); the re-created
    track of the now-parked car never becomes a second one."""
    from efsurveillance.detector import VehicleDetection
    from efsurveillance.tracking import TrackManager

    frame = SyntheticFrame(1000, 500)
    tm = TrackManager(axis="x", miss_grace=2, min_frames=2,
                      move_frac=0.1, min_move_frac=0.05)
    box = lambda cx, tid: VehicleDetection(  # noqa: E731
        "car", 0.9, (cx - 60, 200, cx + 60, 300), track_id=tid)

    # Drives in from the left, stops at cx=700, sits there.
    for i, cx in enumerate([100, 300, 500, 700, 700, 700, 700]):
        tm.update(frame, [box(cx, 11)], seq=i)
    assert tm.has_moved(11)
    assert len(tm.pop_new_confirmed()) == 1      # announced (it moved)
    out = tm.update(frame, [], seq=20)           # track ends
    assert len(out) == 1 and out[0].direction == "in"

    # Same car, still parked, new track id (tracker churn) -> suppressed.
    for i in range(21, 30):
        tm.update(frame, [box(700, 12)], seq=i)
    assert tm.pop_new_confirmed() == []
    assert tm.update(frame, [], seq=45) == []


def test_headon_approach_counts_as_movement():
    """A car driving straight at the camera barely shifts its centre — but its
    box GROWS. That must count as movement or head-on entrances go unlogged."""
    from efsurveillance.detector import VehicleDetection
    from efsurveillance.tracking import TrackManager

    frame = SyntheticFrame(1000, 500)
    tm = TrackManager(axis="x", miss_grace=2, min_frames=2, min_move_frac=0.05)
    sizes = [40, 60, 90, 130]                    # half-widths: approaching
    for i, s in enumerate(sizes):
        tm.update(frame, [VehicleDetection(
            "car", 0.9, (500 - s, 250 - s // 2, 500 + s, 250 + s // 2),
            track_id=21)], seq=i)
    assert tm.has_moved(21)
    out = tm.flush()
    assert len(out) == 1                          # logged (real arrival)


def test_tracker_latest_plate_text_for_overlay():
    from efsurveillance.detector import VehicleDetection
    from efsurveillance.plate_fusion import PlateObservation
    from efsurveillance.tracking import TrackManager

    frame = SyntheticFrame(1000, 500)
    tm = TrackManager(axis="x", miss_grace=2, min_frames=2)
    tm.update(frame, [VehicleDetection("car", 0.9, (100, 200, 220, 300),
                                       track_id=8)], seq=0)
    assert tm.latest_plate_text(8) is None          # no reads yet — honest blank
    tm.add_plate(8, PlateObservation("ABC1234", [0.7] * 7, 0.7))
    tm.add_plate(8, PlateObservation("A8C1234", [0.9] * 7, 0.9))
    assert tm.latest_plate_text(8) == "A8C1234"     # most confident read so far
    assert tm.latest_plate_text(99) is None         # unknown track


def test_live_stream_frame_packet():
    """One frame on the edge->backend live stream: ASCII header, then JPEG."""
    from efsurveillance.live import frame_packet

    jpeg = b"\xff\xd8\xff\xe0hello"
    pkt = frame_packet(jpeg, {"capture_fps": 29.7, "detect_fps": 6.0})
    header, _, body = pkt.partition(b"\n")
    assert header == b"EFSF 9 29.7 6.0"
    assert body == jpeg
    # Missing stats become zeros, never crashes.
    assert frame_packet(jpeg).startswith(b"EFSF 9 0 0\n")


def test_live_overlay_draws_detection_boxes():
    """The live preview burns the detector's boxes into the frame: with an
    overlay the encoded JPEG differs, stale overlays are skipped, and the
    SHARED detection frame is never scribbled on."""
    try:
        import numpy as np
        import cv2  # noqa: F401
    except Exception:
        print("        (cv2 not installed - overlay test skipped)")
        return
    import time as _time

    from efsurveillance.config import Config
    from efsurveillance.live import LivePusher

    cfg = Config().uploader
    frame = np.full((240, 320, 3), 60, dtype=np.uint8)
    overlay = {"ts": _time.monotonic(), "frame_wh": (320, 240),
               "items": [((40, 40, 200, 160), "CAR 91% - ABC1234", "vehicle"),
                         ((210, 60, 260, 200), "PERSON", "person")]}

    def pusher(provider):
        return LivePusher(cfg, camera_id="EFS-OVR", backend_url="http://x",
                          api_token="", overlay_provider=provider)

    plain = pusher(lambda: None)._encode_real(frame)
    boxed = pusher(lambda: overlay)._encode_real(frame)
    assert plain and boxed and boxed != plain       # boxes changed the pixels
    # The shared frame itself must be untouched (detector still reads it).
    assert int(frame.max()) == 60 and int(frame.min()) == 60

    stale = dict(overlay, ts=_time.monotonic() - 10.0)
    unboxed = pusher(lambda: stale)._encode_real(frame)
    assert unboxed == plain                          # stale boxes not drawn


def test_full_mock_pipeline_logs_events():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config()
        cfg.base_dir = Path(tmp)
        cfg.camera.id = "EFS-PIPE"
        cfg.source.backend = "synthetic"
        cfg.source.process_fps = 30.0
        cfg.detector.backend = "mock"
        cfg.detector.mock_interval_seconds = 0.05
        cfg.events.cooldown_seconds = 0.0
        cfg.uploader.enabled = False

        app = SurveillanceApp(cfg)
        app.setup()
        app.run(duration=0.5)
        logged = app.events.count()
        app.shutdown()
        assert logged >= 2, f"expected several events, got {logged}"


def _uploader_cfg():
    cfg = Config()
    return cfg.uploader


def _run_all():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\n{len(tests)}/{len(tests)} edge tests passed.")


if __name__ == "__main__":
    _run_all()
