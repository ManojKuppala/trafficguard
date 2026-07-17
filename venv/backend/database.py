"""
database.py  –  SQLite database layer for TrafficGuard AI
Provides schema creation, insert, and query helpers for challan records.
"""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent.resolve() / "trafficguard.db"

# ──────────────────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────────────────
_CREATE_CHALLANS = """
CREATE TABLE IF NOT EXISTS challans (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    source      TEXT NOT NULL,
    total_fine  INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_VIOLATIONS = """
CREATE TABLE IF NOT EXISTS violations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    challan_id      TEXT    NOT NULL,
    violation_types TEXT    NOT NULL,
    fine_inr        INTEGER NOT NULL DEFAULT 0,
    fine_breakdown  TEXT    NOT NULL DEFAULT '{}',
    evidence        TEXT    NOT NULL DEFAULT '',
    license_plate   TEXT,
    FOREIGN KEY (challan_id) REFERENCES challans(id)
);
"""


def _get_conn() -> sqlite3.Connection:
    """Return a new connection with row-factory enabled."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# ──────────────────────────────────────────────────────────────────────────────
# Initialisation
# ──────────────────────────────────────────────────────────────────────────────
def init_db():
    """Create tables if they don't already exist."""
    conn = _get_conn()
    conn.execute(_CREATE_CHALLANS)
    conn.execute(_CREATE_VIOLATIONS)
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Insert
# ──────────────────────────────────────────────────────────────────────────────
def insert_challan(record_id: str, timestamp: str, source: str,
                   total_fine: int, violations: list[dict]):
    """
    Insert a challan and its violations in a single transaction.
    `violations` is a list of dicts, each with keys:
        violation_types, fine_INR, fine_breakdown, evidence, license_plate (optional)
    """
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO challans (id, timestamp, source, total_fine) VALUES (?, ?, ?, ?)",
            (record_id, timestamp, source, total_fine),
        )
        for v in violations:
            conn.execute(
                """INSERT INTO violations
                   (challan_id, violation_types, fine_inr, fine_breakdown, evidence, license_plate)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    record_id,
                    ",".join(v["violation_types"]),
                    v["fine_INR"],
                    json.dumps(v["fine_breakdown"]),
                    v.get("evidence", ""),
                    v.get("license_plate"),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Queries
# ──────────────────────────────────────────────────────────────────────────────
def get_all_challans() -> list[dict]:
    """Return every challan with its nested violations list."""
    conn = _get_conn()
    challans = conn.execute(
        "SELECT * FROM challans ORDER BY timestamp DESC"
    ).fetchall()

    result = []
    for c in challans:
        viols = conn.execute(
            "SELECT * FROM violations WHERE challan_id = ?", (c["id"],)
        ).fetchall()
        
        # Build violations list with error handling for corrupted data
        violations_list = []
        for v in viols:
            try:
                # Safely parse violation_types (handle NULL or malformed data)
                violation_types = v["violation_types"].split(",") if v["violation_types"] else []
                
                # Safely parse fine_breakdown JSON (handle invalid JSON)
                try:
                    fine_breakdown = json.loads(v["fine_breakdown"]) if v["fine_breakdown"] else {}
                except (json.JSONDecodeError, TypeError):
                    fine_breakdown = {}
                
                violations_list.append({
                    "violation_types": violation_types,
                    "fine_INR":        v["fine_inr"],
                    "fine_breakdown":  fine_breakdown,
                    "evidence":        v["evidence"],
                    "license_plate":   v["license_plate"],
                })
            except Exception as e:
                # Log corruption but continue processing other violations
                print(f"[Warning] Corrupted violation record for challan {c['id']}: {e}")
                continue
        
        result.append({
            "id":         c["id"],
            "timestamp":  c["timestamp"],
            "source":     c["source"],
            "total_fine": c["total_fine"],
            "violations": violations_list,
        })
    conn.close()
    return result


def get_challan_by_id(record_id: str) -> dict | None:
    """Return a single challan or None."""
    conn = _get_conn()
    c = conn.execute("SELECT * FROM challans WHERE id = ?", (record_id,)).fetchone()
    if c is None:
        conn.close()
        return None

    viols = conn.execute(
        "SELECT * FROM violations WHERE challan_id = ?", (record_id,)
    ).fetchall()
    conn.close()

    # Build violations list with error handling for corrupted data
    violations_list = []
    for v in viols:
        try:
            # Safely parse violation_types (handle NULL or malformed data)
            violation_types = v["violation_types"].split(",") if v["violation_types"] else []
            
            # Safely parse fine_breakdown JSON (handle invalid JSON)
            try:
                fine_breakdown = json.loads(v["fine_breakdown"]) if v["fine_breakdown"] else {}
            except (json.JSONDecodeError, TypeError):
                fine_breakdown = {}
            
            violations_list.append({
                "violation_types": violation_types,
                "fine_INR":        v["fine_inr"],
                "fine_breakdown":  fine_breakdown,
                "evidence":        v["evidence"],
                "license_plate":   v["license_plate"],
            })
        except Exception as e:
            # Log corruption but continue processing other violations
            print(f"[Warning] Corrupted violation record for challan {record_id}: {e}")
            continue

    return {
        "id":         c["id"],
        "timestamp":  c["timestamp"],
        "source":     c["source"],
        "total_fine": c["total_fine"],
        "violations": violations_list,
    }
