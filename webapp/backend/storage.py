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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_identities (
    campaign_id   INTEGER PRIMARY KEY REFERENCES campaigns(id) ON DELETE CASCADE,
    engagement_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_campaign_identity_engagement
    ON campaign_identities(engagement_id);
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
CREATE TABLE IF NOT EXISTS execution_comparisons (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id       INTEGER NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    before_snapshot_id INTEGER NOT NULL,
    after_snapshot_id  INTEGER NOT NULL,
    receipt_sha256     TEXT NOT NULL,
    cutover_verdict    TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    receipt_json       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_execution_comparisons_latest
    ON execution_comparisons(execution_id, id);
CREATE TRIGGER IF NOT EXISTS execution_comparisons_no_update
BEFORE UPDATE ON execution_comparisons
BEGIN
    SELECT RAISE(ABORT, 'execution comparison receipts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparisons_no_delete
BEFORE DELETE ON execution_comparisons
BEGIN
    SELECT RAISE(ABORT, 'execution comparison receipts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_sources_no_delete
BEFORE DELETE ON snapshots
WHEN EXISTS (
    SELECT 1 FROM execution_comparisons ec
    WHERE ec.before_snapshot_id = OLD.id OR ec.after_snapshot_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'execution comparison source snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_sources_no_rebind
BEFORE UPDATE OF id, campaign_id, label, uploaded_at, script_version, snapshot_json ON snapshots
WHEN EXISTS (
    SELECT 1 FROM execution_comparisons ec
    WHERE ec.before_snapshot_id = OLD.id OR ec.after_snapshot_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'execution comparison source snapshot bindings are immutable');
END;
-- Companion trigger upgrades stores which already created the earlier no_rebind definition.
-- CREATE TRIGGER IF NOT EXISTS cannot replace that definition in place, and uploaded_at is part
-- of the chronology admission used by an immutable execution comparison receipt.
CREATE TRIGGER IF NOT EXISTS execution_comparison_source_chronology_no_rebind
BEFORE UPDATE OF uploaded_at ON snapshots
WHEN EXISTS (
    SELECT 1 FROM execution_comparisons ec
    WHERE ec.before_snapshot_id = OLD.id OR ec.after_snapshot_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'execution comparison source snapshot chronology is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_sources_no_replace
BEFORE INSERT ON snapshots
WHEN EXISTS (
    SELECT 1 FROM execution_comparisons ec
    WHERE ec.before_snapshot_id = NEW.id OR ec.after_snapshot_id = NEW.id
)
BEGIN
    -- SQLite's REPLACE conflict handler can delete a row without running DELETE triggers when
    -- recursive_triggers is disabled (the default). Refuse insertion over a receipt-bound id too.
    SELECT RAISE(ABORT, 'execution comparison source snapshot bindings are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_engagement_no_delete
BEFORE DELETE ON campaign_identities
WHEN EXISTS (
    SELECT 1 FROM snapshots s
    JOIN execution_comparisons ec
      ON ec.before_snapshot_id = s.id OR ec.after_snapshot_id = s.id
    WHERE s.campaign_id = OLD.campaign_id
)
BEGIN
    SELECT RAISE(ABORT, 'execution comparison engagement bindings are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_engagement_no_rebind
BEFORE UPDATE OF campaign_id, engagement_id ON campaign_identities
WHEN EXISTS (
    SELECT 1 FROM snapshots s
    JOIN execution_comparisons ec
      ON ec.before_snapshot_id = s.id OR ec.after_snapshot_id = s.id
    WHERE s.campaign_id = OLD.campaign_id
)
BEGIN
    SELECT RAISE(ABORT, 'execution comparison engagement bindings are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_engagement_no_replace
BEFORE INSERT ON campaign_identities
WHEN EXISTS (
    SELECT 1 FROM snapshots s
    JOIN execution_comparisons ec
      ON ec.before_snapshot_id = s.id OR ec.after_snapshot_id = s.id
    WHERE s.campaign_id = NEW.campaign_id
)
BEGIN
    SELECT RAISE(ABORT, 'execution comparison engagement bindings are immutable');
END;
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


_NOW_LOCK = threading.Lock()
_LAST_NOW: Optional[datetime] = None


def _now() -> str:
    # Execution evidence ordering is a decision boundary: a snapshot uploaded before a run
    # starts cannot later be relabelled as that run's post-change observation.  Preserve
    # microseconds so ordinary start-then-upload flows have a strict, durable ordering even when
    # both writes occur within the same wall-clock second.
    global _LAST_NOW
    with _NOW_LOCK:
        current = datetime.now(timezone.utc)
        if _LAST_NOW is not None and current <= _LAST_NOW:
            current = _LAST_NOW + timedelta(microseconds=1)
        _LAST_NOW = current
    return current.isoformat(timespec="microseconds")


def _parse_aware_timestamp(value: Any) -> Optional[datetime]:
    """Parse one persisted ISO timestamp, refusing missing/naive/ambiguous values."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _canonical_json_bytes(value: Any) -> bytes:
    """Return the one JSON encoding used for decision-receipt identity checks.

    Comparing parsed Python objects is unsafe at this boundary because Python deliberately treats
    ``False == 0`` and ``1 == 1.0``.  Canonical JSON retains those JSON type distinctions and also
    rejects non-finite numbers, which are outside the receipt contract.
    """
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _canonical_json_identity_matches(left: Any, right: Any) -> bool:
    """Require both canonical bytes and their SHA-256 digest to identify the same JSON value."""
    left_payload = _canonical_json_bytes(left)
    right_payload = _canonical_json_bytes(right)
    return (
        hashlib.sha256(left_payload).digest() == hashlib.sha256(right_payload).digest()
        and left_payload == right_payload
    )


def _canonical_receipt_sha256(value: Any) -> str:
    payload = _canonical_json_bytes(value)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


_SNAPSHOT_BINDING_FIELDS = (
    "source",
    "sha256",
    "bytes",
    "snapshot_id",
    "campaign_id",
    "engagement_id",
    "label",
    "script_version",
)
_COMPARISON_ADDITIVE_FIELDS = frozenset({
    "comparison_schema",
    "comparison_admission",
    "change_intent",
    "protocol_families",
    "precert",
    "cutover_gate",
    "operator_evidence",
    "comparison_receipt",
})


def _snapshot_blob_bytes(value: Any) -> bytes:
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, bytes):
        return value
    return bytes(value)


def _snapshot_binding_from_row(row: sqlite3.Row) -> tuple[bytes, Dict[str, Any]]:
    raw = _snapshot_blob_bytes(row["snapshot_blob"])
    return raw, {
        "source": _SNAPSHOT_BINDING_SOURCE,
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "snapshot_id": int(row["snapshot_id"]),
        "campaign_id": int(row["campaign_id"]),
        "engagement_id": str(row["engagement_id"]),
        "label": str(row["label"]),
        "script_version": str(row["script_version"]),
    }


def _binding_matches(candidate: Any, expected: Dict[str, Any]) -> bool:
    return isinstance(candidate, dict) and all(
        field in candidate
        and type(candidate[field]) is type(expected[field])
        and candidate[field] == expected[field]
        for field in _SNAPSHOT_BINDING_FIELDS
    )


def _comparison_envelope_valid(comparison: Any) -> bool:
    """Verify the detached decision envelope against the complete comparison payload.

    The comparison keeps the legacy delta fields at top level and adds the seven Release-1 fields
    listed above.  Reconstructing that delta here lets persistence reject a rehashed outer wrapper
    whose detached payload or duplicated custody metadata was changed after gate computation.
    """
    if (not isinstance(comparison, dict)
            or comparison.get("comparison_schema") != "source_bound_cutover_comparison/1"):
        return False
    envelope = comparison.get("comparison_receipt")
    admission = comparison.get("comparison_admission")
    if (not isinstance(envelope, dict)
            or envelope.get("schema") != "protocol_receipt_envelope/1"
            or not isinstance(admission, dict)):
        return False
    unsigned = dict(envelope)
    claimed_receipt = unsigned.pop("receipt_sha256", None)
    delta = {
        key: value for key, value in comparison.items()
        if key not in _COMPARISON_ADDITIVE_FIELDS
    }
    payload = {
        "admission": admission,
        "change_intent": comparison.get("change_intent"),
        "protocol_families": comparison.get("protocol_families"),
        "delta": delta,
        "precert": comparison.get("precert"),
        "cutover_gate": comparison.get("cutover_gate"),
        "operator_evidence": comparison.get("operator_evidence"),
    }
    return (
        claimed_receipt == _canonical_receipt_sha256(unsigned)
        and envelope.get("payload_sha256") == _canonical_receipt_sha256(payload)
        and envelope.get("admission") == admission
        and envelope.get("source_binding") == admission.get("source_binding")
        and envelope.get("subject_binding") == admission.get("subject_binding")
        and envelope.get("owner_versions") == admission.get("owner_versions")
        and envelope.get("support_profiles") == admission.get("support_profiles")
    )


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
            # Older stores predate an explicit engagement identity. Give each existing campaign a
            # durable opaque identity exactly once; it is stored beside the campaign and survives
            # a copied/moved USB database. Campaign names/paths are never inferred as identity.
            missing = self._conn.execute(
                """SELECT c.id FROM campaigns c
                   LEFT JOIN campaign_identities i ON i.campaign_id=c.id
                   WHERE i.campaign_id IS NULL ORDER BY c.id"""
            ).fetchall()
            for row in missing:
                self._conn.execute(
                    "INSERT OR IGNORE INTO campaign_identities(campaign_id, engagement_id) VALUES (?,?)",
                    (row["id"], "urn:uuid:" + str(uuid.uuid4())),
                )
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
    def create_campaign(self, name: str, description: str = "",
                        engagement_id: str = "") -> Dict[str, Any]:
        engagement = engagement_id.strip() or ("urn:uuid:" + str(uuid.uuid4()))
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                cur = self._conn.execute(
                    "INSERT INTO campaigns(name, description, created_at) VALUES (?,?,?)",
                    (name.strip() or "Untitled campaign", description.strip(), _now()),
                )
                cid = int(cur.lastrowid or 0)
                self._conn.execute(
                    "INSERT INTO campaign_identities(campaign_id, engagement_id) VALUES (?,?)",
                    (cid, engagement),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return self.get_campaign(cid)  # type: ignore[return-value]

    def list_campaigns(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT c.*, i.engagement_id,
                          COUNT(s.id)            AS n_snapshots,
                          MAX(s.uploaded_at)     AS last_upload
                   FROM campaigns c
                   JOIN campaign_identities i ON i.campaign_id = c.id
                   LEFT JOIN snapshots s ON s.campaign_id = c.id
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
                """SELECT c.*, i.engagement_id FROM campaigns c
                   JOIN campaign_identities i ON i.campaign_id=c.id
                   WHERE c.id = ?""", (campaign_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["snapshots"] = self.list_snapshots(campaign_id)
        return d

    def delete_campaign_if_unreceipted(self, campaign_id: int) -> str:
        """Atomically delete a campaign only when no canonical decision receipt depends on it."""
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                exists = self._conn.execute(
                    "SELECT 1 FROM campaigns WHERE id=?", (campaign_id,)
                ).fetchone()
                if exists is None:
                    self._conn.rollback()
                    return "missing"
                receipt = self._conn.execute(
                    """SELECT 1
                       FROM execution_comparisons ec
                       JOIN executions e ON e.id=ec.execution_id
                       JOIN snapshots s ON s.id=e.snapshot_id
                       WHERE s.campaign_id=? LIMIT 1""",
                    (campaign_id,),
                ).fetchone()
                if receipt is not None:
                    self._conn.rollback()
                    return "receipted"
                self._conn.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
                self._conn.commit()
                return "deleted"
            except Exception:
                self._conn.rollback()
                raise

    def delete_campaign(self, campaign_id: int) -> bool:
        """Compatibility wrapper; campaigns containing decision receipts are immutable."""
        return self.delete_campaign_if_unreceipted(campaign_id) == "deleted"

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
                """SELECT s.id, s.campaign_id, i.engagement_id, s.label, s.uploaded_at,
                          s.script_version, s.n_devices, s.summary_json
                   FROM snapshots s
                   JOIN campaign_identities i ON i.campaign_id=s.campaign_id
                   WHERE s.campaign_id = ? ORDER BY s.uploaded_at ASC, s.id ASC""",
                (campaign_id,),
            ).fetchall()
        return [self._meta_row(r) for r in rows]

    def get_snapshot_meta(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """SELECT s.id, s.campaign_id, i.engagement_id, s.label, s.uploaded_at,
                          s.script_version, s.n_devices, s.summary_json
                   FROM snapshots s
                   JOIN campaign_identities i ON i.campaign_id=s.campaign_id
                   WHERE s.id = ?""", (snapshot_id,)
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
                """SELECT s.id AS snapshot_id, s.campaign_id, i.engagement_id,
                          s.label, s.script_version,
                          CAST(s.snapshot_json AS BLOB) AS snapshot_blob
                   FROM snapshots s
                   JOIN campaign_identities i ON i.campaign_id=s.campaign_id
                   WHERE s.id = ?""", (snapshot_id,)
            ).fetchone()
        if row is None:
            return None
        raw, binding = _snapshot_binding_from_row(row)
        from cisco_toolkit.protocol_assurance import bind_snapshot_json_bytes
        return (
            bind_snapshot_json_bytes(raw),
            binding,
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

    def delete_snapshot_if_unreceipted(self, snapshot_id: int) -> str:
        """Atomically preserve every before/after source named by a canonical receipt."""
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                exists = self._conn.execute(
                    "SELECT 1 FROM snapshots WHERE id=?", (snapshot_id,)
                ).fetchone()
                if exists is None:
                    self._conn.rollback()
                    return "missing"
                receipt = self._conn.execute(
                    """SELECT 1 FROM execution_comparisons
                       WHERE before_snapshot_id=? OR after_snapshot_id=? LIMIT 1""",
                    (snapshot_id, snapshot_id),
                ).fetchone()
                if receipt is not None:
                    self._conn.rollback()
                    return "receipted"
                self._conn.execute("DELETE FROM snapshots WHERE id=?", (snapshot_id,))
                self._conn.commit()
                return "deleted"
            except Exception:
                self._conn.rollback()
                raise

    def delete_snapshot(self, snapshot_id: int) -> bool:
        """Compatibility wrapper; receipt-bound source snapshots are never deleted."""
        return self.delete_snapshot_if_unreceipted(snapshot_id) == "deleted"

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
                # The persisted start instant, not the earlier in-memory plan-build instant, owns
                # the post-change boundary. Freeze it while the same write transaction also reads
                # the current snapshot-id high-water mark. A later snapshot must exceed both this
                # mark and the temporal/capture checks at receipt append.
                persisted_started_at = _now()
                state["started_at"] = persisted_started_at
                policy = state.get("comparison_policy") if isinstance(state, dict) else None
                if isinstance(policy, dict) and policy.get("schema") == (
                    "execution_comparison_policy/1"
                ):
                    high_watermark_row = self._conn.execute(
                        "SELECT COALESCE(MAX(id),0) AS snapshot_id FROM snapshots"
                    ).fetchone()
                    policy["snapshot_id_high_watermark"] = int(
                        high_watermark_row["snapshot_id"] if high_watermark_row else 0
                    )
                cur = self._conn.execute(
                    """INSERT INTO executions(snapshot_id, label, status, started_at, ended_at, state_json)
                       VALUES (?,?,?,?,?,?)""",
                    (snapshot_id, state.get("label", ""), state.get("status", "in_progress"),
                     persisted_started_at, state.get("ended_at"),
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
                "state": json.loads(row["state_json"]), "_state_json": row["state_json"],
                "comparisons": self.list_execution_comparisons(execution_id)}

    def list_execution_comparisons(self, execution_id: int) -> List[Dict[str, Any]]:
        """Append order is the immutable receipt order; integer id defines "latest"."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, execution_id, before_snapshot_id, after_snapshot_id,
                          receipt_sha256, cutover_verdict, created_at, receipt_json
                   FROM execution_comparisons WHERE execution_id=? ORDER BY id ASC""",
                (execution_id,),
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["receipt"] = json.loads(item.pop("receipt_json"))
            out.append(item)
        return out

    def append_execution_comparison_if_unchanged(
            self, execution_id: int, expected_state_json: str,
            receipt: Dict[str, Any]) -> Dict[str, Any]:
        """Atomically append one immutable comparison and move the latest-gate marker.

        ``BEGIN IMMEDIATE`` plus the exact state-json comparison closes both races: a concurrent
        execution mutation cannot be overwritten, and a finish cannot pass between comparison
        computation and receipt append.  The receipt table itself has no update API and a database
        trigger refuses UPDATEs.
        """
        unsigned = dict(receipt) if isinstance(receipt, dict) else {}
        claimed_hash = unsigned.pop("receipt_sha256", None)
        if claimed_hash != _canonical_receipt_sha256(unsigned):
            raise ValueError("execution comparison receipt digest is invalid")
        if receipt.get("schema") != "execution_comparison_receipt/1":
            raise ValueError("execution comparison receipt schema is invalid")
        comparison = receipt.get("comparison")
        if not _comparison_envelope_valid(comparison):
            raise ValueError("execution comparison detached receipt is invalid")
        # Do not try to re-authorize a detached JSON family set here. The canonical comparison's
        # process-local family authority is intentionally lost at the API/wire boundary. Semantic
        # authority is established below, inside BEGIN IMMEDIATE, by recomputing the *entire*
        # comparison from the two exact persisted blobs and requiring canonical JSON equality.
        gate = comparison.get("cutover_gate") if isinstance(comparison, dict) else None
        if not isinstance(gate, dict) or gate.get("schema") != "cutover_gate/1":
            raise ValueError("execution comparison has no canonical cutover gate")
        verdict = str(gate.get("verdict") or "")
        before_snapshot_id = receipt.get("before_snapshot_id")
        after_snapshot_id = receipt.get("after_snapshot_id")
        if (not isinstance(before_snapshot_id, int) or isinstance(before_snapshot_id, bool)
                or not isinstance(after_snapshot_id, int) or isinstance(after_snapshot_id, bool)):
            raise ValueError("execution comparison snapshot identities are invalid")
        encoded_receipt = json.dumps(receipt, separators=(",", ":"), allow_nan=False)
        created_at = _now()
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    """SELECT snapshot_id, status, started_at, state_json
                       FROM executions WHERE id=?""",
                    (execution_id,),
                ).fetchone()
                if row is None:
                    self._conn.rollback()
                    return {"status": "missing"}
                if row["state_json"] != expected_state_json:
                    self._conn.rollback()
                    return {"status": "conflict"}
                if row["status"] != "in_progress":
                    self._conn.rollback()
                    return {"status": "closed"}
                if int(row["snapshot_id"]) != before_snapshot_id:
                    self._conn.rollback()
                    return {"status": "identity_mismatch"}
                state = json.loads(row["state_json"])
                policy = state.get("comparison_policy") if isinstance(state, dict) else None
                if (not isinstance(policy, dict)
                        or policy.get("schema") != "execution_comparison_policy/1"
                        or policy.get("canonical_gate_required") is not True):
                    self._conn.rollback()
                    return {"status": "legacy"}
                snapshot_id_high_watermark = policy.get("snapshot_id_high_watermark")
                if (
                    type(snapshot_id_high_watermark) is not int
                    or snapshot_id_high_watermark < before_snapshot_id
                ):
                    self._conn.rollback()
                    return {"status": "after_not_post_change"}
                from . import execution as execution_owner

                implementation_binding = execution_owner.implementation_evidence_binding(state)
                if (
                    implementation_binding.get("valid") is not True
                    or receipt.get("implementation_binding") != implementation_binding
                ):
                    self._conn.rollback()
                    return {"status": "after_not_post_change"}

                # Re-read both source rows while the write transaction is held. Snapshot blobs are
                # immutable through the API, but another process can delete a row between the
                # route's initial read and this append. Binding to the rows again here ensures the
                # receipt is admitted only while the exact source bytes and custody identities it
                # names still exist. The same check catches an internally miswired/rehashed receipt.
                if before_snapshot_id == after_snapshot_id:
                    self._conn.rollback()
                    return {"status": "source_mismatch"}
                source_rows = self._conn.execute(
                    """SELECT s.id AS snapshot_id, s.campaign_id, i.engagement_id,
                              s.label, s.uploaded_at, s.script_version,
                              CAST(s.snapshot_json AS BLOB) AS snapshot_blob
                       FROM snapshots s
                       JOIN campaign_identities i ON i.campaign_id=s.campaign_id
                       WHERE s.id IN (?,?)""",
                    (before_snapshot_id, after_snapshot_id),
                ).fetchall()
                if len(source_rows) != 2:
                    self._conn.rollback()
                    return {"status": "source_missing"}
                current_bindings: Dict[int, Dict[str, Any]] = {}
                current_snapshots: Dict[int, Dict[str, Any]] = {}
                for source_row in source_rows:
                    raw_source, binding = _snapshot_binding_from_row(source_row)
                    current_bindings[binding["snapshot_id"]] = binding
                    try:
                        from cisco_toolkit.protocol_assurance import bind_snapshot_json_bytes
                        parsed_source = bind_snapshot_json_bytes(raw_source)
                    except (TypeError, ValueError, UnicodeDecodeError):
                        self._conn.rollback()
                        return {"status": "source_mismatch"}
                    if not isinstance(parsed_source, dict):
                        self._conn.rollback()
                        return {"status": "source_mismatch"}
                    current_snapshots[binding["snapshot_id"]] = parsed_source
                before_binding = current_bindings.get(before_snapshot_id)
                after_binding = current_bindings.get(after_snapshot_id)
                if before_binding is None or after_binding is None:
                    self._conn.rollback()
                    return {"status": "source_missing"}

                # A canonical after receipt is post-change evidence for *this* run, not merely a
                # second snapshot from the same campaign.  Enforce the temporal/provenance order
                # again under the same write lock that appends the receipt.  Snapshot IDs provide
                # a database ordering witness; aware upload/start timestamps independently prove
                # that the evidence was introduced after the run began.  Missing or ambiguous
                # timestamps abstain instead of allowing PASS.
                source_by_id = {
                    int(source_row["snapshot_id"]): source_row for source_row in source_rows
                }
                before_row = source_by_id.get(before_snapshot_id)
                after_row = source_by_id.get(after_snapshot_id)
                run_started_at = _parse_aware_timestamp(row["started_at"])
                before_uploaded_at = _parse_aware_timestamp(
                    before_row["uploaded_at"] if before_row is not None else None
                )
                after_uploaded_at = _parse_aware_timestamp(
                    after_row["uploaded_at"] if after_row is not None else None
                )
                after_snapshot = current_snapshots.get(after_snapshot_id)
                after_collected_at = _parse_aware_timestamp(
                    after_snapshot.get("collected_at")
                    if isinstance(after_snapshot, dict) else None
                )
                implementation_completed_at = _parse_aware_timestamp(
                    implementation_binding.get("completed_at")
                )
                if (
                    after_snapshot_id <= snapshot_id_high_watermark
                    or run_started_at is None
                    or before_uploaded_at is None
                    or after_uploaded_at is None
                    or after_collected_at is None
                    or implementation_completed_at is None
                    or receipt.get("after_collected_at") != after_snapshot.get("collected_at")
                    or before_uploaded_at > run_started_at
                    or after_uploaded_at <= run_started_at
                    or after_uploaded_at <= before_uploaded_at
                    or after_collected_at <= run_started_at
                    or after_collected_at <= implementation_completed_at
                    or after_collected_at > after_uploaded_at
                ):
                    self._conn.rollback()
                    return {"status": "after_not_post_change"}

                admission = comparison.get("comparison_admission")
                admission_source = admission.get("source_binding") \
                    if isinstance(admission, dict) else None
                envelope = comparison.get("comparison_receipt")
                envelope_source = envelope.get("source_binding") \
                    if isinstance(envelope, dict) else None
                provenance = comparison.get("provenance")
                delta_source = provenance.get("source_binding") \
                    if isinstance(provenance, dict) else None
                frozen_before = policy.get("before_snapshot")
                source_pairs = (admission_source, envelope_source, delta_source)
                source_mismatch = (
                    before_binding["campaign_id"] != after_binding["campaign_id"]
                    or before_binding["engagement_id"] != after_binding["engagement_id"]
                    or not isinstance(admission, dict)
                    or type(admission.get("campaign_id")) is not int
                    or admission.get("campaign_id") != before_binding["campaign_id"]
                    or not isinstance(admission.get("engagement_id"), str)
                    or admission.get("engagement_id") != before_binding["engagement_id"]
                    or not _binding_matches(frozen_before, before_binding)
                    or any(
                        not isinstance(pair, dict)
                        or not _binding_matches(pair.get("before"), before_binding)
                        or not _binding_matches(pair.get("after"), after_binding)
                        for pair in source_pairs
                    )
                )
                precert = comparison.get("precert")
                precert_source = precert.get("source_binding") \
                    if isinstance(precert, dict) else None
                intent = comparison.get("change_intent")
                intent_binding = intent.get("binding") if isinstance(intent, dict) else None
                if (not isinstance(precert_source, dict)
                        or precert_source.get("before") != before_binding["sha256"]
                        or precert_source.get("after") != after_binding["sha256"]
                        or not isinstance(intent_binding, dict)
                        or not isinstance(intent_binding.get("engagement_id"), str)
                        or intent_binding.get("engagement_id") != before_binding["engagement_id"]
                        or type(intent_binding.get("campaign_id")) is not int
                        or intent_binding.get("campaign_id") != before_binding["campaign_id"]
                        or type(intent_binding.get("before_snapshot_id")) is not int
                        or intent_binding.get("before_snapshot_id") != before_snapshot_id
                        or type(intent_binding.get("after_snapshot_id")) is not int
                        or intent_binding.get("after_snapshot_id") != after_snapshot_id
                        or intent_binding.get("before_sha256") != before_binding["sha256"]
                        or intent_binding.get("after_sha256") != after_binding["sha256"]):
                    source_mismatch = True
                if source_mismatch:
                    self._conn.rollback()
                    return {"status": "source_mismatch"}

                # Digest reconciliation is not semantic reconciliation: a caller can rewrite the
                # delta/certificate/family inputs, recompute their gate, and then recompute every
                # enclosing hash. Re-run the complete comparison owner over the exact blobs read
                # under this write transaction and require byte-for-byte-equivalent JSON values.
                # Execution receipts accept only a canonical valid intent; malformed intent remains
                # visible on the read-only /api/compare surface but cannot mutate execution state.
                intent_status = intent.get("status") if isinstance(intent, dict) else None
                if intent_status == "not_supplied":
                    intent_request = None
                elif intent_status == "reconciled":
                    intent_request = {
                        "expected_changes": intent.get("expected_changes"),
                        "note": intent.get("note"),
                    }
                else:
                    self._conn.rollback()
                    return {"status": "comparison_mismatch"}
                from . import engine as comparison_engine

                canonical_comparison = comparison_engine.compare_bound_pair(
                    current_snapshots[before_snapshot_id],
                    current_snapshots[after_snapshot_id],
                    before_binding=before_binding,
                    after_binding=after_binding,
                    change_intent=intent_request,
                )
                if not _canonical_json_identity_matches(comparison, canonical_comparison):
                    self._conn.rollback()
                    return {"status": "comparison_mismatch"}
                cur = self._conn.execute(
                    """INSERT INTO execution_comparisons(
                           execution_id, before_snapshot_id, after_snapshot_id, receipt_sha256,
                           cutover_verdict, created_at, receipt_json)
                       VALUES (?,?,?,?,?,?,?)""",
                    (execution_id, before_snapshot_id, after_snapshot_id, claimed_hash,
                     verdict, created_at, encoded_receipt),
                )
                receipt_id = int(cur.lastrowid or 0)
                state["latest_comparison"] = {
                    "schema": "execution_latest_comparison/1",
                    "receipt_id": receipt_id,
                    "receipt_sha256": claimed_hash,
                    "before_snapshot_id": before_snapshot_id,
                    "after_snapshot_id": after_snapshot_id,
                    "after_collected_at": after_snapshot.get("collected_at"),
                    "implementation_binding": implementation_binding,
                    "cutover_gate": dict(gate),
                }
                encoded_state = json.dumps(state, separators=(",", ":"), allow_nan=False)
                changed = self._conn.execute(
                    """UPDATE executions SET state_json=?
                       WHERE id=? AND status='in_progress' AND state_json=?""",
                    (encoded_state, execution_id, expected_state_json),
                )
                if changed.rowcount != 1:
                    self._conn.rollback()
                    return {"status": "conflict"}
                self._conn.commit()
                return {"status": "saved", "receipt_id": receipt_id, "state": state}
            except Exception:
                self._conn.rollback()
                raise

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
                """SELECT id, snapshot_id, label, status, started_at, ended_at, state_json
                   FROM executions WHERE snapshot_id = ? ORDER BY started_at DESC, id DESC""",
                (snapshot_id,),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            state = json.loads(item.pop("state_json"))
            if isinstance(state.get("latest_comparison"), dict):
                item["latest_comparison"] = state["latest_comparison"]
            item["comparison_required"] = (
                isinstance(state.get("comparison_policy"), dict)
                and state["comparison_policy"].get("canonical_gate_required") is True
            )
            out.append(item)
        return out

    def delete_execution_if_unreceipted(self, execution_id: int) -> str:
        """Delete an unreceipted run atomically: ``deleted``, ``receipted``, or ``missing``.

        A canonical comparison is an append-only decision record.  The existence check and delete
        share one write transaction so a comparison racing this operation either commits first and
        blocks deletion, or observes that the execution was removed and cannot leave an orphan.
        """
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                exists = self._conn.execute(
                    "SELECT 1 FROM executions WHERE id=?", (execution_id,)
                ).fetchone()
                if exists is None:
                    self._conn.rollback()
                    return "missing"
                receipt = self._conn.execute(
                    "SELECT 1 FROM execution_comparisons WHERE execution_id=? LIMIT 1",
                    (execution_id,),
                ).fetchone()
                if receipt is not None:
                    self._conn.rollback()
                    return "receipted"
                self._conn.execute("DELETE FROM executions WHERE id=?", (execution_id,))
                self._conn.commit()
                return "deleted"
            except Exception:
                self._conn.rollback()
                raise

    def delete_execution(self, execution_id: int) -> bool:
        """Compatibility wrapper; canonical receipt-bearing executions are never deleted."""
        return self.delete_execution_if_unreceipted(execution_id) == "deleted"

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
