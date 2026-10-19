"""R15/R19/R20 synthetic lock budgets, executed only in existing hosted jobs."""
from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as app_module, deliverables, storage  # noqa: E402


class _MeasuredLock:
    def __init__(self, inner):
        self.inner = inner
        self.local = threading.local()
        self.holds = []
        self.hashes = 0

    def acquire(self, *args, **kwargs):
        acquired = self.inner.acquire(*args, **kwargs)
        if acquired:
            self.local.start = time.perf_counter()
        return acquired

    def release(self):
        self.holds.append(time.perf_counter() - self.local.start)
        del self.local.start
        return self.inner.release()

    def locked(self):
        return self.inner.locked()

    def during_finalizer(self, callback, *args):
        return self.inner.during_finalizer(callback, *args)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_exc):
        self.release()

    def clear(self):
        assert not self.locked()
        self.holds.clear()
        self.hashes = 0


class _BeginWitness:
    def __init__(self, inner, attempted):
        self.inner, self.attempted = inner, attempted
        self.waits = []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def execute(self, sql, *args):
        if sql == "BEGIN IMMEDIATE":
            self.attempted.set()
            start = time.perf_counter()
            result = self.inner.execute(sql, *args)
            self.waits.append(time.perf_counter() - start)
            return result
        return self.inner.execute(sql, *args)


@pytest.mark.unshared
def test_large_snapshot_full_history_store_lock_holds_and_other_snapshot_commit_stay_within_2_5_seconds(tmp_path, monkeypatch):
    """Over-budget fails; do not increase the bound or the hosting job's timeout."""
    store = storage.Store(tmp_path / "large-plans.db")
    other = None
    try:
        cid = store.create_campaign("EXAMPLE synthetic lock measurement")["id"]
        sid = store.add_snapshot(cid, "EXAMPLE large", {
            "script_version": "3.23.0", "devices": {}, "interfaces": {},
            "synthetic_padding": "x" * (65 * 1024 * 1024),
        }, {})["id"]
        other_sid = store.add_snapshot(cid, "EXAMPLE independent", {
            "script_version": "3.23.0", "devices": {}, "interfaces": {},
        }, {})["id"]
        snapshot, binding = store.get_bound_snapshot(sid)
        assert binding["bytes"] > 64 * 1024 * 1024
        projection = deliverables.prepare_saved_plan(snapshot, {"convergence_budget_ms": 0})
        selection = 0
        first_digest = None
        # Maximum admitted save has 63 older revisions; measure selection with all 64 present.
        for _ in range(63):
            payload = store.save_plan_revision(sid, "EXAMPLE history", projection, binding, selection,
                admit=lambda candidate: app_module._prepare_new_saved_plan(snapshot, candidate),
                finalize=app_module._finish_saved_plan)
            selection = json.loads(payload)["selection_id"]
            if first_digest is None:
                first_digest = json.loads(payload)["sha256"]
        other = storage.Store(store.db_path)
        other_snapshot, other_binding = other.get_bound_snapshot(other_sid)
        other_projection = deliverables.prepare_saved_plan(other_snapshot, {})
        measured = _MeasuredLock(store._lock)
        store._lock = measured
        original_identity = storage._blob_identity

        def observed_identity(raw):
            if hasattr(measured.local, "start"):
                measured.hashes += 1
            return original_identity(raw)

        monkeypatch.setattr(storage, "_blob_identity", observed_identity)
        finalizing, attempted = threading.Event(), threading.Event()
        begin = _BeginWitness(other._conn, attempted)
        other._conn = begin

        def finalizer(prepared, record):
            finalizing.set()
            assert attempted.wait(2), "different-snapshot transaction never attempted"
            return app_module._finish_saved_plan(prepared, record)

        def independent_save():
            assert finalizing.wait(5)
            return other.save_plan_revision(other_sid, "EXAMPLE concurrent", other_projection,
                other_binding, 0, admit=lambda candidate: app_module._prepare_new_saved_plan(other_snapshot, candidate),
                finalize=app_module._finish_saved_plan)

        measured.clear()
        snapshot, binding = store.get_bound_snapshot(sid)  # The route's existing bound read.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(independent_save)
            payload = store.save_plan_revision(sid, "EXAMPLE revision 64", projection, binding, selection,
                admit=lambda candidate: app_module._prepare_new_saved_plan(snapshot, candidate), finalize=finalizer)
            independent = json.loads(pending.result(timeout=10))
        record = json.loads(payload)
        assert record["revision"] == 64 and independent["revision"] == 1
        save_holds, save_hashes = list(measured.holds), measured.hashes
        assert len(save_holds) == 3  # bound read, bounded marker/count pre-read, publication.
        assert save_hashes == 2
        assert max(save_holds) <= 2.5, {"operation": "save", "holds_s": save_holds}
        assert begin.waits and max(begin.waits) <= 2.5, {"other_snapshot_begin_wait_s": begin.waits}

        measured.clear()
        snapshot, binding = store.get_bound_snapshot(sid)
        selected_bytes = store.select_plan_revision(sid, 1, first_digest,
            record["selection_id"], expected_binding=binding,
            admit=lambda candidate: app_module._prepare_existing_saved_plan(snapshot, candidate),
            finalize=app_module._finish_saved_plan)
        selected = json.loads(selected_bytes)
        select_holds, select_hashes = list(measured.holds), measured.hashes
        assert select_hashes == 2
        assert max(select_holds) <= 2.5, {"operation": "select", "holds_s": select_holds}

        measured.clear()
        context = store.get_saved_plan_context(sid, 1, selected["sha256"], selected["selection_id"])
        assert measured.hashes == 1
        assert app_module._prepare_existing_saved_plan(context["snapshot"], context["plan"]).finish(context["plan"]) == selected_bytes
        measured.clear()
        assert len(store.list_saved_plans(sid)["revisions"]) == 64
        assert measured.hashes == 1
        measured.clear()
        for _ in range(2):
            store.get_saved_plan_context(sid, 1, selected["sha256"], selected["selection_id"])
        assert measured.hashes == 2
        print(json.dumps({"schema": "atlas.saved-plan-lock-measurement/1",
            "platform": sys.platform, "source_bytes": binding["bytes"], "revisions": 64,
            "save_holds_s": save_holds, "select_holds_s": select_holds,
            "other_snapshot_begin_wait_s": begin.waits, "bound_s": 2.5,
            "locked_full_source_hashes": {"save": save_hashes, "select": select_hashes,
                                         "get": 1, "list": 1, "export_contexts": 2}}))
    finally:
        if other is not None:
            other.close()
        store.close()
