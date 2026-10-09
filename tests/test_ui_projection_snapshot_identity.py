"""G41 -- snapshot identity in the engine block.

Every fleet, device and path document's ``engine`` block names the exact byte string its pointers resolve in:
``snapshot_sha256`` and ``snapshot_bytes`` (with their byte form, ``snapshot_digest_form``). The projection receives
a parsed snapshot, so it cannot know those bytes itself. Their one owner is ``protocol_assurance``: only
``bind_snapshot_json_bytes``, which parses and hashes ONE byte string, mints the marker that
``bound_snapshot_source`` reads back. A mapping handed over already parsed is ``not_collected``; a marker its owner no
longer verifies, an owner fault or a malformed receipt is ``unverified``. The projection never hashes a
re-serialisation in the owner's place.

Every expected digest here is computed independently with ``hashlib`` over the bytes the test itself read, never
read back from the module under test. The positive cases use the tracked engine-built sample fleet's real bytes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import re

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import fib
from cisco_toolkit import ui_projection as uip
from cisco_toolkit.protocol_assurance import bind_snapshot_json_bytes, bound_snapshot_source, canonical_sha256

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
PUB, NC, UV = "published", "not_collected", "unverified"
KEYS = ("snapshot_sha256", "snapshot_bytes")
BASIS = {"snapshot_sha256": "protocol_assurance.bound_snapshot_source:sha256",
         "snapshot_bytes": "protocol_assurance.bound_snapshot_source:bytes"}
HEX64 = re.compile(r"[0-9a-f]{64}")


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _published(raw: bytes):
    """The exact identity facts an engine block must carry for `raw` (independently computed)."""
    return {"snapshot_sha256": {"state": PUB, "value": _digest(raw), "subject": None, "refs": [],
                                "basis": BASIS["snapshot_sha256"]},
            "snapshot_bytes": {"state": PUB, "value": len(raw), "subject": None, "refs": [],
                               "basis": BASIS["snapshot_bytes"]}}


def _withheld(engine, state):
    for key in KEYS:
        fact = engine[key]
        assert (fact["state"], fact["value"], fact["subject"], fact["refs"], fact["basis"]) == (
            state, None, None, [], BASIS[key]), (key, fact)
        assert fact["reason"], key
    assert engine["snapshot_sha256"]["reason"] == engine["snapshot_bytes"]["reason"]
    assert engine["snapshot_digest_form"] == uip.SNAPSHOT_DIGEST_FORM


def _without_identity(engine):
    return {key: value for key, value in engine.items() if key not in KEYS}


def _small_raw() -> bytes:
    return b'{"schema":"collect_parse_snapshot/1","devices":{"sw1":{"hostname":"sw1"}},"script_version":"3.23.0"}'


@pytest.fixture(scope="module")
def sample_raw() -> bytes:
    return SAMPLE.read_bytes()


@pytest.fixture(scope="module")
def schema():
    return uip.ui_projection_schema()


def _validator(schema, definition=None):
    if definition is None:
        return Draft202012Validator(schema)
    return Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                                 "$ref": f"#/$defs/{definition}"})


# --------------------------------------------------------------------------------------------------
# I1 -- the real sample's exact bytes: every document kind publishes the same identity, and validates
# --------------------------------------------------------------------------------------------------
def test_i1_bound_sample_bytes_publish_their_exact_identity_in_every_document(sample_raw, schema):
    bound = bind_snapshot_json_bytes(sample_raw)
    expected = _published(sample_raw)
    hosts = sorted(bound["devices"])[:2]
    assert len(hosts) == 2
    payload = uip.project(bound)
    _validator(schema).validate(payload)
    devices = uip.project_devices(bound, hosts)
    for document in devices:
        _validator(schema, "DeviceDocument").validate(document)
    assert devices[0] == uip.project_device(bound, hosts[0])
    path = uip.project_path(bound, "192.0.2.1", "198.51.100.1")
    _validator(schema, "PathDocument").validate(path)
    for engine in (payload["engine"], uip.project_engine(bound), path["engine"], *(d["engine"] for d in devices)):
        assert {key: engine[key] for key in KEYS} == expected
        assert engine["snapshot_digest_form"] == uip.SNAPSHOT_DIGEST_FORM == "exact-parsed-bytes"
        assert re.fullmatch(uip.SNAPSHOT_SHA256_PATTERN, engine["snapshot_sha256"]["value"])
        assert engine == payload["engine"]
    # Projecting never touched the bound snapshot: its owner still verifies it against the same bytes.
    assert bound_snapshot_source(bound) == {"source_bound": True, "sha256": _digest(sample_raw),
                                            "bytes": len(sample_raw)}, "a projection mutated its input"


def test_i1_binding_changes_the_identity_facts_and_nothing_else(sample_raw):
    """Exact-byte binding is an input fact only: the whole bound payload equals the parsed-mapping payload once the
    two identity facts are set aside, and only those two differ."""
    bound = uip.project(bind_snapshot_json_bytes(sample_raw))
    parsed = uip.project(json.loads(sample_raw))
    assert {key: bound["engine"][key] for key in KEYS} == _published(sample_raw)
    _withheld(parsed["engine"], NC)
    assert _without_identity(bound["engine"]) == _without_identity(parsed["engine"])
    assert {k: v for k, v in bound.items() if k != "engine"} == {k: v for k, v in parsed.items() if k != "engine"}


# --------------------------------------------------------------------------------------------------
# I2 -- the identity names a byte string, not a JSON value
# --------------------------------------------------------------------------------------------------
def test_i2_equal_content_in_other_bytes_has_its_own_identity(sample_raw):
    content = json.loads(sample_raw)
    # Insignificant JSON whitespace makes byte strings that differ from the file by construction.
    encodings = {"file": sample_raw, "leading_space": b" " + sample_raw, "trailing_space": sample_raw + b" \n"}
    compact = json.dumps(content, separators=(",", ":")).encode()
    if compact not in encodings.values():
        encodings["compact"] = compact
    assert len(set(encodings.values())) == len(encodings) >= 3
    engines = {}
    for name, raw in encodings.items():
        bound = bind_snapshot_json_bytes(raw)
        assert bound == content, name
        engines[name] = uip.project_engine(bound)
        assert {key: engines[name][key] for key in KEYS} == _published(raw), name
    assert len({engine["snapshot_sha256"]["value"] for engine in engines.values()}) == len(encodings)
    baseline = _without_identity(engines["file"])
    assert all(_without_identity(engine) == baseline for engine in engines.values())


def test_i2_a_parsed_mapping_is_never_hashed_in_place_of_its_bytes(sample_raw):
    """A snapshot handed over already parsed names no file. No digest of the file or of any re-serialisation of the
    mapping -- including the owner's own canonical form -- appears anywhere in the engine block or the payload."""
    content = json.loads(sample_raw)
    payload = uip.project(content)
    engine = payload["engine"]
    _withheld(engine, NC)
    assert "re-serialisation" in engine["snapshot_sha256"]["reason"]
    assert "bind_snapshot_json_bytes" in engine["snapshot_sha256"]["reason"]
    assert not HEX64.search(json.dumps(engine))
    candidates = {sample_raw, json.dumps(content).encode(), json.dumps(content, separators=(",", ":")).encode(),
                  json.dumps(content, sort_keys=True).encode(),
                  json.dumps(content, sort_keys=True, separators=(",", ":")).encode(),
                  json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
                  json.dumps(content, indent=2).encode()}
    text = json.dumps(payload)
    for raw in candidates:
        assert hashlib.sha256(raw).hexdigest() not in text
    assert canonical_sha256(content).removeprefix("sha256:") not in text
    for value in (None, [], "", 0, {}):
        _withheld(uip.project_engine(value), NC)


# --------------------------------------------------------------------------------------------------
# I3 -- a marker its owner no longer verifies is unverified; a plain copy names no file
# --------------------------------------------------------------------------------------------------
def test_i3_detached_marker_is_unverified_and_plain_copies_are_not_collected():
    raw = _small_raw()
    bound = bind_snapshot_json_bytes(raw)
    kept = copy.deepcopy(bound)                       # the transport's per-request copy keeps the exact-byte marker
    assert {key: uip.project_engine(kept)[key] for key in KEYS} == _published(raw)
    _withheld(uip.project_engine(dict(bound)), NC)
    _withheld(uip.project_engine(json.loads(json.dumps(bound))), NC)
    bound["devices"]["sw1"]["hostname"] = "changed after binding"
    engine = uip.project_engine(bound)
    _withheld(engine, UV)
    assert "no longer matches" in engine["snapshot_sha256"]["reason"]
    assert engine["snapshot_schema"]["state"] == PUB              # the rest of the block is unaffected
    assert {key: uip.project_engine(kept)[key] for key in KEYS} == _published(raw)


def test_i3_an_owner_fault_withholds_the_identity(monkeypatch):
    def boom(_value):
        raise RecursionError("synthetic owner fault")

    monkeypatch.setattr(uip, "bound_snapshot_source", boom)
    engine = uip.project_engine(bind_snapshot_json_bytes(_small_raw()))
    _withheld(engine, UV)
    assert "raised RecursionError" in engine["snapshot_sha256"]["reason"]
    assert uip.SNAPSHOT_IDENTITY_OWNER in engine["snapshot_sha256"]["reason"]


_GOOD = "sha256:" + "0123456789abcdef" * 4


@pytest.mark.parametrize("receipt", [
    {"source_bound": True, "sha256": "sha256:" + "A" * 64, "bytes": 10},
    {"source_bound": True, "sha256": "0" * 64, "bytes": 10},
    {"source_bound": True, "sha256": "sha256:" + "0" * 63, "bytes": 10},
    {"source_bound": True, "sha256": _GOOD + "\n", "bytes": 10},
    {"source_bound": True, "sha256": "md5:" + "0" * 64, "bytes": 10},
    {"source_bound": True, "sha256": 7, "bytes": 10},
    {"source_bound": True, "sha256": _GOOD, "bytes": 0},
    {"source_bound": True, "sha256": _GOOD, "bytes": -1},
    {"source_bound": True, "sha256": _GOOD, "bytes": True},
    {"source_bound": True, "sha256": _GOOD, "bytes": 10.5},
    {"source_bound": True, "sha256": _GOOD, "bytes": 2 ** 53},
    {"source_bound": True, "sha256": _GOOD, "bytes": "10"},
    {"source_bound": True, "sha256": _GOOD},
    {"source_bound": "yes", "sha256": _GOOD, "bytes": 10},
    {"source_bound": False, "sha256": _GOOD, "bytes": 10},
    {"sha256": _GOOD, "bytes": 10},
    None, [], "sha256",
])
def test_i3_a_malformed_or_negative_receipt_never_publishes(monkeypatch, receipt):
    monkeypatch.setattr(uip, "bound_snapshot_source", lambda _value: copy.deepcopy(receipt))
    engine = uip.project_engine(bind_snapshot_json_bytes(_small_raw()))
    _withheld(engine, UV)


def test_i3_a_well_formed_receipt_is_published_verbatim(monkeypatch):
    """Control for the malformed receipts: the projection publishes the owner's values as given and computes none."""
    monkeypatch.setattr(uip, "bound_snapshot_source",
                        lambda _value: {"source_bound": True, "sha256": _GOOD, "bytes": 2 ** 53 - 1})
    engine = uip.project_engine(bind_snapshot_json_bytes(_small_raw()))
    assert (engine["snapshot_sha256"]["state"], engine["snapshot_sha256"]["value"]) == (PUB, _GOOD)
    assert (engine["snapshot_bytes"]["state"], engine["snapshot_bytes"]["value"]) == (PUB, 2 ** 53 - 1)
    assert "reason" not in engine["snapshot_sha256"] and "reason" not in engine["snapshot_bytes"]


# --------------------------------------------------------------------------------------------------
# I4 -- one read per context, fresh containers per document, read before any owner touches the snapshot
# --------------------------------------------------------------------------------------------------
def test_i4_identity_is_read_once_per_context_and_each_document_owns_its_facts(monkeypatch, sample_raw):
    calls = []
    real = uip.bound_snapshot_source

    def counted(value):
        calls.append(value)
        return real(value)

    monkeypatch.setattr(uip, "bound_snapshot_source", counted)
    bound = bind_snapshot_json_bytes(sample_raw)
    hosts = sorted(bound["devices"])[:2]
    documents = uip.project_devices(bound, [hosts[0], hosts[1], hosts[0]])
    assert len(calls) == 1 and calls[0] is bound
    first, second, third = (document["engine"] for document in documents)
    assert first == second == third
    assert first["snapshot_sha256"] is not second["snapshot_sha256"] is not third["snapshot_sha256"]
    first["snapshot_sha256"]["value"] = "MUTATED"
    first["snapshot_bytes"]["refs"].append({"pointer": "", "role": "subject"})
    assert {key: second[key] for key in KEYS} == {key: third[key] for key in KEYS} == _published(sample_raw)
    uip.project_engine(bound)
    assert len(calls) == 2                            # a new context reads the owner again


def test_i4_path_reads_the_identity_before_the_route_owner_runs(monkeypatch):
    calls, seen_at_trace = [], []
    real = uip.bound_snapshot_source

    def counted(value):
        calls.append(value)
        return real(value)

    def trace(*_args, **_kwargs):
        seen_at_trace.append(len(calls))
        raise ValueError("synthetic route-owner stop")

    monkeypatch.setattr(uip, "bound_snapshot_source", counted)
    monkeypatch.setattr(fib, "trace_fib_path", trace)
    raw = (b'{"schema":"collect_parse_snapshot/1","routes":{"r1":[{"prefix":"0.0.0.0/0"}]},'
           b'"interfaces":{},"routing_neighbors":{},"l3_forwarding":[]}')
    document = uip.project_path(bind_snapshot_json_bytes(raw), "192.0.2.1", "198.51.100.1")
    assert seen_at_trace == [1], "the route owner ran before the source identity was read"
    assert {key: document["engine"][key] for key in KEYS} == _published(raw)
    assert document["path"]["result"]["state"] == UV        # the stopped owner is a fault, never a result


# --------------------------------------------------------------------------------------------------
# I5 -- the schema closes the identity shape
# --------------------------------------------------------------------------------------------------
def test_i5_schema_closes_the_identity_shape(schema):
    defs = schema["$defs"]
    engine = defs["Engine"]
    assert engine["required"][-3:] == ["snapshot_sha256", "snapshot_bytes", "snapshot_digest_form"]
    assert engine["additionalProperties"] is False
    assert engine["properties"]["snapshot_sha256"] == {"$ref": "#/$defs/Sha256Fact"}
    assert engine["properties"]["snapshot_bytes"] == {"$ref": "#/$defs/PositiveCountFact"}
    assert engine["properties"]["snapshot_digest_form"] == {"type": "string", "const": uip.SNAPSHOT_DIGEST_FORM}
    published, withheld = defs["Sha256Fact"]["oneOf"]
    assert published["properties"]["value"] == {"type": "string", "pattern": uip.SNAPSHOT_SHA256_PATTERN}
    assert withheld["properties"]["value"] == {"type": "null"}
    assert uip.SNAPSHOT_SHA256_PATTERN == "^sha256:[0-9a-f]{64}$"


@pytest.mark.parametrize("forgery", [
    "unprefixed", "uppercase", "short", "zero_bytes", "negative_bytes", "bool_bytes", "other_form", "missing_form",
    "missing_digest", "extra_member", "published_without_value", "withheld_with_value", "withheld_without_reason",
])
def test_i5_schema_rejects_forged_identities(schema, forgery):
    validator = _validator(schema, "Engine")
    engine = uip.project_engine(bind_snapshot_json_bytes(_small_raw()))
    assert validator.is_valid(engine)
    assert validator.is_valid(uip.project_engine(json.loads(_small_raw())))
    sha, size = engine["snapshot_sha256"], engine["snapshot_bytes"]
    if forgery == "unprefixed":
        sha["value"] = sha["value"].removeprefix("sha256:")
    elif forgery == "uppercase":
        sha["value"] = sha["value"].upper().replace("SHA256:", "sha256:")
    elif forgery == "short":
        sha["value"] = sha["value"][:-1]
    elif forgery == "zero_bytes":
        size["value"] = 0
    elif forgery == "negative_bytes":
        size["value"] = -1
    elif forgery == "bool_bytes":
        size["value"] = True
    elif forgery == "other_form":
        engine["snapshot_digest_form"] = "assesshub-store-blob"
    elif forgery == "missing_form":
        del engine["snapshot_digest_form"]
    elif forgery == "missing_digest":
        del engine["snapshot_sha256"]
    elif forgery == "extra_member":
        engine["snapshot_sha256_form"] = "exact-parsed-bytes"
    elif forgery == "published_without_value":
        sha["value"] = None
    elif forgery == "withheld_with_value":
        sha.update(state=NC, reason="synthetic")
    else:
        size.update(state=NC, value=None)
    assert not validator.is_valid(engine)
