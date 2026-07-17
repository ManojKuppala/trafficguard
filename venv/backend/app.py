import os, sys, json, uuid, threading, time
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
import cv2

# Make sure imports resolve from the backend directory
BASE_DIR = Path(__file__).parent.resolve()
FRONTEND_DIR = BASE_DIR.parent / "frontend"
sys.path.insert(0, str(BASE_DIR))

from detector import detect_violations, _validate_models
from challan  import generate_challan
from database import init_db, get_all_challans

app = Flask(
    __name__,
    template_folder=str(FRONTEND_DIR / "templates"),
    static_folder=str(FRONTEND_DIR / "static"),
)
CORS(app)

# Validate models at startup
try:
    _validate_models()
    print("[✓] All model files validated successfully")
except FileNotFoundError as e:
    print(f"[✗] Model validation failed: {e}")
    raise

# SQLite initialization
init_db()   # create tables if they don't exist

UPLOAD_DIR  = FRONTEND_DIR / "static" / "uploads"
RESULTS_DIR = FRONTEND_DIR / "static" / "results"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
ALLOWED_VIDEO = {".mp4", ".avi", ".mov", ".mkv", ".webm"}

# in-memory job store with threading protection
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()  # Protect concurrent access to jobs dict


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────
def _detect_motorcycles_in_frame(frame) -> bool:
    """Check if any motorcycles are detected in the frame. Used to distinguish 'no motorcycles' vs 'no violations'."""
    from detector import _run_yolo_inference, _parse_detections
    try:
        moto_res = _run_yolo_inference("motorcycle", frame, conf=0.30, verbose=False)
        motos, _, _, _, _, _ = _parse_detections(moto_res, 0.30)
        return len(motos) > 0
    except Exception:
        return False  # If detection fails, assume no motorcycles

def _process_image(job_id: str, filepath: Path):
    try:
        with jobs_lock:
            jobs[job_id]["status"] = "processing"
        frame = cv2.imread(str(filepath))
        if frame is None:
            raise ValueError("Could not read image")

        violations = detect_violations(frame, frame_id=0)
        motorcycles_detected = _detect_motorcycles_in_frame(frame)
        challan    = generate_challan(violations, filepath.name) if violations else None
        _finish_job(job_id, violations, challan, filepath.name, motorcycles_detected)
    except Exception as e:
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"]  = str(e)


def _process_video(job_id: str, filepath: Path):
    try:
        with jobs_lock:
            jobs[job_id]["status"] = "processing"
        cap = cv2.VideoCapture(str(filepath))
        if not cap.isOpened():
            raise ValueError("Could not open video")

        fps       = cap.get(cv2.CAP_PROP_FPS) or 25
        total     = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # sample every N frames to keep speed reasonable
        sample_every = max(1, int(fps * 1.5))   # ~every 1.5 seconds

        all_violations = []
        motorcycles_detected_anywhere = False
        frame_idx    = 0
        processed    = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % sample_every == 0:
                viols = detect_violations(frame, frame_id=frame_idx)
                all_violations.extend(viols)
                
                # Check if ANY frame has motorcycles
                if not motorcycles_detected_anywhere and _detect_motorcycles_in_frame(frame):
                    motorcycles_detected_anywhere = True
                    
                processed += 1
                with jobs_lock:
                    jobs[job_id]["progress"] = min(99, int((frame_idx / max(1, total)) * 100))
            frame_idx += 1

        cap.release()

        # ── Deduplication: one entry per physical motorcycle ──────────────────
        # Group by license plate. For "UNREADABLE" plates, further cluster
        # by motorcycle bounding box overlap to avoid merging different bikes.
        def _boxes_similar(b1, b2, thresh=0.4):
            """True if two motorcycle bboxes likely belong to the same vehicle."""
            xs = max(b1[0], b2[0]); ys = max(b1[1], b2[1])
            xe = min(b1[2], b2[2]); ye = min(b1[3], b2[3])
            inter = max(0, xe-xs) * max(0, ye-ys)
            a1 = max(1, (b1[2]-b1[0])*(b1[3]-b1[1]))
            a2 = max(1, (b2[2]-b2[0])*(b2[3]-b2[1]))
            return inter / min(a1, a2) > thresh

        merged: list[dict] = []
        for v in all_violations:
            plate = v.get("license_plate")  # may be absent if OCR found nothing
            matched = None
            for m in merged:
                m_plate    = m.get("license_plate")
                same_plate = (plate and m_plate and plate == m_plate)
                close_box  = _boxes_similar(v["bbox_moto"], m["bbox_moto"])
                if same_plate or close_box:
                    matched = m
                    break
            if matched:
                for vt in v["violation_types"]:
                    if vt not in matched["violation_types"]:
                        matched["violation_types"].append(vt)
                if v["confidence"] > matched["confidence"]:
                    matched["confidence"] = v["confidence"]
                    matched["crop_path"]  = v["crop_path"]
                    matched["frame_id"]   = v["frame_id"]
                # Prefer real plate reading over nothing
                if not matched.get("license_plate") and v.get("license_plate"):
                    matched["license_plate"] = v["license_plate"]
            else:
                merged.append(dict(v))

        challan = generate_challan(merged, filepath.name) if merged else None
        _finish_job(job_id, merged, challan, filepath.name, motorcycles_detected_anywhere)
    except Exception as e:
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"]  = str(e)


def _finish_job(job_id: str, violations: list, challan: dict | None, source: str, motorcycles_detected: bool = False):
    # Build per-violation-type best images (top-3 overall if needed)
    type_map: dict[str, list] = {}
    for v in violations:
        for vtype in v["violation_types"]:
            type_map.setdefault(vtype, []).append(v)

    # Sort each group by confidence
    for vtype in type_map:
        type_map[vtype].sort(key=lambda x: x["confidence"], reverse=True)

    # Determine result message
    if not motorcycles_detected:
        result_message = "no motorcycle"
    elif not violations:
        result_message = "No violations detected"
    else:
        result_message = "Violations detected"

    with jobs_lock:
        jobs[job_id].update({
            "status":          "done",
            "progress":        100,
            "violations":      violations,
            "type_summary":    {k: len(v) for k, v in type_map.items()},
            "challan":         challan,
            "source":          source,
            "result_message":  result_message,
            "motorcycles_detected": motorcycles_detected,
            "total_violations": len(violations),
        })


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f    = request.files["file"]
    ext  = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE | ALLOWED_VIDEO:
        return jsonify({"error": "Unsupported file type"}), 400

    job_id   = uuid.uuid4().hex
    filename = f"{job_id}{ext}"
    savepath = UPLOAD_DIR / filename
    f.save(str(savepath))

    with jobs_lock:
        jobs[job_id] = {"status": "queued", "progress": 0}

    if ext in ALLOWED_IMAGE:
        t = threading.Thread(target=_process_image, args=(job_id, savepath), daemon=True)
    else:
        t = threading.Thread(target=_process_video, args=(job_id, savepath), daemon=True)
    t.start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job"}), 404
    return jsonify(job)


@app.route("/challans")
def challans_history():
    """Return all stored e-challans from the database."""
    records = get_all_challans()
    return jsonify({"total_entries": len(records), "records": records})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
