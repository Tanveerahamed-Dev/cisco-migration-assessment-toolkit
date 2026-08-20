"""Exact-byte snapshot custody is process-local and mutation-sensitive."""

from __future__ import annotations

import hashlib
import json

import pytest

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
