"""Focused regressions for repository-wide review findings in AssessHub/Atlas."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import types
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dev as dev_launcher  # noqa: E402
from backend import app as app_module  # noqa: E402
from backend import deliverables, engine, execution, gates, ingest, pir_docx, serve  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.storage import Store  # noqa: E402


def test_default_asgi_object_defers_hardened_app_creation(monkeypatch):
    calls = []
    sentinel = object()
    monkeypatch.setattr(
        app_module, "create_default_app", lambda: calls.append("create") or sentinel)

    lazy = app_module._LazyDefaultApp()
    assert calls == []
    assert lazy._get() is sentinel
    assert lazy._get() is sentinel
    assert calls == ["create"]


def test_default_db_env_is_read_at_app_creation_time(monkeypatch, tmp_path):
    chosen = tmp_path / "late.db"
    monkeypatch.setenv("ASSESSHUB_DB", str(chosen))
    assert app_module._default_db_path() == str(chosen)


def test_browser_session_makes_token_mode_usable_and_is_httponly(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSESSHUB_TOKEN", "field-secret")
    app = create_app(db_path=str(tmp_path / "session.db"))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/campaigns").status_code == 401
        response = client.post(
            "/api/session", headers={"Authorization": "Bearer field-secret"})
        assert response.status_code == 204
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        # TestClient retained the derived session cookie; no bearer header is needed now.
        assert client.get("/api/campaigns").status_code == 200


def test_same_site_sibling_cannot_csrf_cookie_authenticated_write(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSESSHUB_TOKEN", "field-secret")
    app = create_app(db_path=str(tmp_path / "same-site-csrf.db"))
    with TestClient(app, base_url="https://atlas.example.test") as client:
        assert client.post(
            "/api/session",
            headers={"Authorization": "Bearer field-secret"},
        ).status_code == 204
        response = client.post(
            "/api/demo/seed",
            headers={
                "Origin": "https://compromised.example.test",
                "Sec-Fetch-Site": "same-site",
            },
        )
        assert response.status_code == 403
        assert client.get("/api/campaigns").json() == []


def test_nonloopback_bearer_is_rejected_over_plain_http(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSESSHUB_TOKEN", "field-secret")
    monkeypatch.setattr(app_module, "_client_is_loopback", lambda request: False)
    app = create_app(db_path=str(tmp_path / "remote-tls.db"))
    headers = {"Authorization": "Bearer field-secret"}
    with TestClient(app, base_url="http://assesshub.example") as client:
        response = client.get("/api/campaigns", headers=headers)
        assert response.status_code == 403
        assert "HTTPS" in response.json()["detail"]
    with TestClient(app, base_url="https://assesshub.example") as client:
        assert client.get("/api/campaigns", headers=headers).status_code == 200


def test_security_headers_cover_auth_refusals(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSESSHUB_TOKEN", "field-secret")
    with TestClient(create_app(db_path=str(tmp_path / "headers.db")),
                    base_url="http://localhost") as client:
        response = client.get("/api/campaigns")
    assert response.status_code == 401
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["content-security-policy"] == "frame-ancestors 'self'"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_multipart_declared_limit_is_checked_before_route_parsing(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    with TestClient(create_app(db_path=str(tmp_path / "limit.db")),
                    base_url="http://localhost") as client:
        response = client.post(
            "/api/campaigns/999/snapshots",
            content=b"x",
            headers={
                "Content-Type": "multipart/form-data; boundary=x",
                "Content-Length": str(ingest.MAX_ARCHIVE_BYTES + 3 * 1024 * 1024),
            },
        )
    assert response.status_code == 413


def test_multipart_mime_does_not_grant_upload_limit_to_json_route(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.setenv("ASSESSHUB_MAX_JSON_BODY_BYTES", str(64 * 1024))
    with TestClient(create_app(db_path=str(tmp_path / "mime-limit.db")),
                    base_url="http://localhost") as client:
        response = client.post(
            "/api/campaigns",
            content=b"x",
            headers={
                "Content-Type": "multipart/form-data; boundary=x",
                "Content-Length": str(64 * 1024 + 1),
            },
        )
    assert response.status_code == 413


def test_streamed_body_limit_covers_missing_content_length(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.setenv("ASSESSHUB_MAX_JSON_BODY_BYTES", str(64 * 1024))
    app = create_app(db_path=str(tmp_path / "stream-limit.db"))
    messages = [
        {"type": "http.request", "body": b"x" * (64 * 1024 + 1), "more_body": False},
        {"type": "http.disconnect"},
    ]
    sent = []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/campaigns",
        "raw_path": b"/api/campaigns",
        "query_string": b"",
        "headers": [(b"host", b"localhost"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 80),
    }
    anyio.run(app, scope, receive, send)
    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert starts and starts[0]["status"] == 413


def _execution_state(label: str) -> dict:
    return {
        "label": label,
        "status": "in_progress",
        "started_at": "2026-07-30T00:00:00+00:00",
        "ended_at": None,
        "waves": [],
        "events": [],
    }


def test_execution_compare_and_swap_rejects_cross_process_lost_update(tmp_path):
    db = tmp_path / "cas.db"
    first = Store(db)
    second = None
    try:
        campaign = first.create_campaign("c")
        snapshot = first.add_snapshot(
            campaign["id"], "s", {"devices": {}}, {"engine_schema": "test"})
        execution_id = first.create_execution(snapshot["id"], _execution_state("run"))
        second = Store(db)

        stale_a = first.get_execution(execution_id)
        stale_b = second.get_execution(execution_id)
        assert stale_a and stale_b
        stale_a["state"]["label"] = "operator A"
        assert first.save_execution_if_unchanged(
            execution_id, stale_a["_state_json"], stale_a["state"]) == "saved"
        stale_b["state"]["label"] = "operator B"
        assert second.save_execution_if_unchanged(
            execution_id, stale_b["_state_json"], stale_b["state"]) == "conflict"
        assert first.get_execution(execution_id)["state"]["label"] == "operator A"
    finally:
        if second is not None:
            second.close()
        first.close()


def _decision_snapshot(version: str | None) -> dict:
    snapshot = {
        "devices": {},
        "interfaces": {},
        "health_scores": [],
        "punchlist": [],
    }
    if version is not None:
        snapshot["script_version"] = version
    return snapshot


@pytest.mark.parametrize(
    ("versions", "expected_status"),
    [(("V1", "V2"), "mismatch"), ((None, "V1"), "unverifiable")],
)
def test_engine_schema_gap_is_decision_input_not_posthoc_warning(
        versions, expected_status):
    before = _decision_snapshot(versions[0])
    after = _decision_snapshot(versions[1])
    binding = {
        "before": {"source": "persisted snapshots.snapshot_json blob",
                   "sha256": "sha256:before"},
        "after": {"source": "persisted snapshots.snapshot_json blob",
                  "sha256": "sha256:after"},
    }

    delta = engine.snapshot_delta(before, after, source_binding=binding)
    assert delta["schema_compat"]["status"] == expected_status
    assert delta["verdict"] == "INDETERMINATE"
    assert delta["provenance"]["schema_status"]["status"] == expected_status
    assert delta["provenance"]["source_binding"] == binding

    trend = engine.campaign_trend(
        [before, after],
        source_bindings=[binding["before"], binding["after"]],
    )
    assert trend["schema_compat"]["status"] == expected_status
    assert trend["verdict"] == "INDETERMINATE"
    assert trend["provenance"]["schema_status"]["status"] == expected_status
    assert trend["provenance"]["source_bindings"] == [
        binding["before"], binding["after"]]


def test_bound_snapshot_hashes_exact_persisted_blob_not_semantic_json(tmp_path):
    store = Store(tmp_path / "bindings.db")
    try:
        campaign_id = store.create_campaign("bindings")["id"]
        # Same JSON value, deliberately different key insertion/encoding order.
        first = {
            "devices": {}, "interfaces": {}, "health_scores": [], "punchlist": [],
            "alpha": 1, "beta": 2,
        }
        second = {
            "beta": 2, "alpha": 1,
            "punchlist": [], "health_scores": [], "interfaces": {}, "devices": {},
        }
        first_id = store.add_snapshot(campaign_id, "first", first, {})["id"]
        second_id = store.add_snapshot(campaign_id, "second", second, {})["id"]

        first_bound = store.get_bound_snapshot(first_id)
        second_bound = store.get_bound_snapshot(second_id)
        assert first_bound and second_bound
        assert first_bound[0] == second_bound[0]
        assert first_bound[1]["source"] == "persisted snapshots.snapshot_json blob"
        assert second_bound[1]["source"] == "persisted snapshots.snapshot_json blob"
        first_bytes = json.dumps(first, separators=(",", ":")).encode("utf-8")
        second_bytes = json.dumps(second, separators=(",", ":")).encode("utf-8")
        assert first_bound[1]["sha256"] == (
            "sha256:" + hashlib.sha256(first_bytes).hexdigest())
        assert second_bound[1]["sha256"] == (
            "sha256:" + hashlib.sha256(second_bytes).hexdigest())
        assert first_bound[1]["sha256"] != second_bound[1]["sha256"]
    finally:
        store.close()


def test_pir_recomputes_legacy_stale_success_outcome(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    app = create_app(db_path=str(tmp_path / "legacy-pir.db"))
    store = app.state.store
    campaign_id = store.create_campaign("legacy")["id"]
    snapshot_id = store.add_snapshot(
        campaign_id, "snapshot", {"devices": {}}, {})["id"]
    stale = {
        "label": "Legacy run",
        "status": "completed",
        "started_at": "2026-07-30T00:00:00+00:00",
        "ended_at": "2026-07-30T00:01:00+00:00",
        "outcome": execution.OUTCOME_SUCCESS,
        "plan_summary": {},
        "waves": [{
            "group": "Wave A",
            "steps": [{"status": "pending"}],
            "checks": [{"result": "pending"}],
            "closeout": {"decision": "COMPLETE"},
        }],
        "events": [],
    }
    execution_id = store.create_execution(snapshot_id, stale)
    captured = {}

    def fake_pir(path, state, snapshot_label):
        captured["state"] = state
        Path(path).write_bytes(b"PK-focused-test")

    monkeypatch.setattr(deliverables, "have_docx", lambda: True)
    monkeypatch.setattr(pir_docx, "write_pir_docx", fake_pir)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get(f"/api/executions/{execution_id}/report")

    assert response.status_code == 200
    assert captured["state"]["outcome"] == execution.OUTCOME_PARTIAL
    # Recomputing an export view must not rewrite historical storage as a side effect.
    assert store.get_execution(execution_id)["state"]["outcome"] == execution.OUTCOME_SUCCESS


def test_unc_ingest_is_rejected_before_allowed_root_or_filesystem_access(monkeypatch):
    touched = []
    monkeypatch.setattr(
        ingest, "_allowed_ingest_roots", lambda: touched.append(True) or [])
    with pytest.raises(ingest.IngestError, match="Remote"):
        ingest._resolve_and_scan(r"\\198.51.100.7\share\client", contain=True)
    assert touched == []


def test_ingest_rejects_descendant_reparse_point(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    folder = root / "junction"
    folder.mkdir(parents=True)
    (folder / "show_version.txt").write_text("x", encoding="utf-8")
    monkeypatch.setenv("ASSESSHUB_INGEST_ROOTS", str(root))
    real_lstat = os.lstat

    def marked_lstat(path):
        result = real_lstat(path)
        if Path(path) == folder:
            return types.SimpleNamespace(
                st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return result

    monkeypatch.setattr(ingest.os, "lstat", marked_lstat)
    with pytest.raises(ingest.IngestError, match="symlink or junction"):
        ingest._resolve_and_scan(folder, contain=True)


def test_gate_wave_list_deduplicates_preserving_first_order():
    snapshot = {
        "migration_readiness": [
            {"group": "Wave A"}, {"group": "Wave B"}, {"group": "Wave A"}]}
    assert gates.waves_from_snapshot(snapshot) == ["Wave A", "Wave B"]


def test_filename_fallback_label_is_storage_bounded(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    with TestClient(create_app(db_path=str(tmp_path / "labels.db")),
                    base_url="http://localhost") as client:
        campaign_id = client.post("/api/campaigns", json={"name": "c"}).json()["id"]
        filename = "x" * 500 + ".json"
        response = client.post(
            f"/api/campaigns/{campaign_id}/snapshots",
            files={"file": (filename, json.dumps({"devices": {}}), "application/json")},
        )
    assert response.status_code == 201
    assert len(response.json()["label"]) == 200


def test_write_probe_never_overwrites_fixed_user_file(tmp_path):
    user_file = tmp_path / ".atlas-write-probe"
    user_file.write_text("engineer-owned", encoding="utf-8")
    assert serve._writable_failure(tmp_path) is None
    assert user_file.read_text(encoding="utf-8") == "engineer-owned"
    assert list(tmp_path.glob(".atlas-write-probe-*")) == []


def test_boot_rotation_does_not_claim_unknown_partial_files(tmp_path):
    db = tmp_path / "data" / "hub.db"
    store = Store(db)
    store.create_campaign("evidence")
    store.close()
    backups = db.parent / "backups"
    backups.mkdir()
    parked = backups / "assesshub-other-process.db.partial"
    parked.write_text("still writing", encoding="utf-8")
    hardened = Store(db, boot_hardening=True)
    hardened.close()
    assert parked.read_text(encoding="utf-8") == "still writing"


@pytest.mark.parametrize("host", ["127.0.0.1", "127.9.8.7", "::1", "[::1]", "localhost"])
def test_loopback_bind_detection_includes_ipv6(host):
    assert serve._bind_is_loopback(host)


def test_nonloopback_serve_requires_token_and_tls(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    args = ["--host", "0.0.0.0", "--db", str(tmp_path / "hub.db"), "--no-browser"]
    assert serve.main(args) == 2
    assert "ASSESSHUB_TOKEN" in capsys.readouterr().err

    monkeypatch.setenv("ASSESSHUB_TOKEN", "field-secret")
    assert serve.main(args) == 2
    assert "requires TLS" in capsys.readouterr().err


def test_health_nonce_identifies_the_spawned_portable_child(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.setenv("ASSESSHUB_INSTANCE_NONCE", "spawned-child-123")
    with TestClient(create_app(db_path=str(tmp_path / "nonce.db")),
                    base_url="http://localhost") as client:
        health = client.get("/api/health").json()
    assert health["instance_nonce"] == "spawned-child-123"


class _ExitedLauncher:
    pid = 4242
    returncode = 0

    def __init__(self):
        self.waited = False

    def poll(self):
        return 0

    def wait(self, timeout=None):
        self.waited = True
        return 0


def test_dev_teardown_uses_windows_job_after_launcher_exit(monkeypatch):
    process = _ExitedLauncher()
    terminated = []
    monkeypatch.setattr(dev_launcher, "_is_windows", lambda: True)
    monkeypatch.setattr(
        dev_launcher, "_terminate_windows_job",
        lambda proc: terminated.append(proc.pid) or True,
    )
    monkeypatch.setattr(
        dev_launcher, "_taskkill",
        lambda proc: pytest.fail("job-owned process should not fall back to PID tree lookup"),
    )

    dev_launcher._stop_tree(process)

    assert terminated == [process.pid]
    assert process.waited


def test_dev_teardown_signals_posix_group_after_leader_exit(monkeypatch):
    process = _ExitedLauncher()
    signals = []
    monkeypatch.setattr(dev_launcher, "_is_windows", lambda: False)
    monkeypatch.setattr(
        dev_launcher.os, "killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
        raising=False,
    )

    dev_launcher._stop_tree(process)

    assert signals == [(process.pid, dev_launcher.signal.SIGTERM)]
    assert process.waited


@pytest.mark.parametrize(
    "configured",
    ["*", "null", "https://user@example.com", "https://example.com/path", "file:///tmp/x"],
)
def test_unsafe_cors_configuration_fails_closed(configured, monkeypatch):
    monkeypatch.setenv("ASSESSHUB_CORS_ORIGINS", configured)
    with pytest.raises(ValueError):
        app_module._cors_origins()
