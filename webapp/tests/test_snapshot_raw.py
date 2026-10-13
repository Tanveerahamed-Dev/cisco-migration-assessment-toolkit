"""`GET /api/snapshots/{id}/raw` — the stored snapshot bytes, unchanged, for a runtime consumer.

Atlas Scope (served same-origin under /scope) must compile client evidence in the browser at run
time rather than baking it into a static bundle: AssessHub serves static files outside its access
guard, so any evidence compiled into them would be readable cross-site. This route is the one
source it reads. What it must guarantee, each pinned below:

* the body is EXACTLY the persisted ``snapshots.snapshot_json`` bytes (the store's binding), never a
  re-serialisation — ``sha256(body)`` equals ``X-Snapshot-Sha256`` and ``len(body)`` equals
  ``X-Snapshot-Bytes``, and both equal the store's own binding for the row;
* it is ``Cache-Control: no-store`` (client evidence must not persist in a browser/proxy cache);
* it inherits every /api guard with NO per-route code: cross-site GET 403, foreign Host 403,
  non-loopback peer without a token 403, token mode without the session cookie 401;
* an unknown id is 404, not an empty 200.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend.app import create_app  # noqa: E402


def _carriage_storage_pack(cable_count=3, members=1):
    """Synthetic producer output: persistence tests do not trust uploaded derivatives."""
    cables = []
    for ordinal in range(cable_count):
        end = {"host": "switch-a", "stp_interface": "Gi1/0/1"}
        cables.append({
            "ordinal": ordinal, "index": ordinal, "code_offset": ordinal * (1 + 3 * members),
            "member_count": members,
            "cable": {"members": [{"a": end, "b": {}} for _ in range(members)]},
            "pointers": [], "allowance_values": [],
        })
    return {
        "schema": "carriage_projection_preparation/1",
        "document": {"stored": "okay", "cable_count": cable_count},
        "context": {"stored": "context"}, "cables": cables,
        "vlans": [{"vlan_index": 0, "vlan": 10, "summary": {}, "failed": None,
                   "readable": True, "total": cable_count,
                   "codes": "P" * cable_count * (1 + 3 * members)}],
        "roles": [{"host": "switch-a", "namespace": "pvst_vlan", "instance": 10,
                   "interface": "Gi1/0/1", "rows": [[0, {"role": "designated"}]]}],
    }


def _carriage_store(tmp_path, monkeypatch, *, cable_count=3, members=1):
    from backend import engine
    from backend.storage import Store

    observed = []

    def prepare(raw):
        observed.append(raw)
        return _carriage_storage_pack(cable_count, members)

    monkeypatch.setattr(engine, "prepare_carriage_projection", prepare)
    store = Store(tmp_path / "carriage.db")
    cid = store.create_campaign("synthetic")['id']
    snapshot = {"script_version": "synthetic", "vlan_carriage": {},
                "route_provenance": "final", "client_projection": {"stored": "forged"}}
    sid = store.add_snapshot(cid, "first", snapshot, {})["id"]
    return store, cid, sid, observed


def test_carriage_storage_prepares_final_bytes_once_and_reads_only_the_document(tmp_path, monkeypatch):
    store, _cid, sid, observed = _carriage_store(tmp_path, monkeypatch, cable_count=1200)
    try:
        raw, binding = store.get_snapshot_blob(sid)
        assert observed == [raw]
        assert json.loads(raw)["route_provenance"] == "final"
        queries = []
        store._conn.set_trace_callback(queries.append)
        first = store.get_carriage_document(sid)
        second = store.get_carriage_document(sid)
        assert first == second == ({"stored": "okay", "cable_count": 1200}, binding)
        assert observed == [raw]
        parts = [query for query in queries if "FROM carriage_projection_parts" in query]
        assert len(parts) == 2
        assert all("kind='document'" in query for query in parts)
        assert not any("json_extract" in query.lower() for query in queries)
        assert store.get_snapshot_blob(sid)[0] == raw
    finally:
        store.close()


def test_carriage_storage_prepares_snapshots_without_a_carriage_section(tmp_path, monkeypatch):
    store, cid, _sid, observed = _carriage_store(tmp_path, monkeypatch)
    try:
        sid = store.add_snapshot(cid, "no carriage", {"devices": {}}, {})["id"]
        raw, binding = store.get_snapshot_blob(sid)
        assert observed[-1] == raw
        assert "vlan_carriage" not in json.loads(raw)
        assert store.get_carriage_document(sid) == ({"stored": "okay", "cable_count": 3}, binding)
    finally:
        store.close()


def test_carriage_storage_warm_verification_does_not_decode_document(tmp_path, monkeypatch):
    from backend import storage

    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        _document, binding = store.get_carriage_document(sid)

        def refuse_decode(_value):
            raise AssertionError("warm verification must not decode projection JSON")

        monkeypatch.setattr(storage, "_strict_json_loads", refuse_decode)
        assert store.verify_carriage_document(sid) == binding
        assert store.verify_carriage_document(sid) == binding
        assert store.verify_carriage_document(sid + 1000) is None
        with pytest.raises(AssertionError, match="must not decode"):
            store.get_carriage_document(sid)
    finally:
        store.close()


@pytest.mark.parametrize("mutation", ["blob", "delete", "source"])
def test_carriage_storage_warm_verification_refuses_current_tampering(tmp_path, monkeypatch, mutation):
    from backend.storage import ExecutionReceiptAuthorityError

    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        assert store.get_carriage_document(sid)[0]["stored"] == "okay"
        assert store.verify_carriage_document(sid) is not None
        if mutation == "delete":
            store._conn.execute("DROP TRIGGER carriage_projection_parts_no_delete")
            store._conn.execute(
                "DELETE FROM carriage_projection_parts WHERE snapshot_id=? AND kind='document'", (sid,),
            )
        else:
            if mutation == "blob":
                row = store._conn.execute(
                    "SELECT rowid,payload FROM carriage_projection_parts "
                    "WHERE snapshot_id=? AND kind='document'", (sid,),
                ).fetchone()
                rowid, table, column = row["rowid"], "carriage_projection_parts", "payload"
                forged = bytes(row["payload"]).replace(b"okay", b"evil")
            else:
                rowid, table, column = sid, "snapshots", "snapshot_json"
                forged = store.get_snapshot_blob(sid)[0].replace(b'"final"', b'"other"')
            if hasattr(store._conn, "blobopen"):
                with store._conn.blobopen(table, column, rowid) as blob:
                    blob.write(forged)
            elif mutation == "blob":
                store._conn.execute("DROP TRIGGER carriage_projection_parts_no_update")
                store._conn.execute(
                    "UPDATE carriage_projection_parts SET payload=? WHERE rowid=?", (forged, rowid),
                )
            else:
                store._conn.execute("UPDATE snapshots SET snapshot_json=? WHERE id=?", (forged, rowid))
        store._conn.commit()
        with pytest.raises(ExecutionReceiptAuthorityError):
            store.verify_carriage_document(sid)
    finally:
        store.close()


def test_carriage_storage_page_reads_bounded_members_codes_and_exact_role_groups(tmp_path, monkeypatch):
    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch, cable_count=1200, members=3)
    try:
        queries = []
        store._conn.set_trace_callback(queries.append)
        pack, _binding = store.get_carriage_page_source(sid, 0, offset=199, limit=200)
        materialized = [row for row in pack["cables"] if "cable" in row]
        assert len(materialized) == 133
        assert sum(row["member_count"] for row in materialized) == 399
        assert pack["cables"][-1] == {
            "ordinal": 332, "index": 332, "code_offset": 3320, "member_count": 3,
        }
        assert pack["vlans"][0]["code_start"] == 1990
        assert pack["vlans"][0]["codes"] == "P" * 1330
        assert len(pack["roles"]) == 1
        code_queries = [query for query in queries if "kind='codes'" in query]
        assert len(code_queries) == 5
        assert not any("kind='document'" in query for query in queries)
    finally:
        store.close()


@pytest.mark.parametrize("kind", ["document", "context", "cable", "codes", "role"])
def test_carriage_storage_detects_incremental_blob_tampering(tmp_path, monkeypatch, kind):
    from backend.storage import ExecutionReceiptAuthorityError

    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        row = store._conn.execute(
            "SELECT rowid,payload FROM carriage_projection_parts WHERE snapshot_id=? AND kind=? LIMIT 1",
            (sid, kind),
        ).fetchone()
        original = bytes(row["payload"])
        forged = original.replace(b"okay", b"evil") if kind == "document" else b" " + original[1:]
        if hasattr(store._conn, "blobopen"):
            with store._conn.blobopen("carriage_projection_parts", "payload", row["rowid"]) as blob:
                blob.write(forged)
        else:
            # Python 3.10 lacks blobopen; exercise the same changed exact bytes through SQL.
            store._conn.execute("DROP TRIGGER carriage_projection_parts_no_update")
            store._conn.execute("UPDATE carriage_projection_parts SET payload=? WHERE rowid=?",
                                (forged, row["rowid"]))
        store._conn.commit()
        with pytest.raises(ExecutionReceiptAuthorityError):
            if kind == "document":
                store.get_carriage_document(sid)
            else:
                store.get_carriage_page_source(sid, 0)
    finally:
        store.close()


def test_carriage_storage_retains_raw_source_authority_and_integer_anchors(tmp_path, monkeypatch):
    from backend.storage import ExecutionReceiptAuthorityError

    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        anchor = store._conn.execute(
            "SELECT rowid,typeof(digest_0),typeof(digest_1),typeof(digest_2),typeof(digest_3) "
            "FROM carriage_projection_parts WHERE snapshot_id=? LIMIT 1", (sid,),
        ).fetchone()
        assert tuple(anchor)[1:] == ("integer",) * 4
        if hasattr(store._conn, "blobopen"):
            with pytest.raises(sqlite3.OperationalError):
                store._conn.blobopen("carriage_projection_parts", "digest_0", anchor[0])
        raw = store.get_snapshot_blob(sid)[0]
        forged = raw.replace(b'"final"', b'"other"')
        assert forged != raw and len(forged) == len(raw)
        if hasattr(store._conn, "blobopen"):
            with store._conn.blobopen("snapshots", "snapshot_json", sid) as blob:
                blob.write(forged)
        else:
            store._conn.execute("UPDATE snapshots SET snapshot_json=? WHERE id=?", (forged, sid))
        store._conn.commit()
        with pytest.raises(ExecutionReceiptAuthorityError):
            store.get_carriage_document(sid)
        with pytest.raises(ExecutionReceiptAuthorityError):
            store.get_carriage_page_source(sid, 0)
    finally:
        store.close()


def test_carriage_storage_refuses_cross_snapshot_derivative_substitution(tmp_path, monkeypatch):
    from backend.storage import ExecutionReceiptAuthorityError

    store, cid, first, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        second = store.add_snapshot(cid, "second", {"vlan_carriage": {}}, {})["id"]
        store._conn.execute("DROP TRIGGER carriage_projection_parts_no_update")
        store._conn.execute(
            """UPDATE carriage_projection_parts SET
               (payload,digest_0,digest_1,digest_2,digest_3) =
               (SELECT payload,digest_0,digest_1,digest_2,digest_3 FROM carriage_projection_parts
                WHERE snapshot_id=? AND kind='document')
               WHERE snapshot_id=? AND kind='document'""", (second, first),
        )
        store._conn.commit()
        assert store.get_carriage_document(second)[0]["stored"] == "okay"
        with pytest.raises(ExecutionReceiptAuthorityError):
            store.get_carriage_document(first)
    finally:
        store.close()


def test_carriage_storage_refuses_ordinary_part_rewrite_replace_and_delete(tmp_path, monkeypatch):
    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        for sql in (
            "UPDATE carriage_projection_parts SET payload=x'7b7d' WHERE kind='document'",
            "DELETE FROM carriage_projection_parts WHERE kind='document'",
            "INSERT OR REPLACE INTO carriage_projection_parts SELECT * FROM carriage_projection_parts",
            "UPDATE snapshots SET carriage_projection_required=0",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                store._conn.execute(sql)
            store._conn.rollback()
        assert store.get_carriage_document(sid)[0]["stored"] == "okay"
    finally:
        store.close()


def test_carriage_storage_unreadable_preparation_is_atomic_refusal(tmp_path, monkeypatch):
    from backend import engine

    store, cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(engine, "prepare_carriage_projection", lambda _raw: None)
        with pytest.raises(ValueError, match="unsupported carriage projection"):
            store.add_snapshot(cid, "invalid preparation", {"vlan_carriage": {}}, {})
        assert [row["id"] for row in store.list_snapshots(cid)] == [sid]
        assert store.get_carriage_document(sid)[0]["stored"] == "okay"
    finally:
        store.close()


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_carriage_storage_nonfinite_source_refuses_before_preparation(tmp_path, monkeypatch, nonfinite):
    store, cid, sid, observed = _carriage_store(tmp_path, monkeypatch)
    try:
        with pytest.raises(ValueError):
            store.add_snapshot(cid, "nonfinite", {"devices": {}, "value": nonfinite}, {})
        assert len(observed) == 1
        assert [row["id"] for row in store.list_snapshots(cid)] == [sid]
    finally:
        store.close()


def test_carriage_storage_observer_failure_rolls_back_source_and_all_parts(tmp_path, monkeypatch):
    store, cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        before = store._conn.execute("SELECT COUNT(*) FROM carriage_projection_parts").fetchone()[0]

        def refuse(_digest):
            raise RuntimeError("synthetic observer refusal")

        store.add_snapshot_digest_observer(refuse)
        with pytest.raises(RuntimeError, match="synthetic observer refusal"):
            store.add_snapshot(cid, "rolled back", {"vlan_carriage": {}}, {})
        assert [row["id"] for row in store.list_snapshots(cid)] == [sid]
        assert store._conn.execute("SELECT COUNT(*) FROM carriage_projection_parts").fetchone()[0] == before
        assert store._conn.execute("SELECT COUNT(*) FROM snapshot_authority").fetchone()[0] == 1
    finally:
        store.close()


@pytest.mark.parametrize("kind", ["document", "role"])
def test_carriage_storage_restart_does_not_reseal_missing_parts(tmp_path, monkeypatch, kind):
    from backend.storage import ExecutionReceiptAuthorityError, Store

    store, _cid, sid, observed = _carriage_store(tmp_path, monkeypatch)
    path = store.db_path
    store._conn.execute("DROP TRIGGER carriage_projection_parts_no_delete")
    store._conn.execute("DELETE FROM carriage_projection_parts WHERE snapshot_id=? AND kind=?", (sid, kind))
    store._conn.commit()
    store.close()
    reopened = Store(path)
    try:
        assert len(observed) == 1
        with pytest.raises(ExecutionReceiptAuthorityError):
            if kind == "document":
                reopened.get_carriage_document(sid)
            else:
                reopened.get_carriage_page_source(sid, 0)
    finally:
        reopened.close()


def test_carriage_storage_legacy_migration_prepares_once_from_unchanged_source(tmp_path, monkeypatch):
    from backend.storage import Store

    store, _cid, sid, observed = _carriage_store(tmp_path, monkeypatch)
    path = store.db_path
    raw = store.get_snapshot_blob(sid)[0]
    store._conn.execute("DROP TRIGGER carriage_projection_requirement_no_update")
    store._conn.execute("DROP TABLE carriage_projection_parts")
    store._conn.execute("DROP TABLE carriage_projection_role_presence")
    store._conn.execute("ALTER TABLE snapshots DROP COLUMN carriage_projection_required")
    store._conn.commit()
    store.close()
    migrated = Store(path)
    try:
        assert observed == [raw, raw]
        assert migrated.get_snapshot_blob(sid)[0] == raw
        assert migrated.get_carriage_document(sid)[0]["stored"] == "okay"
    finally:
        migrated.close()
    reopened = Store(path)
    try:
        assert observed == [raw, raw]
        assert reopened.get_carriage_page_source(sid, 0)[0]["cables"]
    finally:
        reopened.close()


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSHUB_TOKEN", raising=False)
    monkeypatch.delenv("ASSESSHUB_ALLOWED_HOSTS", raising=False)
    return str(tmp_path / "raw.db")


@pytest.fixture()
def client(db_path):
    app = create_app(db_path=db_path, scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost") as c:
        yield c


def _seed(client) -> int:
    r = client.post("/api/demo/seed")
    assert r.status_code == 200, r.text
    return r.json()["snapshot"]["id"]


def _stored_blob(db_path: str, snapshot_id: int) -> bytes:
    """The persisted bytes, read straight from SQLite — independent of any app/store accessor."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT CAST(snapshot_json AS BLOB) FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return bytes(row[0])


def test_raw_returns_the_stored_bytes_unchanged_with_their_binding(client, db_path):
    sid = _seed(client)
    r = client.get(f"/api/snapshots/{sid}/raw", headers={"sec-fetch-site": "same-origin"})
    assert r.status_code == 200, r.text[:300]
    body = r.content

    # exact persisted bytes, not a re-serialisation
    assert body == _stored_blob(db_path, sid)
    # the headers are the binding of THOSE bytes
    assert r.headers["x-snapshot-sha256"] == hashlib.sha256(body).hexdigest()
    assert r.headers["x-snapshot-bytes"] == str(len(body))
    # ...and equal the store's own binding (the digest compare/trend receipts already use)
    _snap, binding = client.app.state.store.get_bound_snapshot(sid)
    assert binding["sha256"] == "sha256:" + r.headers["x-snapshot-sha256"]
    assert binding["bytes"] == len(body)
    # the digest form is named, so a consumer never confuses it with a file-level digest
    assert r.headers["x-snapshot-digest-form"] == "assesshub-store-blob"

    assert r.headers["content-type"].split(";")[0].strip() == "application/json"
    assert r.headers["cache-control"] == "no-store"
    # it parses to the stored snapshot
    assert json.loads(body) == client.app.state.store.get_snapshot(sid)


def test_raw_unknown_snapshot_is_404(client):
    _seed(client)
    r = client.get("/api/snapshots/987654/raw")
    assert r.status_code == 404
    assert "x-snapshot-sha256" not in r.headers


def test_raw_refuses_a_cross_site_get(client):
    sid = _seed(client)
    r = client.get(f"/api/snapshots/{sid}/raw", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    assert "cross-site" in r.json()["detail"].lower()
    assert "x-snapshot-sha256" not in r.headers
    # control: the same request same-origin is served, so the 403 above is the guard, not a 404
    assert client.get(f"/api/snapshots/{sid}/raw",
                      headers={"sec-fetch-site": "same-origin"}).status_code == 200


def test_raw_refuses_a_foreign_host_header(client):
    sid = _seed(client)
    r = client.get(f"/api/snapshots/{sid}/raw", headers={"host": "evil.example"})
    assert r.status_code == 403
    assert "host" in r.json()["detail"].lower()
    assert client.get(f"/api/snapshots/{sid}/raw").status_code == 200


def test_raw_refuses_a_non_loopback_peer_without_a_token(db_path):
    app = create_app(db_path=db_path, scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost") as local:
        sid = _seed(local)
        assert local.get(f"/api/snapshots/{sid}/raw").status_code == 200
    app = create_app(db_path=db_path, scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost", client=("10.0.0.5", 50000)) as remote:
        r = remote.get(f"/api/snapshots/{sid}/raw")
        assert r.status_code == 403
        assert "ASSESSHUB_TOKEN" in r.json()["detail"]


def test_raw_in_token_mode_requires_the_session_cookie(db_path, monkeypatch):
    monkeypatch.setenv("ASSESSHUB_TOKEN", "raw-secret")
    app = create_app(db_path=db_path, scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost") as c:
        assert c.post("/api/demo/seed",
                      headers={"Authorization": "Bearer raw-secret"}).status_code == 200
        sid = 1
        r = c.get(f"/api/snapshots/{sid}/raw")
        assert r.status_code == 401
        assert "x-snapshot-sha256" not in r.headers
        # control: the same-origin browser session (what a /scope page's fetch carries) is enough
        assert c.post("/api/session",
                      headers={"Authorization": "Bearer raw-secret"}).status_code == 204
        ok = c.get(f"/api/snapshots/{sid}/raw")
        assert ok.status_code == 200
        assert ok.headers["x-snapshot-sha256"] == hashlib.sha256(ok.content).hexdigest()


def test_a_scope_page_reads_raw_with_the_session_but_cannot_write_with_it(db_path, monkeypatch):
    """Same-origin write containment, token mode. The session cookie a /scope page carries is the
    same authority the AssessHub UI writes with, and the cross-site/CSRF guards pass a same-origin
    request. A /scope page's requests carry a same-origin Referer (Referrer-Policy: same-origin on
    every /scope response), and the /api guard refuses any non-GET request referred from /scope/ —
    before authentication, so neither the cookie nor the Bearer token itself unlocks a write.
    Defence in depth: the viewer has no write code; a hostile script could rewrite its Referer."""
    monkeypatch.setenv("ASSESSHUB_TOKEN", "raw-secret")
    scope_page = {"referer": "http://localhost/scope/snapshots/1/", "origin": "http://localhost",
                  "sec-fetch-site": "same-origin"}
    app = create_app(db_path=db_path, scope_dist_dir=None)
    with TestClient(app, base_url="http://localhost") as c:
        assert c.post("/api/demo/seed",
                      headers={"Authorization": "Bearer raw-secret"}).status_code == 200
        assert c.post("/api/session",
                      headers={"Authorization": "Bearer raw-secret"}).status_code == 204
        read = c.get("/api/snapshots/1/raw", headers=scope_page)
        assert read.status_code == 200
        assert read.headers["x-snapshot-sha256"] == hashlib.sha256(read.content).hexdigest()
        for extra in ({}, {"Authorization": "Bearer raw-secret"}):
            r = c.post("/api/campaigns", json={"name": "from scope"}, headers={**scope_page, **extra})
            assert r.status_code == 403, (extra, r.status_code, r.text[:200])
            assert "Atlas Scope" in r.json()["detail"]
            assert c.delete("/api/snapshots/1", headers={**scope_page, **extra}).status_code == 403
        assert c.get("/api/snapshots/1/raw").status_code == 200  # still there
        # control: the same session writes when the request is not referred from /scope/
        ui_page = {**scope_page, "referer": "http://localhost/campaigns"}
        created = c.post("/api/campaigns", json={"name": "from the UI"}, headers=ui_page)
        assert created.status_code == 201, created.text[:200]


# ── the digest forms are NOT the same fact (docs/ssot.md, "Facts that live in two homes") ─────────
_REPO = Path(__file__).resolve().parents[2]
_ATLAS_SCOPE_TOOLS = _REPO / "atlas-scope" / "tools"
_SAMPLE = _REPO / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
_REQUIRE_REAL_TOOLCHAIN_ENV = "ATLAS_SCOPE_REQUIRE_REAL_TOOLCHAIN"

#: Runs Atlas Scope's ONE compiler (the same module the browser runs) twice: over the bytes this
#: route serves, labelled as an AssessHub stored blob, and over the tracked sample FILE, labelled as a
#: repository file. Prints the two bindings and whether every compiled document is identical once
#: its `meta` (the binding) is set aside.
_COMPILE_BOTH = r"""
const [modelUrl, validateUrl, bindingUrl, storePath, filePath, snapshotId, fileRel] = process.argv.slice(1);
const { readFileSync } = await import("node:fs");
const { compileAll } = await import(modelUrl);
const { assertValidSnapshot } = await import(validateUrl);
const { bindSource } = await import(bindingUrl);
const compile = (path, label) => {
  const bytes = new Uint8Array(readFileSync(path));
  const v = assertValidSnapshot(bytes);
  const binding = bindSource(bytes, label);
  return { binding, set: compileAll(v.snap, binding, { schemaAssumed: v.schemaAssumed }) };
};
const store = compile(storePath, { source: `assesshub:snapshot/${snapshotId}`, sourceOrigin: "assesshub-store",
                                   sourceDigestForm: "assesshub-store-blob" });
const file = compile(filePath, { source: fileRel, sourceOrigin: "repository-file" });
const sansMeta = (doc) => JSON.stringify(Object.fromEntries(Object.entries(doc).filter(([k]) => k !== "meta")));
const identical = Object.fromEntries(Object.keys(store.set).map((k) => [k, sansMeta(store.set[k]) === sansMeta(file.set[k])]));
console.log(JSON.stringify({ store: store.binding, file: file.binding, identical }));
"""


def test_the_store_blob_digest_is_its_own_form_and_the_compiled_fabric_does_not_depend_on_it(
        client, tmp_path):
    """Four digests name 'the sample snapshot' and they are four different facts: the LF-normalised
    FILE digest and the Git blob id (both over the tracked file), the exact bytes-as-read digest, and
    the AssessHub STORE-BLOB digest this route serves (the store re-serialises what it parses). The
    compiled fabric is a projection of the snapshot CONTENT: compiled from the stored blob or from the
    file, every compiled document is identical except the binding, and the store-form binding is
    exactly this route's headers. Runs Atlas Scope's real compiler (node)."""
    import os
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node or not (_ATLAS_SCOPE_TOOLS / "lib" / "compile-model.mjs").is_file():
        reason = "node or atlas-scope/tools is absent: the cross-language digest-form pin is skipped"
        if os.environ.get(_REQUIRE_REAL_TOOLCHAIN_ENV) == "1":
            pytest.fail(f"{_REQUIRE_REAL_TOOLCHAIN_ENV}=1 but {reason}", pytrace=False)
        pytest.skip(reason)
    sid = _seed(client)
    raw = client.get(f"/api/snapshots/{sid}/raw")
    assert raw.status_code == 200
    stored = tmp_path / "stored.json"
    stored.write_bytes(raw.content)
    proc = subprocess.run(
        [node, "--input-type=module", "-e", _COMPILE_BOTH,
         (_ATLAS_SCOPE_TOOLS / "lib" / "compile-model.mjs").as_uri(),
         (_ATLAS_SCOPE_TOOLS / "lib" / "validate-snapshot.mjs").as_uri(),
         (_ATLAS_SCOPE_TOOLS / "source-binding.mjs").as_uri(),
         str(stored), str(_SAMPLE), str(sid), "webapp/sample_data/sample_fleet.snapshot.json"],
        capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    store, file = result["store"], result["file"]

    # the store-form binding IS this route's binding
    assert store["sourceDigestForm"] == raw.headers["x-snapshot-digest-form"] == "assesshub-store-blob"
    assert store["sourceSha256"] == raw.headers["x-snapshot-sha256"]
    assert store["sourceBytes"] == int(raw.headers["x-snapshot-bytes"]) == len(raw.content)
    # ...and the file-form binding is a different fact over different bytes
    file_bytes = _SAMPLE.read_bytes()
    lf = file_bytes.replace(b"\r\n", b"\n")
    assert file["sourceDigestForm"] == "lf-normalised"
    assert file["sourceSha256"] == hashlib.sha256(lf).hexdigest() != store["sourceSha256"]
    assert file["sourceExactSha256"] == "sha256:" + hashlib.sha256(file_bytes).hexdigest()
    assert file["sourceGitBlob"] == hashlib.sha1(b"blob %d\0" % len(lf) + lf).hexdigest()
    assert len({file["sourceSha256"], store["sourceSha256"], file["sourceGitBlob"],
                file["sourceExactSha256"].removeprefix("sha256:")}) >= 3
    # the compiled model does not depend on which form bound it
    assert result["identical"] and all(result["identical"].values()), result["identical"]
