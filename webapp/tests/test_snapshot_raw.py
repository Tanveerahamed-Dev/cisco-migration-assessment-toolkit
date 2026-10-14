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
import re
import sqlite3
import sys
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend.app import create_app  # noqa: E402


def _trace_bootstrap_connections(monkeypatch):
    from backend import storage

    original_connect = sqlite3.connect
    scripts, statements, cleanup = [], [], []

    class TracedConnection(sqlite3.Connection):
        def executescript(self, sql):
            scripts.append(sql)
            return super().executescript(sql)

        def rollback(self):
            cleanup.append("rollback")
            return super().rollback()

        def close(self):
            cleanup.append("close")
            return super().close()

    def connect(*args, **kwargs):
        connection = original_connect(*args, **{**kwargs, "factory": TracedConnection})
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(storage.sqlite3, "connect", connect)
    return original_connect, scripts, statements, cleanup


def test_fresh_store_schema_bootstrap_uses_one_transaction_before_migrations(tmp_path, monkeypatch):
    from backend import engine, storage

    _connect, scripts, statements, _cleanup = _trace_bootstrap_connections(monkeypatch)
    store = storage.Store(tmp_path / "fresh-bootstrap.db")
    try:
        assert scripts == ["BEGIN IMMEDIATE;\n" + storage._SCHEMA + "\nCOMMIT;"]
        normalized = [statement.strip().rstrip(";").strip().upper() for statement in statements]
        begin = normalized.index("BEGIN IMMEDIATE")
        commit = normalized.index("COMMIT", begin + 1)
        schema_count = len(re.findall(r"^CREATE (?:TABLE|INDEX|TRIGGER)\b", storage._SCHEMA, re.MULTILINE))
        actual_count = sum(bool(re.search(r"\bCREATE (?:TABLE|INDEX|TRIGGER)\b", statement))
                           for statement in normalized[begin + 1:commit])
        assert actual_count == schema_count
        assert normalized.count("BEGIN IMMEDIATE") == 1
        assert next(i for i, statement in enumerate(normalized)
                    if statement.startswith("ALTER TABLE")) > commit
        assert store._conn.in_transaction is False
        # The bootstrap transaction is closed before the first real snapshot/source anchor.
        monkeypatch.setattr(engine, "prepare_carriage_projection", lambda _raw: _carriage_storage_pack())
        cid = store.create_campaign("first guarded source")["id"]
        sid = store.add_snapshot(cid, "first", {"devices": {}, "marker": "before"}, {})["id"]
        assert store.get_carriage_document(sid)[0]["stored"] == "okay"
        raw = store.get_snapshot_blob(sid)[0]
        store._conn.execute("UPDATE snapshots SET snapshot_json=? WHERE id=?",
                            (raw.replace(b"before", b"after!"), sid))
        store._conn.commit()
        with pytest.raises(storage.ExecutionReceiptAuthorityError):
            store.get_carriage_document(sid)
    finally:
        store.close()


@pytest.mark.parametrize("existing", ["same_version", "partial", "view_only"])
def test_existing_store_bootstrap_keeps_original_script_and_locking(tmp_path, monkeypatch, existing):
    from backend import storage

    database = tmp_path / "existing-bootstrap.db"
    prior_view_sql = None
    if existing == "same_version":
        storage.Store(database).close()
    else:
        connection = sqlite3.connect(database)
        if existing == "partial":
            connection.execute("CREATE TABLE retained_partial_evidence(value TEXT)")
            connection.execute("INSERT INTO retained_partial_evidence VALUES ('keep')")
        else:
            connection.execute("CREATE VIEW retained_readonly_view AS SELECT 'keep' AS value")
            prior_view_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='view' AND name='retained_readonly_view'"
            ).fetchone()[0]
        connection.commit()
        connection.close()
    _connect, scripts, statements, _cleanup = _trace_bootstrap_connections(monkeypatch)
    store = storage.Store(database)
    try:
        assert scripts == [storage._SCHEMA]
        assert scripts[0] is storage._SCHEMA
        assert not any("BEGIN IMMEDIATE" in statement.upper() for statement in statements)
        if existing == "partial":
            assert store._conn.execute("SELECT value FROM retained_partial_evidence").fetchone()[0] == "keep"
        elif existing == "view_only":
            assert store._conn.execute("SELECT value FROM retained_readonly_view").fetchone()[0] == "keep"
            assert store._conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='view' AND name='retained_readonly_view'"
            ).fetchone()[0] == prior_view_sql
    finally:
        store.close()


def test_fresh_store_failed_bootstrap_rolls_back_every_schema_object_and_closes(tmp_path, monkeypatch):
    from backend import storage

    database = tmp_path / "failed-bootstrap.db"
    original_connect, _scripts, _statements, cleanup = _trace_bootstrap_connections(monkeypatch)
    monkeypatch.setattr(storage, "_SCHEMA", storage._SCHEMA + "\nSELECT * FROM missing_bootstrap_guard;")
    with pytest.raises(sqlite3.OperationalError, match="missing_bootstrap_guard"):
        storage.Store(database)
    assert cleanup == ["rollback", "close"]
    connection = original_connect(database, timeout=0.1)
    try:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index','trigger')").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        connection.execute("BEGIN IMMEDIATE")
        connection.rollback()
    finally:
        connection.close()


def test_fresh_bootstrap_preserves_control_exception_when_both_cleanup_calls_fail(tmp_path, monkeypatch):
    from backend import storage

    database = tmp_path / "cleanup-failure.db"
    original_connect = sqlite3.connect
    original_error = KeyboardInterrupt("bootstrap interrupted")
    cleanup = []

    class FailingCleanupConnection(sqlite3.Connection):
        def executescript(self, _sql):
            super().executescript("BEGIN IMMEDIATE; CREATE TABLE unfinished_bootstrap(value);")
            raise original_error

        def rollback(self):
            cleanup.append("rollback")
            super().rollback()
            raise RuntimeError("secondary rollback error")

        def close(self):
            cleanup.append("close")
            super().close()
            raise RuntimeError("secondary close error")

    monkeypatch.setattr(storage.sqlite3, "connect", lambda *args, **kwargs: original_connect(
        *args, **{**kwargs, "factory": FailingCleanupConnection}))
    with pytest.raises(KeyboardInterrupt) as raised:
        storage.Store(database)
    assert raised.value is original_error
    assert cleanup == ["rollback", "close"]
    connection = original_connect(database, timeout=0.1)
    try:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    finally:
        connection.close()


def _carriage_storage_pack(cable_count=3, members=1):
    """Synthetic producer output: persistence tests do not trust uploaded derivatives."""
    cables = [{"ordinal": ordinal, "index": ordinal, "member_count": members}
              for ordinal in range(cable_count)]

    def rows():
        for meta in cables:
            if members > 400:
                yield {**meta, "dictionary": b"",
                       "variants": iter([{"vlan_index": 0, "bytes": None, "payload": None}])}
                continue
            raw = json.dumps({"stored": "row", "index": meta["index"]}, separators=(",", ":")).encode()
            dictionary = b"stored row dictionary"
            compressor = zlib.compressobj(zdict=dictionary)
            payload = compressor.compress(raw) + compressor.flush()
            yield {**meta, "dictionary": dictionary,
                   "variants": iter([{"vlan_index": 0, "bytes": len(raw), "payload": payload}])}

    return {
        "schema": "carriage_projection_preparation/2",
        "document": {"stored": "okay", "cable_count": cable_count},
        "context": {"stored": "context"}, "cables": cables,
        "vlans": [{"vlan_index": 0, "vlan": 10, "summary": {}, "failed": None,
                   "readable": True, "total": cable_count}],
        "rows": rows(),
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
        parts = [query for query in queries if "FROM carriage_projection_v2_parts" in query]
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


def test_carriage_storage_bundle_reads_and_hashes_source_once_without_decoding_document(tmp_path, monkeypatch):
    from backend import storage

    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        expected_raw, expected_binding = store.get_snapshot_blob(sid)
        expected_pack, _binding = store.get_carriage_page_source(sid, 0)
        expected_document = bytes(store._conn.execute(
            "SELECT payload FROM carriage_projection_v2_parts WHERE snapshot_id=? AND kind='document'", (sid,),
        ).fetchone()[0])
        source_hashes = []
        original_identity = storage._blob_identity
        original_loads = storage._strict_json_loads

        def identity(value):
            if value == expected_raw:
                source_hashes.append(value)
            return original_identity(value)

        def loads(value):
            assert value not in (expected_raw, expected_document), "bundle decoded source/full document"
            return original_loads(value)

        monkeypatch.setattr(storage, "_blob_identity", identity)
        monkeypatch.setattr(storage, "_strict_json_loads", loads)
        queries = []
        store._conn.set_trace_callback(queries.append)
        raw, binding, pack = store.get_carriage_page_bundle(sid, 0)
        assert (raw, binding, pack) == (expected_raw, expected_binding, expected_pack)
        assert source_hashes == [expected_raw]
        assert sum("CAST(s.snapshot_json AS BLOB)" in query for query in queries) == 1
        assert queries.count("BEGIN") == queries.count("COMMIT") == 1
        assert not any("kind='document'" in query for query in queries)
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
            store._conn.execute("DROP TRIGGER carriage_projection_v2_parts_no_delete")
            store._conn.execute(
                "DELETE FROM carriage_projection_v2_parts WHERE snapshot_id=? AND kind='document'", (sid,),
            )
        else:
            if mutation == "blob":
                row = store._conn.execute(
                    "SELECT rowid,payload FROM carriage_projection_v2_parts "
                    "WHERE snapshot_id=? AND kind='document'", (sid,),
                ).fetchone()
                rowid, table, column = row["rowid"], "carriage_projection_v2_parts", "payload"
                forged = bytes(row["payload"]).replace(b"okay", b"evil")
            else:
                rowid, table, column = sid, "snapshots", "snapshot_json"
                forged = store.get_snapshot_blob(sid)[0].replace(b'"final"', b'"other"')
            if hasattr(store._conn, "blobopen"):
                with store._conn.blobopen(table, column, rowid) as blob:
                    blob.write(forged)
            elif mutation == "blob":
                store._conn.execute("DROP TRIGGER carriage_projection_v2_parts_no_update")
                store._conn.execute(
                    "UPDATE carriage_projection_v2_parts SET payload=? WHERE rowid=?", (forged, rowid),
                )
            else:
                store._conn.execute("UPDATE snapshots SET snapshot_json=? WHERE id=?", (forged, rowid))
        store._conn.commit()
        with pytest.raises(ExecutionReceiptAuthorityError):
            store.verify_carriage_document(sid)
        if mutation == "source":
            with pytest.raises(ExecutionReceiptAuthorityError):
                store.get_carriage_page_bundle(sid, 0)
        else:
            # A page certifies only its independently anchored context/summary/row fragments.
            assert store.get_carriage_page_bundle(sid, 0)[2]["rows"]
    finally:
        store.close()


def test_carriage_storage_page_reads_only_bounded_precomputed_rows(tmp_path, monkeypatch):
    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch, cable_count=1200, members=3)
    try:
        queries = []
        store._conn.set_trace_callback(queries.append)
        pack, _binding = store.get_carriage_page_source(sid, 0, offset=199, limit=200)
        materialized = [row for row in pack["rows"] if "payload" in row]
        assert len(materialized) == 133
        assert sum(row["member_count"] for row in materialized) == 399
        assert pack["rows"][-1]["ordinal"] == 332
        assert pack["rows"][-1]["member_count"] == 3
        assert "payload" not in pack["rows"][-1]
        for row in materialized:
            decoder = zlib.decompressobj(zdict=row["dictionary"])
            raw = decoder.decompress(row["payload"]) + decoder.flush()
            assert len(raw) == row["bytes"]
            assert json.loads(raw) == {"stored": "row", "index": row["index"]}
        assert not any("role" in query or "codes" in query for query in queries)
        assert not any("kind='document'" in query for query in queries)
    finally:
        store.close()


def test_carriage_storage_unknown_selector_is_distinct_from_missing_derivative(tmp_path, monkeypatch):
    from backend.storage import ExecutionReceiptAuthorityError

    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        with pytest.raises(IndexError, match="prepared carriage selector"):
            store.get_carriage_page_bundle(sid, 1)
        store._conn.execute("DROP TRIGGER carriage_projection_v2_parts_no_delete")
        store._conn.execute(
            "DELETE FROM carriage_projection_v2_parts WHERE snapshot_id=? AND kind='vlan'", (sid,),
        )
        store._conn.commit()
        with pytest.raises(ExecutionReceiptAuthorityError, match="missing"):
            store.get_carriage_page_bundle(sid, 0)
    finally:
        store.close()


def test_carriage_storage_oversized_member_row_reads_only_held_metadata(tmp_path, monkeypatch):
    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch, members=401)
    try:
        queries = []
        store._conn.set_trace_callback(queries.append)
        pack, _binding = store.get_carriage_page_source(sid, 0)
        assert pack["rows"] == [{"ordinal": 0, "index": 0, "member_count": 401, "bytes": None}]
        assert not any("kind='dictionary'" in query or "kind='row:0'" in query for query in queries)
    finally:
        store.close()


def test_carriage_storage_page_stops_before_expanded_byte_boundary_payload(tmp_path, monkeypatch):
    from backend import engine

    store, cid, _sid, _observed = _carriage_store(tmp_path, monkeypatch)

    def prepare(_raw):
        result = _carriage_storage_pack(3)

        def rows():
            for meta in result["cables"]:
                raw = json.dumps({"index": meta["index"], "stored": "x" * 1_600_000}).encode()
                dictionary = raw[-32768:]
                compressor = zlib.compressobj(zdict=dictionary)
                payload = compressor.compress(raw) + compressor.flush()
                yield {**meta, "dictionary": dictionary,
                       "variants": iter([{"vlan_index": 0, "bytes": len(raw), "payload": payload}])}

        result["rows"] = rows()
        return result

    try:
        monkeypatch.setattr(engine, "prepare_carriage_projection", prepare)
        sid = store.add_snapshot(cid, "byte boundary", {"devices": {}}, {})["id"]
        queries = []
        store._conn.set_trace_callback(queries.append)
        pack, _binding = store.get_carriage_page_source(sid, 0)
        assert len(pack["rows"]) == 2
        assert "payload" in pack["rows"][0]
        assert "payload" not in pack["rows"][1]
        assert not any("kind='row:0' AND part_key='1'" in query for query in queries)
        assert not any("kind='dictionary' AND part_key='1'" in query for query in queries)
    finally:
        store.close()


def test_carriage_storage_payload_census_counts_every_materialized_part(tmp_path, monkeypatch):
    from backend.storage import CARRIAGE_PROJECTION_PAYLOAD_LIMIT

    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        actual = store._conn.execute(
            "SELECT SUM(length(payload)) FROM carriage_projection_v2_parts WHERE snapshot_id=?", (sid,),
        ).fetchone()[0]
        assert store.get_carriage_projection_payload_bytes(sid) == actual
        assert 0 < actual <= CARRIAGE_PROJECTION_PAYLOAD_LIMIT == 64_000_000
    finally:
        store.close()


def test_carriage_storage_materialization_limit_rolls_back_and_closes_stream(tmp_path, monkeypatch):
    from backend import engine, storage

    store, cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    streams = []

    class TrackedRows:
        def __init__(self, source):
            self.source = source
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.source)

        def close(self):
            self.closed = True
            self.source.close()

    def prepare(_raw):
        result = _carriage_storage_pack(30)
        result["rows"] = TrackedRows(result["rows"])
        streams.append(result["rows"])
        return result

    try:
        before = store._conn.execute("SELECT COUNT(*) FROM carriage_projection_v2_parts").fetchone()[0]
        monkeypatch.setattr(engine, "prepare_carriage_projection", prepare)
        monkeypatch.setattr(storage, "CARRIAGE_PROJECTION_PAYLOAD_LIMIT", 1000)
        with pytest.raises(storage.CarriagePreparationLimitError, match="carriage derivative payload exceeds"):
            store.add_snapshot(cid, "over limit", {"devices": {}}, {})
        assert streams and all(stream.closed for stream in streams)
        assert [row["id"] for row in store.list_snapshots(cid)] == [sid]
        assert store._conn.execute("SELECT COUNT(*) FROM carriage_projection_v2_parts").fetchone()[0] == before
        assert store._conn.execute("SELECT COUNT(*) FROM snapshot_authority").fetchone()[0] == 1
    finally:
        store.close()


@pytest.mark.parametrize("kind", ["document", "context", "vlan", "row_meta:0", "row:0", "dictionary"])
def test_carriage_storage_detects_incremental_blob_tampering(tmp_path, monkeypatch, kind):
    from backend.storage import ExecutionReceiptAuthorityError

    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        row = store._conn.execute(
            "SELECT rowid,payload FROM carriage_projection_v2_parts WHERE snapshot_id=? AND kind=? LIMIT 1",
            (sid, kind),
        ).fetchone()
        original = bytes(row["payload"])
        forged = original.replace(b"okay", b"evil") if kind == "document" else b" " + original[1:]
        if hasattr(store._conn, "blobopen"):
            with store._conn.blobopen("carriage_projection_v2_parts", "payload", row["rowid"]) as blob:
                blob.write(forged)
        else:
            # Python 3.10 lacks blobopen; exercise the same changed exact bytes through SQL.
            store._conn.execute("DROP TRIGGER carriage_projection_v2_parts_no_update")
            store._conn.execute("UPDATE carriage_projection_v2_parts SET payload=? WHERE rowid=?",
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
            "FROM carriage_projection_v2_parts WHERE snapshot_id=? LIMIT 1", (sid,),
        ).fetchone()
        assert tuple(anchor)[1:] == ("integer",) * 4
        if hasattr(store._conn, "blobopen"):
            with pytest.raises(sqlite3.OperationalError):
                store._conn.blobopen("carriage_projection_v2_parts", "digest_0", anchor[0])
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


@pytest.mark.parametrize("kind", ["document", "context", "row:0", "dictionary"])
def test_carriage_storage_refuses_cross_snapshot_derivative_substitution(tmp_path, monkeypatch, kind):
    from backend.storage import ExecutionReceiptAuthorityError

    store, cid, first, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        second = store.add_snapshot(cid, "second", {"vlan_carriage": {}}, {})["id"]
        store._conn.execute("DROP TRIGGER carriage_projection_v2_parts_no_update")
        key = "0" if kind in ("row:0", "dictionary") else ""
        store._conn.execute(
            """UPDATE carriage_projection_v2_parts SET
               (payload,digest_0,digest_1,digest_2,digest_3) =
               (SELECT payload,digest_0,digest_1,digest_2,digest_3 FROM carriage_projection_v2_parts
                WHERE snapshot_id=? AND kind=? AND part_key=?)
               WHERE snapshot_id=? AND kind=? AND part_key=?""",
            (second, kind, key, first, kind, key),
        )
        store._conn.commit()
        assert store.get_carriage_document(second)[0]["stored"] == "okay"
        with pytest.raises(ExecutionReceiptAuthorityError):
            if kind == "document":
                store.get_carriage_document(first)
            else:
                store.get_carriage_page_bundle(first, 0)
    finally:
        store.close()


def test_carriage_storage_refuses_ordinary_part_rewrite_replace_and_delete(tmp_path, monkeypatch):
    store, _cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    try:
        for sql in (
            "UPDATE carriage_projection_v2_parts SET payload=x'7b7d' WHERE kind='document'",
            "DELETE FROM carriage_projection_v2_parts WHERE kind='document'",
            "INSERT OR REPLACE INTO carriage_projection_v2_parts SELECT * FROM carriage_projection_v2_parts",
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
        before = store._conn.execute("SELECT COUNT(*) FROM carriage_projection_v2_parts").fetchone()[0]

        def refuse(_digest):
            raise RuntimeError("synthetic observer refusal")

        store.add_snapshot_digest_observer(refuse)
        with pytest.raises(RuntimeError, match="synthetic observer refusal"):
            store.add_snapshot(cid, "rolled back", {"vlan_carriage": {}}, {})
        assert [row["id"] for row in store.list_snapshots(cid)] == [sid]
        assert store._conn.execute("SELECT COUNT(*) FROM carriage_projection_v2_parts").fetchone()[0] == before
        assert store._conn.execute("SELECT COUNT(*) FROM snapshot_authority").fetchone()[0] == 1
    finally:
        store.close()


@pytest.mark.parametrize("kind", ["document", "dictionary", "row:0"])
def test_carriage_storage_restart_does_not_reseal_missing_parts(tmp_path, monkeypatch, kind):
    from backend.storage import ExecutionReceiptAuthorityError, Store

    store, _cid, sid, observed = _carriage_store(tmp_path, monkeypatch)
    path = store.db_path
    store._conn.execute("DROP TRIGGER carriage_projection_v2_parts_no_delete")
    store._conn.execute("DELETE FROM carriage_projection_v2_parts WHERE snapshot_id=? AND kind=?", (sid, kind))
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
    store._conn.execute("DROP TRIGGER carriage_projection_version_no_update")
    store._conn.execute("DROP TABLE carriage_projection_v2_parts")
    store._conn.execute("DROP TABLE carriage_projection_role_presence")
    store._conn.execute("ALTER TABLE snapshots DROP COLUMN carriage_projection_required")
    store._conn.execute("ALTER TABLE snapshots DROP COLUMN carriage_projection_version")
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
        assert reopened.get_carriage_page_source(sid, 0)[0]["rows"]
    finally:
        reopened.close()


def test_carriage_storage_superseded_v1_derivative_refuses_without_resealing(tmp_path, monkeypatch):
    from backend.storage import ExecutionReceiptAuthorityError, Store

    store, _cid, sid, observed = _carriage_store(tmp_path, monkeypatch)
    path = store.db_path
    raw = store.get_snapshot_blob(sid)[0]
    store._conn.execute("DROP TABLE carriage_projection_v2_parts")
    store._conn.execute("DROP TRIGGER carriage_projection_version_no_update")
    store._conn.execute("ALTER TABLE snapshots DROP COLUMN carriage_projection_version")
    store._conn.execute(
        """INSERT INTO carriage_projection_parts
           (snapshot_id,projection_version,kind,part_key,ordinal,payload,digest_0,digest_1,digest_2,digest_3)
           VALUES (?,1,'document','',0,?,0,0,0,0)""", (sid, b"superseded-v1"),
    )
    store._conn.commit()
    store.close()
    reopened = Store(path)
    try:
        assert observed == [raw]
        assert reopened.get_snapshot_blob(sid)[0] == raw
        assert reopened._conn.execute("SELECT payload FROM carriage_projection_parts").fetchone()[0] == b"superseded-v1"
        assert reopened._conn.execute("SELECT COUNT(*) FROM carriage_projection_v2_parts").fetchone()[0] == 0
        for read in (lambda: reopened.get_carriage_document(sid),
                     lambda: reopened.get_carriage_page_bundle(sid, 0),
                     lambda: reopened.get_carriage_projection_payload_bytes(sid)):
            with pytest.raises(ExecutionReceiptAuthorityError, match="unavailable"):
                read()
    finally:
        reopened.close()


def _round3_raw_only_fixture(tmp_path, monkeypatch, *, snapshots=1):
    store, cid, sid, observed = _carriage_store(tmp_path, monkeypatch)
    ids = [sid]
    for index in range(1, snapshots):
        ids.append(store.add_snapshot(cid, f"legacy-{index}", {"devices": {}, "index": index}, {})["id"])
    sources = {item: store.get_snapshot_blob(item) for item in ids}
    path = store.db_path
    store._conn.execute("DROP TRIGGER carriage_projection_requirement_no_update")
    store._conn.execute("DROP TRIGGER carriage_projection_version_no_update")
    store._conn.execute("DROP TABLE carriage_projection_v2_parts")
    store._conn.execute("DROP TABLE carriage_projection_role_presence")
    store._conn.execute("ALTER TABLE snapshots DROP COLUMN carriage_projection_required")
    store._conn.execute("ALTER TABLE snapshots DROP COLUMN carriage_projection_version")
    store._conn.commit()
    store.close()
    return path, ids, sources, observed


def _round3_leave_pending_upgrade(path, monkeypatch):
    from backend import storage

    with monkeypatch.context() as patch:
        patch.setattr(storage, "CARRIAGE_PROJECTION_PAYLOAD_LIMIT", 1)
        with pytest.raises(storage.CarriagePreparationLimitError):
            storage.Store(path)


def test_pending_carriage_upgrade_recovers_after_real_payload_refusal(tmp_path, monkeypatch):
    from backend.storage import Store

    path, ids, sources, observed = _round3_raw_only_fixture(tmp_path, monkeypatch)
    _round3_leave_pending_upgrade(path, monkeypatch)
    connection = sqlite3.connect(path, timeout=0.1)
    try:
        assert connection.execute("SELECT carriage_projection_version FROM snapshots").fetchall() == [(-2,)]
        assert connection.execute("SELECT COUNT(*) FROM snapshot_authority").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM carriage_projection_v2_parts").fetchone()[0] == 0
        connection.execute("BEGIN IMMEDIATE")  # Failed Store released its transaction/connection.
        connection.rollback()
    finally:
        connection.close()
    reopened = Store(path)
    try:
        assert reopened.get_snapshot_blob(ids[0]) == sources[ids[0]]
        assert reopened.get_carriage_document(ids[0])[0]["stored"] == "okay"
        assert reopened._conn.execute("SELECT carriage_projection_version FROM snapshots").fetchall()[0][0] == 2
        assert len(observed) == 3  # Initial fixture, refused attempt, source-bound retry.
    finally:
        reopened.close()


@pytest.mark.parametrize("loss", ["row", "table"])
def test_pending_carriage_upgrade_never_reseals_missing_source_anchor(tmp_path, monkeypatch, loss):
    from backend import storage

    path, ids, sources, observed = _round3_raw_only_fixture(tmp_path, monkeypatch)
    _round3_leave_pending_upgrade(path, monkeypatch)
    connection = sqlite3.connect(path)
    try:
        if loss == "table":
            connection.execute("DROP TABLE snapshot_authority")
        else:
            connection.execute("DELETE FROM snapshot_authority WHERE snapshot_id=?", (ids[0],))
        raw = sources[ids[0]][0]
        forged = raw.replace(b'"final"', b'"other"')
        assert forged != raw and len(forged) == len(raw)
        connection.execute("UPDATE snapshots SET snapshot_json=? WHERE id=?", (forged, ids[0]))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(storage.ExecutionReceiptAuthorityError):
        storage.Store(path)
    assert len(observed) == 2
    connection = sqlite3.connect(path, timeout=0.1)
    try:
        assert connection.execute("SELECT carriage_projection_version FROM snapshots").fetchone()[0] == -2
        assert connection.execute("SELECT CAST(snapshot_json AS BLOB) FROM snapshots").fetchone()[0] == forged
        if loss == "table":
            assert connection.execute("SELECT 1 FROM sqlite_master WHERE name='snapshot_authority'").fetchone() is None
        else:
            assert connection.execute("SELECT COUNT(*) FROM snapshot_authority").fetchone()[0] == 0
        connection.execute("BEGIN IMMEDIATE")
        connection.rollback()
    finally:
        connection.close()


def test_raw_only_initial_anchor_failure_rolls_back_schema_and_markers(tmp_path, monkeypatch):
    from backend import storage

    path, ids, sources, _observed = _round3_raw_only_fixture(tmp_path, monkeypatch)
    connection = sqlite3.connect(path)
    try:
        for table in ("snapshot_authority", "execution_comparison_authority", "execution_l2_failure_trial_authority"):
            connection.execute(f"DROP TABLE {table}")
        connection.commit()
    finally:
        connection.close()

    def refuse_anchor(**_kwargs):
        raise RuntimeError("synthetic initial-anchor refusal")

    with monkeypatch.context() as patch:
        patch.setattr(storage, "_snapshot_authority_limbs", refuse_anchor)
        with pytest.raises(RuntimeError, match="initial-anchor refusal"):
            storage.Store(path)
    connection = sqlite3.connect(path, timeout=0.1)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(snapshots)")}
        assert "carriage_projection_required" not in columns
        assert "carriage_projection_version" not in columns
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"snapshot_authority", "execution_comparison_authority",
                    "execution_l2_failure_trial_authority", "carriage_projection_v2_parts"} & tables
        assert connection.execute("SELECT CAST(snapshot_json AS BLOB) FROM snapshots").fetchone()[0] == sources[ids[0]][0]
    finally:
        connection.close()
    reopened = storage.Store(path)
    try:
        assert reopened.get_carriage_document(ids[0])[0]["stored"] == "okay"
    finally:
        reopened.close()


def test_pending_carriage_partial_publication_control_failure_rolls_back_and_retries(tmp_path, monkeypatch):
    from backend import storage

    path, ids, sources, _observed = _round3_raw_only_fixture(tmp_path, monkeypatch)
    _round3_leave_pending_upgrade(path, monkeypatch)
    original_write = storage.Store._write_carriage_projection_locked
    original_error = KeyboardInterrupt("synthetic publication interruption")

    def interrupt_after_first_part(self, snapshot_id, staged, source):
        kind_size, key_size, _ordinal, payload_size = storage._CARRIAGE_STAGE_HEADER.unpack_from(staged)
        end = storage._CARRIAGE_STAGE_HEADER.size + kind_size + key_size + payload_size
        original_write(self, snapshot_id, staged[:end], source)
        raise original_error

    with monkeypatch.context() as patch:
        patch.setattr(storage.Store, "_write_carriage_projection_locked", interrupt_after_first_part)
        with pytest.raises(KeyboardInterrupt) as raised:
            storage.Store(path)
        assert raised.value is original_error
    connection = sqlite3.connect(path, timeout=0.1)
    try:
        assert connection.execute("SELECT carriage_projection_version FROM snapshots").fetchone()[0] == -2
        assert connection.execute("SELECT COUNT(*) FROM carriage_projection_v2_parts").fetchone()[0] == 0
        connection.execute("BEGIN IMMEDIATE")
        connection.rollback()
    finally:
        connection.close()
    reopened = storage.Store(path)
    try:
        assert reopened.get_snapshot_blob(ids[0]) == sources[ids[0]]
        assert reopened.get_carriage_document(ids[0])[0]["stored"] == "okay"
    finally:
        reopened.close()


def test_pending_carriage_upgrade_stages_one_snapshot_outside_transaction_at_a_time(tmp_path, monkeypatch):
    from backend import storage

    path, ids, _sources, _observed = _round3_raw_only_fixture(tmp_path, monkeypatch, snapshots=3)
    original_stage = storage.Store._stage_carriage_projection
    completed_before_stage = []

    def stage(self, preparation):
        assert self._lock.acquire(blocking=False), "legacy preparation owns the shared read lock"
        self._lock.release()
        assert not self._conn.in_transaction
        completed_before_stage.append(self._conn.execute(
            "SELECT COUNT(*) FROM snapshots WHERE carriage_projection_version=2"
        ).fetchone()[0])
        return original_stage(self, preparation)

    monkeypatch.setattr(storage.Store, "_stage_carriage_projection", stage)
    reopened = storage.Store(path)
    try:
        assert completed_before_stage == [0, 1, 2]
        assert all(reopened.get_carriage_document(sid) is not None for sid in ids)
    finally:
        reopened.close()


@pytest.mark.parametrize("legacy_id", [-1, 0])
def test_pending_carriage_upgrade_preserves_supported_nonpositive_snapshot_ids(tmp_path, monkeypatch, legacy_id):
    from backend.storage import Store

    path, ids, sources, _observed = _round3_raw_only_fixture(tmp_path, monkeypatch)
    connection = sqlite3.connect(path)
    try:
        for table in ("snapshot_authority", "execution_comparison_authority", "execution_l2_failure_trial_authority"):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("UPDATE snapshots SET id=? WHERE id=?", (legacy_id, ids[0]))
        connection.commit()
    finally:
        connection.close()
    reopened = Store(path)
    try:
        raw, binding = reopened.get_snapshot_blob(legacy_id)
        assert raw == sources[ids[0]][0]
        assert binding["snapshot_id"] == legacy_id
        assert reopened.get_carriage_document(legacy_id)[0]["stored"] == "okay"
    finally:
        reopened.close()


def test_carriage_staging_encodes_parts_outside_read_lock_and_owns_aliases(tmp_path, monkeypatch):
    from backend import storage

    store, cid, _sid, _observed = _carriage_store(tmp_path, monkeypatch)
    original_stage = store._stage_carriage_projection
    original_encode = storage._canonical_json_bytes

    def encode(value):
        anchor = isinstance(value, dict) and ("source_authority" in value
                 or value.get("schema") == "snapshot_source_authority/1")
        if not anchor:
            assert not store._lock.locked(), "part encoding still owns the shared read lock"
            assert not store._conn.in_transaction
        return original_encode(value)

    def stage(preparation):
        result = original_stage(preparation)
        assert type(result) is bytes
        assert len(result) <= storage.CARRIAGE_PROJECTION_PAYLOAD_LIMIT + storage._CARRIAGE_STAGING_METADATA_LIMIT
        preparation["document"]["stored"] = "changed after ownership"
        preparation["context"]["stored"] = "changed after ownership"
        return result

    try:
        monkeypatch.setattr(storage, "_canonical_json_bytes", encode)
        monkeypatch.setattr(store, "_stage_carriage_projection", stage)
        sid = store.add_snapshot(cid, "owned stage", {"devices": {}}, {})["id"]
        assert store.get_carriage_document(sid)[0]["stored"] == "okay"
        assert store.get_carriage_page_source(sid, 0)[0]["context"]["stored"] == "context"
    finally:
        store.close()


@pytest.mark.parametrize("target", ["dictionary", "payload"])
def test_carriage_staging_refuses_bytes_subclass_length_hooks(tmp_path, monkeypatch, target):
    from backend import engine

    store, cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    calls = []

    class MisleadingBytes(bytes):
        def __len__(self):
            calls.append("length hook")
            return 0

    def prepare(_raw):
        result = _carriage_storage_pack()
        original_rows = result["rows"]

        def rows():
            try:
                for row in original_rows:
                    if target == "dictionary":
                        row["dictionary"] = MisleadingBytes(row["dictionary"])
                    else:
                        variants = list(row["variants"])
                        variants[0]["payload"] = MisleadingBytes(variants[0]["payload"])
                        row["variants"] = iter(variants)
                    yield row
            finally:
                original_rows.close()

        result["rows"] = rows()
        return result

    try:
        monkeypatch.setattr(engine, "prepare_carriage_projection", prepare)
        with pytest.raises(ValueError, match="materialization"):
            store.add_snapshot(cid, "foreign binary", {"devices": {}}, {})
        assert calls == []
        assert [row["id"] for row in store.list_snapshots(cid)] == [sid]
    finally:
        store.close()


def test_carriage_staging_metadata_refusal_and_observer_control_error_are_atomic(tmp_path, monkeypatch):
    from backend import storage

    store, cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    original_error = KeyboardInterrupt("synthetic observer interruption")

    def refuse(_digest):
        raise original_error

    try:
        with monkeypatch.context() as patch:
            patch.setattr(storage, "_CARRIAGE_STAGING_METADATA_LIMIT", 1)
            with pytest.raises(storage.CarriagePreparationLimitError, match="staging metadata"):
                store.add_snapshot(cid, "metadata bound", {"devices": {}}, {})
        store.add_snapshot_digest_observer(refuse)
        with pytest.raises(KeyboardInterrupt) as raised:
            store.add_snapshot(cid, "observer control error", {"devices": {}}, {})
        assert raised.value is original_error
        assert [row["id"] for row in store.list_snapshots(cid)] == [sid]
        assert store._conn.execute("SELECT COUNT(*) FROM snapshot_authority").fetchone()[0] == 1
        assert store.get_carriage_document(sid)[0]["stored"] == "okay"
    finally:
        store.close()


@pytest.mark.parametrize("primary_failure", [False, True])
def test_carriage_staging_cleanup_preserves_primary_and_attempts_every_close(tmp_path, monkeypatch, primary_failure):
    from backend import engine, storage

    store, cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    events = []
    primary = KeyboardInterrupt("row preparation interrupted")
    variant_cleanup = RuntimeError("variant cleanup failed")
    original_buffer = storage.io.BytesIO

    class FailingBuffer(original_buffer):
        def close(self):
            events.append("buffer")
            super().close()
            raise RuntimeError("buffer cleanup failed")

    class Variants:
        def __init__(self, source):
            self.source = source

        def __iter__(self):
            return self

        def __next__(self):
            if primary_failure:
                raise primary
            return next(self.source)

        def close(self):
            events.append("variant")
            raise variant_cleanup

    class Rows:
        def __init__(self, source):
            self.source = source

        def __iter__(self):
            return self

        def __next__(self):
            row = next(self.source)
            row["variants"] = Variants(row["variants"])
            return row

        def close(self):
            events.append("stream")
            self.source.close()
            raise RuntimeError("stream cleanup failed")

    def prepare(_raw):
        result = _carriage_storage_pack()
        result["rows"] = Rows(result["rows"])
        return result

    try:
        monkeypatch.setattr(storage.io, "BytesIO", FailingBuffer)
        monkeypatch.setattr(engine, "prepare_carriage_projection", prepare)
        with pytest.raises(BaseException) as raised:
            store.add_snapshot(cid, "failing cleanup", {"devices": {}}, {})
        assert raised.value is (primary if primary_failure else variant_cleanup)
        assert events == ["variant", "stream", "buffer"]
        assert [row["id"] for row in store.list_snapshots(cid)] == [sid]
    finally:
        store.close()


def test_failed_carriage_rollback_poison_prevents_reading_partial_snapshot(tmp_path, monkeypatch):
    from backend import storage

    original_connect = sqlite3.connect
    events = []

    class FailedRollbackConnection(sqlite3.Connection):
        refuse_cleanup = False

        def rollback(self):
            if self.refuse_cleanup:
                events.append("rollback")
                raise RuntimeError("rollback refused")
            return super().rollback()

        def close(self):
            if self.refuse_cleanup:
                events.append("close")
                raise RuntimeError("close refused")
            return super().close()

    monkeypatch.setattr(storage.sqlite3, "connect", lambda *args, **kwargs: original_connect(
        *args, **{**kwargs, "factory": FailedRollbackConnection}))
    store, cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    connection = store._conn
    original_error = KeyboardInterrupt("observer interrupted publication")

    def refuse(_digest):
        connection.refuse_cleanup = True
        raise original_error

    try:
        store.add_snapshot_digest_observer(refuse)
        with pytest.raises(KeyboardInterrupt) as raised:
            store.add_snapshot(cid, "must never be exposed", {"devices": {}}, {})
        assert raised.value is original_error
        assert events == ["rollback", "close"]
        for read in (lambda: store.list_snapshots(cid), lambda: store.get_snapshot_meta(sid),
                     lambda: store.get_snapshot(sid + 1), lambda: store.get_carriage_document(sid)):
            with pytest.raises(storage.ExecutionReceiptAuthorityError, match="unusable"):
                read()
    finally:
        connection.refuse_cleanup = False
        sqlite3.Connection.rollback(connection)
        sqlite3.Connection.close(connection)
    reader = original_connect(tmp_path / "carriage.db")
    try:
        assert reader.execute("SELECT id FROM snapshots").fetchall() == [(sid,)]
    finally:
        reader.close()


def test_carriage_stage_page_limit_lookup_failure_closes_owned_stream_and_buffer(tmp_path, monkeypatch):
    from backend import engine, storage

    store, cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    original_buffer = storage.io.BytesIO
    original_error = KeyboardInterrupt("page-limit lookup interrupted")
    events = []

    class Buffer(original_buffer):
        def close(self):
            events.append("buffer")
            super().close()

    class Rows:
        def close(self):
            events.append("stream")

    def prepare(_raw):
        result = _carriage_storage_pack()
        result["rows"].close()
        result["rows"] = Rows()
        return result

    def refuse_limits():
        raise original_error

    try:
        monkeypatch.setattr(storage.io, "BytesIO", Buffer)
        monkeypatch.setattr(engine, "prepare_carriage_projection", prepare)
        monkeypatch.setattr(engine, "carriage_page_limits", refuse_limits)
        with pytest.raises(KeyboardInterrupt) as raised:
            store.add_snapshot(cid, "setup refused", {"devices": {}}, {})
        assert raised.value is original_error
        assert events == ["stream", "buffer"]
        assert [row["id"] for row in store.list_snapshots(cid)] == [sid]
    finally:
        store.close()


def test_carriage_preparation_busy_refuses_before_input_access_or_side_effects(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from backend import storage

    store, cid, sid, observed = _carriage_store(tmp_path, monkeypatch)
    original_blob = store.get_snapshot_blob(sid)
    attempted_reads, statements = [], []

    class UnreadableSnapshot(dict):
        def get(self, *_args, **_kwargs):
            attempted_reads.append("snapshot")
            raise AssertionError("busy admission touched a snapshot before refusing")

    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            with store.snapshot_preparation():
                store._conn.set_trace_callback(statements.append)
                try:
                    insertion = workers.submit(store.add_snapshot, cid, "busy", UnreadableSnapshot(), {})
                    with pytest.raises(storage.CarriagePreparationBusyError):
                        insertion.result(timeout=3)
                    # The internal startup path shares the same refusal, including reentry.
                    resume = workers.submit(store._resume_pending_carriage_upgrades)
                    with pytest.raises(storage.CarriagePreparationBusyError):
                        resume.result(timeout=3)
                finally:
                    store._conn.set_trace_callback(None)
        assert attempted_reads == []
        assert statements == []
        assert len(observed) == 1
        assert store.get_snapshot_blob(sid) == original_blob
        assert [row["id"] for row in store.list_snapshots(cid)] == [sid]
        assert store._conn.execute("SELECT COUNT(*) FROM snapshot_authority").fetchone()[0] == 1
        assert store._conn.execute("SELECT DISTINCT snapshot_id FROM carriage_projection_v2_parts").fetchall()[0][0] == sid
        added = store.add_snapshot(cid, "retry after busy", {"devices": {}}, {})
        assert added["id"] != sid
        assert store.get_carriage_document(added["id"])[0]["stored"] == "okay"
    finally:
        store.close()


def test_carriage_preparation_lease_is_same_thread_single_use_and_cannot_escape(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from backend import engine, storage

    store, cid, sid, observed = _carriage_store(tmp_path, monkeypatch)
    original_prepare = engine.prepare_carriage_projection
    reentrant_calls = []

    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            with store.snapshot_preparation() as preparation:
                assert not store._lock.locked()
                assert not store._conn.in_transaction
                foreign_thread = workers.submit(preparation.add_snapshot, cid, "foreign worker", {"devices": {}}, {})
                with pytest.raises(storage.CarriagePreparationBusyError):
                    foreign_thread.result(timeout=3)
                with pytest.raises(storage.CarriagePreparationBusyError):
                    with store.snapshot_preparation():
                        pytest.fail("nested reservation entered")

                def prepare(raw):
                    with pytest.raises(storage.CarriagePreparationBusyError):
                        preparation.add_snapshot(cid, "reentrant", {"devices": {}}, {})
                    reentrant_calls.append("refused")
                    return original_prepare(raw)

                with monkeypatch.context() as patch:
                    patch.setattr(engine, "prepare_carriage_projection", prepare)
                    added = preparation.add_snapshot(cid, "owned worker", {"devices": {}}, {})
                with pytest.raises(storage.CarriagePreparationBusyError):
                    preparation.add_snapshot(cid, "already consumed", {"devices": {}}, {})
            with pytest.raises(storage.CarriagePreparationBusyError):
                preparation.add_snapshot(cid, "escaped", {"devices": {}}, {})
            # Even an unused lease expires; a new reservation cannot revive it.
            with store.snapshot_preparation() as unused:
                pass
            with store.snapshot_preparation() as replacement:
                with pytest.raises(storage.CarriagePreparationBusyError):
                    unused.add_snapshot(cid, "expired unused", {"devices": {}}, {})
                last = replacement.add_snapshot(cid, "new reservation", {"devices": {}}, {})
        assert reentrant_calls == ["refused"]
        assert len(observed) == 3
        assert [row["id"] for row in store.list_snapshots(cid)] == [sid, added["id"], last["id"]]
        assert store.get_carriage_document(added["id"])[0]["stored"] == "okay"
        assert store.get_carriage_document(last["id"])[0]["stored"] == "okay"
    finally:
        store.close()


@pytest.mark.parametrize("failure", ["lease", "before_use", "serialization", "producer", "publication"])
def test_carriage_preparation_reservation_releases_after_control_failure_and_allows_retry(
        tmp_path, monkeypatch, failure):
    from backend import engine, storage

    store, cid, sid, _observed = _carriage_store(tmp_path, monkeypatch)
    original_blob = store.get_snapshot_blob(sid)
    original_write = store._write_carriage_projection_locked
    primary = KeyboardInterrupt("synthetic reserved preparation interruption")

    def refuse(*_args, **_kwargs):
        raise primary

    def interrupt_publication(*args, **kwargs):
        original_write(*args, **kwargs)
        raise primary

    try:
        with monkeypatch.context() as patch:
            if failure == "lease":
                patch.setattr(storage, "_SnapshotPreparation", refuse)
            elif failure == "serialization":
                patch.setattr(storage.json, "dumps", refuse)
            elif failure == "producer":
                patch.setattr(engine, "prepare_carriage_projection", refuse)
            elif failure == "publication":
                patch.setattr(store, "_write_carriage_projection_locked", interrupt_publication)
            with pytest.raises(KeyboardInterrupt) as raised:
                with store.snapshot_preparation() as preparation:
                    if failure == "before_use":
                        raise primary
                    preparation.add_snapshot(cid, "must roll back", {"devices": {}}, {})
            assert raised.value is primary
        assert not store._preparation_lock.locked()
        assert not store._conn.in_transaction
        assert store.get_snapshot_blob(sid) == original_blob
        assert [row["id"] for row in store.list_snapshots(cid)] == [sid]
        assert store._conn.execute("SELECT COUNT(*) FROM snapshot_authority").fetchone()[0] == 1
        assert [row[0] for row in store._conn.execute(
            "SELECT DISTINCT snapshot_id FROM carriage_projection_v2_parts"
        )] == [sid]
        retried = store.add_snapshot(cid, "after interruption", {"devices": {}}, {})
        assert retried["id"] != sid
        assert store.get_carriage_document(retried["id"])[0]["stored"] == "okay"
    finally:
        store.close()


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
