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


def _observe_real_original_marshal(monkeypatch):
    marshal, calls = pa.marshal.dumps, []

    def observed(whole, version):
        assert type(whole) is dict and version == 2
        calls.append(whole)
        return marshal(whole, version)

    monkeypatch.setattr(pa.marshal, "dumps", observed)
    return calls


def test_real_original_codec_checks_live_copies_new_keys_aliases_and_late_mutation(monkeypatch):
    raw = (b'{"first":[],"second":[],"non_interned_key_abcdefghijklmnopqrstuvwxyz":'
           b'{"rows":[false,1,0.0,-0.0,null,"\\ud800","\\ud83d\\ude00"]}}')
    bound = pa.bind_snapshot_json_bytes(raw)
    keepalive = bound["non_interned_key_abcdefghijklmnopqrstuvwxyz"]
    copied = deepcopy(bound)
    key = next(key for key in copied if key.startswith("non_interned"))
    new_key = ("_" + key)[1:]
    assert new_key == key and new_key is not key
    copied[new_key] = copied.pop(key)
    copied["second"] = copied["first"]
    assert copied[new_key] is not keepalive and copied["first"] is not bound["first"]
    expected = _original_source(bound)
    assert bound._bound_content_proof.binary_text == pa.marshal.dumps(dict(bound), 2)
    calls = _observe_real_original_marshal(monkeypatch)
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
    assert len(calls) == 4
    assert all(value is not subject and value[new_key] is subject[new_key]
               for value, subject in zip(calls, (bound, copied, copied, bound)))
    copied[new_key]["rows"][-1] = "changed"
    assert _fallback_matches_original(copied, monkeypatch)["source_bound"] is False
    assert pa.bound_snapshot_source(bound) == expected


@pytest.mark.parametrize("shape", ["scalar", "dict", "list", "recursive-key"])
def test_original_codec_refuses_foreign_hooks_without_copyreg_or_reduction(monkeypatch, shape):
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
    calls = _observe_real_original_marshal(monkeypatch)
    with pytest.raises(ValueError) as actual:
        pa._snapshot_identity_binary(value)
    assert actual.value.__context__ is None and getattr(actual.value, "__notes__", []) == []
    assert len(calls) == 1 and calls[0] is not value
    assert events == []


@pytest.mark.parametrize("kind", ["bytearray", "bytearray-subclass", "buffer", "released", "noncontiguous"])
def test_original_codec_preserves_buffer_domains_and_same_complete_copy(monkeypatch, kind):
    callbacks = []

    class ForeignBytearray(bytearray):
        def __reduce_ex__(self, _protocol):
            callbacks.append("reduce_ex")
            raise AssertionError("foreign bytearray reduction executed")

    value = (bytearray(b"value") if kind == "bytearray" else ForeignBytearray(b"value")
             if kind == "bytearray-subclass" else memoryview(b"value")[::2]
             if kind == "noncontiguous" else memoryview(b"value"))
    if kind == "released":
        value.release()
    whole = {"field": value, "tail": [False, 0, -0.0, None]}
    original = pa.marshal.dumps
    try:
        expected = original(dict(whole), 2)
    except Exception as error:
        expected_error = (type(error), error.args)
    else:
        expected_error = None
    original_callbacks = list(callbacks)
    callbacks.clear()
    calls = _observe_real_original_marshal(monkeypatch)
    if expected_error is not None:
        with pytest.raises(expected_error[0]) as caught:
            pa._snapshot_identity_binary(whole)
        assert caught.value.args == expected_error[1] and caught.value.__context__ is None
    else:
        assert pa._snapshot_identity_binary(whole) == expected
    assert len(calls) == 1 and calls[0] is not whole
    assert calls[0]["field"] is value and calls[0]["tail"] is whole["tail"]
    assert callbacks == original_callbacks == []


def test_original_codec_preserves_one_genuine_root_copy_hook_trace(monkeypatch):
    events = []

    class Source(dict):
        def __iter__(self):
            events.append("iter")
            return dict.__iter__(self)

        def keys(self):
            events.append("keys")
            return dict.keys(self)

        def __getitem__(self, key):
            events.append(("get", key))
            return dict.__getitem__(self, key)

    value = Source(field=[False, 1, -0.0], tail={"last": "value"})
    original_whole = dict(value)
    original = pa.marshal.dumps(original_whole, 2)
    expected_events = list(events)
    assert ("get", "tail") in expected_events  # Genuine mapping-copy path, not a flags-only fake.
    events.clear()
    calls = _observe_real_original_marshal(monkeypatch)
    assert pa._snapshot_identity_binary(value) == original
    assert events == expected_events and len(calls) == 1
    assert calls[0] is not value and type(calls[0]) is dict
    assert calls[0]["field"] is value["field"] and calls[0]["tail"] is value["tail"]


@pytest.mark.parametrize("outer", [False, True])
def test_original_codec_error_retains_exact_object_context_and_notes(monkeypatch, outer):
    value = {"field": [False, 1, "value"]}
    original_error = OSError("declared original encoder refusal")
    ambient = RuntimeError("deliberately pre-existing outer context")
    calls = []

    def refused_marshal(whole, version):
        calls.append(whole)
        assert type(whole) is dict and version == 2
        raise original_error

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
    assert len(calls) == 1 and calls[0] is not value and calls[0]["field"] is value["field"]


@pytest.mark.parametrize("fault", ["allocation", "runtime", "nonbytes", "incomplete"])
def test_original_codec_fault_retains_complete_json_and_scaffold_fallback(monkeypatch, fault):
    bound = pa.bind_snapshot_json_bytes(b'{"nested":{"rows":[false,1,0.0]},"last":"value"}')
    marshal, calls = pa.marshal.dumps, []

    def observed_marshal(whole, version):
        assert type(whole) is dict and version == 2
        assert whole is not bound and whole["nested"] is bound["nested"]
        calls.append(whole)
        result = marshal(whole, version)  # Genuine original native operation before declared fault.
        if fault in ("allocation", "runtime"):
            raise (MemoryError if fault == "allocation" else OSError)("declared original codec fault")
        if fault == "nonbytes":
            return bytearray(result)
        return result + b"declared incomplete observation"

    monkeypatch.setattr(pa.marshal, "dumps", observed_marshal)
    assert _fresh_encoder_matches_original(bound, monkeypatch)["source_bound"] is True
    assert len(calls) == 2  # EACH source read attempts the complete original codec before fallback.


@pytest.mark.parametrize("drift", ["profile", "base", "factory", "refusal", "stream"])
def test_removed_encoder_namespace_cannot_intercept_original_codec(monkeypatch, drift):
    value = {"field": [1, False], "tail": {"last": "value"}}
    original = pa.marshal.dumps(dict(value), 2)
    intercepted = []

    def unexpected(*args, **kwargs):
        intercepted.append((args, kwargs))
        raise AssertionError("removed optional encoder invoked")

    name, replacement = {
        "profile": ("_SNAPSHOT_C_PICKLER_PROFILES", ()),
        "base": ("pickle", SimpleNamespace(Pickler=unexpected)),
        "factory": ("_SnapshotDataPickler", unexpected),
        "refusal": ("_SNAPSHOT_PICKLER_REFUSAL_OWNER", unexpected),
        "stream": ("io", SimpleNamespace(BytesIO=unexpected)),
    }[drift]
    assert not hasattr(pa, name)
    monkeypatch.setattr(pa, name, replacement, raising=False)
    calls = _observe_real_original_marshal(monkeypatch)
    assert pa._snapshot_identity_binary(value) == original
    assert intercepted == [] and len(calls) == 1
    assert calls[0] is not value and calls[0]["field"] is value["field"]


def test_original_codec_process_control_error_is_preserved_without_second_call(monkeypatch):
    marshal, calls = pa.marshal.dumps, []
    value = {"rows": [1]}
    stopped = KeyboardInterrupt("declared original codec interruption")

    def observed_marshal(whole, version):
        calls.append(whole)
        assert type(whole) is dict and whole is not value and whole["rows"] is value["rows"] and version == 2
        marshal(whole, version)  # Genuine native operation before the process-control exception.
        raise stopped

    monkeypatch.setattr(pa.marshal, "dumps", observed_marshal)
    with pytest.raises(KeyboardInterrupt) as caught:
        pa._snapshot_identity_binary(value)
    assert caught.value is stopped and len(calls) == 1


def test_original_native_refusal_adds_no_foreign_reduction_or_attribute_hooks():
    hooks = []

    class Foreign:
        def __getattribute__(self, name):
            if name in ("__reduce__", "__reduce_ex__", "__getstate__", "__module__", "__qualname__"):
                hooks.append(name)
            return object.__getattribute__(self, name)

        def __reduce_ex__(self, _protocol):
            hooks.append("reduce_ex")
            raise AssertionError("foreign reducer executed")

        def __repr__(self):
            hooks.append("repr")
            return "foreign"

    foreign = Foreign()
    value = {"field": foreign}
    try:
        pa.marshal.dumps(dict(value), 2)
    except Exception as error:
        expected_error = (type(error), error.args)
    else:
        pytest.fail("genuine original codec must refuse the foreign object")
    with pytest.raises(expected_error[0]) as caught:
        pa._snapshot_identity_binary(value)
    assert caught.value.args == expected_error[1] and caught.value.__context__ is None
    current = caught.value.__traceback__
    while current.tb_next is not None:
        current = current.tb_next
    assert current.tb_frame.f_code is pa._snapshot_identity_binary.__code__
    whole = current.tb_frame.f_locals["whole"]
    assert type(whole) is dict and whole is not value and whole["field"] is foreign
    assert hooks == []
