import cv2
import numpy as np
from ultralytics import YOLO
import easyocr
import re
import uuid
import torch
from pathlib import Path

# Limit CPU threads to prevent massive thread pool memory overhead on multi-core host servers
torch.set_num_threads(1)
cv2.setNumThreads(0)

# ─────────────────────────────────────────────────────────────────────────────

# Paths
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
FRONTEND_DIR = BASE_DIR.parent / "frontend"

MODEL_PATHS = {
    "motorcycle":   BASE_DIR / "motorcycle.pt",
    "helmet":       BASE_DIR / "helmet.pt",
    "license":      BASE_DIR / "license.pt",
    "person_phone": BASE_DIR / "person_phone.pt",
}
RESULTS_DIR = FRONTEND_DIR / "static" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Memory-Optimized Dynamic Inference
# ─────────────────────────────────────────────────────────────────────────────
import gc

def _trim_memory():
    """Force release of allocated C/Python memory back to the OS (Linux glibc)."""
    gc.collect()
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass

def _validate_models():
    """Validate that all required model files exist at startup."""
    missing = []
    for name, path in MODEL_PATHS.items():
        if not path.exists():
            missing.append(f"{name} ({path})")
    if missing:
        raise FileNotFoundError(f"Missing model files: {', '.join(missing)}")

def _run_yolo_inference(name: str, frame, **kwargs):
    """Load a model, run inference, delete the model from memory, and release RAM."""
    if not MODEL_PATHS[name].exists():
        raise FileNotFoundError(f"Model file not found: {MODEL_PATHS[name]}")
    model = YOLO(str(MODEL_PATHS[name]))
    result = model(frame, **kwargs)[0]
    del model
    _trim_memory()
    return result

# ─────────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ─────────────────────────────────────────────────────────────────────────────
def _iou(a, b) -> float:
    xa, ya = max(a[0], b[0]), max(a[1], b[1])
    xb, yb = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, xb - xa) * max(0, yb - ya)
    if inter == 0:
        return 0.0
    aA = (a[2]-a[0]) * (a[3]-a[1])
    aB = (b[2]-b[0]) * (b[3]-b[1])
    return inter / (aA + aB - inter)

def _overlap_ratio(inner, outer) -> float:
    """Fraction of `inner` that overlaps `outer`."""
    xa, ya = max(inner[0], outer[0]), max(inner[1], outer[1])
    xb, yb = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0, xb - xa) * max(0, yb - ya)
    area = max(1, (inner[2]-inner[0]) * (inner[3]-inner[1]))
    return inter / area

def _expand_box(box, shape, pad=30):
    h, w = shape[:2]
    return [max(0,box[0]-pad), max(0,box[1]-pad),
            min(w,box[2]+pad), min(h,box[3]+pad)]

def _merge_boxes(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]

def _box_center(b):
    return ((b[0]+b[2])//2, (b[1]+b[3])//2)

def _box_dist(a, b):
    ca, cb = _box_center(a), _box_center(b)
    return ((ca[0]-cb[0])**2 + (ca[1]-cb[1])**2) ** 0.5

# ─────────────────────────────────────────────────────────────────────────────
# Improved OCR  –  tries 5 preprocessing variants, returns best match
# ─────────────────────────────────────────────────────────────────────────────
_INDIAN_PLATE_RE = re.compile(
    r'[A-Z]{2}\s*\d{1,2}\s*[A-Z]{1,3}\s*\d{3,4}', re.IGNORECASE
)

def _preprocess_variants(gray: np.ndarray):
    """Return list of preprocessed images to try OCR on."""
    variants = []
    # 1. pure resize + otsu
    g = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, v1 = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(v1)

    # 2. CLAHE + otsu
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    g2 = clahe.apply(cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
    _, v2 = cv2.threshold(g2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(v2)

    # 3. bilateral filter + adaptive threshold
    g3 = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    g3 = cv2.bilateralFilter(g3, 11, 17, 17)
    v3 = cv2.adaptiveThreshold(g3, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 15, 8)
    variants.append(v3)

    # 4. inverted otsu (for dark-on-light plates)
    v4 = cv2.bitwise_not(v1)
    variants.append(v4)

    # 5. raw gray upscaled (let EasyOCR handle it)
    variants.append(cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))

    return variants

def _read_plate(frame: np.ndarray, plate_box: list) -> str:
    x1, y1, x2, y2 = [int(v) for v in plate_box]
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0 or crop.shape[0] < 5 or crop.shape[1] < 10:
        return "UNREADABLE"

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    
    # Load OCR reader ONCE for the current plate crop (to avoid loading/unloading inside the loop)
    reader = easyocr.Reader(["en"], gpu=False)
    candidates = []

    for img in _preprocess_variants(gray):
        results = reader.readtext(
            img, detail=1,
            allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ",
            paragraph=False
        )
        text = " ".join(r[1] for r in results).strip().upper()
        text = re.sub(r'\s+', ' ', text)
        if not text:
            continue
        # score: does it match Indian plate pattern?
        score = 2 if _INDIAN_PLATE_RE.search(text) else (1 if len(text) >= 4 else 0)
        candidates.append((score, len(text), text))

    # Free EasyOCR memory immediately after processing the plate
    del reader
    _trim_memory()

    if not candidates:
        return "UNREADABLE"

    # pick highest score, then longest
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best = candidates[0][2]
    return best if best else "UNREADABLE"


# ─────────────────────────────────────────────────────────────────────────────
# Collect all detections from a model result into categorised lists
# ─────────────────────────────────────────────────────────────────────────────
def _parse_detections(result, conf_thresh: float):
    motos, persons, helmets, no_helmets, phones, plates = [], [], [], [], [], []
    for box in result.boxes:
        if float(box.conf[0]) < conf_thresh:
            continue
        cls_name = result.names[int(box.cls[0])].lower()
        b = [int(v) for v in box.xyxy[0].tolist()]
        conf = float(box.conf[0])

        if   "motorcycle" in cls_name or "motorbike" in cls_name or cls_name == "bike":
            motos.append({"box": b, "conf": conf})
        elif cls_name == "person":
            persons.append({"box": b, "conf": conf})
        elif "without" in cls_name or "no_helmet" in cls_name or "no-helmet" in cls_name:
            no_helmets.append({"box": b, "conf": conf})
        elif "helmet" in cls_name:                   # "with helmet" or bare "helmet"
            helmets.append({"box": b, "conf": conf})
        elif "phone" in cls_name or "mobile" in cls_name or "cell" in cls_name:
            if conf >= 0.45:
                phones.append({"box": b, "conf": conf})
        elif "license" in cls_name or "plate" in cls_name or "number" in cls_name:
            plates.append({"box": b, "conf": conf})

    return motos, persons, helmets, no_helmets, phones, plates

# ─────────────────────────────────────────────────────────────────────────────
# Main detection entry point
# ─────────────────────────────────────────────────────────────────────────────
def detect_violations(frame: np.ndarray, frame_id: int = 0,
                      conf_moto: float = 0.30) -> list[dict]:
    """
    Run the full violation detection pipeline on one BGR frame.
    Returns list of violation dicts.
    CONFIDENCE: motorcycle detection threshold increased to 0.25 to reduce false positives
    """
    violations = []

    # Stricter thresholds to reduce false positives:
    # - Motorcycle: 0.30 (very strict)
    # - Helmet/Person: 0.30 (strict - only high confidence detections)
    # - License plate: 0.20 (moderate)
    moto_res = _run_yolo_inference("motorcycle", frame, conf=conf_moto, verbose=False)
    m_motos, m_persons, m_helmets, m_no_helmets, m_phones, m_plates = \
        _parse_detections(moto_res, conf_moto)

    hel_res  = _run_yolo_inference("helmet", frame, conf=0.15, verbose=False)
    _, _, h_helmets, h_no_helmets, _, _ = \
        _parse_detections(hel_res, 0.15)

    pp_res   = _run_yolo_inference("person_phone", frame, conf=0.15, verbose=False)
    _, pp_persons, _, _, pp_phones, _ = \
        _parse_detections(pp_res, 0.15)

    lic_res  = _run_yolo_inference("license", frame, conf=0.15, verbose=False)
    _, _, _, _, _, l_plates = \
        _parse_detections(lic_res, 0.15)


    # Merge lists (combined detections from all relevant models)
    motos     = m_motos
    persons   = _dedup_boxes(m_persons + pp_persons)
    helmets   = _dedup_boxes(m_helmets + h_helmets)
    no_helmets= _dedup_boxes(m_no_helmets + h_no_helmets)
    phones    = _dedup_boxes(m_phones + pp_phones)
    plates    = _dedup_boxes(m_plates + l_plates)

    if not motos:
        return []

    # ── Per-motorcycle analysis ───────────────────────────────────
    for moto in motos:
        mb = moto["box"]
        moto_h = mb[3] - mb[1]
        moto_w = mb[2] - mb[0]

        # Find riders — lower thresholds so partial overlaps count
        riders = [p for p in persons
                  if _overlap_ratio(p["box"], mb) > 0.12
                  or _iou(p["box"], mb) > 0.05
                  or _box_dist(p["box"], mb) < moto_h * 0.6]

        # Fallback synthetic rider if no real person near moto
        if not riders:
            synthetic_rider = {
                "box": [mb[0], mb[1], mb[2], mb[1] + int(moto_h * 0.6)],
                "conf": moto["conf"] * 0.6,
                "synthetic": True
            }
            riders = [synthetic_rider]

        vio_types  = []
        conf_score = moto["conf"]

        # 1. Triple riding - check ALL riders (real and synthetic) to catch all occupants
        if len(riders) >= 3:
            vio_types.append("Triple Riding")

        # 2. Helmet violation —  ONLY check REAL riders, not synthetic ones
        real_riders = [r for r in riders if not r.get("synthetic")]
        
        for rider in real_riders:  # Changed: only real riders, skip synthetic
            rb = rider["box"]
            head_box = [rb[0], rb[1], rb[2], rb[1] + int((rb[3]-rb[1]) * 0.45)]

            # Stricter helmet detection: require 15% overlap minimum (was 8%)
            has_helmet = any(
                _overlap_ratio(h["box"], head_box) > 0.15
                or _iou(h["box"], head_box) > 0.10
                for h in helmets
            )
            # Stricter no-helmet detection: require 15% overlap (was 8%)
            explicit_no_helmet = any(
                _overlap_ratio(nh["box"], rb) > 0.15
                or _overlap_ratio(nh["box"], head_box) > 0.15
                for nh in no_helmets
            )
            if explicit_no_helmet or not has_helmet:
                if "Helmet Violation" not in vio_types:
                    vio_types.append("Helmet Violation")
                break

        # 3. Mobile phone usage — 4 strategies, most generous wins
        # Expanded moto region (1.5× size) for contextual phone check
        exp_mb = [mb[0] - moto_w//3, mb[1] - moto_h//3,
                  mb[2] + moto_w//3, mb[3] + moto_h//3]
        phone_found = False

        for ph in phones:
            pb = ph["box"]
            # Strategy A: phone overlaps any rider box
            if any(_overlap_ratio(pb, r["box"]) > 0.05
                   or _iou(pb, r["box"]) > 0.04 for r in riders):
                phone_found = True; break
            # Strategy B: phone within 300px of moto centre
            if _box_dist(pb, mb) < 300:
                phone_found = True; break
            # Strategy C: phone inside expanded moto region
            if _overlap_ratio(pb, exp_mb) > 0.05:
                phone_found = True; break
            # Strategy D: phone's centre is within moto bounding box (expanded)
            pc = _box_center(pb)
            if exp_mb[0] <= pc[0] <= exp_mb[2] and exp_mb[1] <= pc[1] <= exp_mb[3]:
                phone_found = True; break

        if phone_found:
            vio_types.append("Mobile Usage")

        if not vio_types:
            continue


        # 4. License plate
        plate_text     = None          # None = no text extracted
        best_plate_box = None
        best_score     = -1

        for pl in plates:
            ov   = _overlap_ratio(pl["box"], mb)
            dist = _box_dist(pl["box"], mb)
            score = ov * 10 - dist / 1000
            if score > best_score:
                best_score     = score
                best_plate_box = pl["box"]

        # FIXED: Removed fallback that picked closest plate without overlap
        # This prevented reading plates from completely different vehicles in frame
        # Only use plates that actually overlap with the motorcycle

        if best_plate_box:
            padded  = _expand_box(best_plate_box, frame.shape, pad=8)
            raw_txt = _read_plate(frame, padded)
            # Only keep text if something real was extracted
            if raw_txt and raw_txt not in ("UNREADABLE", "NOT DETECTED", "UNKNOWN"):
                plate_text = raw_txt

        # 5. Crop violation image  (moto + riders only, no plate box)
        real_rider_boxes = [r["box"] for r in riders if not r.get("synthetic")]
        crop_parts = [mb] + real_rider_boxes
        crop_box   = _expand_box(_merge_boxes(crop_parts), frame.shape, pad=25)
        crop_img   = frame[crop_box[1]:crop_box[3], crop_box[0]:crop_box[2]].copy()

        # Annotate text bar
        plate_label = f"   Plate: {plate_text}" if plate_text else ""
        label = f"{' | '.join(vio_types)}{plate_label}"
        overlay = crop_img.copy()
        cv2.rectangle(overlay, (0, 0), (crop_img.shape[1], 32), (15, 15, 15), -1)
        cv2.addWeighted(overlay, 0.75, crop_img, 0.25, 0, crop_img)
        cv2.putText(crop_img, label, (6, 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.58, (0, 240, 100), 1, cv2.LINE_AA)

        # Draw bounding boxes
        ox, oy = crop_box[0], crop_box[1]

        # Motorcycle box (blue)
        cv2.rectangle(crop_img,
                      (mb[0]-ox, mb[1]-oy), (mb[2]-ox, mb[3]-oy),
                      (255, 120, 0), 2)

        # Riders: ONE merged green box for triple-riding, individual boxes otherwise
        if real_rider_boxes:
            if "Triple Riding" in vio_types:
                merged_rb = _merge_boxes(real_rider_boxes)
                cv2.rectangle(crop_img,
                              (merged_rb[0]-ox, merged_rb[1]-oy),
                              (merged_rb[2]-ox, merged_rb[3]-oy),
                              (0, 220, 80), 2)
                cv2.putText(crop_img, "Triple Riding",
                            (merged_rb[0]-ox+4, max(merged_rb[1]-oy-6, 40)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 220, 80), 1, cv2.LINE_AA)
            else:
                for r in riders:
                    if not r.get("synthetic"):
                        rb = r["box"]
                        cv2.rectangle(crop_img,
                                      (rb[0]-ox, rb[1]-oy), (rb[2]-ox, rb[3]-oy),
                                      (0, 220, 80), 2)

        # Small yellow bounding box for license plate (if inside crop region)
        if best_plate_box:
            px1, py1, px2, py2 = best_plate_box
            # clamp to crop bounds
            cx1 = max(0, px1 - ox); cy1 = max(0, py1 - oy)
            cx2 = min(crop_img.shape[1], px2 - ox)
            cy2 = min(crop_img.shape[0], py2 - oy)
            if cx2 > cx1 and cy2 > cy1:
                cv2.rectangle(crop_img, (cx1, cy1), (cx2, cy2), (0, 220, 255), 1)
                cv2.putText(crop_img, "Plate",
                            (cx1, max(cy1 - 4, 36)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 220, 255), 1, cv2.LINE_AA)



        # Save
        fname = f"violation_{frame_id}_{uuid.uuid4().hex[:8]}.jpg"
        fpath = RESULTS_DIR / fname
        cv2.imwrite(str(fpath), crop_img, [cv2.IMWRITE_JPEG_QUALITY, 92])

        vio_entry = {
            "violation_types": vio_types,
            "crop_path":       f"static/results/{fname}",
            "bbox_moto":       mb,
            "confidence":      round(conf_score, 3),
            "frame_id":        frame_id,
        }
        # Only include license_plate if real text was extracted
        if plate_text:
            vio_entry["license_plate"] = plate_text

        violations.append(vio_entry)

    return violations


def _dedup_boxes(items: list, iou_thresh: float = 0.5) -> list:
    """Remove near-duplicate boxes (NMS-style) keeping highest confidence."""
    if not items:
        return []
    items = sorted(items, key=lambda x: x["conf"], reverse=True)
    kept = []
    for item in items:
        if not any(_iou(item["box"], k["box"]) > iou_thresh for k in kept):
            kept.append(item)
    return kept
