"""
challan.py  –  Generate e-challans and store them in the SQLite database.
"""
import uuid
from datetime import datetime

from database import insert_challan

FINE_TABLE = {
    "Helmet Violation": 1000,
    "Triple Riding":    2000,
    "Mobile Usage":     1500,
}


def generate_challan(violations: list[dict], source_file: str) -> dict:
    """
    Build violation records, persist them to the database, and return
    a summary dict for the frontend.
    """
    record_id = f"ECHL-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:5].upper()}"
    timestamp = datetime.now().isoformat(timespec="seconds")

    # Build clean violation list
    vio_records = []
    grand_total = 0
    for v in violations:
        fine = sum(FINE_TABLE.get(vt, 0) for vt in v["violation_types"])
        grand_total += fine
        entry = {
            "violation_types": v["violation_types"],
            "fine_INR":        fine,
            "fine_breakdown":  {vt: FINE_TABLE.get(vt, 0) for vt in v["violation_types"]},
            "evidence":        v.get("crop_path", ""),
        }
        if v.get("license_plate"):
            entry["license_plate"] = v["license_plate"]
        vio_records.append(entry)

    # ── Persist to SQLite ────────────────────────────────────────────────────
    insert_challan(
        record_id=record_id,
        timestamp=timestamp,
        source=source_file,
        total_fine=grand_total,
        violations=vio_records,
    )

    return {
        "challan_id":       record_id,
        "total_fines":      grand_total,
        "violations_count": len(violations),
    }
