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
CREATE TABLE IF NOT EXISTS snapshot_authority (
    snapshot_id INTEGER PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
    authority_version INTEGER NOT NULL CHECK (authority_version = 1),
    digest_0    INTEGER NOT NULL,
    digest_1    INTEGER NOT NULL,
    digest_2    INTEGER NOT NULL,
    digest_3    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS executions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'in_progress',
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    state_json  TEXT NOT NULL,
    comparison_required INTEGER NOT NULL DEFAULT 0 CHECK (comparison_required IN (0,1)),
    snapshot_id_high_watermark INTEGER NOT NULL DEFAULT 0,
    lifecycle_state INTEGER NOT NULL DEFAULT 0 CHECK (lifecycle_state IN (0,1,2)),
    started_at_epoch_us INTEGER NOT NULL DEFAULT 0,
    ended_at_epoch_us INTEGER
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
CREATE TABLE IF NOT EXISTS execution_comparison_authority (
    comparison_id INTEGER PRIMARY KEY
        REFERENCES execution_comparisons(id) ON DELETE CASCADE,
    authority_version INTEGER NOT NULL CHECK (authority_version = 1),
    verdict_code  INTEGER NOT NULL CHECK (verdict_code IN (1,2,3,4,5,6)),
    digest_0      INTEGER NOT NULL,
    digest_1      INTEGER NOT NULL,
    digest_2      INTEGER NOT NULL,
    digest_3      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_l2_failure_trial_sources (
    comparison_id            INTEGER PRIMARY KEY
                                 REFERENCES execution_comparisons(id),
    pre_failure_snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id),
    post_failure_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    recovery_snapshot_id     INTEGER NOT NULL REFERENCES snapshots(id),
    witness_blob             BLOB NOT NULL,
    witness_sha256           TEXT NOT NULL,
    source                   TEXT NOT NULL,
    campaign_id              INTEGER NOT NULL,
    engagement_id            TEXT NOT NULL,
    CHECK (pre_failure_snapshot_id <> post_failure_snapshot_id),
    CHECK (pre_failure_snapshot_id <> recovery_snapshot_id),
    CHECK (post_failure_snapshot_id <> recovery_snapshot_id)
);
CREATE INDEX IF NOT EXISTS ix_execution_l2_trial_pre
    ON execution_l2_failure_trial_sources(pre_failure_snapshot_id);
CREATE INDEX IF NOT EXISTS ix_execution_l2_trial_post
    ON execution_l2_failure_trial_sources(post_failure_snapshot_id);
CREATE INDEX IF NOT EXISTS ix_execution_l2_trial_recovery
    ON execution_l2_failure_trial_sources(recovery_snapshot_id);
CREATE TABLE IF NOT EXISTS execution_l2_failure_trial_authority (
    comparison_id INTEGER PRIMARY KEY
        REFERENCES execution_l2_failure_trial_sources(comparison_id) ON DELETE CASCADE,
    authority_version INTEGER NOT NULL CHECK (authority_version = 1),
    source_code   INTEGER NOT NULL CHECK (source_code = 1),
    digest_0      INTEGER NOT NULL,
    digest_1      INTEGER NOT NULL,
    digest_2      INTEGER NOT NULL,
    digest_3      INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS snapshot_authority_no_update
BEFORE UPDATE ON snapshot_authority
BEGIN
    SELECT RAISE(ABORT, 'snapshot authority is immutable');
END;
CREATE TRIGGER IF NOT EXISTS snapshot_authority_no_replace
BEFORE INSERT ON snapshot_authority
WHEN EXISTS (SELECT 1 FROM snapshot_authority WHERE snapshot_id=NEW.snapshot_id)
BEGIN
    SELECT RAISE(ABORT, 'snapshot authority is immutable');
END;
CREATE TRIGGER IF NOT EXISTS snapshot_authority_receipted_no_delete
BEFORE DELETE ON snapshot_authority
WHEN EXISTS (
    SELECT 1 FROM execution_comparisons ec
    WHERE ec.before_snapshot_id=OLD.snapshot_id OR ec.after_snapshot_id=OLD.snapshot_id
    UNION ALL
    SELECT 1 FROM execution_l2_failure_trial_sources trial
    WHERE trial.pre_failure_snapshot_id=OLD.snapshot_id
       OR trial.post_failure_snapshot_id=OLD.snapshot_id
       OR trial.recovery_snapshot_id=OLD.snapshot_id
)
BEGIN
    SELECT RAISE(ABORT, 'receipted snapshot authority is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_authority_no_update
BEFORE UPDATE ON execution_comparison_authority
BEGIN
    SELECT RAISE(ABORT, 'execution comparison authority is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_authority_no_delete
BEFORE DELETE ON execution_comparison_authority
BEGIN
    SELECT RAISE(ABORT, 'execution comparison authority is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_authority_no_replace
BEFORE INSERT ON execution_comparison_authority
WHEN EXISTS (
    SELECT 1 FROM execution_comparison_authority WHERE comparison_id=NEW.comparison_id
)
BEGIN
    SELECT RAISE(ABORT, 'execution comparison authority is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_l2_failure_trial_authority_no_update
BEFORE UPDATE ON execution_l2_failure_trial_authority
BEGIN
    SELECT RAISE(ABORT, 'execution L2 failure-trial authority is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_l2_failure_trial_authority_no_delete
BEFORE DELETE ON execution_l2_failure_trial_authority
BEGIN
    SELECT RAISE(ABORT, 'execution L2 failure-trial authority is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_l2_failure_trial_authority_no_replace
BEFORE INSERT ON execution_l2_failure_trial_authority
WHEN EXISTS (
    SELECT 1 FROM execution_l2_failure_trial_authority
    WHERE comparison_id=NEW.comparison_id
)
BEGIN
    SELECT RAISE(ABORT, 'execution L2 failure-trial authority is immutable');
END;
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
CREATE TRIGGER IF NOT EXISTS execution_comparisons_no_replace
BEFORE INSERT ON execution_comparisons
WHEN EXISTS (
    SELECT 1 FROM execution_comparisons WHERE id = NEW.id
)
BEGIN
    -- INSERT OR REPLACE can delete the old row without running DELETE triggers when
    -- recursive_triggers is disabled. Refuse insertion over an immutable receipt id.
    SELECT RAISE(ABORT, 'execution comparison receipts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_owner_no_delete
BEFORE DELETE ON executions
WHEN EXISTS (
    SELECT 1 FROM execution_comparisons WHERE execution_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'receipted execution source identity is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_owner_no_rebind
BEFORE UPDATE OF id, snapshot_id, started_at, started_at_epoch_us,
                 comparison_required, snapshot_id_high_watermark ON executions
WHEN EXISTS (
    SELECT 1 FROM execution_comparisons WHERE execution_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'receipted execution source identity is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_policy_no_rebind
BEFORE UPDATE OF comparison_required, snapshot_id_high_watermark ON executions
WHEN EXISTS (
    SELECT 1 FROM execution_comparisons WHERE execution_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'receipted execution comparison policy is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_comparison_owner_no_replace
BEFORE INSERT ON executions
WHEN EXISTS (
    SELECT 1 FROM execution_comparisons WHERE execution_id = NEW.id
)
BEGIN
    SELECT RAISE(ABORT, 'receipted execution source identity is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_lifecycle_no_reopen
BEFORE UPDATE OF lifecycle_state, ended_at_epoch_us ON executions
WHEN OLD.lifecycle_state <> 0 AND (
    NEW.lifecycle_state <> OLD.lifecycle_state
    OR NEW.ended_at_epoch_us IS NOT OLD.ended_at_epoch_us
)
BEGIN
    SELECT RAISE(ABORT, 'closed execution lifecycle is immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_l2_failure_trial_sources_no_update
BEFORE UPDATE ON execution_l2_failure_trial_sources
BEGIN
    SELECT RAISE(ABORT, 'execution L2 failure-trial sources are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_l2_failure_trial_sources_no_delete
BEFORE DELETE ON execution_l2_failure_trial_sources
BEGIN
    SELECT RAISE(ABORT, 'execution L2 failure-trial sources are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_l2_failure_trial_sources_no_replace
BEFORE INSERT ON execution_l2_failure_trial_sources
WHEN EXISTS (
    SELECT 1 FROM execution_l2_failure_trial_sources
    WHERE comparison_id = NEW.comparison_id
)
BEGIN
    -- INSERT OR REPLACE can delete the old row without DELETE triggers when recursive_triggers
    -- is disabled. Refuse insertion over the immutable comparison-owned source identity.
    SELECT RAISE(ABORT, 'execution L2 failure-trial sources are immutable');
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
CREATE TRIGGER IF NOT EXISTS execution_l2_failure_trial_snapshots_no_delete
BEFORE DELETE ON snapshots
WHEN EXISTS (
    SELECT 1 FROM execution_l2_failure_trial_sources trial
    WHERE trial.pre_failure_snapshot_id = OLD.id
       OR trial.post_failure_snapshot_id = OLD.id
       OR trial.recovery_snapshot_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'execution L2 failure-trial source snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_l2_failure_trial_snapshots_no_rebind
BEFORE UPDATE OF id, campaign_id, label, uploaded_at, script_version, snapshot_json ON snapshots
WHEN EXISTS (
    SELECT 1 FROM execution_l2_failure_trial_sources trial
    WHERE trial.pre_failure_snapshot_id = OLD.id
       OR trial.post_failure_snapshot_id = OLD.id
       OR trial.recovery_snapshot_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'execution L2 failure-trial source bindings are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_l2_failure_trial_snapshots_no_replace
BEFORE INSERT ON snapshots
WHEN EXISTS (
    SELECT 1 FROM execution_l2_failure_trial_sources trial
    WHERE trial.pre_failure_snapshot_id = NEW.id
       OR trial.post_failure_snapshot_id = NEW.id
       OR trial.recovery_snapshot_id = NEW.id
)
BEGIN
    SELECT RAISE(ABORT, 'execution L2 failure-trial source bindings are immutable');
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
CREATE TRIGGER IF NOT EXISTS execution_l2_failure_trial_engagement_no_delete
BEFORE DELETE ON campaign_identities
WHEN EXISTS (
    SELECT 1 FROM snapshots s
    JOIN execution_l2_failure_trial_sources trial
      ON trial.pre_failure_snapshot_id = s.id
      OR trial.post_failure_snapshot_id = s.id
      OR trial.recovery_snapshot_id = s.id
    WHERE s.campaign_id = OLD.campaign_id
)
BEGIN
    SELECT RAISE(ABORT, 'execution L2 failure-trial engagement bindings are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_l2_failure_trial_engagement_no_rebind
BEFORE UPDATE OF campaign_id, engagement_id ON campaign_identities
WHEN EXISTS (
    SELECT 1 FROM snapshots s
    JOIN execution_l2_failure_trial_sources trial
      ON trial.pre_failure_snapshot_id = s.id
      OR trial.post_failure_snapshot_id = s.id
      OR trial.recovery_snapshot_id = s.id
    WHERE s.campaign_id = OLD.campaign_id
)
BEGIN
    SELECT RAISE(ABORT, 'execution L2 failure-trial engagement bindings are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_l2_failure_trial_engagement_no_replace
BEFORE INSERT ON campaign_identities
WHEN EXISTS (
    SELECT 1 FROM snapshots s
    JOIN execution_l2_failure_trial_sources trial
      ON trial.pre_failure_snapshot_id = s.id
      OR trial.post_failure_snapshot_id = s.id
      OR trial.recovery_snapshot_id = s.id
    WHERE s.campaign_id = NEW.campaign_id
)
BEGIN
    SELECT RAISE(ABORT, 'execution L2 failure-trial engagement bindings are immutable');
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


def _timestamp_epoch_us(value: Any) -> Optional[int]:
    """Return an exact INTEGER epoch witness for an aware source timestamp."""
    parsed = _parse_aware_timestamp(value)
    if parsed is None:
        return None
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = parsed - epoch
    return (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )


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


def _reject_duplicate_json_object(pairs: List[tuple[str, Any]]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _strict_json_loads(value: Any) -> Any:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        raise ValueError("persisted JSON is not text")
    return json.loads(value, object_pairs_hook=_reject_duplicate_json_object)


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
_CUTOVER_VERDICT_CODES = {
    "PASS": 1,
    "REVIEW": 2,
    "INDETERMINATE": 3,
    "FAIL": 4,
    "CONDITIONAL": 5,
    "REGRESSED": 6,
}
_TRIAL_SOURCE_CODE = 1


def _authority_limbs(value: Dict[str, Any]) -> tuple[int, int, int, int]:
    """SHA-256 as four signed SQLite INTEGERs, which incremental BLOB writes cannot open."""
    digest = hashlib.sha256(_canonical_json_bytes(value)).digest()
    return tuple(
        int.from_bytes(digest[offset:offset + 8], "big", signed=True)
        for offset in range(0, 32, 8)
    )  # type: ignore[return-value]


def _blob_identity(value: Any) -> Dict[str, Any]:
    raw = _snapshot_blob_bytes(value)
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _snapshot_authority_limbs(
        *, snapshot_id: int, campaign_id: int, engagement_id: str,
        label: str, uploaded_at: str, script_version: str,
        snapshot_blob: Any) -> tuple[int, int, int, int]:
    return _authority_limbs({
        "schema": "snapshot_source_authority/1",
        "source": _SNAPSHOT_BINDING_SOURCE,
        "snapshot_id": int(snapshot_id),
        "campaign_id": int(campaign_id),
        "engagement_id": str(engagement_id),
        "label": str(label),
        "uploaded_at": str(uploaded_at),
        "script_version": str(script_version),
        "snapshot_blob": _blob_identity(snapshot_blob),
    })


def _comparison_authority_limbs(
        *, comparison_id: int, execution_id: int, before_snapshot_id: int,
        after_snapshot_id: int, receipt_sha256: str, cutover_verdict: str,
        created_at: str, receipt_blob: Any) -> tuple[int, int, int, int]:
    return _authority_limbs({
        "schema": "execution_comparison_authority/1",
        "comparison_id": int(comparison_id),
        "execution_id": int(execution_id),
        "before_snapshot_id": int(before_snapshot_id),
        "after_snapshot_id": int(after_snapshot_id),
        "receipt_sha256": str(receipt_sha256),
        "cutover_verdict": str(cutover_verdict),
        "created_at": str(created_at),
        "receipt_blob": _blob_identity(receipt_blob),
    })


def _trial_authority_limbs(
        *, comparison_id: int, pre_failure_snapshot_id: int,
        post_failure_snapshot_id: int, recovery_snapshot_id: int,
        witness_blob: Any, witness_sha256: str, source: str,
        campaign_id: int, engagement_id: str) -> tuple[int, int, int, int]:
    return _authority_limbs({
        "schema": "execution_l2_failure_trial_authority/1",
        "comparison_id": int(comparison_id),
        "pre_failure_snapshot_id": int(pre_failure_snapshot_id),
        "post_failure_snapshot_id": int(post_failure_snapshot_id),
        "recovery_snapshot_id": int(recovery_snapshot_id),
        "witness_blob": _blob_identity(witness_blob),
        "witness_sha256": str(witness_sha256),
        "source": str(source),
        "campaign_id": int(campaign_id),
        "engagement_id": str(engagement_id),
    })


def _authority_row_matches(
        row: sqlite3.Row, expected: tuple[int, int, int, int],
        *, prefix: str = "authority_digest") -> bool:
    return all(
        type(row[f"{prefix}_{index}"]) is int
        and int(row[f"{prefix}_{index}"]) == expected[index]
        for index in range(4)
    )


def _snapshot_authority_row_valid(row: sqlite3.Row) -> bool:
    if (
        "authority_snapshot_id" not in row.keys()
        or type(row["authority_snapshot_id"]) is not int
        or int(row["authority_snapshot_id"]) != int(row["snapshot_id"])
        or "authority_version" not in row.keys()
        or type(row["authority_version"]) is not int
        or int(row["authority_version"]) != 1
    ):
        return False
    expected = _snapshot_authority_limbs(
        snapshot_id=row["snapshot_id"],
        campaign_id=row["campaign_id"],
        engagement_id=row["engagement_id"],
        label=row["label"],
        uploaded_at=row["uploaded_at"],
        script_version=row["script_version"],
        snapshot_blob=row["snapshot_blob"],
    )
    return _authority_row_matches(row, expected)


class StoreCorruptError(RuntimeError):
    """The SQLite store failed its boot integrity check. The file was NOT modified."""


class ExecutionReceiptAuthorityError(RuntimeError):
    """Persisted execution decision rows cannot be re-authorized from their exact sources."""


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
            existing_tables = {
                str(row["name"])
                for row in self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            backfill_snapshot_authority = "snapshot_authority" not in existing_tables
            backfill_comparison_authority = (
                "execution_comparison_authority" not in existing_tables
            )
            backfill_trial_authority = (
                "execution_l2_failure_trial_authority" not in existing_tables
            )
            self._conn.executescript(_SCHEMA)
            # v2/legacy classification is decision-bearing even before the first comparison exists.
            # Keep it in INTEGER columns (sqlite blobopen can incrementally rewrite TEXT/BLOB
            # without firing row triggers) and migrate older stores once from their historical
            # state plus any already-appended canonical receipt rows.
            execution_columns = {
                str(row["name"])
                for row in self._conn.execute("PRAGMA table_info(executions)").fetchall()
            }
            migrate_execution_authority = (
                "comparison_required" not in execution_columns
                or "snapshot_id_high_watermark" not in execution_columns
                or "lifecycle_state" not in execution_columns
                or "started_at_epoch_us" not in execution_columns
                or "ended_at_epoch_us" not in execution_columns
            )
            if migrate_execution_authority:
                # The current schema's immutability triggers may already have been created above;
                # suspend only the two policy-column guards while those columns are initialized.
                self._conn.execute(
                    "DROP TRIGGER IF EXISTS execution_comparison_owner_no_rebind"
                )
                self._conn.execute(
                    "DROP TRIGGER IF EXISTS execution_comparison_policy_no_rebind"
                )
            if "comparison_required" not in execution_columns:
                self._conn.execute(
                    "ALTER TABLE executions ADD COLUMN comparison_required "
                    "INTEGER NOT NULL DEFAULT 0 CHECK (comparison_required IN (0,1))"
                )
            if "snapshot_id_high_watermark" not in execution_columns:
                self._conn.execute(
                    "ALTER TABLE executions ADD COLUMN snapshot_id_high_watermark "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            if "lifecycle_state" not in execution_columns:
                self._conn.execute(
                    "ALTER TABLE executions ADD COLUMN lifecycle_state "
                    "INTEGER NOT NULL DEFAULT 0 CHECK (lifecycle_state IN (0,1,2))"
                )
            if "started_at_epoch_us" not in execution_columns:
                self._conn.execute(
                    "ALTER TABLE executions ADD COLUMN started_at_epoch_us "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            if "ended_at_epoch_us" not in execution_columns:
                self._conn.execute(
                    "ALTER TABLE executions ADD COLUMN ended_at_epoch_us INTEGER"
                )
            execution_rows = self._conn.execute(
                """SELECT e.id, e.snapshot_id, e.status, e.started_at, e.ended_at,
                          e.state_json,
                          EXISTS(SELECT 1 FROM execution_comparisons ec
                                 WHERE ec.execution_id=e.id) AS has_receipt,
                          e.comparison_required, e.snapshot_id_high_watermark,
                          e.lifecycle_state, e.started_at_epoch_us, e.ended_at_epoch_us
                   FROM executions e"""
            ).fetchall() if migrate_execution_authority else []
            for execution_row in execution_rows:
                required = bool(execution_row["has_receipt"])
                high_watermark = int(execution_row["snapshot_id"])
                lifecycle_state = {
                    "completed": 1,
                    "aborted": 2,
                }.get(str(execution_row["status"]), 0)
                started_at_epoch_us = _timestamp_epoch_us(execution_row["started_at"]) or 0
                ended_at_epoch_us = _timestamp_epoch_us(execution_row["ended_at"])
                try:
                    prior_state = _strict_json_loads(execution_row["state_json"])
                except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    prior_state = None
                policy = prior_state.get("comparison_policy") \
                    if isinstance(prior_state, dict) else None
                if (
                    isinstance(policy, dict)
                    and policy.get("schema") == "execution_comparison_policy/1"
                    and policy.get("canonical_gate_required") is True
                ):
                    required = True
                    candidate = policy.get("snapshot_id_high_watermark")
                    if type(candidate) is int and candidate >= high_watermark:
                        high_watermark = candidate
                if (
                    int(execution_row["comparison_required"]) != int(required)
                    or int(execution_row["snapshot_id_high_watermark"]) != high_watermark
                    or int(execution_row["lifecycle_state"]) != lifecycle_state
                    or int(execution_row["started_at_epoch_us"]) != started_at_epoch_us
                    or execution_row["ended_at_epoch_us"] != ended_at_epoch_us
                ):
                    self._conn.execute(
                        """UPDATE executions
                           SET comparison_required=?, snapshot_id_high_watermark=?,
                               lifecycle_state=?, started_at_epoch_us=?, ended_at_epoch_us=?
                           WHERE id=?""",
                        (int(required), high_watermark, lifecycle_state,
                         started_at_epoch_us, ended_at_epoch_us,
                         int(execution_row["id"])),
                    )
            if migrate_execution_authority:
                self._conn.executescript("""
                    CREATE TRIGGER execution_comparison_owner_no_rebind
                    BEFORE UPDATE OF id, snapshot_id, started_at, started_at_epoch_us,
                                     comparison_required, snapshot_id_high_watermark ON executions
                    WHEN EXISTS (
                        SELECT 1 FROM execution_comparisons WHERE execution_id = OLD.id
                    )
                    BEGIN
                        SELECT RAISE(ABORT, 'receipted execution source identity is immutable');
                    END;
                    CREATE TRIGGER execution_comparison_policy_no_rebind
                    BEFORE UPDATE OF comparison_required, snapshot_id_high_watermark ON executions
                    WHEN EXISTS (
                        SELECT 1 FROM execution_comparisons WHERE execution_id = OLD.id
                    )
                    BEGIN
                        SELECT RAISE(ABORT, 'receipted execution comparison policy is immutable');
                    END;
                """)
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
            # One-time trust migration: anchor the exact rows present when this release first opens
            # an older database. After the INTEGER-only tables exist, missing rows are never
            # backfilled on later boots; a torn/deleted anchor therefore fails closed.
            if backfill_snapshot_authority:
                rows = self._conn.execute(
                    """SELECT s.id AS snapshot_id, s.campaign_id, i.engagement_id,
                              s.label, s.uploaded_at, s.script_version,
                              CAST(s.snapshot_json AS BLOB) AS snapshot_blob
                       FROM snapshots s
                       JOIN campaign_identities i ON i.campaign_id=s.campaign_id
                       ORDER BY s.id"""
                ).fetchall()
                for row in rows:
                    limbs = _snapshot_authority_limbs(
                        snapshot_id=row["snapshot_id"],
                        campaign_id=row["campaign_id"],
                        engagement_id=row["engagement_id"],
                        label=row["label"],
                        uploaded_at=row["uploaded_at"],
                        script_version=row["script_version"],
                        snapshot_blob=row["snapshot_blob"],
                    )
                    self._conn.execute(
                        """INSERT INTO snapshot_authority(
                               snapshot_id,authority_version,digest_0,digest_1,digest_2,digest_3)
                           VALUES (?,?,?,?,?,?)""",
                        (int(row["snapshot_id"]), 1, *limbs),
                    )
            if backfill_comparison_authority:
                rows = self._conn.execute(
                    """SELECT id, execution_id, before_snapshot_id, after_snapshot_id,
                              receipt_sha256, cutover_verdict, created_at,
                              CAST(receipt_json AS BLOB) AS receipt_blob
                       FROM execution_comparisons ORDER BY id"""
                ).fetchall()
                for row in rows:
                    verdict_code = _CUTOVER_VERDICT_CODES.get(str(row["cutover_verdict"]))
                    if verdict_code is None:
                        raise ExecutionReceiptAuthorityError(
                            f"cannot migrate comparison {row['id']}: invalid cutover verdict"
                        )
                    limbs = _comparison_authority_limbs(
                        comparison_id=row["id"],
                        execution_id=row["execution_id"],
                        before_snapshot_id=row["before_snapshot_id"],
                        after_snapshot_id=row["after_snapshot_id"],
                        receipt_sha256=row["receipt_sha256"],
                        cutover_verdict=row["cutover_verdict"],
                        created_at=row["created_at"],
                        receipt_blob=row["receipt_blob"],
                    )
                    self._conn.execute(
                        """INSERT INTO execution_comparison_authority(
                               comparison_id,authority_version,verdict_code,
                               digest_0,digest_1,digest_2,digest_3)
                           VALUES (?,?,?,?,?,?,?)""",
                        (int(row["id"]), 1, verdict_code, *limbs),
                    )
            if backfill_trial_authority:
                rows = self._conn.execute(
                    """SELECT comparison_id, pre_failure_snapshot_id,
                              post_failure_snapshot_id, recovery_snapshot_id,
                              CAST(witness_blob AS BLOB) AS witness_blob,
                              witness_sha256, source, campaign_id, engagement_id
                       FROM execution_l2_failure_trial_sources ORDER BY comparison_id"""
                ).fetchall()
                for row in rows:
                    if row["source"] != _SNAPSHOT_BINDING_SOURCE:
                        raise ExecutionReceiptAuthorityError(
                            f"cannot migrate trial {row['comparison_id']}: invalid source owner"
                        )
                    limbs = _trial_authority_limbs(
                        comparison_id=row["comparison_id"],
                        pre_failure_snapshot_id=row["pre_failure_snapshot_id"],
                        post_failure_snapshot_id=row["post_failure_snapshot_id"],
                        recovery_snapshot_id=row["recovery_snapshot_id"],
                        witness_blob=row["witness_blob"],
                        witness_sha256=row["witness_sha256"],
                        source=row["source"],
                        campaign_id=row["campaign_id"],
                        engagement_id=row["engagement_id"],
                    )
                    self._conn.execute(
                        """INSERT INTO execution_l2_failure_trial_authority(
                               comparison_id,authority_version,source_code,
                               digest_0,digest_1,digest_2,digest_3)
                           VALUES (?,?,?,?,?,?,?)""",
                        (int(row["comparison_id"]), 1, _TRIAL_SOURCE_CODE, *limbs),
                    )
            if (
                backfill_snapshot_authority
                or backfill_comparison_authority
                or backfill_trial_authority
            ):
                # A one-time upgrade seals the exact bytes that are present, but only after the
                # pre-anchor history has passed the same semantic replay used by every live read.
                # Thus a malformed/torn old receipt cannot become authoritative merely because the
                # new tables were absent. Subsequent opens never reseal a missing or mismatched row.
                execution_rows = self._conn.execute(
                    """SELECT e.id, e.snapshot_id, e.label, e.status, e.started_at,
                              e.ended_at, e.state_json, e.comparison_required,
                              e.snapshot_id_high_watermark, e.lifecycle_state,
                              e.started_at_epoch_us, e.ended_at_epoch_us
                       FROM executions e
                       WHERE EXISTS (
                           SELECT 1 FROM execution_comparisons ec
                           WHERE ec.execution_id=e.id
                       )
                       ORDER BY e.id"""
                ).fetchall()
                for execution_row in execution_rows:
                    try:
                        state = _strict_json_loads(execution_row["state_json"])
                    except (TypeError, ValueError, UnicodeDecodeError,
                            json.JSONDecodeError) as exc:
                        raise ExecutionReceiptAuthorityError(
                            "cannot migrate execution comparison authority: "
                            "execution state JSON is invalid"
                        ) from exc
                    if not isinstance(state, dict):
                        raise ExecutionReceiptAuthorityError(
                            "cannot migrate execution comparison authority: "
                            "execution state is not an object"
                        )
                    self._execution_receipt_authority_locked(
                        int(execution_row["id"]), execution_row, state
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
        stored_label = label.strip() or "snapshot"
        uploaded_at = _now()
        script_version = str(snapshot.get("script_version", ""))
        summary_json = json.dumps(summary, separators=(",", ":"))
        snapshot_json = json.dumps(snapshot, separators=(",", ":"))
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                identity = self._conn.execute(
                    "SELECT engagement_id FROM campaign_identities WHERE campaign_id=?",
                    (campaign_id,),
                ).fetchone()
                if identity is None:
                    raise ValueError("snapshot campaign has no durable engagement identity")
                cur = self._conn.execute(
                    """INSERT INTO snapshots(campaign_id, label, uploaded_at, script_version,
                                             n_devices, summary_json, snapshot_json)
                       VALUES (?,?,?,?,?,?,?)""",
                    (campaign_id, stored_label, uploaded_at, script_version,
                     _n, summary_json, snapshot_json),
                )
                sid = int(cur.lastrowid or 0)
                limbs = _snapshot_authority_limbs(
                    snapshot_id=sid,
                    campaign_id=campaign_id,
                    engagement_id=identity["engagement_id"],
                    label=stored_label,
                    uploaded_at=uploaded_at,
                    script_version=script_version,
                    snapshot_blob=snapshot_json.encode("utf-8"),
                )
                self._conn.execute(
                    """INSERT INTO snapshot_authority(
                           snapshot_id,authority_version,digest_0,digest_1,digest_2,digest_3)
                       VALUES (?,?,?,?,?,?)""",
                    (sid, 1, *limbs),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
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
                          s.label, s.uploaded_at, s.script_version,
                           CAST(s.snapshot_json AS BLOB) AS snapshot_blob,
                           sa.snapshot_id AS authority_snapshot_id,
                           sa.authority_version AS authority_version,
                          sa.digest_0 AS authority_digest_0,
                          sa.digest_1 AS authority_digest_1,
                          sa.digest_2 AS authority_digest_2,
                          sa.digest_3 AS authority_digest_3
                   FROM snapshots s
                   JOIN campaign_identities i ON i.campaign_id=s.campaign_id
                   LEFT JOIN snapshot_authority sa ON sa.snapshot_id=s.id
                   WHERE s.id = ?""", (snapshot_id,)
            ).fetchone()
        if row is None:
            return None
        if not _snapshot_authority_row_valid(row):
            raise ExecutionReceiptAuthorityError(
                "snapshot source authority does not reconcile with exact persisted bytes"
            )
        raw, binding = _snapshot_binding_from_row(row)
        from cisco_toolkit.protocol_assurance import bind_snapshot_json_bytes
        return (
            bind_snapshot_json_bytes(raw),
            binding,
        )

    def get_bound_snapshot_set(
            self, snapshot_ids: List[int]) -> Optional[Dict[int, Dict[str, Any]]]:
        """Read a distinct persisted source set from one SQLite statement snapshot.

        Failure-trial phase custody must not be assembled from sequential blob and metadata reads:
        a concurrent delete/rebind between those reads would create a source receipt that never
        existed.  This owner returns the exact blob binding and its upload-order witness from the
        same rows and statement.  Callers still re-read under ``BEGIN IMMEDIATE`` before a durable
        execution append.
        """
        if (not isinstance(snapshot_ids, list) or not snapshot_ids
                or any(type(value) is not int or value <= 0 for value in snapshot_ids)
                or len(set(snapshot_ids)) != len(snapshot_ids)):
            raise ValueError("snapshot_ids must be a non-empty list of distinct positive integers")
        placeholders = ",".join("?" for _ in snapshot_ids)
        with self._lock:
            rows = self._conn.execute(
                 f"""SELECT s.id AS snapshot_id, s.campaign_id, i.engagement_id,
                            s.label, s.uploaded_at, s.script_version,
                            CAST(s.snapshot_json AS BLOB) AS snapshot_blob,
                            sa.snapshot_id AS authority_snapshot_id,
                            sa.authority_version AS authority_version,
                            sa.digest_0 AS authority_digest_0,
                            sa.digest_1 AS authority_digest_1,
                            sa.digest_2 AS authority_digest_2,
                            sa.digest_3 AS authority_digest_3
                     FROM snapshots s
                     JOIN campaign_identities i ON i.campaign_id=s.campaign_id
                     LEFT JOIN snapshot_authority sa ON sa.snapshot_id=s.id
                     WHERE s.id IN ({placeholders})""",
                tuple(snapshot_ids),
            ).fetchall()
        if len(rows) != len(snapshot_ids):
            return None
        from cisco_toolkit.protocol_assurance import bind_snapshot_json_bytes

        result: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            if not _snapshot_authority_row_valid(row):
                raise ExecutionReceiptAuthorityError(
                    "snapshot source authority does not reconcile with exact persisted bytes"
                )
            raw, binding = _snapshot_binding_from_row(row)
            result[int(binding["snapshot_id"])] = {
                "snapshot": bind_snapshot_json_bytes(raw),
                "binding": binding,
                "uploaded_at": str(row["uploaded_at"]),
            }
        return result

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
                       WHERE before_snapshot_id=? OR after_snapshot_id=?
                       UNION ALL
                       SELECT 1 FROM execution_l2_failure_trial_sources
                       WHERE pre_failure_snapshot_id=? OR post_failure_snapshot_id=?
                          OR recovery_snapshot_id=?
                       LIMIT 1""",
                    (snapshot_id, snapshot_id, snapshot_id, snapshot_id, snapshot_id),
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
                persisted_started_at_epoch_us = _timestamp_epoch_us(persisted_started_at)
                assert persisted_started_at_epoch_us is not None
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
                comparison_required = int(
                    isinstance(policy, dict)
                    and policy.get("schema") == "execution_comparison_policy/1"
                    and policy.get("canonical_gate_required") is True
                )
                snapshot_id_high_watermark = (
                    int(policy.get("snapshot_id_high_watermark"))
                    if comparison_required
                    and type(policy.get("snapshot_id_high_watermark")) is int
                    else int(snapshot_id)
                )
                cur = self._conn.execute(
                    """INSERT INTO executions(
                           snapshot_id, label, status, started_at, ended_at, state_json,
                           comparison_required, snapshot_id_high_watermark, lifecycle_state,
                           started_at_epoch_us, ended_at_epoch_us)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (snapshot_id, state.get("label", ""), state.get("status", "in_progress"),
                     persisted_started_at, state.get("ended_at"),
                     json.dumps(state, separators=(",", ":")), comparison_required,
                     snapshot_id_high_watermark, 0, persisted_started_at_epoch_us, None),
                )
                execution_id = int(cur.lastrowid or 0)
                self._conn.commit()
                return execution_id
            except Exception:
                self._conn.rollback()
                raise

    def _execution_receipt_authority_locked(
            self, execution_id: int, execution_row: sqlite3.Row,
            state: Dict[str, Any]) -> Dict[str, Any]:
        """Re-authorize the complete append-only comparison history from persisted sources.

        ``executions.state_json`` carries the mutable war-room record, but its latest-gate and L2
        re-trial leaves are caches. SQLite row triggers do not fire for incremental ``blobopen``
        writes, so those leaves may never authorize a read, append, mutation, finish, or PIR. This
        fold runs inside the caller's SQLite transaction, validates every immutable receipt against
        the exact current source bytes, and rebuilds the two decision-bearing mirrors.
        """
        comparison_rows = self._conn.execute(
            """SELECT ec.id, ec.execution_id, ec.before_snapshot_id, ec.after_snapshot_id,
                      ec.receipt_sha256, ec.cutover_verdict, ec.created_at,
                      CAST(ec.receipt_json AS BLOB) AS receipt_blob,
                      ca.comparison_id AS authority_comparison_id,
                      ca.authority_version AS authority_version,
                      ca.verdict_code AS authority_verdict_code,
                      ca.digest_0 AS authority_digest_0,
                      ca.digest_1 AS authority_digest_1,
                      ca.digest_2 AS authority_digest_2,
                      ca.digest_3 AS authority_digest_3
               FROM execution_comparisons ec
               LEFT JOIN execution_comparison_authority ca ON ca.comparison_id=ec.id
               WHERE ec.execution_id=? ORDER BY ec.id ASC""",
            (execution_id,),
        ).fetchall()
        projected = dict(state)
        canonical_required = bool(
            comparison_rows
            or (
                "comparison_required" in execution_row.keys()
                and int(execution_row["comparison_required"]) == 1
            )
        )
        # Column mirrors own the database header, while the INTEGER lifecycle marker owns the
        # closed/open decision. sqlite blobopen can rewrite TEXT (including both state_json and
        # status) without firing triggers, but it cannot open an INTEGER value.
        for field in ("label", "started_at"):
            if field in execution_row.keys():
                projected[field] = execution_row[field]
        try:
            lifecycle_state = int(execution_row["lifecycle_state"])
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ExecutionReceiptAuthorityError(
                "execution lifecycle authority is missing"
            ) from exc
        lifecycle_status = {0: "in_progress", 1: "completed", 2: "aborted"}.get(
            lifecycle_state
        )
        if lifecycle_status is None:
            raise ExecutionReceiptAuthorityError("execution lifecycle authority is invalid")
        projected["status"] = lifecycle_status
        started_at_epoch_us = _timestamp_epoch_us(execution_row["started_at"])
        try:
            durable_started_at_epoch_us = int(execution_row["started_at_epoch_us"])
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ExecutionReceiptAuthorityError(
                "execution start-time authority is missing"
            ) from exc
        if canonical_required and (
            started_at_epoch_us is None
            or durable_started_at_epoch_us <= 0
            or started_at_epoch_us != durable_started_at_epoch_us
        ):
            raise ExecutionReceiptAuthorityError(
                "execution start-time authority does not reconcile"
            )
        if lifecycle_state == 0:
            projected["ended_at"] = None
        else:
            ended_at = execution_row["ended_at"]
            ended_at_epoch_us = _timestamp_epoch_us(ended_at)
            durable_ended_at_epoch_us = execution_row["ended_at_epoch_us"]
            if canonical_required and (
                ended_at_epoch_us is None
                or type(durable_ended_at_epoch_us) is not int
                or ended_at_epoch_us != durable_ended_at_epoch_us
                or (
                    started_at_epoch_us is not None
                    and ended_at_epoch_us < started_at_epoch_us
                )
            ):
                raise ExecutionReceiptAuthorityError(
                    "execution end-time authority does not reconcile"
                )
            projected["ended_at"] = ended_at
        if not comparison_rows:
            if canonical_required:
                source_row = self._conn.execute(
                    """SELECT s.id AS snapshot_id, s.campaign_id, i.engagement_id,
                               s.label, s.uploaded_at, s.script_version,
                               CAST(s.snapshot_json AS BLOB) AS snapshot_blob,
                               sa.snapshot_id AS authority_snapshot_id,
                               sa.authority_version AS authority_version,
                               sa.digest_0 AS authority_digest_0,
                               sa.digest_1 AS authority_digest_1,
                               sa.digest_2 AS authority_digest_2,
                               sa.digest_3 AS authority_digest_3
                        FROM snapshots s
                        JOIN campaign_identities i ON i.campaign_id=s.campaign_id
                        LEFT JOIN snapshot_authority sa ON sa.snapshot_id=s.id
                        WHERE s.id=?""",
                    (int(execution_row["snapshot_id"]),),
                ).fetchone()
                if source_row is None:
                    raise ExecutionReceiptAuthorityError(
                        "canonical execution start snapshot is missing"
                    )
                if not _snapshot_authority_row_valid(source_row):
                    raise ExecutionReceiptAuthorityError(
                        "canonical execution start snapshot authority does not reconcile"
                    )
                _raw, before_binding = _snapshot_binding_from_row(source_row)
                high_watermark = int(execution_row["snapshot_id"])
                if "snapshot_id_high_watermark" in execution_row.keys():
                    high_watermark = int(execution_row["snapshot_id_high_watermark"])
                projected["execution_schema"] = "cutover_execution/2"
                projected["comparison_policy"] = {
                    "schema": "execution_comparison_policy/1",
                    "canonical_gate_required": True,
                    "before_snapshot": before_binding,
                    "snapshot_id_high_watermark": high_watermark,
                }
                projected.pop("latest_comparison", None)
                projected.pop("l2_failure_trial_requirement", None)
            return {
                "state": projected,
                "comparisons": [],
                "latest_comparison": None,
                "l2_failure_trial_requirement": None,
            }

        from . import engine as comparison_engine
        from cisco_toolkit.l2_rehearsal import compute_observed_l2_failure_evidence
        from cisco_toolkit.protocol_assurance import bind_snapshot_json_bytes

        def invalid(detail: str) -> None:
            raise ExecutionReceiptAuthorityError(
                f"execution comparison authority is invalid: {detail}"
            )

        validated: List[Dict[str, Any]] = []
        latest: Optional[Dict[str, Any]] = None
        active_requirement: Optional[Dict[str, Any]] = None
        first_before_binding: Optional[Dict[str, Any]] = None
        previous_after: Optional[Dict[str, Any]] = None

        for comparison_row in comparison_rows:
            receipt_id = int(comparison_row["id"])
            verdict_code = _CUTOVER_VERDICT_CODES.get(str(comparison_row["cutover_verdict"]))
            expected_comparison_authority = _comparison_authority_limbs(
                comparison_id=receipt_id,
                execution_id=comparison_row["execution_id"],
                before_snapshot_id=comparison_row["before_snapshot_id"],
                after_snapshot_id=comparison_row["after_snapshot_id"],
                receipt_sha256=comparison_row["receipt_sha256"],
                cutover_verdict=comparison_row["cutover_verdict"],
                created_at=comparison_row["created_at"],
                receipt_blob=comparison_row["receipt_blob"],
            )
            if (
                verdict_code is None
                or type(comparison_row["authority_comparison_id"]) is not int
                or int(comparison_row["authority_comparison_id"]) != receipt_id
                or type(comparison_row["authority_version"]) is not int
                or int(comparison_row["authority_version"]) != 1
                or type(comparison_row["authority_verdict_code"]) is not int
                or int(comparison_row["authority_verdict_code"]) != verdict_code
                or not _authority_row_matches(
                    comparison_row, expected_comparison_authority
                )
            ):
                invalid(f"receipt {receipt_id} INTEGER authority does not reconcile")
            try:
                receipt = _strict_json_loads(comparison_row["receipt_blob"])
            except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                invalid(f"receipt {receipt_id} JSON cannot be decoded ({exc})")
            if not isinstance(receipt, dict):
                invalid(f"receipt {receipt_id} is not a JSON object")
            unsigned = dict(receipt)
            claimed_hash = unsigned.pop("receipt_sha256", None)
            if (
                receipt.get("schema") != "execution_comparison_receipt/1"
                or not isinstance(claimed_hash, str)
                or claimed_hash != _canonical_receipt_sha256(unsigned)
                or comparison_row["receipt_sha256"] != claimed_hash
            ):
                invalid(f"receipt {receipt_id} outer digest/schema does not reconcile")
            before_id = receipt.get("before_snapshot_id")
            after_id = receipt.get("after_snapshot_id")
            if (
                type(before_id) is not int
                or type(after_id) is not int
                or before_id <= 0
                or after_id <= 0
                or before_id == after_id
                or int(comparison_row["before_snapshot_id"]) != before_id
                or int(comparison_row["after_snapshot_id"]) != after_id
                or int(execution_row["snapshot_id"]) != before_id
            ):
                invalid(f"receipt {receipt_id} snapshot identities do not reconcile")
            comparison = receipt.get("comparison")
            if not _comparison_envelope_valid(comparison):
                invalid(f"receipt {receipt_id} detached comparison envelope is invalid")
            gate = comparison.get("cutover_gate") if isinstance(comparison, dict) else None
            if (
                not isinstance(gate, dict)
                or gate.get("schema") != "cutover_gate/1"
                or comparison_row["cutover_verdict"] != gate.get("verdict")
            ):
                invalid(f"receipt {receipt_id} canonical gate/header does not reconcile")
            implementation_binding = receipt.get("implementation_binding")
            if (
                not isinstance(implementation_binding, dict)
                or implementation_binding.get("schema")
                != "execution_implementation_binding/1"
                or implementation_binding.get("valid") is not True
                or _parse_aware_timestamp(implementation_binding.get("completed_at")) is None
            ):
                invalid(f"receipt {receipt_id} implementation binding is invalid")

            trial_rows = self._conn.execute(
                """SELECT trial.comparison_id, trial.pre_failure_snapshot_id,
                          trial.post_failure_snapshot_id, trial.recovery_snapshot_id,
                          CAST(trial.witness_blob AS BLOB) AS witness_blob,
                          trial.witness_sha256, trial.source,
                          trial.campaign_id, trial.engagement_id,
                          ta.comparison_id AS authority_trial_comparison_id,
                          ta.authority_version AS authority_version,
                          ta.source_code AS authority_source_code,
                          ta.digest_0 AS authority_digest_0,
                          ta.digest_1 AS authority_digest_1,
                          ta.digest_2 AS authority_digest_2,
                          ta.digest_3 AS authority_digest_3
                   FROM execution_l2_failure_trial_sources trial
                   LEFT JOIN execution_l2_failure_trial_authority ta
                     ON ta.comparison_id=trial.comparison_id
                   WHERE trial.comparison_id=?""",
                (receipt_id,),
            ).fetchall()
            if len(trial_rows) > 1:
                invalid(f"receipt {receipt_id} has multiple observed-trial source rows")
            trial_row = trial_rows[0] if trial_rows else None
            operator_evidence = comparison.get("operator_evidence") \
                if isinstance(comparison, dict) else None
            rehearsal = operator_evidence.get("rehearsal") \
                if isinstance(operator_evidence, dict) else None
            observed_claim = rehearsal.get("observed_l2_failure_evidence") \
                if isinstance(rehearsal, dict) else None
            if isinstance(observed_claim, dict) != (trial_row is not None):
                invalid(f"receipt {receipt_id} observed claim/source-row presence differs")

            trial_ids: Optional[tuple[int, int, int]] = None
            witness_bytes = b""
            source_ids = [before_id, after_id]
            if trial_row is not None:
                expected_trial_authority = _trial_authority_limbs(
                    comparison_id=trial_row["comparison_id"],
                    pre_failure_snapshot_id=trial_row["pre_failure_snapshot_id"],
                    post_failure_snapshot_id=trial_row["post_failure_snapshot_id"],
                    recovery_snapshot_id=trial_row["recovery_snapshot_id"],
                    witness_blob=trial_row["witness_blob"],
                    witness_sha256=trial_row["witness_sha256"],
                    source=trial_row["source"],
                    campaign_id=trial_row["campaign_id"],
                    engagement_id=trial_row["engagement_id"],
                )
                if (
                    type(trial_row["authority_trial_comparison_id"]) is not int
                    or int(trial_row["authority_trial_comparison_id"]) != receipt_id
                    or type(trial_row["authority_version"]) is not int
                    or int(trial_row["authority_version"]) != 1
                    or type(trial_row["authority_source_code"]) is not int
                    or int(trial_row["authority_source_code"]) != _TRIAL_SOURCE_CODE
                    or not _authority_row_matches(trial_row, expected_trial_authority)
                ):
                    invalid(f"receipt {receipt_id} observed-trial INTEGER authority differs")
                trial_ids = (
                    int(trial_row["pre_failure_snapshot_id"]),
                    int(trial_row["post_failure_snapshot_id"]),
                    int(trial_row["recovery_snapshot_id"]),
                )
                if trial_ids[2] != after_id or len({before_id, *trial_ids}) != 4:
                    invalid(f"receipt {receipt_id} observed phase identities are invalid")
                witness_bytes = _snapshot_blob_bytes(trial_row["witness_blob"])
                if (
                    not witness_bytes
                    or len(witness_bytes) > 64 * 1024
                    or trial_row["witness_sha256"]
                    != "sha256:" + hashlib.sha256(witness_bytes).hexdigest()
                    or trial_row["source"] != _SNAPSHOT_BINDING_SOURCE
                ):
                    invalid(f"receipt {receipt_id} observed witness custody is invalid")
                source_ids = [before_id, *trial_ids]

            placeholders = ",".join("?" for _ in source_ids)
            source_rows = self._conn.execute(
                f"""SELECT s.id AS snapshot_id, s.campaign_id, i.engagement_id,
                           s.label, s.uploaded_at, s.script_version,
                           CAST(s.snapshot_json AS BLOB) AS snapshot_blob,
                           sa.snapshot_id AS authority_snapshot_id,
                           sa.authority_version AS authority_version,
                           sa.digest_0 AS authority_digest_0,
                           sa.digest_1 AS authority_digest_1,
                           sa.digest_2 AS authority_digest_2,
                           sa.digest_3 AS authority_digest_3
                    FROM snapshots s
                    JOIN campaign_identities i ON i.campaign_id=s.campaign_id
                    LEFT JOIN snapshot_authority sa ON sa.snapshot_id=s.id
                    WHERE s.id IN ({placeholders})""",
                tuple(source_ids),
            ).fetchall()
            if len(source_rows) != len(source_ids):
                invalid(f"receipt {receipt_id} is missing a bound snapshot source")
            rows_by_id = {int(row["snapshot_id"]): row for row in source_rows}
            bindings: Dict[int, Dict[str, Any]] = {}
            snapshots: Dict[int, Dict[str, Any]] = {}
            for source_row in source_rows:
                if not _snapshot_authority_row_valid(source_row):
                    invalid(f"receipt {receipt_id} snapshot INTEGER authority differs")
                raw_source, binding = _snapshot_binding_from_row(source_row)
                try:
                    snapshot = bind_snapshot_json_bytes(raw_source)
                except (TypeError, ValueError, UnicodeDecodeError) as exc:
                    invalid(f"receipt {receipt_id} source JSON is invalid ({exc})")
                if not isinstance(snapshot, dict):
                    invalid(f"receipt {receipt_id} source JSON is not an object")
                bindings[binding["snapshot_id"]] = binding
                snapshots[binding["snapshot_id"]] = snapshot
            before_binding = bindings[before_id]
            after_binding = bindings[after_id]
            if (
                before_binding["campaign_id"] != after_binding["campaign_id"]
                or before_binding["engagement_id"] != after_binding["engagement_id"]
            ):
                invalid(f"receipt {receipt_id} before/after context differs")
            if first_before_binding is None:
                first_before_binding = before_binding
            elif not _canonical_json_identity_matches(first_before_binding, before_binding):
                invalid(f"receipt {receipt_id} changed the execution before binding")

            if trial_row is not None and trial_ids is not None:
                if (
                    int(trial_row["campaign_id"]) != before_binding["campaign_id"]
                    or trial_row["engagement_id"] != before_binding["engagement_id"]
                    or any(
                        bindings[phase_id]["campaign_id"] != before_binding["campaign_id"]
                        or bindings[phase_id]["engagement_id"]
                        != before_binding["engagement_id"]
                        for phase_id in trial_ids
                    )
                ):
                    invalid(f"receipt {receipt_id} observed phase context differs")

            intent = comparison.get("change_intent")
            intent_status = intent.get("status") if isinstance(intent, dict) else None
            if intent_status == "not_supplied":
                intent_request = None
            elif intent_status == "reconciled":
                intent_request = {
                    "expected_changes": intent.get("expected_changes"),
                    "note": intent.get("note"),
                }
            else:
                invalid(f"receipt {receipt_id} change intent cannot be replayed")

            canonical_trial = None
            phase_sources: Optional[Dict[str, Dict[str, Any]]] = None
            incoming_observed: Optional[Dict[str, Any]] = None
            if trial_row is not None and trial_ids is not None:
                custody = {
                    phase: {
                        "source": bindings[phase_id]["source"],
                        "source_id": f"snapshot:{phase_id}",
                        "campaign_id": bindings[phase_id]["campaign_id"],
                        "engagement_id": bindings[phase_id]["engagement_id"],
                        "custody_at": rows_by_id[phase_id]["uploaded_at"],
                    }
                    for phase, phase_id in zip(
                        ("pre_failure", "post_failure", "recovery"), trial_ids
                    )
                }
                canonical_trial = compute_observed_l2_failure_evidence(
                    snapshots[trial_ids[0]],
                    snapshots[trial_ids[1]],
                    snapshots[trial_ids[2]],
                    witness_bytes=witness_bytes,
                    phase_custody=custody,
                )

            canonical_comparison = comparison_engine.compare_bound_pair(
                snapshots[before_id],
                snapshots[after_id],
                before_binding=before_binding,
                after_binding=after_binding,
                change_intent=intent_request,
                l2_failure_trial=canonical_trial,
            )
            if not _canonical_json_identity_matches(comparison, canonical_comparison):
                invalid(f"receipt {receipt_id} does not match exact-source recomputation")
            if receipt.get("after_collected_at") != snapshots[after_id].get("collected_at"):
                invalid(f"receipt {receipt_id} after collection binding differs")
            canonical_receipt = comparison_engine.compact_execution_comparison(
                canonical_comparison,
                before_snapshot_id=before_id,
                after_snapshot_id=after_id,
                after_collected_at=snapshots[after_id].get("collected_at"),
                implementation_binding=implementation_binding,
            )
            if not _canonical_json_identity_matches(receipt, canonical_receipt):
                invalid(f"receipt {receipt_id} outer payload does not match recomputation")

            run_started = _parse_aware_timestamp(execution_row["started_at"])
            before_uploaded = _parse_aware_timestamp(rows_by_id[before_id]["uploaded_at"])
            after_uploaded = _parse_aware_timestamp(rows_by_id[after_id]["uploaded_at"])
            after_collected = _parse_aware_timestamp(snapshots[after_id].get("collected_at"))
            implementation_completed = _parse_aware_timestamp(
                implementation_binding.get("completed_at")
            )
            if (
                run_started is None
                or before_uploaded is None
                or after_uploaded is None
                or after_collected is None
                or implementation_completed is None
                or before_uploaded > run_started
                or after_uploaded <= run_started
                or after_uploaded <= before_uploaded
                or after_collected <= run_started
                or after_collected <= implementation_completed
                or after_collected > after_uploaded
            ):
                invalid(f"receipt {receipt_id} source chronology is invalid")
            if (
                previous_after is not None
                and previous_after.get("implementation_binding") == implementation_binding
                and (
                    after_id <= previous_after["snapshot_id"]
                    or after_collected <= previous_after["collected_at"]
                    or after_uploaded <= previous_after["uploaded_at"]
                )
            ):
                invalid(f"receipt {receipt_id} regressed latest evidence chronology")

            if trial_row is not None and trial_ids is not None:
                try:
                    witness_value = _strict_json_loads(witness_bytes)
                except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    witness_value = None
                induced = _parse_aware_timestamp(
                    witness_value.get("induced_at")
                    if isinstance(witness_value, dict) else None
                )
                trial_collected = [
                    _parse_aware_timestamp(snapshots[phase_id].get("collected_at"))
                    for phase_id in trial_ids
                ]
                trial_uploaded = [
                    _parse_aware_timestamp(rows_by_id[phase_id]["uploaded_at"])
                    for phase_id in trial_ids
                ]
                if (
                    induced is None
                    or any(value is None for value in (*trial_collected, *trial_uploaded))
                    or not (before_id < trial_ids[0] < trial_ids[1] < trial_ids[2])
                    or not (
                        implementation_completed < trial_collected[0]
                        < induced < trial_collected[1] < trial_collected[2]
                    )
                    or not (
                        implementation_completed < trial_uploaded[0]
                        < trial_uploaded[1] < trial_uploaded[2]
                    )
                    or any(
                        collected > uploaded
                        for collected, uploaded in zip(trial_collected, trial_uploaded)
                    )
                ):
                    invalid(f"receipt {receipt_id} observed phase chronology is invalid")
                canonical_gate = canonical_comparison.get("cutover_gate")
                canonical_gate = canonical_gate if isinstance(canonical_gate, dict) else {}
                incoming_observed = {
                    "family": canonical_gate.get("l2_observed_trial_family"),
                    "subject": canonical_gate.get("l2_observed_trial_subject"),
                    "failure_scenario": canonical_gate.get("l2_observed_trial_scenario"),
                    "status": canonical_gate.get("l2_observed_trial_status"),
                }
                phase_sources = {
                    phase: {
                        "snapshot_id": phase_id,
                        "collected_at": snapshots[phase_id].get("collected_at"),
                        "uploaded_at": rows_by_id[phase_id]["uploaded_at"],
                    }
                    for phase, phase_id in zip(
                        ("pre_failure", "post_failure", "recovery"), trial_ids
                    )
                }

            def requirement_for(status: str) -> Dict[str, Any]:
                assert incoming_observed is not None and phase_sources is not None
                return {
                    "schema": "execution_l2_failure_trial_requirement/1",
                    "family": incoming_observed["family"],
                    "subject": incoming_observed["subject"],
                    "failure_scenario": incoming_observed["failure_scenario"],
                    "status": status,
                    "phase_sources": phase_sources,
                    "latest_receipt_id": receipt_id,
                }

            if active_requirement is not None:
                # Older stores may contain receipts appended before the monotone re-trial ratchet
                # was introduced. An ordinary PASS, a different scenario, or a replayed stale
                # survival in that history is not proof that the original local failure vanished.
                # Keep the active anchor; only an exact, strictly newer trial may update/clear it.
                exact_retrial = bool(
                    incoming_observed is not None
                    and phase_sources is not None
                    and all(
                        incoming_observed.get(field) == active_requirement.get(field)
                        for field in ("family", "subject", "failure_scenario")
                    )
                )
                if exact_retrial:
                    active_recovery = active_requirement["phase_sources"]["recovery"]
                    incoming_pre = phase_sources["pre_failure"]
                    retrial_is_newer = bool(
                        incoming_pre["snapshot_id"] > active_recovery["snapshot_id"]
                        and _parse_aware_timestamp(incoming_pre["collected_at"])
                        > _parse_aware_timestamp(active_recovery["collected_at"])
                        and _parse_aware_timestamp(incoming_pre["uploaded_at"])
                        > _parse_aware_timestamp(active_recovery["uploaded_at"])
                    )
                    if retrial_is_newer:
                        observed_status = incoming_observed.get("status")
                        if observed_status == "observed_survival":
                            active_requirement = None
                        elif observed_status in {"observed_failure", "not_verified"}:
                            retained_status = (
                                "observed_failure"
                                if active_requirement.get("status") == "observed_failure"
                                or observed_status == "observed_failure"
                                else "not_verified"
                            )
                            active_requirement = requirement_for(retained_status)
                        else:
                            invalid(f"receipt {receipt_id} has an invalid observed L2 status")
            elif incoming_observed is not None:
                observed_status = incoming_observed.get("status")
                if observed_status in {"observed_failure", "not_verified"}:
                    active_requirement = requirement_for(observed_status)
                elif observed_status != "observed_survival":
                    invalid(f"receipt {receipt_id} has an invalid observed L2 status")

            canonical_gate = canonical_comparison["cutover_gate"]
            latest = {
                "schema": "execution_latest_comparison/1",
                "receipt_id": receipt_id,
                "receipt_sha256": claimed_hash,
                "before_snapshot_id": before_id,
                "after_snapshot_id": after_id,
                "after_collected_at": snapshots[after_id].get("collected_at"),
                "after_uploaded_at": rows_by_id[after_id]["uploaded_at"],
                "implementation_binding": implementation_binding,
                "cutover_gate": dict(canonical_gate),
            }
            previous_after = {
                "snapshot_id": after_id,
                "collected_at": after_collected,
                "uploaded_at": after_uploaded,
                "implementation_binding": implementation_binding,
            }
            item = {
                key: comparison_row[key]
                for key in (
                    "id", "execution_id", "before_snapshot_id", "after_snapshot_id",
                    "receipt_sha256", "cutover_verdict", "created_at",
                )
            }
            item["receipt"] = receipt
            validated.append(item)

        assert latest is not None and first_before_binding is not None
        high_watermark = (
            int(execution_row["snapshot_id_high_watermark"])
            if "snapshot_id_high_watermark" in execution_row.keys()
            else int(execution_row["snapshot_id"])
        )
        projected["execution_schema"] = "cutover_execution/2"
        projected["comparison_policy"] = {
            "schema": "execution_comparison_policy/1",
            "canonical_gate_required": True,
            "before_snapshot": first_before_binding,
            "snapshot_id_high_watermark": high_watermark,
        }
        projected["latest_comparison"] = latest
        if active_requirement is None:
            projected.pop("l2_failure_trial_requirement", None)
        else:
            projected["l2_failure_trial_requirement"] = active_requirement
        return {
            "state": projected,
            "comparisons": validated,
            "latest_comparison": latest,
            "l2_failure_trial_requirement": active_requirement,
        }

    def get_execution(self, execution_id: int) -> Optional[Dict[str, Any]]:
        """{'id', 'snapshot_id', 'state'} or None."""
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                row = self._conn.execute(
                    """SELECT id, snapshot_id, label, status, started_at, ended_at, state_json,
                              comparison_required, snapshot_id_high_watermark, lifecycle_state,
                              started_at_epoch_us, ended_at_epoch_us
                       FROM executions WHERE id = ?""",
                    (execution_id,),
                ).fetchone()
                if not row:
                    self._conn.rollback()
                    return None
                try:
                    state = _strict_json_loads(row["state_json"])
                except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ExecutionReceiptAuthorityError(
                        f"execution state JSON is invalid: {exc}"
                    ) from exc
                if not isinstance(state, dict):
                    raise ExecutionReceiptAuthorityError(
                        "execution state JSON is not an object"
                    )
                authority = self._execution_receipt_authority_locked(
                    execution_id, row, state
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return {
            "id": row["id"],
            "snapshot_id": row["snapshot_id"],
            "state": authority["state"],
            "_state_json": row["state_json"],
            "comparisons": authority["comparisons"],
        }

    def list_execution_comparisons(self, execution_id: int) -> List[Dict[str, Any]]:
        """Return only receipts re-authorized from one coherent SQLite read snapshot."""
        rec = self.get_execution(execution_id)
        return list(rec.get("comparisons") or []) if rec else []

    def append_execution_comparison_if_unchanged(
            self, execution_id: int, expected_state_json: str,
            receipt: Dict[str, Any], *,
            l2_failure_trial_source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        operator_evidence = comparison.get("operator_evidence")
        rehearsal = operator_evidence.get("rehearsal") \
            if isinstance(operator_evidence, dict) else None
        observed_claim = rehearsal.get("observed_l2_failure_evidence") \
            if isinstance(rehearsal, dict) else None
        has_observed_claim = isinstance(observed_claim, dict)
        if has_observed_claim != isinstance(l2_failure_trial_source, dict):
            raise ValueError(
                "observed execution evidence requires its independent persisted trial source"
            )
        trial_source = dict(l2_failure_trial_source or {})
        trial_snapshot_ids: tuple[int, int, int] | None = None
        trial_witness = b""
        if has_observed_claim:
            pre_failure_snapshot_id = trial_source.get("pre_failure_snapshot_id")
            post_failure_snapshot_id = trial_source.get("post_failure_snapshot_id")
            recovery_snapshot_id = trial_source.get("recovery_snapshot_id")
            if (
                trial_source.get("schema") != "stored_l2_failure_trial_source/1"
                or any(
                    type(value) is not int or value <= 0
                    for value in (
                        pre_failure_snapshot_id,
                        post_failure_snapshot_id,
                        recovery_snapshot_id,
                    )
                )
                or len({
                    before_snapshot_id,
                    pre_failure_snapshot_id,
                    post_failure_snapshot_id,
                    recovery_snapshot_id,
                }) != 4
                or recovery_snapshot_id != after_snapshot_id
            ):
                raise ValueError("execution L2 failure-trial snapshot identities are invalid")
            raw_witness = trial_source.get("witness_bytes")
            if not isinstance(raw_witness, (bytes, bytearray, memoryview)):
                raise ValueError("execution L2 failure-trial witness bytes are missing")
            trial_witness = bytes(raw_witness)
            if not trial_witness or len(trial_witness) > 64 * 1024:
                raise ValueError("execution L2 failure-trial witness bytes are invalid")
            if trial_source.get("witness_sha256") != (
                "sha256:" + hashlib.sha256(trial_witness).hexdigest()
            ):
                raise ValueError("execution L2 failure-trial witness digest is invalid")
            trial_snapshot_ids = (
                pre_failure_snapshot_id,
                post_failure_snapshot_id,
                recovery_snapshot_id,
            )
        encoded_receipt = json.dumps(receipt, separators=(",", ":"), allow_nan=False)
        created_at = _now()
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    """SELECT id, snapshot_id, label, status, started_at, ended_at, state_json,
                              comparison_required, snapshot_id_high_watermark, lifecycle_state,
                              started_at_epoch_us, ended_at_epoch_us
                       FROM executions WHERE id=?""",
                    (execution_id,),
                ).fetchone()
                if row is None:
                    self._conn.rollback()
                    return {"status": "missing"}
                if row["state_json"] != expected_state_json:
                    self._conn.rollback()
                    return {"status": "conflict"}
                if int(row["lifecycle_state"]) != 0:
                    self._conn.rollback()
                    return {"status": "closed"}
                if int(row["snapshot_id"]) != before_snapshot_id:
                    self._conn.rollback()
                    return {"status": "identity_mismatch"}
                try:
                    state = _strict_json_loads(row["state_json"])
                except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    self._conn.rollback()
                    return {"status": "authority_invalid"}
                if not isinstance(state, dict):
                    self._conn.rollback()
                    return {"status": "authority_invalid"}
                try:
                    authority = self._execution_receipt_authority_locked(
                        execution_id, row, state
                    )
                except ExecutionReceiptAuthorityError:
                    self._conn.rollback()
                    return {"status": "authority_invalid"}
                state = authority["state"]
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

                # Re-read every source row while the write transaction is held. Snapshot blobs are
                # immutable through the API, but another process can delete a row between the
                # route's initial read and this append. Binding to the rows again here ensures the
                # receipt is admitted only while the exact source bytes and custody identities it
                # names still exist. The same check catches an internally miswired/rehashed receipt.
                if before_snapshot_id == after_snapshot_id:
                    self._conn.rollback()
                    return {"status": "source_mismatch"}
                source_ids = (
                    [before_snapshot_id, *trial_snapshot_ids]
                    if trial_snapshot_ids is not None
                    else [before_snapshot_id, after_snapshot_id]
                )
                placeholders = ",".join("?" for _ in source_ids)
                source_rows = self._conn.execute(
                    f"""SELECT s.id AS snapshot_id, s.campaign_id, i.engagement_id,
                               s.label, s.uploaded_at, s.script_version,
                               CAST(s.snapshot_json AS BLOB) AS snapshot_blob,
                               sa.snapshot_id AS authority_snapshot_id,
                               sa.authority_version AS authority_version,
                               sa.digest_0 AS authority_digest_0,
                               sa.digest_1 AS authority_digest_1,
                               sa.digest_2 AS authority_digest_2,
                               sa.digest_3 AS authority_digest_3
                        FROM snapshots s
                        JOIN campaign_identities i ON i.campaign_id=s.campaign_id
                        LEFT JOIN snapshot_authority sa ON sa.snapshot_id=s.id
                        WHERE s.id IN ({placeholders})""",
                    tuple(source_ids),
                ).fetchall()
                if len(source_rows) != len(source_ids):
                    self._conn.rollback()
                    return {"status": "source_missing"}
                current_bindings: Dict[int, Dict[str, Any]] = {}
                current_snapshots: Dict[int, Dict[str, Any]] = {}
                for source_row in source_rows:
                    if not _snapshot_authority_row_valid(source_row):
                        self._conn.rollback()
                        return {"status": "authority_invalid"}
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
                if trial_snapshot_ids is not None:
                    trial_bindings = [
                        current_bindings.get(snapshot_id)
                        for snapshot_id in trial_snapshot_ids
                    ]
                    if (
                        any(binding is None for binding in trial_bindings)
                        or any(
                            binding.get("source") != _SNAPSHOT_BINDING_SOURCE
                            or binding.get("campaign_id") != before_binding["campaign_id"]
                            or binding.get("engagement_id") != before_binding["engagement_id"]
                            for binding in trial_bindings
                            if isinstance(binding, dict)
                        )
                        or trial_source.get("source") != _SNAPSHOT_BINDING_SOURCE
                        or trial_source.get("campaign_id") != before_binding["campaign_id"]
                        or trial_source.get("engagement_id") != before_binding["engagement_id"]
                    ):
                        self._conn.rollback()
                        return {"status": "source_mismatch"}

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
                latest_chronology_invalid = False
                latest_comparison = state.get("latest_comparison")
                if (
                    isinstance(latest_comparison, dict)
                    and latest_comparison.get("implementation_binding")
                    == implementation_binding
                ):
                    latest_after_id = latest_comparison.get("after_snapshot_id")
                    latest_collected_at = _parse_aware_timestamp(
                        latest_comparison.get("after_collected_at")
                    )
                    latest_source_row = (
                        self._conn.execute(
                            "SELECT uploaded_at FROM snapshots WHERE id=?",
                            (latest_after_id,),
                        ).fetchone()
                        if type(latest_after_id) is int else None
                    )
                    latest_uploaded_at = _parse_aware_timestamp(
                        latest_source_row["uploaded_at"]
                        if latest_source_row is not None else None
                    )
                    latest_chronology_invalid = bool(
                        type(latest_after_id) is not int
                        or latest_collected_at is None
                        or latest_uploaded_at is None
                        or after_snapshot_id <= latest_after_id
                        or after_collected_at is None
                        or after_uploaded_at is None
                        or after_collected_at <= latest_collected_at
                        or after_uploaded_at <= latest_uploaded_at
                    )
                trial_chronology_invalid = False
                if trial_snapshot_ids is not None:
                    pre_id, post_id, recovery_id = trial_snapshot_ids
                    pre_row = source_by_id.get(pre_id)
                    post_row = source_by_id.get(post_id)
                    recovery_row = source_by_id.get(recovery_id)
                    pre_snapshot = current_snapshots.get(pre_id)
                    post_snapshot = current_snapshots.get(post_id)
                    recovery_snapshot = current_snapshots.get(recovery_id)
                    trial_uploaded = [
                        _parse_aware_timestamp(
                            phase_row["uploaded_at"] if phase_row is not None else None
                        )
                        for phase_row in (pre_row, post_row, recovery_row)
                    ]
                    trial_collected = [
                        _parse_aware_timestamp(
                            phase_snapshot.get("collected_at")
                            if isinstance(phase_snapshot, dict) else None
                        )
                        for phase_snapshot in (pre_snapshot, post_snapshot, recovery_snapshot)
                    ]
                    try:
                        from cisco_toolkit.protocol_assurance import reject_duplicate_json_keys

                        witness_value = json.loads(
                            trial_witness.decode("utf-8"),
                            object_pairs_hook=reject_duplicate_json_keys,
                        )
                    except (UnicodeDecodeError, ValueError):
                        witness_value = None
                    induced_at = _parse_aware_timestamp(
                        witness_value.get("induced_at")
                        if isinstance(witness_value, dict) else None
                    )
                    complete_times = (
                        implementation_completed_at,
                        induced_at,
                        *trial_uploaded,
                        *trial_collected,
                    )
                    trial_chronology_invalid = bool(
                        any(value is None for value in complete_times)
                        or not (snapshot_id_high_watermark < pre_id < post_id < recovery_id)
                        or not (
                            implementation_completed_at < trial_collected[0]
                            < induced_at < trial_collected[1] < trial_collected[2]
                        )
                        or not (
                            implementation_completed_at < trial_uploaded[0]
                            < trial_uploaded[1] < trial_uploaded[2]
                        )
                        or any(
                            collected > uploaded
                            for collected, uploaded in zip(trial_collected, trial_uploaded)
                        )
                    )
                if latest_chronology_invalid:
                    self._conn.rollback()
                    return {"status": "comparison_not_newer"}
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
                    or trial_chronology_invalid
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

                canonical_l2_trial = None
                if trial_snapshot_ids is not None:
                    from cisco_toolkit.l2_rehearsal import (
                        compute_observed_l2_failure_evidence,
                    )

                    pre_id, post_id, recovery_id = trial_snapshot_ids
                    custody = {
                        phase: {
                            "source": current_bindings[snapshot_id]["source"],
                            "source_id": f"snapshot:{snapshot_id}",
                            "campaign_id": current_bindings[snapshot_id]["campaign_id"],
                            "engagement_id": current_bindings[snapshot_id]["engagement_id"],
                            "custody_at": source_by_id[snapshot_id]["uploaded_at"],
                        }
                        for phase, snapshot_id in (
                            ("pre_failure", pre_id),
                            ("post_failure", post_id),
                            ("recovery", recovery_id),
                        )
                    }
                    canonical_l2_trial = compute_observed_l2_failure_evidence(
                        current_snapshots[pre_id],
                        current_snapshots[post_id],
                        current_snapshots[recovery_id],
                        witness_bytes=trial_witness,
                        phase_custody=custody,
                    )

                canonical_comparison = comparison_engine.compare_bound_pair(
                    current_snapshots[before_snapshot_id],
                    current_snapshots[after_snapshot_id],
                    before_binding=before_binding,
                    after_binding=after_binding,
                    change_intent=intent_request,
                    l2_failure_trial=canonical_l2_trial,
                )
                if not _canonical_json_identity_matches(comparison, canonical_comparison):
                    self._conn.rollback()
                    return {"status": "comparison_mismatch"}
                canonical_gate = canonical_comparison.get("cutover_gate")
                canonical_gate = canonical_gate if isinstance(canonical_gate, dict) else {}
                incoming_observed = {
                    "family": canonical_gate.get("l2_observed_trial_family"),
                    "subject": canonical_gate.get("l2_observed_trial_subject"),
                    "failure_scenario": canonical_gate.get("l2_observed_trial_scenario"),
                    "status": canonical_gate.get("l2_observed_trial_status"),
                } if trial_snapshot_ids is not None else None
                incoming_phase_sources = None
                if trial_snapshot_ids is not None:
                    incoming_phase_sources = {
                        phase: {
                            "snapshot_id": snapshot_id,
                            "collected_at": current_snapshots[snapshot_id].get("collected_at"),
                            "uploaded_at": source_by_id[snapshot_id]["uploaded_at"],
                        }
                        for phase, snapshot_id in zip(
                            ("pre_failure", "post_failure", "recovery"),
                            trial_snapshot_ids,
                        )
                    }

                def observed_requirement(status: str) -> Dict[str, Any]:
                    return {
                        "schema": "execution_l2_failure_trial_requirement/1",
                        "family": incoming_observed["family"],
                        "subject": incoming_observed["subject"],
                        "failure_scenario": incoming_observed["failure_scenario"],
                        "status": status,
                        "phase_sources": incoming_phase_sources,
                    }

                active_trial_requirement = state.get("l2_failure_trial_requirement")
                if isinstance(active_trial_requirement, dict):
                    exact_retrial = bool(
                        isinstance(incoming_observed, dict)
                        and all(
                            incoming_observed.get(field)
                            == active_trial_requirement.get(field)
                            for field in ("family", "subject", "failure_scenario")
                        )
                    )
                    if not exact_retrial:
                        self._conn.rollback()
                        return {"status": "l2_trial_required"}
                    active_phases = active_trial_requirement.get("phase_sources")
                    active_recovery = active_phases.get("recovery") \
                        if isinstance(active_phases, dict) else None
                    incoming_pre = incoming_phase_sources.get("pre_failure") \
                        if isinstance(incoming_phase_sources, dict) else None
                    active_recovery_collected = _parse_aware_timestamp(
                        active_recovery.get("collected_at")
                        if isinstance(active_recovery, dict) else None
                    )
                    active_recovery_uploaded = _parse_aware_timestamp(
                        active_recovery.get("uploaded_at")
                        if isinstance(active_recovery, dict) else None
                    )
                    incoming_pre_collected = _parse_aware_timestamp(
                        incoming_pre.get("collected_at")
                        if isinstance(incoming_pre, dict) else None
                    )
                    incoming_pre_uploaded = _parse_aware_timestamp(
                        incoming_pre.get("uploaded_at")
                        if isinstance(incoming_pre, dict) else None
                    )
                    retrial_is_newer = bool(
                        isinstance(active_recovery, dict)
                        and isinstance(incoming_pre, dict)
                        and type(active_recovery.get("snapshot_id")) is int
                        and type(incoming_pre.get("snapshot_id")) is int
                        and incoming_pre["snapshot_id"] > active_recovery["snapshot_id"]
                        and active_recovery_collected is not None
                        and active_recovery_uploaded is not None
                        and incoming_pre_collected is not None
                        and incoming_pre_uploaded is not None
                        and incoming_pre_collected > active_recovery_collected
                        and incoming_pre_uploaded > active_recovery_uploaded
                    )
                    if not retrial_is_newer:
                        self._conn.rollback()
                        return {"status": "l2_trial_required"}
                    if incoming_observed.get("status") == "observed_survival":
                        state.pop("l2_failure_trial_requirement", None)
                    elif incoming_observed.get("status") in {
                        "observed_failure", "not_verified"
                    }:
                        retained_status = (
                            "observed_failure"
                            if (
                                active_trial_requirement.get("status") == "observed_failure"
                                or incoming_observed.get("status") == "observed_failure"
                            ) else "not_verified"
                        )
                        state["l2_failure_trial_requirement"] = observed_requirement(
                            retained_status
                        )
                    else:
                        self._conn.rollback()
                        return {"status": "l2_trial_required"}
                elif (
                    isinstance(incoming_observed, dict)
                    and incoming_observed.get("status") in {
                        "observed_failure", "not_verified"
                    }
                ):
                    state["l2_failure_trial_requirement"] = observed_requirement(
                        incoming_observed["status"]
                    )
                cur = self._conn.execute(
                    """INSERT INTO execution_comparisons(
                           execution_id, before_snapshot_id, after_snapshot_id, receipt_sha256,
                           cutover_verdict, created_at, receipt_json)
                       VALUES (?,?,?,?,?,?,?)""",
                    (execution_id, before_snapshot_id, after_snapshot_id, claimed_hash,
                     verdict, created_at, encoded_receipt),
                )
                receipt_id = int(cur.lastrowid or 0)
                verdict_code = _CUTOVER_VERDICT_CODES.get(str(verdict))
                if verdict_code is None:
                    self._conn.rollback()
                    return {"status": "authority_invalid"}
                comparison_limbs = _comparison_authority_limbs(
                    comparison_id=receipt_id,
                    execution_id=execution_id,
                    before_snapshot_id=before_snapshot_id,
                    after_snapshot_id=after_snapshot_id,
                    receipt_sha256=claimed_hash,
                    cutover_verdict=verdict,
                    created_at=created_at,
                    receipt_blob=encoded_receipt.encode("utf-8"),
                )
                self._conn.execute(
                    """INSERT INTO execution_comparison_authority(
                           comparison_id,authority_version,verdict_code,
                           digest_0,digest_1,digest_2,digest_3)
                       VALUES (?,?,?,?,?,?,?)""",
                    (receipt_id, 1, verdict_code, *comparison_limbs),
                )
                active_requirement = state.get("l2_failure_trial_requirement")
                if isinstance(active_requirement, dict):
                    active_requirement["latest_receipt_id"] = receipt_id
                if trial_snapshot_ids is not None:
                    pre_id, post_id, recovery_id = trial_snapshot_ids
                    self._conn.execute(
                        """INSERT INTO execution_l2_failure_trial_sources(
                               comparison_id, pre_failure_snapshot_id,
                               post_failure_snapshot_id, recovery_snapshot_id,
                               witness_blob, witness_sha256, source, campaign_id, engagement_id)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            receipt_id,
                            pre_id,
                            post_id,
                            recovery_id,
                            sqlite3.Binary(trial_witness),
                            trial_source["witness_sha256"],
                            _SNAPSHOT_BINDING_SOURCE,
                            before_binding["campaign_id"],
                            before_binding["engagement_id"],
                        ),
                    )
                    trial_limbs = _trial_authority_limbs(
                        comparison_id=receipt_id,
                        pre_failure_snapshot_id=pre_id,
                        post_failure_snapshot_id=post_id,
                        recovery_snapshot_id=recovery_id,
                        witness_blob=trial_witness,
                        witness_sha256=trial_source["witness_sha256"],
                        source=_SNAPSHOT_BINDING_SOURCE,
                        campaign_id=before_binding["campaign_id"],
                        engagement_id=before_binding["engagement_id"],
                    )
                    self._conn.execute(
                        """INSERT INTO execution_l2_failure_trial_authority(
                               comparison_id,authority_version,source_code,
                               digest_0,digest_1,digest_2,digest_3)
                           VALUES (?,?,?,?,?,?,?)""",
                        (receipt_id, 1, _TRIAL_SOURCE_CODE, *trial_limbs),
                    )
                state["latest_comparison"] = {
                    "schema": "execution_latest_comparison/1",
                    "receipt_id": receipt_id,
                    "receipt_sha256": claimed_hash,
                    "before_snapshot_id": before_snapshot_id,
                    "after_snapshot_id": after_snapshot_id,
                    "after_collected_at": after_snapshot.get("collected_at"),
                    "after_uploaded_at": after_row["uploaded_at"],
                    "implementation_binding": implementation_binding,
                    "cutover_gate": dict(gate),
                }
                encoded_state = json.dumps(state, separators=(",", ":"), allow_nan=False)
                changed = self._conn.execute(
                    """UPDATE executions SET state_json=?, status='in_progress'
                       WHERE id=? AND lifecycle_state=0 AND state_json=?""",
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
        """CAS a mutable run while reapplying receipt-derived decision authority."""
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    """SELECT id, snapshot_id, label, status, started_at, ended_at, state_json,
                              comparison_required, snapshot_id_high_watermark, lifecycle_state,
                              started_at_epoch_us, ended_at_epoch_us
                       FROM executions WHERE id=?""",
                    (execution_id,),
                ).fetchone()
                if row is None:
                    self._conn.rollback()
                    return "missing"
                if row["state_json"] != expected_state_json:
                    self._conn.rollback()
                    return "conflict"
                if int(row["lifecycle_state"]) != 0:
                    self._conn.rollback()
                    return "closed"
                try:
                    persisted_state = _strict_json_loads(row["state_json"])
                    if not isinstance(persisted_state, dict):
                        raise ValueError("execution state is not an object")
                    authority = self._execution_receipt_authority_locked(
                        execution_id, row, persisted_state
                    )
                except (ExecutionReceiptAuthorityError, TypeError, ValueError,
                        UnicodeDecodeError, json.JSONDecodeError):
                    self._conn.rollback()
                    return "authority_invalid"
                authorized_state = dict(state)
                authority_state = authority["state"]
                authorized_state["started_at"] = authority_state.get("started_at")
                for key in ("latest_comparison", "l2_failure_trial_requirement"):
                    if key in authority_state:
                        authorized_state[key] = authority_state[key]
                    else:
                        authorized_state.pop(key, None)
                if (
                    authority["comparisons"]
                    or int(row["comparison_required"]) == 1
                ):
                    authorized_state["execution_schema"] = authority_state["execution_schema"]
                    authorized_state["comparison_policy"] = authority_state["comparison_policy"]
                from . import execution as execution_owner
                authorized_state = execution_owner.with_current_outcome(authorized_state)
                authorized_status = authorized_state.get("status", "in_progress")
                lifecycle_state = {
                    "in_progress": 0,
                    "completed": 1,
                    "aborted": 2,
                }.get(authorized_status)
                if lifecycle_state is None:
                    self._conn.rollback()
                    return "authority_invalid"
                if lifecycle_state == 0:
                    authorized_state["ended_at"] = None
                    ended_at_epoch_us = None
                else:
                    ended_at_epoch_us = _timestamp_epoch_us(
                        authorized_state.get("ended_at")
                    )
                    if ended_at_epoch_us is None:
                        self._conn.rollback()
                        return "authority_invalid"
                encoded = json.dumps(
                    authorized_state, separators=(",", ":"), allow_nan=False
                )
                cur = self._conn.execute(
                    """UPDATE executions SET label=?, status=?, ended_at=?, state_json=?,
                                             lifecycle_state=?, ended_at_epoch_us=?
                       WHERE id=? AND lifecycle_state=0 AND state_json=?""",
                    (authorized_state.get("label", ""),
                     authorized_status, authorized_state.get("ended_at"), encoded,
                     lifecycle_state, ended_at_epoch_us,
                     execution_id, expected_state_json),
                )
                if cur.rowcount != 1:
                    self._conn.rollback()
                    return "conflict"
                self._conn.commit()
                state.clear()
                state.update(authorized_state)
                return "saved"
            except Exception:
                self._conn.rollback()
                raise

    def save_execution(self, execution_id: int, state: Dict[str, Any]) -> bool:
        """Compatibility wrapper over the authority-preserving compare-and-swap mutation."""
        rec = self.get_execution(execution_id)
        if rec is None:
            return False
        return self.save_execution_if_unchanged(
            execution_id, rec["_state_json"], state
        ) == "saved"

    def count_executions(self, snapshot_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM executions WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
        return int(row["n"]) if row else 0

    def list_executions(self, snapshot_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                rows = self._conn.execute(
                    """SELECT id, snapshot_id, label, status, started_at, ended_at, state_json,
                              comparison_required, snapshot_id_high_watermark, lifecycle_state,
                              started_at_epoch_us, ended_at_epoch_us
                       FROM executions WHERE snapshot_id = ? ORDER BY started_at DESC, id DESC""",
                    (snapshot_id,),
                ).fetchall()
                out = []
                for row in rows:
                    try:
                        state = _strict_json_loads(row["state_json"])
                    except (TypeError, ValueError, UnicodeDecodeError,
                            json.JSONDecodeError) as exc:
                        raise ExecutionReceiptAuthorityError(
                            f"execution {row['id']} state JSON is invalid: {exc}"
                        ) from exc
                    if not isinstance(state, dict):
                        raise ExecutionReceiptAuthorityError(
                            f"execution {row['id']} state JSON is not an object"
                        )
                    authority = self._execution_receipt_authority_locked(
                        int(row["id"]), row, state
                    )
                    projected = authority["state"]
                    item = {
                        "id": row["id"],
                        "snapshot_id": row["snapshot_id"],
                        "label": projected.get("label", ""),
                        "status": projected.get("status", "in_progress"),
                        "started_at": projected.get("started_at"),
                        "ended_at": projected.get("ended_at"),
                    }
                    if isinstance(projected.get("latest_comparison"), dict):
                        item["latest_comparison"] = projected["latest_comparison"]
                    item["comparison_required"] = (
                        isinstance(projected.get("comparison_policy"), dict)
                        and projected["comparison_policy"].get(
                            "canonical_gate_required"
                        ) is True
                    )
                    out.append(item)
                self._conn.commit()
                return out
            except Exception:
                self._conn.rollback()
                raise

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
