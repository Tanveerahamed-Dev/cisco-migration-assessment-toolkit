"""SQLite persistence for AssessHub.

A *campaign* is a migration project (a fleet over time); a *snapshot* is one collection (one
wave / cutover checkpoint) stored as the raw engine snapshot JSON plus a cached headline summary.
The full snapshot is the source of truth; the summary is a derived cache for fast dashboards.
stdlib only (sqlite3) — no extra runtime dependency.

``boot_hardening`` (ADR-0004 P3, opt-in — only the production entry ``serve.main`` turns it on):
on a USB stick the store IS the client evidence and the stick gets yanked. A hardened boot proves
the file is sound (``PRAGMA quick_check``) before anything touches it, keeps a rotating
timestamped copy under ``<data>/backups/``, and pins rollback-journal durability. Corruption is
fatal and NON-destructive: :class:`StoreCorruptError` refuses the boot and the corrupt file is
left byte-identical for a human restore (README-FIELD).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import uuid
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


_BACKUP_DIR = "backups"
_BACKUP_PREFIX = "assesshub-"
_BACKUP_KEEP = 3
#: Only files WE wrote may be rotated. The glob `assesshub-*.db` also matches an engineer's own
#: parked copies (`assesshub-pre-cutover.db`) — and because those sort AFTER the digit stamps,
#: a loose glob deletes the fresh backup the instant it is written, silently disabling backups
#: forever, and can delete the engineer's file too. Both were reproduced.
_BACKUP_RE = re.compile(r"^assesshub-\d{8}T\d{6}Z\.db$")
_PARTIAL_SUFFIX = ".partial"
_SNAPSHOT_BINDING_SOURCE = "persisted snapshots.snapshot_json blob"


class StoreCorruptError(RuntimeError):
    """The SQLite store failed its boot integrity check. The file was NOT modified."""


def _our_backups(backups: Path) -> List[Path]:
    """Backups this code created, oldest first — never the engineer's own parked copies."""
    return sorted((p for p in backups.glob(f"{_BACKUP_PREFIX}*.db") if _BACKUP_RE.match(p.name)),
                  key=lambda p: p.name)


class Store:
    """Thin, thread-safe SQLite wrapper. One connection guarded by a lock — fine for a single-process
    dev/demo server; swap for a pool or Postgres if this ever needs real concurrency."""

    def __init__(self, db_path: str | Path, *, boot_hardening: bool = False):
        self.db_path = str(db_path)
        dbfile = Path(self.db_path)
        dbfile.parent.mkdir(parents=True, exist_ok=True)
        # mtime BEFORE we connect: it decides backup freshness, and opening may recover a journal.
        db_mtime = dbfile.stat().st_mtime if dbfile.is_file() else None
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if boot_hardening:
            self._boot_hardening(dbfile, db_mtime)  # BEFORE the schema touches a corrupt file
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def _boot_hardening(self, dbfile: Path, db_mtime: float | None) -> None:
        """Unplug-safety (ADR-0004 P3): integrity-check, back up, pin durability.

        Corruption refuses the boot and leaves the file byte-identical — it is client evidence;
        restore is the human's call (README-FIELD, 'Corruption'). A failed BACKUP only warns:
        a rotation hiccup must not strand the engineer mid-engagement, and because it reprints
        every boot the degradation is never silent."""
        backups = dbfile.parent / _BACKUP_DIR
        try:
            rows = self._conn.execute("PRAGMA quick_check").fetchall()
            ok = len(rows) == 1 and rows[0][0] == "ok"
            detail = "" if ok else "; ".join(str(r[0]) for r in rows[:3])
        except sqlite3.OperationalError as e:
            # NOT corruption: "database is locked" (a second Atlas instance) and transient I/O
            # errors raise OperationalError, which subclasses DatabaseError. Calling that
            # corruption told the engineer to overwrite a HEALTHY store holding the newest
            # evidence with an older backup — the worst advice this program can give.
            print(f"[warn] could not verify the store ({e}) — is Atlas already running? "
                  f"Continuing WITHOUT unplug protection this session.", file=sys.stderr)
            return
        except sqlite3.DatabaseError as e:  # not even a database (torn/overwritten header)
            ok, detail = False, str(e)
        if not ok:
            self._conn.close()
            raise StoreCorruptError(
                f"integrity check failed for {dbfile}: {detail}\n"
                f"  The file was left untouched. To restore: close Atlas, copy the newest "
                f"backup from {backups} over it, start again, run --selftest."
            )
        # DELETE + FULL are SQLite's defaults — pinned so nobody "optimizes" to WAL: an orphaned
        # -wal file after a stick yank on exFAT silently loses committed transactions, while a
        # rollback journal recovers on the next open.
        self._conn.execute("PRAGMA journal_mode = DELETE")
        self._conn.execute("PRAGMA synchronous = FULL")
        if db_mtime is None:
            return  # first boot: an empty store is not evidence worth copying

        # INVARIANT: an EMPTY store never displaces backups that hold evidence. A 0-byte file is a
        # *valid empty* SQLite database (quick_check says "ok"), and the schema is recreated on the
        # next boot — so a truncated store looks perfectly healthy and, backed up three times,
        # rotates the real evidence off the stick. That destroys exactly what this feature exists
        # to protect, and it was reproduced end-to-end before this guard existed.
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM campaigns").fetchone()  # table may not exist yet
            n_campaigns = row[0] if row else 0
        except sqlite3.DatabaseError:
            n_campaigns = 0
        if n_campaigns == 0 and _our_backups(backups):
            print(f"[warn] {dbfile} holds NO campaigns while backups in {backups} do — it looks "
                  f"TRUNCATED or replaced. Not backing it up, so those backups survive. If this "
                  f"is unexpected, stop now and restore before continuing "
                  f"(README-FIELD.txt, 'Corruption').", file=sys.stderr)
            return

        try:
            backups.mkdir(parents=True, exist_ok=True)
            have = _our_backups(backups)
            newest = max((b.stat().st_mtime for b in have), default=None)
            if newest is not None and newest >= db_mtime:
                # Unchanged since the last copy — don't churn the stick. Clock skew (FAT32 stores
                # LOCAL time; a stick written on another offset reads "in the future") would
                # otherwise suppress every future backup in silence, so say so once.
                if newest > db_mtime + 60:
                    print(f"[warn] newest backup is dated AFTER the store "
                          f"({int(newest - db_mtime)}s) — clock skew or a stale file in {backups}. "
                          f"Backups stay suppressed until the store is newer.", file=sys.stderr)
                return
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            final = backups / f"{_BACKUP_PREFIX}{stamp}.db"
            # Write to a partial name and rename only on success: a backup killed by a yank or a
            # full stick must never be mistaken for a good one (an empty stub also passes
            # quick_check), nor occupy a keep-slot.
            # The partial name is process-owned and unguessable. A fixed timestamp name lets a
            # concurrent boot share (and then delete) another process's in-progress backup.
            tmp = backups / (
                f"{_BACKUP_PREFIX}{stamp}-{os.getpid()}-{uuid.uuid4().hex}"
                f".db{_PARTIAL_SUFFIX}"
            )
            try:
                dest = sqlite3.connect(str(tmp))
                try:
                    self._conn.backup(dest)
                finally:
                    dest.close()
                os.replace(tmp, final)
            finally:
                tmp.unlink(missing_ok=True)  # no-op once renamed
        except (OSError, sqlite3.Error) as e:
            print(f"[warn] boot backup failed ({e}) — unplug protection degraded this session",
                  file=sys.stderr)
        # Rotate only completed files that match our exact timestamp pattern. Unknown ``.partial``
        # files are not ours to delete: another Atlas process may still be writing one, and an
        # engineer may have deliberately parked a file under that broad glob.
        try:
            for old in _our_backups(backups)[:-_BACKUP_KEEP]:
                old.unlink(missing_ok=True)
        except OSError as e:
            print(f"[warn] backup rotation failed ({e})", file=sys.stderr)

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

    def update_summary(self, snapshot_id: int, summary: Dict[str, Any]) -> bool:
        """Refresh ONLY the cached headline summary (the snapshot_json stays immutable). Used to
        self-heal a summary frozen by an older engine schema than the one now serving live sections
        (see app._summary_freshened). False when the row no longer exists."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE snapshots SET summary_json = ? WHERE id = ?",
                (json.dumps(summary, separators=(",", ":")), snapshot_id))
            self._conn.commit()
            return cur.rowcount > 0

    def get_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        """Full raw snapshot dict (or None)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT snapshot_json FROM snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
        return json.loads(row["snapshot_json"]) if row else None

    def get_bound_snapshot(
            self, snapshot_id: int) -> Optional[tuple[Dict[str, Any], Dict[str, str]]]:
        """Read one snapshot and bind its parsed object to the exact persisted JSON bytes.

        Original upload/archive bytes are not retained. The authoritative webapp compare/trend
        input is therefore the blob in ``snapshots.snapshot_json``. Both parsing and SHA-256 consume
        the same byte sequence from this single database read.
        """
        with self._lock:
            row = self._conn.execute(
                """SELECT CAST(snapshot_json AS BLOB) AS snapshot_blob
                   FROM snapshots WHERE id = ?""", (snapshot_id,)
            ).fetchone()
        if row is None:
            return None
        raw = row["snapshot_blob"]
        if isinstance(raw, memoryview):
            raw = raw.tobytes()
        elif isinstance(raw, str):
            raw = raw.encode("utf-8")
        elif not isinstance(raw, bytes):
            raw = bytes(raw)
        return (
            json.loads(raw),
            {
                "source": _SNAPSHOT_BINDING_SOURCE,
                "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            },
        )

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
    def create_execution(self, snapshot_id: int, state: Dict[str, Any],
                         *, auto_label: bool = False) -> int:
        with self._lock:
            try:
                # Serialize label selection + insert across independent Store instances/processes.
                self._conn.execute("BEGIN IMMEDIATE")
                if auto_label:
                    labels = self._conn.execute(
                        "SELECT label FROM executions WHERE snapshot_id=?", (snapshot_id,)
                    ).fetchall()
                    used = {
                        int(match.group(1))
                        for row in labels
                        if (match := re.fullmatch(r"Cutover run ([1-9]\d*)", str(row["label"])))
                    }
                    ordinal = max(used, default=0) + 1
                    state["label"] = f"Cutover run {ordinal}"
                cur = self._conn.execute(
                    """INSERT INTO executions(snapshot_id, label, status, started_at, ended_at, state_json)
                       VALUES (?,?,?,?,?,?)""",
                    (snapshot_id, state.get("label", ""), state.get("status", "in_progress"),
                     state.get("started_at", _now()), state.get("ended_at"),
                     json.dumps(state, separators=(",", ":"))),
                )
                execution_id = int(cur.lastrowid or 0)
                self._conn.commit()
                return execution_id
            except Exception:
                self._conn.rollback()
                raise

    def get_execution(self, execution_id: int) -> Optional[Dict[str, Any]]:
        """{'id', 'snapshot_id', 'state'} or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, snapshot_id, state_json FROM executions WHERE id = ?", (execution_id,)
            ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "snapshot_id": row["snapshot_id"],
                "state": json.loads(row["state_json"]), "_state_json": row["state_json"]}

    def save_execution_if_unchanged(self, execution_id: int, expected_state_json: str,
                                    state: Dict[str, Any]) -> str:
        """Atomic cross-process compare-and-swap: ``saved``, ``conflict``, or ``missing``."""
        encoded = json.dumps(state, separators=(",", ":"))
        with self._lock:
            cur = self._conn.execute(
                """UPDATE executions SET label=?, status=?, ended_at=?, state_json=?
                   WHERE id=? AND state_json=?""",
                (state.get("label", ""), state.get("status", "in_progress"),
                 state.get("ended_at"), encoded, execution_id, expected_state_json),
            )
            self._conn.commit()
            if cur.rowcount > 0:
                return "saved"
            exists = self._conn.execute(
                "SELECT 1 FROM executions WHERE id=?", (execution_id,)
            ).fetchone()
            return "conflict" if exists else "missing"

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
