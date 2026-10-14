"""Hosted round-4 admission and real TCP disconnect controls, using a tiny real carriage source."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import socket
import sys
from threading import Event, Thread

import anyio.to_thread
from fastapi.testclient import TestClient
import httpx
import pytest
from starlette import formparsers
import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol

from test_carriage_ingestion import _small_snapshot_bytes, _upload

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as backend_app, engine  # noqa: E402


def _counts(store):
    with store._lock:
        return {
            table: store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "campaigns", "campaign_identities", "snapshots", "snapshot_authority",
                "carriage_projection_v2_parts",
            )
        }


def _gate_real_rows(monkeypatch):
    original = engine.prepare_carriage_projection
    entered, release = Event(), Event()
    calls = []

    def gated_preparation(raw):
        calls.append(raw)
        preparation = original(raw)
        rows = preparation["rows"]

        def gated_rows():
            try:
                entered.set()  # The real consumer's first next(), after upload admission.
                assert release.wait(20), "test did not release the real preparation stream"
                yield from rows
            finally:
                rows.close()

        return {**preparation, "rows": gated_rows()}

    monkeypatch.setattr(engine, "prepare_carriage_projection", gated_preparation)
    return original, entered, release, calls


def _free_heavy_slots(app):
    held = 0
    try:
        while app.state.generation_semaphore.acquire(blocking=False):
            held += 1
        return held
    finally:
        for _ in range(held):
            app.state.generation_semaphore.release()


@pytest.mark.parametrize("heavy_capacity", [1, 4])
def test_simultaneous_demo_seeds_refuse_before_side_effects_and_leave_committed_reads_live(
        tmp_path, monkeypatch, heavy_capacity):
    """One shared three-worker portal falsifies both the global cap and free-slot stage contention."""
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.delenv("ASSESSHUB_ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("ASSESSHUB_MAX_CONCURRENT_GENERATIONS", str(heavy_capacity))
    # Exercise the unchanged production one/four admission bounds on either runner size.
    monkeypatch.setattr(backend_app, "_physical_memory_bytes", lambda: 16 * 1024**3)
    app = backend_app.create_app(db_path=str(tmp_path / "seed-contention.db"), scope_dist_dir=None)
    payload = _small_snapshot_bytes()
    sample = tmp_path / "synthetic.snapshot.json"
    sample.write_bytes(payload)
    sample_reads = []

    class ObservedSample:
        def exists(self):
            return sample.exists()

        def read_text(self, **kwargs):
            sample_reads.append(True)
            return sample.read_text(**kwargs)

    monkeypatch.setattr(backend_app, "SAMPLE_SNAPSHOT", ObservedSample())
    seeds_arrived, seeds_start = Event(), Event()
    seed_scopes = []
    seed_count = 4  # More public staging callers than the isolated shared worker capacity.

    async def observed_app(scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/api/demo/seed":
            seed_scopes.append(scope)
            if len(seed_scopes) == seed_count:
                seeds_arrived.set()
        await app(scope, receive, send)

    async def resize_test_workers():
        limiter = anyio.to_thread.current_default_thread_limiter()
        original_tokens = limiter.total_tokens
        limiter.total_tokens = 3
        return limiter, original_tokens

    async def restore_test_workers(limiter, original_tokens):
        limiter.total_tokens = original_tokens

    with TestClient(observed_app, base_url="http://localhost", client=("127.0.0.1", 50000),
                    raise_server_exceptions=False) as client:
        store = app.state.store
        campaign_id = store.create_campaign("Seed admission control")["id"]
        committed = _upload(client, campaign_id, payload, "committed before contention")
        assert committed.status_code == 201
        snapshot_id = committed.json()["id"]
        metadata_before = client.get(f"/api/snapshots/{snapshot_id}")
        raw_before = client.get(f"/api/snapshots/{snapshot_id}/raw")
        assert metadata_before.status_code == raw_before.status_code == 200
        counts_before = _counts(store)
        assert _free_heavy_slots(app) == heavy_capacity
        original, entered, release, preparation_calls = _gate_real_rows(monkeypatch)
        assert client.portal is not None
        limiter, original_tokens = client.portal.call(resize_test_workers)

        def seed():
            assert seeds_start.wait(20), "test did not launch the simultaneous seeds"
            return client.post("/api/demo/seed")

        def read_committed():
            metadata = client.get(f"/api/snapshots/{snapshot_id}")
            raw = client.get(f"/api/snapshots/{snapshot_id}/raw")
            assert metadata.status_code == raw.status_code == 200
            assert metadata.json() == metadata_before.json()
            assert raw.content == raw_before.content
            assert raw.headers["x-snapshot-sha256"] == hashlib.sha256(raw.content).hexdigest()
            assert not release.is_set()
            return True

        try:
            with ThreadPoolExecutor(max_workers=seed_count + 2) as pool:
                pending = pool.submit(_upload, client, campaign_id, payload, "accepted upload")
                try:
                    assert entered.wait(20), "the accepted upload did not enter its genuine row stream"
                    assert limiter.total_tokens == 3
                    assert _free_heavy_slots(app) == heavy_capacity - 1
                    summarize = backend_app.summary.summarize
                    summary_calls = []

                    def observed_summary(*args, **kwargs):
                        summary_calls.append(True)
                        return summarize(*args, **kwargs)

                    monkeypatch.setattr(backend_app.summary, "summarize", observed_summary)
                    seeds = [pool.submit(seed) for _ in range(seed_count)]
                    seeds_start.set()
                    assert seeds_arrived.wait(10), "public seeds did not reach the shared ASGI loop"
                    assert pool.submit(read_committed).result(timeout=10) is True
                    for refused in (future.result(timeout=10) for future in seeds):
                        assert refused.status_code == 503, refused.text
                        assert refused.headers.get("retry-after") == "5"
                    assert not pending.done() and not release.is_set()
                    assert len(preparation_calls) == 1
                    assert sample_reads == summary_calls == []
                    assert _counts(store) == counts_before
                    assert _free_heavy_slots(app) == heavy_capacity - 1
                    with store._lock:
                        assert store._conn.in_transaction is False
                finally:
                    seeds_start.set()
                    release.set()
                assert pending.result(timeout=20).status_code == 201
            monkeypatch.setattr(engine, "prepare_carriage_projection", original)
            assert _free_heavy_slots(app) == heavy_capacity
            # The exact same public route is usable once admission and the stage are free.
            seeded = client.post("/api/demo/seed")
            assert seeded.status_code == 200, seeded.text
            assert len(sample_reads) == len(summary_calls) == 1
            assert client.get(f"/api/snapshots/{snapshot_id}/raw").content == raw_before.content
        finally:
            release.set()
            client.portal.call(restore_test_workers, limiter, original_tokens)


def test_real_server_late_client_disconnect_finishes_one_atomic_upload_and_releases_resources(
        tmp_path, monkeypatch):
    """A fully accepted request completes despite a closed TCP client; closing the page is not cancel."""
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.delenv("ASSESSHUB_ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("ASSESSHUB_MAX_CONCURRENT_GENERATIONS", "1")
    app = backend_app.create_app(db_path=str(tmp_path / "late-disconnect.db"), scope_dist_dir=None)
    store = app.state.store
    payload = _small_snapshot_bytes()
    campaign_id = store.create_campaign("Accepted upload disconnect control")["id"]
    disconnected, handler_finished, ready = Event(), Event(), Event()
    target_peer = []
    server_errors = []

    class ObservedH11Protocol(H11Protocol):
        def connection_made(self, transport):
            self.observed_peer = transport.get_extra_info("peername")
            super().connection_made(transport)

        def connection_lost(self, exc):
            super().connection_lost(exc)
            if target_peer and self.observed_peer == target_peer[0]:
                disconnected.set()

    async def observed_app(scope, receive, send):
        try:
            await app(scope, receive, send)
        finally:
            if (scope.get("type") == "http" and target_peer
                    and tuple(scope.get("client") or ()) == target_peer[0]
                    and scope.get("path") == f"/api/campaigns/{campaign_id}/snapshots"):
                handler_finished.set()

    class ObservedServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                ready.set()

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = ObservedServer(uvicorn.Config(
        observed_app, host="127.0.0.1", port=port, loop="asyncio", http=ObservedH11Protocol,
        ws="none", lifespan="on", access_log=False, log_level="warning",
    ))

    def run_server():
        try:
            server.run(sockets=[listener])
        except BaseException as exc:
            server_errors.append(exc)

    thread = Thread(target=run_server, name="carriage-late-disconnect", daemon=True)
    thread.start()
    release = Event()
    connection = None
    try:
        assert ready.wait(20), f"the real Uvicorn server did not start: {server_errors!r}"
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20, trust_env=False) as client:
            committed = _upload(client, campaign_id, payload, "committed before disconnect")
            assert committed.status_code == 201
            existing_id = committed.json()["id"]
            metadata_before = client.get(f"/api/snapshots/{existing_id}")
            raw_before = client.get(f"/api/snapshots/{existing_id}/raw")
            assert metadata_before.status_code == raw_before.status_code == 200
            counts_before = _counts(store)
            original, entered, release, preparation_calls = _gate_real_rows(monkeypatch)
            body_spools, upload_spools = [], []
            original_spool = backend_app.tempfile.SpooledTemporaryFile
            original_upload_spool = formparsers.SpooledTemporaryFile

            def observed_spool(*args, **kwargs):
                spool = original_spool(*args, **kwargs)
                body_spools.append(spool)
                return spool

            def observed_upload_spool(*args, **kwargs):
                spool = original_upload_spool(*args, **kwargs)
                upload_spools.append(spool)
                return spool

            monkeypatch.setattr(backend_app.tempfile, "SpooledTemporaryFile", observed_spool)
            monkeypatch.setattr(formparsers, "SpooledTemporaryFile", observed_upload_spool)
            boundary = b"carriage-late-disconnect-boundary"
            body = (
                b"--" + boundary + b'\r\nContent-Disposition: form-data; name="label"\r\n\r\n'
                b"accepted before late disconnect\r\n--" + boundary
                + b'\r\nContent-Disposition: form-data; name="file"; filename="synthetic.snapshot.json"'
                b"\r\nContent-Type: application/json\r\n\r\n" + payload + b"\r\n--" + boundary + b"--\r\n"
            )
            connection = socket.create_connection(("127.0.0.1", port), timeout=20)
            target_peer.append(connection.getsockname())
            header = (
                f"POST /api/campaigns/{campaign_id}/snapshots HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Content-Type: multipart/form-data; boundary={boundary.decode('ascii')}\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode("ascii")
            connection.sendall(header + body)
            assert entered.wait(20), "the complete TCP multipart body was not accepted for preparation"
            assert len(preparation_calls) == 1 and not handler_finished.is_set()
            assert _free_heavy_slots(app) == 0
            assert _counts(store) == counts_before
            connection.shutdown(socket.SHUT_RDWR)
            connection.close()
            connection = None
            assert disconnected.wait(10), "Uvicorn did not observe loss of the accepted upload connection"
            assert not handler_finished.is_set() and not release.is_set()
            assert _counts(store) == counts_before
            assert client.get(f"/api/snapshots/{existing_id}").json() == metadata_before.json()
            assert client.get(f"/api/snapshots/{existing_id}/raw").content == raw_before.content
            release.set()
            assert handler_finished.wait(20), "accepted upload did not finish after its disconnected client"
            assert body_spools and upload_spools
            assert all(spool.closed for spool in body_spools + upload_spools)
            assert _free_heavy_slots(app) == 1
            assert store._preparation_lock.acquire(blocking=False)
            store._preparation_lock.release()
            snapshots = client.get(f"/api/campaigns/{campaign_id}")
            assert snapshots.status_code == 200
            rows = snapshots.json()["snapshots"]
            assert len(rows) == 2
            accepted = [row for row in rows if row["id"] != existing_id]
            assert len(accepted) == 1 and accepted[0]["label"] == "accepted before late disconnect"
            accepted_id = accepted[0]["id"]
            raw = client.get(f"/api/snapshots/{accepted_id}/raw")
            assert raw.status_code == 200
            assert raw.headers["x-snapshot-sha256"] == hashlib.sha256(raw.content).hexdigest()
            assert json.loads(raw.content)["vlan_carriage"] == json.loads(payload)["vlan_carriage"]
            assert client.get(f"/api/snapshots/{accepted_id}/ui-projection/inventory").status_code == 200
            counts_after = _counts(store)
            assert counts_after["campaigns"] == counts_before["campaigns"]
            assert counts_after["campaign_identities"] == counts_before["campaign_identities"]
            assert counts_after["snapshots"] == counts_after["snapshot_authority"] == 2
            assert counts_after["carriage_projection_v2_parts"] > counts_before["carriage_projection_v2_parts"]
            with store._lock:
                assert store._conn.in_transaction is False
                assert tuple(store._conn.execute(
                    "SELECT carriage_projection_required, carriage_projection_version FROM snapshots WHERE id=?",
                    (accepted_id,),
                ).fetchone()) == (1, 2)
            monkeypatch.setattr(engine, "prepare_carriage_projection", original)
            retry = _upload(client, campaign_id, payload, "later deliberate upload")
            assert retry.status_code == 201 and retry.json()["id"] != accepted_id
            assert _free_heavy_slots(app) == 1
            assert all(spool.closed for spool in body_spools + upload_spools)
            assert len(store.list_snapshots(campaign_id)) == 3
            assert client.get(f"/api/snapshots/{existing_id}").json() == metadata_before.json()
            assert client.get(f"/api/snapshots/{existing_id}/raw").content == raw_before.content
    finally:
        release.set()
        if connection is not None:
            connection.close()
        server.should_exit = True
        thread.join(timeout=20)
        listener.close()
    assert not thread.is_alive(), "the real server retained upload work after shutdown"
    assert server_errors == []
