"""SQLite persistence for AssessHub.

A *campaign* is a migration project (a fleet over time); a *snapshot* is one collection (one
wave / cutover checkpoint) stored as the raw engine snapshot JSON plus a cached headline summary.
The full snapshot is the source of truth; the summary is a derived cache for fast dashboards.
stdlib only (sqlite3) — no extra runtime dependency.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id    INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    label          TEXT NOT NULL,
    uploaded_at    TEXT NOT NULL,
    script_version TEXT NOT NULL DEFAULT '',
    n_devices      INTEGER NOT NULL DEFAULT 0,
    summary_json   TEXT NOT NULL DEFAULT '{}',
    snapshot_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_snapshots_campaign ON snapshots(campaign_id, uploaded_at);
CREATE TABLE IF NOT EXISTS executions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'in_progress',
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    state_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_executions_snapshot ON executions(snapshot_id, started_at);
CREATE TABLE IF NOT EXISTS gates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    wave        TEXT NOT NULL,
    gate        TEXT NOT NULL,
    decision    TEXT NOT NULL,
    signed_by   TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    decided_at  TEXT NOT NULL,
    UNIQUE(campaign_id, wave, gate)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """Thin, thread-safe SQLite wrapper. One connection guarded by a lock — fine for a single-process
    dev/demo server; swap for a pool or Postgres if this ever needs real concurrency."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- campaigns ---------------------------------------------------------
    def create_campaign(self, name: str, description: str = "") -> Dict[str, Any]:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO campaigns(name, description, created_at) VALUES (?,?,?)",
                (name.strip() or "Untitled campaign", description.strip(), _now()),
            )
            self._conn.commit()
            cid = cur.lastrowid
        return self.get_campaign(cid)  # type: ignore[return-value]

    def list_campaigns(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT c.*,
                          COUNT(s.id)            AS n_snapshots,
                          MAX(s.uploaded_at)     AS last_upload
                   FROM campaigns c LEFT JOIN snapshots s ON s.campaign_id = c.id
                   GROUP BY c.id ORDER BY c.created_at DESC"""
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            latest = self._latest_summary(d["id"])
            d["latest_summary"] = latest
            out.append(d)
        return out

    def get_campaign(self, campaign_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["snapshots"] = self.list_snapshots(campaign_id)
        return d

    def delete_campaign(self, campaign_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # -- snapshots ---------------------------------------------------------
    def add_snapshot(self, campaign_id: int, label: str, snapshot: Dict[str, Any],
                     summary: Dict[str, Any]) -> Dict[str, Any]:
        # SSOT: the canonical inventoried count (executive_brief.scale.n_devices), falling back to
        # len(devices) ONLY when the canonical field is ABSENT. isinstance-guarded so a truthy non-dict
        # executive_brief/scale on a malformed upload degrades instead of raising AttributeError (-> a 500
        # on every upload). `is not None` (NOT `or`) so a legitimate canonical 0 is recorded as 0, not
        # silently replaced by the len() recount (the project's `or`-masks-zero bug class).
        _eb = snapshot.get("executive_brief")
        _scale = _eb.get("scale") if isinstance(_eb, dict) else None
        _n = _scale.get("n_devices") if isinstance(_scale, dict) else None
        if _n is None:
            _dev = snapshot.get("devices")
            _n = len(_dev) if isinstance(_dev, (dict, list)) else 0
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO snapshots(campaign_id, label, uploaded_at, script_version,
                                         n_devices, summary_json, snapshot_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (campaign_id, label.strip() or "snapshot", _now(),
                 str(snapshot.get("script_version", "")),
                 _n,
                 json.dumps(summary, separators=(",", ":")),
                 json.dumps(snapshot, separators=(",", ":"))),
            )
            self._conn.commit()
            sid = cur.lastrowid
        return self.get_snapshot_meta(sid)  # type: ignore[return-value]

    def list_snapshots(self, campaign_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, campaign_id, label, uploaded_at, script_version, n_devices, summary_json
                   FROM snapshots WHERE campaign_id = ? ORDER BY uploaded_at ASC, id ASC""",
                (campaign_id,),
            ).fetchall()
        return [self._meta_row(r) for r in rows]

    def get_snapshot_meta(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """SELECT id, campaign_id, label, uploaded_at, script_version, n_devices, summary_json
                   FROM snapshots WHERE id = ?""", (snapshot_id,)
            ).fetchone()
        return self._meta_row(row) if row else None

    def get_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        """Full raw snapshot dict (or None)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT snapshot_json FROM snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
        return json.loads(row["snapshot_json"]) if row else None

    def get_snapshot_section(self, snapshot_id: int, key: str) -> Any:
        """One top-level section of a snapshot WITHOUT deserializing the whole multi-MB blob —
        sqlite's json_extract parses in C and returns just the subtree (V3.23.159: the gate board
        reads this per fetch). Callers pass a literal section name, never user input -- but the JSON
        path is BOUND as a parameter (not f-string-interpolated) so a future caller that forwards a
        request value cannot break out of the string literal into SQL (audit-6 sec: closes a latent
        SQL-injection sink; a hostile `key` is now confined to json_extract's path language, which
        cannot reach another table). Falls back to the full parse on a sqlite built without JSON1."""
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT json_extract(snapshot_json, ?) AS sect "
                    "FROM snapshots WHERE id = ?", ("$." + key, snapshot_id)).fetchone()
        except sqlite3.OperationalError:
            snap = self.get_snapshot(snapshot_id)
            return (snap or {}).get(key)
        if row is None or row["sect"] is None:
            return None
        sect = row["sect"]
        # json_extract returns a JSON *object/array* as an encoded string, but a JSON SCALAR (string/number/
        # bool) is returned as the native Python value -- json.loads(int) raises TypeError and json.loads(a bare
        # string) raises JSONDecodeError, neither caught above, so a section that is a scalar in a malformed
        # upload (e.g. {"design_blueprint": 5}) 500'd. Only decode an encoded str; return a native scalar as-is.
        if not isinstance(sect, (str, bytes, bytearray)):
            return sect
        try:
            return json.loads(sect)
        except (json.JSONDecodeError, ValueError):
            return sect   # a bare scalar string -> hand back the raw value; callers isinstance-check it

    def campaign_exists(self, campaign_id: int) -> bool:
        """Existence check without parsing every snapshot summary (V3.23.159: get_campaign was
        being used as a boolean on the gate-board hot path)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        return row is not None

    def latest_snapshot_id(self, campaign_id: int) -> Optional[int]:
        with self._lock:
            row = self._conn.execute(
                """SELECT id FROM snapshots WHERE campaign_id = ?
                   ORDER BY uploaded_at DESC, id DESC LIMIT 1""", (campaign_id,)).fetchone()
        return int(row["id"]) if row else None

    def delete_snapshot(self, snapshot_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # -- executions ----------------------------------------------------------
    # A live cutover-execution run (war room) over one snapshot's plan. The state blob is the source
    # of truth; label/status/timestamps are mirrored into columns for cheap listing.
    def create_execution(self, snapshot_id: int, state: Dict[str, Any]) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO executions(snapshot_id, label, status, started_at, ended_at, state_json)
                   VALUES (?,?,?,?,?,?)""",
                (snapshot_id, state.get("label", ""), state.get("status", "in_progress"),
                 state.get("started_at", _now()), state.get("ended_at"),
                 json.dumps(state, separators=(",", ":"))),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def get_execution(self, execution_id: int) -> Optional[Dict[str, Any]]:
        """{'id', 'snapshot_id', 'state'} or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, snapshot_id, state_json FROM executions WHERE id = ?", (execution_id,)
            ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "snapshot_id": row["snapshot_id"],
                "state": json.loads(row["state_json"])}

    def save_execution(self, execution_id: int, state: Dict[str, Any]) -> bool:
        """False when the row no longer exists (deleted mid-flight) — a silent 0-row UPDATE would
        let a mutation report success for state that was never persisted."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE executions SET label=?, status=?, ended_at=?, state_json=? WHERE id=?",
                (state.get("label", ""), state.get("status", "in_progress"),
                 state.get("ended_at"), json.dumps(state, separators=(",", ":")), execution_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def count_executions(self, snapshot_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM executions WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
        return int(row["n"]) if row else 0

    def list_executions(self, snapshot_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, snapshot_id, label, status, started_at, ended_at
                   FROM executions WHERE snapshot_id = ? ORDER BY started_at DESC, id DESC""",
                (snapshot_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_execution(self, execution_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM executions WHERE id = ?", (execution_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # -- gates ---------------------------------------------------------------
    # Per-(wave, gate) sign-off dispositions for a campaign's T-minus calendar. An absent row IS
    # the 'pending' state — clearing a decision deletes the row, so the table only ever holds
    # decisions someone actually made (and the engagement plan of record only renders real state).
    def upsert_gate(self, campaign_id: int, wave: str, gate: str, decision: str,
                    signed_by: str = "", note: str = "") -> None:
        # V3.23.159: no read-back — the route answers with list_gates, so the old SELECT-after-
        # INSERT was a dead query held under the lock on every sign-off click.
        with self._lock:
            self._conn.execute(
                """INSERT INTO gates(campaign_id, wave, gate, decision, signed_by, note, decided_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(campaign_id, wave, gate) DO UPDATE SET
                       decision=excluded.decision, signed_by=excluded.signed_by,
                       note=excluded.note, decided_at=excluded.decided_at""",
                (campaign_id, wave, gate, decision, signed_by.strip(), note.strip(), _now()),
            )
            self._conn.commit()

    def clear_gate(self, campaign_id: int, wave: str, gate: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM gates WHERE campaign_id=? AND wave=? AND gate=?",
                (campaign_id, wave, gate))
            self._conn.commit()
            return cur.rowcount > 0

    def list_gates(self, campaign_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT wave, gate, decision, signed_by, note, decided_at
                   FROM gates WHERE campaign_id = ? ORDER BY wave ASC, gate ASC""",
                (campaign_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- helpers -----------------------------------------------------------
    def _meta_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        d["summary"] = json.loads(d.pop("summary_json") or "{}")
        return d

    def _latest_summary(self, campaign_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """SELECT summary_json FROM snapshots WHERE campaign_id = ?
                   ORDER BY uploaded_at DESC, id DESC LIMIT 1""", (campaign_id,)
            ).fetchone()
        return json.loads(row["summary_json"]) if row else None
