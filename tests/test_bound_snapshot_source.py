"""Exact-byte snapshot custody is process-local and mutation-sensitive."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
from types import SimpleNamespace

import pytest

from cisco_toolkit import protocol_assurance as pa
from cisco_toolkit.protocol_assurance import (
    bind_snapshot_json_bytes,
    bound_snapshot_source,
)


def test_exact_json_bytes_mint_the_only_positive_source_marker() -> None:
    raw = b'{"devices":{"edge-1":{"platform":"iosxe"}},"script_version":"3.23.0"}'

    snapshot = bind_snapshot_json_bytes(raw)

    assert bound_snapshot_source(snapshot) == {
        "source_bound": True,
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def test_any_nested_mutation_invalidates_the_exact_byte_marker() -> None:
    snapshot = bind_snapshot_json_bytes(b'{"devices":{"edge-1":{"role":"access"}}}')

    snapshot["devices"]["edge-1"]["role"] = "core"

    assert bound_snapshot_source(snapshot) == {
        "source_bound": False,
        "sha256": "",
        "bytes": 0,
    }


def test_serialization_and_plain_mapping_copy_cannot_recreate_authority() -> None:
    snapshot = bind_snapshot_json_bytes(b'{"devices":{"edge-1":{}}}')

    detached_json = json.loads(json.dumps(snapshot))
    detached_mapping = dict(snapshot)

    assert bound_snapshot_source(detached_json)["source_bound"] is False
    assert bound_snapshot_source(detached_mapping)["source_bound"] is False


@pytest.mark.parametrize(
    "raw",
    (
        b"[]",
        b"null",
        b'{"metric":NaN}',
        b'{"metric":Infinity}',
        b'{"metric":-Infinity}',
    ),
)
def test_non_object_or_non_finite_json_cannot_be_bound(raw: bytes) -> None:
    with pytest.raises(ValueError):
        bind_snapshot_json_bytes(raw)


def test_only_byte_sources_can_mint_authority() -> None:
    with pytest.raises(TypeError, match="snapshot source must be bytes"):
        bind_snapshot_json_bytes({"devices": {}})


@pytest.mark.parametrize(
    "raw",
    (
        b'{"devices":{"first":{}},"devices":{"second":{}}}',
        b'{"devices":{"edge":{"role":"access","role":"core"}}}',
    ),
)
def test_duplicate_json_members_cannot_be_bound(raw: bytes) -> None:
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        bind_snapshot_json_bytes(raw)


def _original_source(value):
    """The pre-optimization canonical guard: mismatches must preserve even its unusual equivalences."""
    if (not isinstance(value, pa.BoundSnapshot)
            or pa.canonical_sha256(dict(value)) != value._bound_payload_sha256):
        return {"source_bound": False, "sha256": "", "bytes": 0}
    return {"source_bound": True, "sha256": value._bound_source_sha256,
            "bytes": value._bound_source_bytes}


def _fallback_matches_original(value, monkeypatch):
    expected = _original_source(value)
    original, calls = pa.canonical_sha256, []

    def observed(payload):
        calls.append(payload)
        return original(payload)

    monkeypatch.setattr(pa, "canonical_sha256", observed)
    actual = pa.bound_snapshot_source(value)
    assert actual == expected
    assert len(calls) == 1
    return actual


def test_binder_mints_immutable_content_proof_and_checks_complete_live_copies(monkeypatch):
    bound = pa.bind_snapshot_json_bytes(b'{"nested":{"rows":[1,false,0.0,"value",null]},"tail":true}')
    expected = _original_source(bound)
    copy = deepcopy(bound)
    proof = bound._bound_content_proof
    assert type(proof) is pa._BoundSnapshotContentProof and copy._bound_content_proof is proof
    assert copy["nested"] is not bound["nested"] and copy["nested"]["rows"] is not bound["nested"]["rows"]
    pending = [proof.payload]
    while pending:
        node = pending.pop()
        assert type(node) not in (dict, list)
        if type(node) is tuple:
            pending.extend(node)
    with pytest.raises(FrozenInstanceError):
        proof.source_bytes = 0

    def cannot_skip_full_content_check(_payload):
        raise AssertionError("unchanged typed live content uses the complete immutable proof walk")

    monkeypatch.setattr(pa, "canonical_sha256", cannot_skip_full_content_check)
    assert pa.bound_snapshot_source(bound) == pa.bound_snapshot_source(copy) == expected
    copy["nested"]["rows"][-1] = "changed"
    # The shared proof is not a mutable-object validation verdict: the copied payload must be re-read.
    with pytest.raises(AssertionError, match="immutable proof walk"):
        pa.bound_snapshot_source(copy)
    assert pa.bound_snapshot_source(bound) == expected


@pytest.mark.parametrize("damage", [
    "nested-value", "array-order", "missing-key", "extra-key", "bool-to-int", "int-to-float",
    "float-to-int", "signed-zero", "nonfinite", "unsupported", "cycle", "container-subclass", "scalar-subclass",
    "integer-subclass", "float-subclass",
])
def test_current_content_mismatches_keep_the_original_canonical_guard(monkeypatch, damage):
    bound = pa.bind_snapshot_json_bytes(b'{"nested":{"rows":[1,2]},"flag":false,"integer":0,"float":0.0,"text":"v"}')
    if damage == "nested-value":
        bound["nested"]["rows"][1] = 3
    elif damage == "array-order":
        bound["nested"]["rows"].reverse()
    elif damage == "missing-key":
        del bound["text"]
    elif damage == "extra-key":
        bound["extra"] = "v"
    elif damage == "bool-to-int":
        bound["flag"] = 0
    elif damage == "int-to-float":
        bound["integer"] = 0.0
    elif damage == "float-to-int":
        bound["float"] = 0
    elif damage == "signed-zero":
        bound["float"] = -0.0
    elif damage == "nonfinite":
        bound["float"] = float("inf")
    elif damage == "unsupported":
        bound["text"] = object()
    elif damage == "cycle":
        bound["nested"]["rows"][0] = bound
    elif damage == "container-subclass":
        bound["nested"] = type("ForeignDict", (dict,), {})(bound["nested"])
    elif damage == "scalar-subclass":
        bound["text"] = type("ForeignStr", (str,), {})("v")
    elif damage == "integer-subclass":
        bound["integer"] = type("ForeignInt", (int,), {})(0)
    else:
        bound["float"] = type("ForeignFloat", (float,), {})(0.0)
    result = _fallback_matches_original(bound, monkeypatch)
    assert result["source_bound"] == (damage in (
        "container-subclass", "scalar-subclass", "integer-subclass", "float-subclass"))


@pytest.mark.parametrize("damage", ["integer-key", "string-subclass-key"])
def test_key_types_fall_back_even_when_canonical_json_is_equivalent(monkeypatch, damage):
    bound = pa.bind_snapshot_json_bytes(b'{"1":"value"}')
    value = bound.pop("1")
    key = 1 if damage == "integer-key" else type("ForeignKey", (str,), {})("1")
    bound[key] = value
    assert _fallback_matches_original(bound, monkeypatch)["source_bound"] is True


def test_dict_insertion_order_matches_sorted_canonical_content_without_rewriting_values(monkeypatch):
    bound = pa.bind_snapshot_json_bytes(b'{"first":1,"second":{"a":1,"b":2}}')
    expected = _original_source(bound)
    bound["first"] = bound.pop("first")
    bound["second"]["a"] = bound["second"].pop("a")
    assert list(bound) == ["second", "first"] and list(bound["second"]) == ["b", "a"]
    monkeypatch.setattr(pa, "canonical_sha256", lambda _value: pytest.fail("equal complete content needs no re-encoding"))
    assert pa.bound_snapshot_source(bound) == expected


@pytest.mark.parametrize("marker,kind", [
    ("_bound_source_sha256", "different"), ("_bound_source_sha256", "subclass"),
    ("_bound_payload_sha256", "different"), ("_bound_payload_sha256", "subclass"),
    ("_bound_source_bytes", "different"), ("_bound_source_bytes", "float"),
    ("_bound_source_bytes", "subclass"),
])
def test_every_original_marker_type_and_value_is_checked_before_the_fast_path(monkeypatch, marker, kind):
    bound = pa.bind_snapshot_json_bytes(b'{"field":1}')
    original = getattr(bound, marker)
    if kind == "different":
        value = original + 1 if type(original) is int else "sha256:" + "0" * 64
    elif kind == "float":
        value = float(original)
    else:
        value = type("ForeignMarker", (type(original),), {})(original)
    setattr(bound, marker, value)
    result = _fallback_matches_original(bound, monkeypatch)
    assert result["source_bound"] == (marker != "_bound_payload_sha256" or kind == "subclass")
    if marker == "_bound_source_bytes":
        assert type(result["bytes"]) is type(value)  # Preserve the original result, never coerce float/int markers.


@pytest.mark.parametrize("proof_kind", ["missing", "fake", "incomplete", "foreign-content", "foreign-byte-form"])
def test_missing_fake_and_other_source_proofs_cannot_bypass_the_canonical_guard(monkeypatch, proof_kind):
    bound = pa.bind_snapshot_json_bytes(b'{"field":1}')
    if proof_kind == "missing":
        bound._bound_content_proof = None
    elif proof_kind == "incomplete":
        bound._bound_content_proof = object.__new__(pa._BoundSnapshotContentProof)
    elif proof_kind == "fake":
        proof = bound._bound_content_proof
        bound._bound_content_proof = SimpleNamespace(source_sha256=proof.source_sha256,
                                                     source_bytes=proof.source_bytes,
                                                     payload_sha256=proof.payload_sha256, payload=proof.payload)
    else:
        other = pa.bind_snapshot_json_bytes(b'{"field":2}' if proof_kind == "foreign-content" else b'{ "field": 1 }')
        bound._bound_content_proof = other._bound_content_proof
    assert _fallback_matches_original(bound, monkeypatch)["source_bound"] is True


def test_foreign_proof_cannot_bless_mutated_content_or_a_supplied_payload_digest(monkeypatch):
    bound = pa.bind_snapshot_json_bytes(b'{"field":1}')
    other = pa.bind_snapshot_json_bytes(b'{"field":2}')
    bound["field"] = 2
    bound._bound_content_proof = other._bound_content_proof
    assert _fallback_matches_original(bound, monkeypatch)["source_bound"] is False


@pytest.mark.parametrize("digest_ok", [False, True])
def test_constructor_never_builds_a_proof_from_caller_supplied_digests(monkeypatch, digest_ok):
    payload = {"field": [1, 2]}
    bound = pa.BoundSnapshot(payload, source_sha256="sha256:" + "a" * 64, source_bytes=123,
                            payload_sha256=pa.canonical_sha256(payload) if digest_ok else "sha256:" + "0" * 64,
                            _authority=pa._BOUND_SNAPSHOT_AUTHORITY)
    assert bound._bound_content_proof is None
    assert _fallback_matches_original(bound, monkeypatch)["source_bound"] is digest_ok


def test_proof_construction_requires_the_existing_binder_authority():
    with pytest.raises(TypeError, match="_authority"):
        pa._snapshot_content_proof({"field": 1}, "supplied", 100, "supplied")
    with pytest.raises(TypeError, match="_authority"):
        pa._BoundSnapshotContentProof("supplied", 100, "supplied", (dict, ()))
    with pytest.raises(TypeError, match="exact-byte binder"):
        pa._snapshot_content_proof({"field": 1}, "supplied", 100, "supplied", _authority=object())
    with pytest.raises(TypeError, match="exact-byte binder"):
        pa._BoundSnapshotContentProof("supplied", 100, "supplied", (dict, ()), _authority=object())


def test_a_bound_snapshot_subclass_keeps_the_original_guard_even_with_a_real_proof(monkeypatch):
    original = pa.bind_snapshot_json_bytes(b'{"field":1}')
    foreign = type("ForeignSnapshot", (pa.BoundSnapshot,), {})(
        dict(original), source_sha256=original._bound_source_sha256, source_bytes=original._bound_source_bytes,
        payload_sha256=original._bound_payload_sha256, _authority=pa._BOUND_SNAPSHOT_AUTHORITY)
    foreign._bound_content_proof = original._bound_content_proof
    assert _fallback_matches_original(foreign, monkeypatch)["source_bound"] is True


@pytest.mark.parametrize("failure", ["node-bound", "depth-bound", "allocation", "deep-input"])
def test_optional_proof_failure_leaves_the_original_binder_and_guard_available(monkeypatch, failure):
    raw = b'{"field":[1,2,3]}'
    if failure == "node-bound":
        monkeypatch.setattr(pa, "_MAX_SNAPSHOT_PROOF_NODES", 1)
    elif failure == "depth-bound":
        monkeypatch.setattr(pa, "_MAX_SNAPSHOT_PROOF_DEPTH", 0)
    elif failure == "allocation":
        def exhausted(*_args, **_kwargs):
            raise MemoryError("optional proof allocation")
        monkeypatch.setattr(pa, "_BoundSnapshotContentProof", exhausted)
    else:
        raw = b'{"deep":' + b"[" * 160 + b"0" + b"]" * 160 + b"}"
    bound = pa.bind_snapshot_json_bytes(raw)
    assert bound._bound_content_proof is None
    assert _fallback_matches_original(bound, monkeypatch)["source_bound"] is True


def test_detached_json_or_dict_stays_unbound_even_when_it_carries_serialized_marker_names():
    bound = pa.bind_snapshot_json_bytes(b'{"field":1,"projection_custody":{"sha256":"caller-supplied"}}')
    for detached in (dict(bound), json.loads(json.dumps(bound))):
        detached["_bound_content_proof"] = "caller-supplied proof"
        assert pa.bound_snapshot_source(detached) == {"source_bound": False, "sha256": "", "bytes": 0}
