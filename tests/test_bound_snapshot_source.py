"""Exact-byte snapshot custody is process-local and mutation-sensitive."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
import sys
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


def _fresh_encoder_matches_original(value, monkeypatch):
    expected = _original_source(value)
    encoder, calls = pa._snapshot_identity_text, []

    def observed(payload):
        assert payload is value  # The entire current source, never a fragment or previous validation result.
        text = encoder(payload)
        calls.append(text)
        return text

    monkeypatch.setattr(pa, "_snapshot_identity_text", observed)
    monkeypatch.setattr(pa, "canonical_sha256", lambda _value: pytest.fail("eligible equal full encoding is observed"))
    for _ in range(2):
        actual = pa.bound_snapshot_source(value)
        assert actual == expected
        assert all(type(actual[key]) is type(expected[key]) for key in expected)
    assert calls == [value._bound_content_proof.text, value._bound_content_proof.text]
    return actual


def _fresh_binary_matches_original(value, monkeypatch):
    expected = _original_source(value)
    encoder, calls = pa._snapshot_identity_binary, []

    def observed(payload):
        assert payload is value  # Complete current graph, never a fragment or prior read verdict.
        current = encoder(payload)
        calls.append(current)
        return current

    monkeypatch.setattr(pa, "_snapshot_identity_binary", observed)
    monkeypatch.setattr(pa, "_snapshot_identity_text", lambda _value: pytest.fail("complete typed binary matched"))
    monkeypatch.setattr(pa, "canonical_sha256", lambda _value: pytest.fail("complete typed binary matched"))
    for _ in range(2):
        actual = pa.bound_snapshot_source(value)
        assert actual == expected
        assert all(type(actual[key]) is type(expected[key]) for key in expected)
    assert calls == [value._bound_content_proof.binary_text, value._bound_content_proof.binary_text]
    assert type(calls[0]) is bytes
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

    encoder, calls = pa._snapshot_identity_binary, []

    def observed(payload):
        calls.append(payload)
        return encoder(payload)

    def canonical_fallback(_payload):
        raise AssertionError("a changed full encoding must fall back to the original canonical guard")

    monkeypatch.setattr(pa, "_snapshot_identity_binary", observed)
    monkeypatch.setattr(pa, "canonical_sha256", canonical_fallback)
    assert pa.bound_snapshot_source(bound) == pa.bound_snapshot_source(copy) == expected
    copy["nested"]["rows"][-1] = "changed"
    # The shared proof is not a mutable-object validation verdict: the copied payload must be re-read.
    with pytest.raises(AssertionError, match="canonical guard"):
        pa.bound_snapshot_source(copy)
    assert pa.bound_snapshot_source(bound) == expected
    assert len(calls) == 4 and calls[0] is bound and calls[1] is copy and calls[2] is copy and calls[3] is bound


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
    result = (_fresh_encoder_matches_original(bound, monkeypatch) if damage in (
        "scalar-subclass", "integer-subclass", "float-subclass") else _fallback_matches_original(bound, monkeypatch))
    assert result["source_bound"] == (damage in (
        "container-subclass", "scalar-subclass", "integer-subclass", "float-subclass"))


@pytest.mark.parametrize("damage", ["integer-key", "string-subclass-key"])
def test_key_types_fall_back_even_when_canonical_json_is_equivalent(monkeypatch, damage):
    bound = pa.bind_snapshot_json_bytes(b'{"1":"value"}')
    value = bound.pop("1")
    key = 1 if damage == "integer-key" else type("ForeignKey", (str,), {})("1")
    bound[key] = value
    assert _fallback_matches_original(bound, monkeypatch)["source_bound"] is True


def test_dict_insertion_order_conservatively_uses_canonical_content_without_rewriting_values(monkeypatch):
    bound = pa.bind_snapshot_json_bytes(b'{"first":1,"second":{"a":1,"b":2}}')
    expected = _original_source(bound)
    bound["first"] = bound.pop("first")
    bound["second"]["a"] = bound["second"].pop("a")
    assert list(bound) == ["second", "first"] and list(bound["second"]) == ["b", "a"]
    assert _fallback_matches_original(bound, monkeypatch) == expected


def test_mixed_integer_string_keys_cannot_fastaccept_identical_unsorted_text(monkeypatch):
    bound = pa.bind_snapshot_json_bytes(b'{"1":"value","tail":2}')
    proof = bound._bound_content_proof
    bound.clear()
    bound[1], bound["tail"] = "value", 2
    assert pa._snapshot_identity_text(bound) == proof.text  # Unsorted text alone would miss the unsafe key.
    assert _fallback_matches_original(bound, monkeypatch)["source_bound"] is False


def test_equal_new_plain_key_objects_keep_the_original_result_through_complete_typed_encoding(monkeypatch):
    bound = pa.bind_snapshot_json_bytes(b'{"non_interned_key_abcdefghijklmnopqrstuvwxyz":1}')
    key = next(iter(bound))
    keys, identities, _children = bound._bound_content_proof.payload[1]
    assert keys[0] is key and identities == (id(key),)
    new_key = ("_" + key)[1:]
    assert new_key == key and new_key is not key
    item = bound.pop(key)
    bound[new_key] = item
    assert pa._snapshot_identity_text(bound) == bound._bound_content_proof.text
    assert _fresh_binary_matches_original(bound, monkeypatch)["source_bound"] is True


def test_custom_comparison_key_cannot_replace_a_sortable_builtin_key(monkeypatch):
    class ForeignKey(str):
        def __lt__(self, _other):
            raise TypeError("foreign key cannot supply the canonical sortable-key premise")

    bound = pa.bind_snapshot_json_bytes(b'{"first":1,"second":2}')
    item = bound.pop("first")
    bound[ForeignKey("first")] = item
    _fallback_matches_original(bound, monkeypatch)


@pytest.mark.parametrize("damage", ["empty-dict", "empty-list", "nested-array-container", "tuple-array"])
def test_the_complete_scaffold_guards_empty_and_nested_container_positions(monkeypatch, damage):
    bound = pa.bind_snapshot_json_bytes(b'{"empty":{},"rows":[[],{"nested":[]}]}')
    if damage == "empty-dict":
        bound["empty"] = type("ForeignDict", (dict,), {})()
    elif damage == "empty-list":
        bound["rows"][0] = type("ForeignList", (list,), {})()
    elif damage == "nested-array-container":
        bound["rows"][1]["nested"] = type("ForeignNested", (list,), {})()
    else:
        bound["rows"] = tuple(bound["rows"])
    assert pa._snapshot_identity_text(bound) == bound._bound_content_proof.text
    assert _fallback_matches_original(bound, monkeypatch)["source_bound"] is True


def test_array_aliases_are_checked_by_full_content_not_original_mutable_identity(monkeypatch):
    bound = pa.bind_snapshot_json_bytes(b'{"first":[],"second":[]}')
    bound["second"] = bound["first"]  # Equal JSON content; every container position remains a built-in list.
    _fresh_binary_matches_original(bound, monkeypatch)


def test_a_later_mutation_of_aliased_arrays_reaches_the_original_canonical_guard(monkeypatch):
    bound = pa.bind_snapshot_json_bytes(b'{"first":[],"second":[]}')
    bound["second"] = bound["first"]
    bound["first"].append(1)
    assert bound["second"] == [1]
    assert _fallback_matches_original(bound, monkeypatch)["source_bound"] is False


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
                                                     payload_sha256=proof.payload_sha256, payload=proof.payload,
                                                     text=proof.text)
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
        pa._BoundSnapshotContentProof("supplied", 100, "supplied", (dict, ()), "{}")
    with pytest.raises(TypeError, match="exact-byte binder"):
        pa._snapshot_content_proof({"field": 1}, "supplied", 100, "supplied", _authority=object())
    with pytest.raises(TypeError, match="exact-byte binder"):
        pa._BoundSnapshotContentProof("supplied", 100, "supplied", (dict, ()), "{}", _authority=object())


def test_a_bound_snapshot_subclass_keeps_the_original_guard_even_with_a_real_proof(monkeypatch):
    original = pa.bind_snapshot_json_bytes(b'{"field":1}')
    foreign = type("ForeignSnapshot", (pa.BoundSnapshot,), {})(
        dict(original), source_sha256=original._bound_source_sha256, source_bytes=original._bound_source_bytes,
        payload_sha256=original._bound_payload_sha256, _authority=pa._BOUND_SNAPSHOT_AUTHORITY)
    foreign._bound_content_proof = original._bound_content_proof
    assert _fallback_matches_original(foreign, monkeypatch)["source_bound"] is True


@pytest.mark.parametrize("failure", ["node-bound", "depth-bound", "allocation", "encoder", "deep-input"])
def test_optional_proof_failure_leaves_the_original_binder_and_guard_available(monkeypatch, failure):
    raw = b'{"field":[1,2,3]}'
    if failure == "node-bound":
        monkeypatch.setattr(pa, "_MAX_SNAPSHOT_PROOF_NODES", 1)
    elif failure == "depth-bound":
        monkeypatch.setattr(pa, "_MAX_SNAPSHOT_PROOF_DEPTH", 0)
    elif failure in ("allocation", "encoder"):
        def exhausted(*_args, **_kwargs):
            raise MemoryError("optional proof allocation")
        monkeypatch.setattr(pa, "_BoundSnapshotContentProof" if failure == "allocation" else "_snapshot_identity_text",
                            exhausted)
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


@pytest.mark.parametrize("raw", [
    b'{"value":[false,0,0.0,-0.0,null],"tail":{"empty":[]}}',
    b'{"value":[9007199254740993,-9007199254740993,1.25],"tail":{"empty":{}}}',
    b'{"value":["\\ud800","\\udfff","\\ud83d\\ude00","\\u2028"],"tail":"last"}',
])
def test_fresh_binary_observes_complete_types_unicode_and_last_containers(raw, monkeypatch):
    _fresh_binary_matches_original(pa.bind_snapshot_json_bytes(raw), monkeypatch)


@pytest.mark.parametrize("failure", ["retained-byte-bound", "runtime", "allocation"])
def test_optional_binary_construction_failure_retains_the_original_complete_proof(monkeypatch, failure):
    if failure == "retained-byte-bound":
        monkeypatch.setattr(pa, "_MAX_SNAPSHOT_PROOF_BINARY_BYTES", 0)
    else:
        def failed(_value):
            raise (MemoryError if failure == "allocation" else RuntimeError)("optional binary observation")
        monkeypatch.setattr(pa, "_snapshot_identity_binary", failed)
    bound = pa.bind_snapshot_json_bytes(b'{"nested":{"rows":[false,1,0.0]},"last":"value"}')
    assert type(bound._bound_content_proof) is pa._BoundSnapshotContentProof
    assert bound._bound_content_proof.binary_text is None
    _fresh_encoder_matches_original(bound, monkeypatch)


@pytest.mark.parametrize("failure", ["exception", "different", "unsupported-result"])
def test_optional_binary_read_failure_keeps_the_unchanged_json_scaffold_guard(monkeypatch, failure):
    bound = pa.bind_snapshot_json_bytes(b'{"field":[1,2]}')
    assert type(bound._bound_content_proof.binary_text) is bytes
    def failed(_value):
        if failure == "exception":
            raise OSError("optional binary audit event refused")
        if failure == "unsupported-result":
            return bytearray(bound._bound_content_proof.binary_text)
        return b"different incomplete observation"
    monkeypatch.setattr(pa, "_snapshot_identity_binary", failed)
    _fresh_encoder_matches_original(bound, monkeypatch)


def test_non_json_buffer_provider_cannot_recreate_json_typed_binary_authority(monkeypatch):
    bound = pa.bind_snapshot_json_bytes(b'{"field":"value"}')
    calls = []
    class Buffer:
        def __buffer__(self, flags):
            calls.append(flags)
            return memoryview(b"value")
    bound["field"] = Buffer()
    assert _fallback_matches_original(bound, monkeypatch)["source_bound"] is False
    assert bool(calls) is (sys.version_info >= (3, 12))


def _actual_c_data_writer_available():
    # Independent inspected runtime inventory, not a flag copied from the implementation.
    return (sys.implementation.name == "cpython" and sys.version_info[:3] in {
        (3, 10, 22), (3, 11, 17), (3, 12, 15), (3, 13, 16), (3, 14, 8),
    } and pa.pickle.Pickler.__module__ == "_pickle")


def _observe_real_data_dump_and_marshal(monkeypatch):
    dump, marshal = pa._SnapshotDataPickler.dump, pa.marshal.dumps
    calls = []

    def observed_dump(self, value):
        # Wrapping the inherited method keeps the guarded factory/refusal owners intact.
        assert self.fast == 1
        calls.append(("candidate", value))
        return dump(self, value)

    def observed_marshal(value, version):
        calls.append(("marshal", value))
        assert version == 2
        return marshal(value, version)

    monkeypatch.setattr(pa._SnapshotDataPickler, "dump", observed_dump)
    monkeypatch.setattr(pa.marshal, "dumps", observed_marshal)
    return calls


def test_real_c_data_lane_checks_live_copies_new_keys_aliases_and_late_mutation(monkeypatch):
    raw = (b'{"first":[],"second":[],"non_interned_key_abcdefghijklmnopqrstuvwxyz":'
           b'{"rows":[false,1,0.0,-0.0,null,"\\ud800","\\ud83d\\ude00"]}}')
    bound = pa.bind_snapshot_json_bytes(raw)
    keepalive = bound["non_interned_key_abcdefghijklmnopqrstuvwxyz"]
    copied = deepcopy(bound)
    key = next(key for key in copied if key.startswith("non_interned"))
    new_key = ("_" + key)[1:]
    assert new_key == key and new_key is not key
    copied[new_key] = copied.pop(key)
    # Replacing the final key preserves order on the genuine copied binder object/proof.
    copied["second"] = copied["first"]
    assert copied[new_key] is not keepalive and copied["first"] is not bound["first"]
    expected = _original_source(bound)
    calls = _observe_real_data_dump_and_marshal(monkeypatch)
    encoder, complete = pa._snapshot_identity_binary, []

    def observed(value):
        complete.append(value)
        return encoder(value)

    monkeypatch.setattr(pa, "_snapshot_identity_binary", observed)
    for subject in (bound, copied, copied, bound):
        actual = pa.bound_snapshot_source(subject)
        assert actual == expected and all(type(actual[k]) is type(expected[k]) for k in expected)
    assert len(complete) == 4 and all(current is wanted for current, wanted in zip(
        complete, (bound, copied, copied, bound)))
    lane = "candidate" if _actual_c_data_writer_available() else "marshal"
    assert [kind for kind, _value in calls] == [lane] * 4
    assert all(type(value) is dict and value is not subject and value[new_key] is subject[new_key]
               for (_kind, value), subject in zip(calls, (bound, copied, copied, bound)))
    assert bound._bound_content_proof.binary_text.startswith(b"\x80\x04") is _actual_c_data_writer_available()
    copied[new_key]["rows"][-1] = "changed"
    assert _fallback_matches_original(copied, monkeypatch)["source_bound"] is False
    assert pa.bound_snapshot_source(bound) == expected


@pytest.mark.parametrize("shape", ["scalar", "dict", "list", "recursive-key"])
def test_foreign_hooks_and_copyreg_are_refused_before_original_codec(monkeypatch, shape):
    import copyreg
    events = []

    class ForeignStr(str):
        def __reduce_ex__(self, _protocol):
            events.append("reduce_ex")
            raise AssertionError("foreign reduction executed")

        def __reduce__(self):
            events.append("reduce")
            raise AssertionError("foreign reduction executed")

        def __getstate__(self):
            events.append("getstate")
            raise AssertionError("foreign state executed")

        def __repr__(self):
            events.append("repr")
            return str.__repr__(self)

        def __getattribute__(self, name):
            if name in ("__reduce__", "__reduce_ex__", "__getstate__", "__module__", "__qualname__"):
                events.append("getattr")
            return str.__getattribute__(self, name)

    class ForeignDict(dict):
        def __reduce_ex__(self, _protocol):
            events.append("reduce_ex")
            raise AssertionError("foreign dictionary reduction executed")

        def items(self):
            events.append("items")
            return dict.items(self)

    class ForeignList(list):
        def __reduce_ex__(self, _protocol):
            events.append("reduce_ex")
            raise AssertionError("foreign list reduction executed")

        def __iter__(self):
            events.append("iter")
            return list.__iter__(self)

    class ForeignValue:
        def __reduce_ex__(self, _protocol):
            events.append("value-reduce")
            raise AssertionError("value reached after failed key")

    def registered(_value):
        events.append("copyreg")
        raise AssertionError("registered reduction executed")

    for kind in (ForeignStr, ForeignDict, ForeignList, ForeignValue):
        monkeypatch.setitem(copyreg.dispatch_table, kind, registered)
    value = ({"field": ForeignStr("value")} if shape == "scalar" else
             {"field": ForeignDict(a=1)} if shape == "dict" else
             {"field": ForeignList([1])} if shape == "list" else
             {(ForeignStr("raw_private_key"),): ForeignValue()})
    dump, marshal = pa._SnapshotDataPickler.dump, pa.marshal.dumps
    calls = []

    def observed_dump(self, whole):
        calls.append(("candidate", whole))
        return dump(self, whole)

    def observed_marshal(whole, version):
        assert events == []  # Includes repr/value hooks on the failed recursive key.
        calls.append(("marshal", whole))
        return marshal(whole, version)

    monkeypatch.setattr(pa._SnapshotDataPickler, "dump", observed_dump)
    monkeypatch.setattr(pa.marshal, "dumps", observed_marshal)
    with pytest.raises(ValueError) as actual:
        pa._snapshot_identity_binary(value)
    assert actual.value.__context__ is None
    assert getattr(actual.value, "__notes__", []) == []
    assert [kind for kind, _ in calls] == (["candidate", "marshal"] if _actual_c_data_writer_available()
                                          else ["marshal"])
    assert len(calls) == 1 or calls[0][1] is calls[1][1]
    assert events == []


@pytest.mark.parametrize("kind", ["bytearray", "bytearray-subclass", "buffer", "released", "noncontiguous"])
def test_native_unsupported_data_preserves_same_whole_original_fallback(monkeypatch, kind):
    class ForeignBytearray(bytearray):
        def __reduce_ex__(self, _protocol):
            raise AssertionError("foreign bytearray reduction executed")

    value = (bytearray(b"value") if kind == "bytearray" else ForeignBytearray(b"value")
             if kind == "bytearray-subclass" else pa.pickle.PickleBuffer(
                 memoryview(b"value")[::2] if kind == "noncontiguous" else b"value"))
    if kind == "released":
        value.release()
    whole = {"field": value}
    original = pa.marshal.dumps
    try:
        expected = original(dict(whole), 2)
    except Exception as error:
        expected_error = (type(error), error.args)
    else:
        expected_error = None
    calls = _observe_real_data_dump_and_marshal(monkeypatch)
    if expected_error is not None:
        with pytest.raises(expected_error[0]) as caught:
            pa._snapshot_identity_binary(whole)
        assert caught.value.args == expected_error[1]
        assert caught.value.__context__ is None
    else:
        assert pa._snapshot_identity_binary(whole) == expected
    assert [mode for mode, _ in calls] == (["candidate", "marshal"] if _actual_c_data_writer_available()
                                         else ["marshal"])
    assert len(calls) == 1 or calls[0][1] is calls[1][1]
    assert calls[-1][1]["field"] is value


def test_protocol4_wrapper_refusal_adds_no_python_buffer_export(monkeypatch):
    calls = []

    class Buffer:
        def __buffer__(self, flags):
            calls.append(flags)
            return memoryview(b"value")

    # On older interpreters use a real native exporter; the old direct-Buffer test remains literal.
    value = pa.pickle.PickleBuffer(Buffer() if sys.version_info >= (3, 12) else memoryview(b"value"))
    construction_calls = list(calls)
    dump, marshal = pa._SnapshotDataPickler.dump, pa.marshal.dumps
    codec_calls = []

    def observed_dump(self, whole):
        codec_calls.append(("candidate", whole))
        try:
            return dump(self, whole)
        finally:
            assert calls == construction_calls

    def observed_marshal(whole, version):
        assert calls == construction_calls
        codec_calls.append(("marshal", whole))
        return marshal(whole, version)

    monkeypatch.setattr(pa._SnapshotDataPickler, "dump", observed_dump)
    monkeypatch.setattr(pa.marshal, "dumps", observed_marshal)
    pa._snapshot_identity_binary({"field": value})
    assert [mode for mode, _ in codec_calls] == (["candidate", "marshal"] if _actual_c_data_writer_available()
                                               else ["marshal"])
    assert len(codec_calls) == 1 or codec_calls[0][1] is codec_calls[1][1]
    # Observe wrapper exports against the actual standalone original operation, without borrowing a count.
    before_original = len(calls)
    marshal({"field": value}, 2)
    assert len(calls) - before_original == before_original - len(construction_calls)


@pytest.mark.parametrize("outer", [False, True])
def test_discarded_candidate_notes_do_not_replace_original_error_context(monkeypatch, outer):
    class ForeignValue:
        def __reduce_ex__(self, _protocol):
            raise AssertionError("foreign reducer executed")

    # A successfully encoded native recursive key precedes a failing value/error-note path.
    key = (("raw_private_key", frozenset({("safe", 1)})),)
    value = {key: ForeignValue()}
    original_error = OSError("declared original encoder refusal")
    ambient = RuntimeError("deliberately pre-existing outer context")
    dump, calls = pa._SnapshotDataPickler.dump, []

    def observed_dump(self, whole):
        calls.append(("candidate", whole))
        return dump(self, whole)

    def refused_marshal(whole, version):
        calls.append(("marshal", whole))
        assert version == 2
        raise original_error

    monkeypatch.setattr(pa._SnapshotDataPickler, "dump", observed_dump)
    monkeypatch.setattr(pa.marshal, "dumps", refused_marshal)
    if outer:
        try:
            raise ambient
        except RuntimeError:
            with pytest.raises(OSError) as caught:
                pa._snapshot_identity_binary(value)
    else:
        with pytest.raises(OSError) as caught:
            pa._snapshot_identity_binary(value)
    assert caught.value is original_error and caught.value.args == ("declared original encoder refusal",)
    assert caught.value.__context__ is (ambient if outer else None)
    assert getattr(caught.value, "__notes__", []) == []
    assert [mode for mode, _ in calls] == (["candidate", "marshal"] if _actual_c_data_writer_available()
                                         else ["marshal"])
    assert len(calls) == 1 or calls[0][1] is calls[1][1]


@pytest.mark.parametrize("fault", ["construction", "allocation", "dump", "nonbytes"])
def test_real_candidate_fault_preserves_one_original_codec(monkeypatch, fault):
    init, dump, marshal = pa._SnapshotDataPickler.__init__, pa._SnapshotDataPickler.dump, pa.marshal.dumps
    candidate_calls, legacy_calls = [], []
    value = {"rows": [False, 1, 0.0, "value"]}
    expected = marshal(dict(value), 2)

    def observed_init(self, stream, *args, **kwargs):
        candidate_calls.append("construction")
        init(self, stream, *args, **kwargs)
        self.test_stream = stream
        if fault in ("construction", "allocation"):
            raise (MemoryError if fault == "allocation" else OSError)("candidate construction")

    def observed_dump(self, whole):
        candidate_calls.append("dump")
        dump(self, whole)  # Genuine C operation before either fault below.
        if fault == "dump":
            raise OSError("candidate dump")
        if fault == "nonbytes":
            self.test_stream.getvalue = lambda: bytearray(b"unsupported result")

    def observed_marshal(whole, version):
        legacy_calls.append(whole)
        return marshal(whole, version)

    monkeypatch.setattr(pa._SnapshotDataPickler, "__init__", observed_init)
    monkeypatch.setattr(pa._SnapshotDataPickler, "dump", observed_dump)
    monkeypatch.setattr(pa.marshal, "dumps", observed_marshal)
    assert pa._snapshot_identity_binary(value) == expected
    expected_calls = []
    if _actual_c_data_writer_available():
        expected_calls = (["construction"] if fault in ("construction", "allocation") else
                          ["construction", "dump"])
    assert candidate_calls == expected_calls
    assert len(legacy_calls) == 1 and legacy_calls[0] is not value and legacy_calls[0]["rows"] is value["rows"]


@pytest.mark.parametrize("drift", ["profile", "base", "factory", "refusal", "stream"])
def test_unavailable_or_drifted_candidate_uses_original_without_invoking_it(monkeypatch, drift):
    value = {"field": [1, False]}
    marshal, calls = pa.marshal.dumps, []
    expected = marshal(dict(value), 2)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("unavailable candidate invoked")

    if drift == "profile":
        monkeypatch.setattr(pa, "_SNAPSHOT_C_PICKLER_PROFILES", ())
        monkeypatch.setattr(pa._SnapshotDataPickler, "dump", unexpected)
    elif drift == "base":
        monkeypatch.setattr(pa.pickle, "Pickler", unexpected)
    elif drift == "factory":
        monkeypatch.setattr(pa, "_SnapshotDataPickler", unexpected)
    elif drift == "refusal":
        monkeypatch.setattr(pa._SnapshotDataPickler, "reducer_override", unexpected)
        monkeypatch.setattr(pa._SnapshotDataPickler, "dump", unexpected)
    else:
        monkeypatch.setattr(pa.io, "BytesIO", unexpected)

    def observed_marshal(whole, version):
        calls.append(whole)
        return marshal(whole, version)

    monkeypatch.setattr(pa.marshal, "dumps", observed_marshal)
    assert pa._snapshot_identity_binary(value) == expected
    assert len(calls) == 1 and calls[0] is not value and calls[0]["field"] is value["field"]


def test_candidate_process_control_error_is_preserved_without_original_fallback(monkeypatch):
    dump, marshal, calls = pa._SnapshotDataPickler.dump, pa.marshal.dumps, []
    stopped = KeyboardInterrupt("declared candidate interruption")

    def observed_dump(self, whole):
        dump(self, whole)
        raise stopped

    def observed_marshal(whole, version):
        calls.append(whole)
        return marshal(whole, version)

    monkeypatch.setattr(pa._SnapshotDataPickler, "dump", observed_dump)
    monkeypatch.setattr(pa.marshal, "dumps", observed_marshal)
    if _actual_c_data_writer_available():
        with pytest.raises(KeyboardInterrupt) as caught:
            pa._snapshot_identity_binary({"rows": [1]})
        assert caught.value is stopped and calls == []
    else:
        assert pa._snapshot_identity_binary({"rows": [1]}) == marshal({"rows": [1]}, 2)
        assert len(calls) == 1
