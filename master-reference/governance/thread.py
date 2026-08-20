"""Content-addressed bitemporal event thread for reference lifecycle facts."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Iterable, Mapping


GENESIS = "0" * 64
EVENT_TYPES = frozenset(
    {
        "added",
        "expanded",
        "verified",
        "surfaced",
        "corrected",
        "renamed",
        "deprecated",
        "superseded",
        "gap_opened",
        "gap_closed",
        "evidence_invalidated",
        "verification_revoked",
        "outcome_measured",
    }
)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def event_hash(event_without_hash: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(event_without_hash)).hexdigest()


def append_event(events: Iterable[Mapping[str, Any]], event: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return a new chain with ``event`` appended; never mutate the caller."""

    chain = [deepcopy(dict(item)) for item in events]
    previous = chain[-1].get("event_hash", GENESIS) if chain else GENESIS
    record = deepcopy(dict(event))
    if record.get("event_type") not in EVENT_TYPES:
        raise ValueError("unknown event_type")
    required = {
        "entity_id",
        "event_type",
        "effective_time",
        "recorded_time",
        "source_commit",
        "source_tree",
        "actor_role",
    }
    missing = sorted(name for name in required if not record.get(name))
    if missing:
        raise ValueError(f"missing event fields: {', '.join(missing)}")
    record["previous_event_hash"] = previous
    record["event_hash"] = event_hash(record)
    chain.append(record)
    return chain


def verify_events(events: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    errors: list[str] = []
    previous = GENESIS
    for index, event in enumerate(events):
        if event.get("previous_event_hash") != previous:
            errors.append(f"event:{index}:previous_hash_mismatch")
        claimed = event.get("event_hash")
        material = dict(event)
        material.pop("event_hash", None)
        actual = event_hash(material)
        if claimed != actual:
            errors.append(f"event:{index}:hash_mismatch")
        if event.get("event_type") not in EVENT_TYPES:
            errors.append(f"event:{index}:event_type_invalid")
        previous = str(claimed or "")
    return tuple(errors)


def replay_events(events: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Materialize current entity state after validating the entire chain."""

    chain = list(events)
    errors = verify_events(chain)
    if errors:
        raise ValueError("invalid event chain: " + ", ".join(errors))

    state: dict[str, dict[str, Any]] = {}
    for event in chain:
        entity_id = str(event["entity_id"])
        current = state.setdefault(entity_id, {"entity_id": entity_id, "aliases": []})
        current["last_event_hash"] = event["event_hash"]
        current["effective_time"] = event["effective_time"]
        current["recorded_time"] = event["recorded_time"]
        current["event_type"] = event["event_type"]
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            current.update(deepcopy(dict(payload)))
        if event["event_type"] == "renamed" and isinstance(event.get("alias"), str):
            current["aliases"] = sorted(set([*current.get("aliases", []), event["alias"]]))
        if event["event_type"] in {"superseded", "deprecated", "verification_revoked"}:
            current["current"] = False
        else:
            current.setdefault("current", True)
    return state
