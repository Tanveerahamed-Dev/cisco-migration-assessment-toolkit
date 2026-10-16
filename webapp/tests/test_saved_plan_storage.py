"""Saved-plan custody, selection concurrency, and additive portable-database preservation.

Synthetic storage tests only. A plan is an unapproved artifact over immutable evidence; these
tests do not turn saved JSON, a hash, or a green suite into operational approval.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import shutil
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import storage  # noqa: E402
from backend.storage import (  # noqa: E402
    SavedPlanConflictError, SavedPlanIntegrityError, SavedPlanLimitError, Store,
    saved_plan_digest,
)
from cisco_toolkit.protocol_assurance import BoundSnapshot  # noqa: E402
from portable.database_preflight import census, migrate_and_compare  # noqa: E402


_PLAN_TABLES = ("plan_revisions", "plan_revision_authority", "plan_selection_events")


def _projection(value=24):
    return {"requirements": {"ports": value},
            "sections": {"design_blueprint": {"choice": "synthetic"}},
            "derivation": {"schema": "synthetic-plan/1", "owner": "test"}}


def _seed(store, *, name="synthetic", label="baseline"):
    cid = store.create_campaign(name)["id"]
    sid = store.add_snapshot(cid, label, {
        "script_version": "3.23.0", "devices": {}, "capture_note": "old",
    }, {})["id"]
    raw, binding = store.get_snapshot_blob(sid)
    return cid, sid, raw, binding


@pytest.fixture()
def seeded(tmp_path):
    store = Store(tmp_path / "plans.db")
    cid, sid, raw, binding = _seed(store)
    try:
        yield store, cid, sid, raw, binding
    finally:
        store.close()


def _save(store, sid, binding, selection=0, *, label="Plan alpha", projection=None):
    return store.save_plan_revision(sid, label, _projection() if projection is None else projection,
                                    binding, selection)


def _counts(store):
    return tuple(store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                 for table in _PLAN_TABLES)


def _context(store, sid, plan):
    return store.get_saved_plan_context(sid, plan["revision"], plan["sha256"], plan["selection_id"])


def test_save_reopen_and_select_preserve_assessment_bytes_and_unapproved_posture(seeded):
    store, cid, sid, raw, binding = seeded
    assert store.list_saved_plans(sid) == {
        "assessment": binding, "selection_id": 0, "selected_revision": None, "revisions": [],
    }
    projection = _projection()
    first = _save(store, sid, binding, projection=projection)
    projection["requirements"]["ports"] = 999
    assert first["projection"]["requirements"]["ports"] == 24
    assert first["status"] == "UNAPPROVED_DRAFT"
    assert first["schema"] == "atlas.saved_plan/1"
    assert first["revision"] == 1
    assert first["assessment"] == binding
    assert first["sha256"] == saved_plan_digest(first)
    assert store.get_snapshot_blob(sid) == (raw, binding)
    assert store.list_gates(cid) == []
    assert store.count_executions(sid) == 0
    context = _context(store, sid, first)
    assert isinstance(context["snapshot"], BoundSnapshot)
    assert dict(context["snapshot"]) == json.loads(raw)
    assert context["binding"] == binding and context["plan"] == first
    context["plan"]["projection"]["requirements"]["ports"] = 700
    assert _context(store, sid, first)["plan"]["projection"]["requirements"]["ports"] == 24


def test_complete_immutable_envelope_has_one_utf8_digest_owner(seeded):
    store, _cid, sid, _raw, binding = seeded
    plan = _save(store, sid, binding, label="Plan café")
    immutable = {key: value for key, value in plan.items() if key not in {"sha256", "selection_id"}}
    wire = json.dumps(immutable, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    assert plan["sha256"] == "sha256:" + hashlib.sha256(wire).hexdigest()
    reselected = store.select_plan_revision(sid, 1, plan["sha256"], plan["selection_id"])
    assert reselected["sha256"] == plan["sha256"]
    assert reselected["selection_id"] > plan["selection_id"]
    for key, value in (("label", "Different"), ("revision", 2),
                       ("created_at", "2026-10-16T00:00:00+00:00"),
                       ("projection", _projection(48))):
        changed = {**plan, key: value}
        assert saved_plan_digest(changed) != plan["sha256"]
    changed = deepcopy(plan)
    changed["assessment"]["label"] = "different assessment"
    assert saved_plan_digest(changed) != plan["sha256"]
    for changed in ({**plan, "status": "APPROVED"}, {**plan, "schema": "atlas.saved_plan/2"},
                    {**plan, "extra": "not part of the closed envelope"}):
        with pytest.raises(ValueError):
            saved_plan_digest(changed)


def test_aware_utc_spellings_validate_without_rewriting_immutable_hash_input(seeded):
    store, _cid, sid, _raw, binding = seeded
    original = _save(store, sid, binding)
    digests = []
    for created_at in ("2026-10-15T00:00:00Z", "2026-10-15T00:00:00+00:00"):
        plan = {**original, "created_at": created_at}
        before = deepcopy(plan)
        immutable = {key: value for key, value in plan.items() if key not in {"sha256", "selection_id"}}
        raw = json.dumps(immutable, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
        digest = saved_plan_digest(plan)
        assert digest == "sha256:" + hashlib.sha256(raw).hexdigest()
        assert plan == before and plan["created_at"] == created_at
        digests.append(digest)
    assert digests[0] != digests[1]  # validation equivalence never rewrites the immutable bytes


@pytest.mark.parametrize("created_at", [None, False, 0, "", "2026-10-15", "2026-10-15T00:00:00",
                                         "2026-10-15T00:00:00ZZ", "2026-10-15T00:00:00+00:00Z"])
def test_plan_timestamp_compatibility_keeps_naive_malformed_and_nonstring_refusals(seeded, created_at):
    store, _cid, sid, _raw, binding = seeded
    plan = _save(store, sid, binding)
    with pytest.raises(ValueError, match="metadata"):
        saved_plan_digest({**plan, "created_at": created_at})


@pytest.mark.parametrize("fraction", ["1", "12", "123", "1234", "12345", "123456"])
def test_fractional_utc_z_metadata_preserves_original_hash_bytes(seeded, fraction):
    store, _cid, sid, _raw, binding = seeded
    original = _save(store, sid, binding)
    created_at = "2026-10-15T12:34:56." + fraction + "Z"
    plan = {**original, "created_at": created_at}
    before = deepcopy(plan)
    immutable = {key: value for key, value in plan.items() if key not in {"sha256", "selection_id"}}
    raw = json.dumps(immutable, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    digest = saved_plan_digest(plan)
    assert digest == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert plan == before and plan["created_at"] == created_at
    offset = {**plan, "created_at": "2026-10-15T12:34:56." + fraction.ljust(6, "0") + "+00:00"}
    assert storage._parse_saved_plan_timestamp(created_at) == storage._parse_aware_timestamp(
        offset["created_at"],
    )
    assert saved_plan_digest(offset) != digest


@pytest.mark.parametrize("created_at", [
    "2026-10-15T00:00:00ZZZ", "2026-10-15Z00:00:00Z", "2026-10-15T00:00:00Z+00:00",
    "2026-10-15T00:00:00+00:00ZZ", "2026-10-15T00:00:00-02:00Z",
    "2026-10-15T00:00:00+02:00Z", "2026-10-15T00:00:00z", "2026-10-15T00:00:00zZ",
    "2026-10-15T00:00:00Zz", "2026-10-15T00:00:00z+00:00", "2026-10-15z00:00:00+00:00",
    "2026-10-15T00:00:00.Z", "2026-10-15T00:00:00,123Z", "2026-10-15T00:00:00.1234567Z",
    "2026-10-15T00:00Z", "2026-10-15Z", "20261015T000000Z", "2026-W42-4T00:00:00Z",
    "2026-10-15 00:00:00Z", "2026-10-15T00:00:00Z\n", " 2026-10-15T00:00:00Z",
    "2026-02-30T00:00:00Z", "2026-10-15T24:00:00Z", "2026-10-15T00:60:00Z",
    "2026-10-15T00:00:60Z",
])
def test_utc_z_metadata_refuses_noncanonical_designators_and_invalid_wallclock(seeded, created_at):
    store, _cid, sid, _raw, binding = seeded
    plan = _save(store, sid, binding)
    with pytest.raises(ValueError, match="metadata"):
        saved_plan_digest({**plan, "created_at": created_at})


@pytest.mark.parametrize("created_at", [
    "2026-10-15T00:00:00ZZ", "2026-10-15Z00:00:00Z", "2026-10-15T00:00:00Z+00:00",
    "2026-10-15T00:00:00+00:00Z", "2026-10-15T00:00:00z",
])
def test_invalid_z_designators_are_refused_before_legacy_parsing(monkeypatch, created_at):
    def forbidden(_value):
        raise AssertionError("malformed UTC-Z metadata must not reach the legacy parser")

    monkeypatch.setattr(storage, "_parse_aware_timestamp", forbidden)
    assert storage._parse_saved_plan_timestamp(created_at) is None


@pytest.mark.parametrize("created_at", [
    "2026-10-15T12:34:56+00:00", "2026-10-15T12:34:56.123456+03:00",
    "2026-10-15 12:34:56-02:00",
])
def test_non_z_aware_plan_metadata_keeps_legacy_parser_behavior(seeded, created_at):
    store, _cid, sid, _raw, binding = seeded
    plan = _save(store, sid, binding)
    assert storage._parse_saved_plan_timestamp(created_at) == storage._parse_aware_timestamp(created_at)
    assert saved_plan_digest({**plan, "created_at": created_at}).startswith("sha256:")


@pytest.mark.parametrize(("created_at", "fields"), [
    ("0001-01-01T00:00:00Z", (1, 1, 1, 0, 0, 0, 0)),
    ("9999-12-31T23:59:59.999999Z", (9999, 12, 31, 23, 59, 59, 999999)),
    ("2000-02-29T00:00:00.000001Z", (2000, 2, 29, 0, 0, 0, 1)),
    ("2024-02-29T23:59:59Z", (2024, 2, 29, 23, 59, 59, 0)),
    ("2026-10-15T00:00:00.0Z", (2026, 10, 15, 0, 0, 0, 0)),
    ("2026-10-15T23:59:59.1Z", (2026, 10, 15, 23, 59, 59, 100000)),
    ("2026-12-31T23:59:59.999Z", (2026, 12, 31, 23, 59, 59, 999000)),
])
def test_valid_utc_z_calendar_boundaries_never_use_iso_parser(seeded, monkeypatch, created_at, fields):
    store, _cid, sid, _raw, binding = seeded
    original = _save(store, sid, binding)

    def forbidden(_value):
        raise AssertionError("UTC-Z validation must not depend on the legacy ISO parser")

    monkeypatch.setattr(storage, "_parse_aware_timestamp", forbidden)
    parsed = storage._parse_saved_plan_timestamp(created_at)
    assert parsed is not None
    assert parsed == datetime(*fields, tzinfo=timezone.utc)
    assert parsed.tzinfo is timezone.utc
    plan = {**original, "created_at": created_at}
    before = deepcopy(plan)
    immutable = {key: value for key, value in plan.items() if key not in {"sha256", "selection_id"}}
    raw = json.dumps(immutable, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    assert saved_plan_digest(plan) == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert plan == before and plan["created_at"] == created_at


@pytest.mark.parametrize("created_at", [
    "0000-01-01T00:00:00Z", "10000-01-01T00:00:00Z", "2026-00-01T00:00:00Z",
    "2026-13-01T00:00:00Z", "2026-01-00T00:00:00Z", "2026-01-32T00:00:00Z",
    "1900-02-29T00:00:00Z", "2026-02-29T00:00:00Z", "2026-04-31T00:00:00Z",
    "2026-10-15T24:00:00Z", "2026-10-15T24:00:00.000000Z", "2026-10-15T24:01:00Z",
    "2026-10-15T99:59:59Z", "2026-10-15T23:60:00Z", "2026-10-15T23:59:60Z",
    "2026-10-15T23:59:59ZZ", "2026-10-15T23:59:59+00:00Z", "2026-10-15T23:59:59z",
])
def test_invalid_utc_z_calendar_and_clock_never_use_iso_parser(seeded, monkeypatch, created_at):
    store, _cid, sid, _raw, binding = seeded
    plan = _save(store, sid, binding)

    def forbidden(_value):
        raise AssertionError("UTC-Z refusal must not depend on the legacy ISO parser")

    monkeypatch.setattr(storage, "_parse_aware_timestamp", forbidden)
    assert storage._parse_saved_plan_timestamp(created_at) is None
    with pytest.raises(ValueError, match="metadata"):
        saved_plan_digest({**plan, "created_at": created_at})


def test_utc_z_plan_and_selection_survive_reopen_without_resealing(seeded, monkeypatch):
    store, _cid, sid, raw, binding = seeded
    timestamp = storage._now().replace("+00:00", "Z")
    monkeypatch.setattr(storage, "_now", lambda: timestamp)
    plan = _save(store, sid, binding)
    assert plan["created_at"] == timestamp
    assert _context(store, sid, plan)["plan"] == plan
    selected = store.select_plan_revision(sid, plan["revision"], plan["sha256"], plan["selection_id"])
    assert selected["sha256"] == plan["sha256"] and selected["created_at"] == timestamp
    assert selected["selection_id"] > plan["selection_id"]
    assert _context(store, sid, selected)["plan"] == selected
    assert store.get_snapshot_blob(sid) == (raw, binding)


def test_restart_never_recomputes_saved_projection(tmp_path, monkeypatch):
    path = tmp_path / "restart.db"
    store = Store(path)
    _cid, sid, raw, binding = _seed(store)
    plan = _save(store, sid, binding)
    store.close()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("reopening a saved plan must not derive a new one")

    from cisco_toolkit import design_advisor
    monkeypatch.setattr(design_advisor, "compute_design_blueprint", forbidden)
    reopened = Store(path)
    try:
        assert _context(reopened, sid, plan)["plan"] == plan
        assert reopened.get_snapshot_blob(sid) == (raw, binding)
        assert reopened.list_saved_plans(sid)["selected_revision"] == 1
    finally:
        reopened.close()


def test_stale_save_selection_and_aba_never_silently_choose_latest(seeded):
    store, _cid, sid, _raw, binding = seeded
    first = _save(store, sid, binding)
    second = _save(store, sid, binding, first["selection_id"], projection=_projection(48))
    before = _counts(store)
    with pytest.raises(SavedPlanConflictError):
        _save(store, sid, binding, first["selection_id"])
    with pytest.raises(SavedPlanConflictError):
        _context(store, sid, first)
    with pytest.raises(SavedPlanConflictError):
        store.select_plan_revision(sid, 1, first["sha256"], first["selection_id"])
    assert _counts(store) == before
    returned = store.select_plan_revision(sid, 1, first["sha256"], second["selection_id"])
    assert returned["sha256"] == first["sha256"]
    assert returned["selection_id"] > second["selection_id"]
    with pytest.raises(SavedPlanConflictError):
        _context(store, sid, first)
    assert _context(store, sid, returned)["plan"] == returned


@pytest.mark.parametrize("field,changed", [
    ("snapshot_id", True), ("campaign_id", 999), ("engagement_id", "foreign"),
    ("label", "stale"), ("script_version", "other"), ("bytes", 0.0),
    ("sha256", "sha256:" + "0" * 64), ("source", "foreign"),
])
def test_save_requires_complete_exact_typed_source_binding(seeded, field, changed):
    store, _cid, sid, _raw, binding = seeded
    wrong = {**binding, field: changed}
    with pytest.raises(SavedPlanConflictError):
        _save(store, sid, wrong)
    assert _counts(store) == (0, 0, 0)


def test_missing_and_extra_binding_fields_are_refused(seeded):
    store, _cid, sid, _raw, binding = seeded
    for wrong in ({key: value for key, value in binding.items() if key != "label"},
                  {**binding, "extra": False}):
        with pytest.raises(SavedPlanConflictError):
            _save(store, sid, wrong)
    assert _counts(store) == (0, 0, 0)


def test_equal_snapshot_content_does_not_authorize_cross_campaign_or_revision_substitution(seeded):
    store, _cid, sid, raw, binding = seeded
    _other_cid, other_sid, other_raw, other_binding = _seed(store, name="other")
    assert other_raw == raw
    first = _save(store, sid, binding)
    other = _save(store, other_sid, other_binding)
    assert first["sha256"] != other["sha256"]
    with pytest.raises(SavedPlanConflictError):
        store.select_plan_revision(other_sid, 1, first["sha256"], other["selection_id"])
    with pytest.raises(SavedPlanConflictError):
        _context(store, other_sid, first)
    with pytest.raises(SavedPlanConflictError):
        _save(store, other_sid, binding, other["selection_id"])
    assert store.get_saved_plan_context(other_sid, 2, first["sha256"], other["selection_id"]) is None
    assert store.list_saved_plans(999999) is None
    assert _save(store, 999999, binding) is None
    assert store.select_plan_revision(sid, 999, first["sha256"], first["selection_id"]) is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), (1, 2), {1: "coerced key"}, b"bytes"])
def test_non_json_projection_values_never_create_rows(seeded, bad):
    store, _cid, sid, _raw, binding = seeded
    with pytest.raises(ValueError):
        _save(store, sid, binding, projection={"requirements": bad})
    assert _counts(store) == (0, 0, 0)


def test_cycles_depth_and_payload_limits_refuse_without_rows(seeded):
    store, _cid, sid, _raw, binding = seeded
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError, match="cycle"):
        _save(store, sid, binding, projection=cyclic)
    deep = {}
    leaf = deep
    for _ in range(70):
        leaf["next"] = {}
        leaf = leaf["next"]
    with pytest.raises(SavedPlanLimitError):
        _save(store, sid, binding, projection=deep)
    with pytest.raises(SavedPlanLimitError):
        _save(store, sid, binding, projection={"large": "x" * storage.SAVED_PLAN_MAX_BYTES})
    assert _counts(store) == (0, 0, 0)


@pytest.mark.parametrize(
    "text,count", [("x" * (1024 * 1024), 1024), ("\x00" * 4096, 1024)],
    ids=("plain-1mib-repeated-1024", "nul-4096-repeated-1024"),
)
def test_aggregate_and_escaped_alias_overflow_refuse_before_encoder_allocation(monkeypatch, text, count):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("oversized aggregate reached the JSON encoder")

    monkeypatch.setattr(json.JSONEncoder, "iterencode", forbidden)
    with pytest.raises(SavedPlanLimitError, match="4 MiB"):
        storage.saved_plan_json_bytes({"payload": [text] * count})


def test_bounded_serializer_preserves_utf8_escape_and_numeric_canonical_identity():
    value = {"unicode": "café \U0001f642", "escaped": '"\\\b\f\n\r\t\x00\x1f',
             "array": [None, True, False, 0, -2, 1.25, -0.0, 1e200], "empty": {}}
    expected = json.dumps(value, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":"), sort_keys=True).encode("utf-8")
    assert storage.saved_plan_json_bytes(value) == expected


@pytest.mark.parametrize("bad", [True, -1, 1.5, "0", 1 << 63])
def test_selection_counter_types_and_overflow_are_refused(seeded, bad):
    store, _cid, sid, _raw, binding = seeded
    with pytest.raises(ValueError):
        _save(store, sid, binding, bad)
    assert _counts(store) == (0, 0, 0)


def test_actual_revision_and_selection_history_budgets(seeded):
    store, _cid, sid, raw, binding = seeded
    selected = 0
    for number in range(1, 65):
        plan = _save(store, sid, binding, selected, label=f"Plan {number}")
        assert plan["revision"] == number
        selected = plan["selection_id"]
    with pytest.raises(SavedPlanLimitError, match="revision"):
        _save(store, sid, binding, selected)
    assert _counts(store) == (64, 64, 64)
    for _ in range(64, 256):
        plan = store.select_plan_revision(sid, 64, plan["sha256"], selected)
        selected = plan["selection_id"]
    with pytest.raises(SavedPlanLimitError, match="selection"):
        store.select_plan_revision(sid, 64, plan["sha256"], selected)
    assert _counts(store) == (64, 64, 256)
    assert store.get_snapshot_blob(sid) == (raw, binding)


@pytest.mark.parametrize("table", ["plan_revisions", "plan_selection_events"])
def test_global_integer_id_exhaustion_rolls_back_save(seeded, table):
    store, _cid, sid, _raw, binding = seeded
    store._conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)", (table, (1 << 63) - 1))
    store._conn.commit()
    with pytest.raises(SavedPlanLimitError, match="identity space"):
        _save(store, sid, binding)
    assert _counts(store) == (0, 0, 0)


class _FailOnceConnection:
    def __init__(self, connection, statement, error):
        self.connection, self.statement, self.error = connection, statement, error
        self.armed = True

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, *args, **kwargs):
        if self.armed and self.statement in sql:
            self.armed = False
            raise self.error
        return self.connection.execute(sql, *args, **kwargs)


@pytest.mark.parametrize("statement", [
    "INSERT INTO plan_revision_authority", "INSERT INTO plan_selection_events",
    "UPDATE snapshots SET saved_plan_required",
])
@pytest.mark.parametrize("error_type", [sqlite3.OperationalError, KeyboardInterrupt])
def test_partial_save_rolls_back_revision_anchor_event_and_sequences(seeded, statement, error_type):
    store, _cid, sid, raw, binding = seeded
    sequence_before = store._conn.execute("SELECT name,seq FROM sqlite_sequence ORDER BY name").fetchall()
    store._conn = _FailOnceConnection(store._conn, statement, error_type("injected publication failure"))
    with pytest.raises(error_type, match="injected"):
        _save(store, sid, binding)
    assert _counts(store) == (0, 0, 0)
    assert store._conn.execute("SELECT name,seq FROM sqlite_sequence ORDER BY name").fetchall() == sequence_before
    assert store.list_saved_plans(sid)["selection_id"] == 0
    assert tuple(store._conn.execute(
        "SELECT saved_plan_required,saved_plan_revision_count,saved_plan_selection_id FROM snapshots WHERE id=?",
        (sid,),
    ).fetchone()) == (0, 0, 0)
    assert store.get_snapshot_blob(sid) == (raw, binding)
    assert _save(store, sid, binding)["revision"] == 1


@pytest.mark.parametrize("table,trigger", [
    ("plan_revisions", "plan_revisions"),
    ("plan_revision_authority", "plan_revision_authority"),
    ("plan_selection_events", "plan_selection_events"),
])
def test_revision_authority_and_event_update_delete_replace_are_blocked(seeded, table, trigger):
    store, _cid, sid, _raw, binding = seeded
    _save(store, sid, binding)
    column = "authority_version" if table == "plan_revision_authority" else "revision"
    for sql in (f"UPDATE {table} SET {column}={column}", f"DELETE FROM {table}",
                f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store._conn.execute(sql)
        store._conn.rollback()
    assert _counts(store) == (1, 1, 1)
    assert store._conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (trigger + "_no_replace",)).fetchone()


def test_plan_dependencies_refuse_source_and_campaign_deletion_or_rebinding(seeded):
    store, cid, sid, _raw, binding = seeded
    _save(store, sid, binding)
    assert store.delete_snapshot_if_unreceipted(sid) == "planned"
    assert store.delete_campaign_if_unreceipted(cid) == "planned"
    for sql, args in (
        ("UPDATE snapshots SET label='changed' WHERE id=?", (sid,)),
        ("DELETE FROM snapshots WHERE id=?", (sid,)),
        ("INSERT OR REPLACE INTO snapshots SELECT * FROM snapshots WHERE id=?", (sid,)),
        ("DELETE FROM snapshot_authority WHERE snapshot_id=?", (sid,)),
        ("UPDATE campaign_identities SET engagement_id='changed' WHERE campaign_id=?", (cid,)),
        ("DELETE FROM campaign_identities WHERE campaign_id=?", (cid,)),
        ("INSERT OR REPLACE INTO campaign_identities SELECT * FROM campaign_identities WHERE campaign_id=?", (cid,)),
        ("DELETE FROM campaigns WHERE id=?", (cid,)),
        ("UPDATE campaigns SET id=999 WHERE id=?", (cid,)),
        ("INSERT OR REPLACE INTO campaigns SELECT * FROM campaigns WHERE id=?", (cid,)),
    ):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store._conn.execute(sql, args)
        store._conn.rollback()


def _rewrite_blob(store, table, column, rowid, old, new, trigger):
    raw = store._conn.execute(f"SELECT CAST({column} AS BLOB) FROM {table} WHERE rowid=?", (rowid,)).fetchone()[0]
    assert old in raw and len(old) == len(new)
    changed = raw.replace(old, new, 1)
    if hasattr(store._conn, "blobopen"):
        with store._conn.blobopen(table, column, rowid) as blob:
            blob.write(changed)
    else:
        # Python 3.10 has no incremental BLOB API; retain exact-byte tamper coverage through SQL.
        store._conn.execute(f"DROP TRIGGER {trigger}")
        store._conn.execute(f"UPDATE {table} SET {column}=? WHERE rowid=?", (changed, rowid))
    store._conn.commit()


@pytest.mark.parametrize("target", ["plan", "source", "event"])
def test_incremental_blob_tamper_is_rejected_on_every_plan_surface(seeded, target):
    store, _cid, sid, _raw, binding = seeded
    plan = _save(store, sid, binding)
    if target == "plan":
        rowid = store._conn.execute("SELECT id FROM plan_revisions WHERE snapshot_id=?", (sid,)).fetchone()[0]
        _rewrite_blob(store, "plan_revisions", "plan_json", rowid, b"alpha", b"omega", "plan_revisions_no_update")
    elif target == "source":
        _rewrite_blob(store, "snapshots", "snapshot_json", sid, b'"old"', b'"new"', "saved_plan_snapshot_no_rebind")
    else:
        _rewrite_blob(store, "plan_selection_events", "plan_sha256", plan["selection_id"],
                      plan["sha256"].encode(), ("sha256:" + "0" * 64).encode(), "plan_selection_events_no_update")
    for operation in (lambda: store.list_saved_plans(sid), lambda: _context(store, sid, plan),
                      lambda: _save(store, sid, binding, plan["selection_id"]),
                      lambda: store.select_plan_revision(sid, 1, plan["sha256"], plan["selection_id"])):
        with pytest.raises(SavedPlanIntegrityError):
            operation()
    assert _counts(store) == (1, 1, 1)


@pytest.mark.parametrize("missing", ["anchor", "events"])
def test_restart_does_not_reseal_or_reselect_missing_history(tmp_path, missing):
    path = tmp_path / "torn.db"
    store = Store(path)
    _cid, sid, _raw, binding = _seed(store)
    plan = _save(store, sid, binding)
    table = "plan_revision_authority" if missing == "anchor" else "plan_selection_events"
    store._conn.execute(f"DROP TRIGGER {table}_no_delete")
    store._conn.execute(f"DELETE FROM {table}")
    store._conn.commit()
    store.close()
    reopened = Store(path)
    try:
        with pytest.raises(SavedPlanIntegrityError):
            _context(reopened, sid, plan)
        assert reopened._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        reopened.close()


@pytest.mark.parametrize("loss", ["rows", "tables", "selection_tail"])
def test_durable_markers_refuse_total_history_or_latest_tail_loss_after_restart(tmp_path, loss):
    path = tmp_path / "lost-history.db"
    store = Store(path)
    cid, sid, raw, binding = _seed(store)
    first = _save(store, sid, binding)
    last = store.select_plan_revision(sid, 1, first["sha256"], first["selection_id"])
    markers = tuple(store._conn.execute(
        "SELECT saved_plan_required,saved_plan_revision_count,saved_plan_selection_id FROM snapshots WHERE id=?",
        (sid,),
    ).fetchone())
    assert markers == (1, 1, last["selection_id"])
    for table in _PLAN_TABLES:
        store._conn.execute(f"DROP TRIGGER {table}_no_delete")
    if loss == "tables":
        for table in reversed(_PLAN_TABLES):
            store._conn.execute(f"DROP TABLE {table}")
    elif loss == "rows":
        for table in reversed(_PLAN_TABLES):
            store._conn.execute(f"DELETE FROM {table}")
    else:
        store._conn.execute("DELETE FROM plan_selection_events WHERE id=?", (last["selection_id"],))
    store._conn.commit()
    store.close()
    reopened = Store(path)
    try:
        for operation in (lambda: reopened.list_saved_plans(sid),
                          lambda: _context(reopened, sid, first),
                          lambda: _save(reopened, sid, binding)):
            with pytest.raises(SavedPlanIntegrityError):
                operation()
        assert reopened.delete_snapshot_if_unreceipted(sid) == "planned"
        assert reopened.delete_campaign_if_unreceipted(cid) == "planned"
        assert reopened.get_snapshot_blob(sid) == (raw, binding)
        assert tuple(reopened._conn.execute(
            "SELECT saved_plan_required,saved_plan_revision_count,saved_plan_selection_id FROM snapshots WHERE id=?",
            (sid,),
        ).fetchone()) == markers
        with pytest.raises(sqlite3.IntegrityError, match="cannot regress"):
            reopened._conn.execute("UPDATE snapshots SET saved_plan_required=0 WHERE id=?", (sid,))
        reopened._conn.rollback()
    finally:
        reopened.close()


def test_integer_markers_and_plan_anchors_cannot_be_incrementally_rewritten(seeded):
    store, _cid, sid, _raw, binding = seeded
    _save(store, sid, binding)
    for column in ("saved_plan_required", "saved_plan_revision_count", "saved_plan_selection_id"):
        with pytest.raises(sqlite3.IntegrityError, match="cannot regress"):
            store._conn.execute(f"UPDATE snapshots SET {column}=0 WHERE id=?", (sid,))
        store._conn.rollback()
        if hasattr(store._conn, "blobopen"):
            with pytest.raises(sqlite3.OperationalError):
                store._conn.blobopen("snapshots", column, sid)
    anchor_id = store._conn.execute("SELECT plan_id FROM plan_revision_authority").fetchone()[0]
    if hasattr(store._conn, "blobopen"):
        with pytest.raises(sqlite3.OperationalError):
            store._conn.blobopen("plan_revision_authority", "digest_0", anchor_id)


def test_two_store_connections_publish_only_one_save_for_the_same_selection(seeded):
    first_store, _cid, sid, _raw, binding = seeded
    second_store = Store(first_store.db_path)
    barrier = threading.Barrier(2)

    def save_one(store):
        barrier.wait(timeout=10)
        try:
            return _save(store, sid, binding)
        except SavedPlanConflictError:
            return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(save_one, store) for store in (first_store, second_store)]
            outcomes = [future.result(timeout=20) for future in futures]
        assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
        assert outcomes.count("conflict") == 1
        assert _counts(first_store) == (1, 1, 1)
    finally:
        second_store.close()


def test_payload_preparation_does_not_hold_the_shared_database_lock(seeded, monkeypatch):
    store, _cid, sid, _raw, binding = seeded
    entered, release = threading.Event(), threading.Event()
    original = storage._saved_plan_json_bytes
    projection = _projection()

    def paused(value):
        if value is projection:
            entered.set()
            assert release.wait(timeout=10)
        return original(value)

    monkeypatch.setattr(storage, "_saved_plan_json_bytes", paused)
    with ThreadPoolExecutor(max_workers=2) as workers:
        pending = workers.submit(_save, store, sid, binding, projection=projection)
        try:
            assert entered.wait(timeout=10)
            read = workers.submit(store.list_saved_plans, sid)
            assert read.result(timeout=5)["selection_id"] == 0
        finally:
            release.set()
        assert pending.result(timeout=10)["revision"] == 1


def test_export_context_detects_selection_change_after_render_admission(seeded):
    store, _cid, sid, raw, binding = seeded
    first = _save(store, sid, binding)
    frozen = _context(store, sid, first)
    with ThreadPoolExecutor(max_workers=1) as workers:
        second = workers.submit(_save, store, sid, binding, first["selection_id"],
                                projection=_projection(48)).result(timeout=10)
    assert frozen["plan"] == first and dict(frozen["snapshot"]) == json.loads(raw)
    with pytest.raises(SavedPlanConflictError):
        _context(store, sid, first)
    assert _context(store, sid, second)["plan"] == second


def test_boot_backup_and_preflight_preserve_saved_revisions_and_selection(tmp_path):
    path = tmp_path / "data" / "assesshub.db"
    store = Store(path)
    _cid, sid, raw, binding = _seed(store)
    plan = _save(store, sid, binding)
    store.close()
    hardened = Store(path, boot_hardening=True)
    hardened.close()
    backups = sorted((path.parent / "backups").glob("assesshub-*.db"))
    assert len(backups) == 1
    restored_path = tmp_path / "restored.db"
    shutil.copyfile(backups[0], restored_path)
    restored = Store(restored_path)
    try:
        assert _context(restored, sid, plan)["plan"] == plan
        assert restored.get_snapshot_blob(sid) == (raw, binding)
    finally:
        restored.close()
    source_bytes = path.read_bytes()
    copied = tmp_path / "preflight.db"
    shutil.copyfile(path, copied)
    before = census(copied)
    report = migrate_and_compare(copied, Store)
    assert report["status"] == "pass"
    assert report["before"]["table_set_digest"] == before["table_set_digest"]
    assert report["after"]["table_set_digest"] == before["table_set_digest"]
    assert path.read_bytes() == source_bytes


def test_additive_plan_schema_preserves_prior_store_rows_and_objects(tmp_path):
    path = tmp_path / "pre-plan.db"
    store = Store(path)
    _cid, sid, raw, binding = _seed(store)
    for row in store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' "
        "AND (name LIKE 'plan_%' OR name LIKE 'saved_plan_%')"
    ).fetchall():
        store._conn.execute(f'DROP TRIGGER "{row[0]}"')
    for table in reversed(_PLAN_TABLES):
        store._conn.execute(f"DROP TABLE {table}")
    for column in ("saved_plan_required", "saved_plan_revision_count", "saved_plan_selection_id"):
        store._conn.execute(f"ALTER TABLE snapshots DROP COLUMN {column}")
    store._conn.commit()
    store.close()
    before = census(path)
    prior_snapshot_columns = next(table["columns"] for table in before["tables"] if table["name"] == "snapshots")
    assert not any(column["name"].startswith("saved_plan_") for column in prior_snapshot_columns)
    report = migrate_and_compare(path, Store)
    assert report["status"] == "pass"
    assert report["after"]["user_version"] == before["user_version"]
    assert report["after"]["sqlite_sequence"] == before["sqlite_sequence"]
    assert set(_PLAN_TABLES) <= {table["name"] for table in report["after"]["tables"]}
    reopened = Store(path)
    try:
        assert reopened.get_snapshot_blob(sid) == (raw, binding)
        assert _counts(reopened) == (0, 0, 0)
    finally:
        reopened.close()
