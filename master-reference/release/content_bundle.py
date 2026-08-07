"""Allowlisted reader for curated Atlas knowledge contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .model import ReleaseInputError, read_bytes, sha256_bytes


CONTENT_FILES = (
    "atlas-core.json",
    "capability-catalog.json",
    "delivery-governance.json",
    "open-horizon-register.json",
    "output-contract.json",
)


@dataclass(frozen=True)
class ContentBundle:
    root: Path
    core: dict[str, Any]
    capabilities: dict[str, Any]
    governance: dict[str, Any]
    horizon: dict[str, Any]
    output_contract: dict[str, Any]
    receipts: tuple[dict[str, Any], ...]
    raw_files: dict[str, bytes]


def _object(
    root: Path,
    name: str,
    source_reader: Callable[[str], bytes] | None,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    raw = source_reader(name) if source_reader is not None else read_bytes(root, name)
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseInputError(f"curated content is not valid UTF-8 JSON: {name}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "1.0.0":
        raise ReleaseInputError(f"curated content has an unsupported schema: {name}")
    return (
        value,
        {"path": f"master-reference/content/{name}", "sha256": sha256_bytes(raw), "bytes": len(raw)},
        raw,
    )


def load_content_bundle(
    root: Path,
    *,
    source_reader: Callable[[str], bytes] | None = None,
) -> ContentBundle:
    root = root.resolve(strict=True)
    loaded = [_object(root, name, source_reader) for name in CONTENT_FILES]
    core, capabilities, governance, horizon, output_contract = (item[0] for item in loaded)
    receipts = tuple(item[1] for item in loaded)
    raw_files = {name: item[2] for name, item in zip(CONTENT_FILES, loaded, strict=True)}

    if not isinstance(capabilities.get("domains"), list) or any(
        not isinstance(domain, dict) or not isinstance(domain.get("entries"), list)
        for domain in capabilities.get("domains", [])
    ):
        raise ReleaseInputError("capability catalog is missing domains or nested entries")
    if not isinstance(governance.get("gaps"), list) or not isinstance(governance.get("decision_queue"), list):
        raise ReleaseInputError("delivery governance is missing gaps or decision_queue")
    if not isinstance(governance.get("opportunity_portfolio"), dict) or not isinstance(
        governance["opportunity_portfolio"].get("items"), list
    ):
        raise ReleaseInputError("delivery governance is missing opportunity_portfolio")
    if not isinstance(horizon.get("signals"), list) or not isinstance(horizon.get("watch_families"), list):
        raise ReleaseInputError("open horizon register is missing signals or watch families")
    members = output_contract.get("members")
    if not isinstance(output_contract.get("catalog_version"), str) or not isinstance(members, list) or not members:
        raise ReleaseInputError("output contract is missing catalog_version or members")
    member_ids: set[str] = set()
    member_paths: set[str] = set()
    for item in members:
        if not isinstance(item, dict):
            raise ReleaseInputError("output contract member is not an object")
        identifier = item.get("id")
        emission = item.get("emission")
        manifest_member = item.get("manifest_member")
        if not isinstance(identifier, str) or not identifier or identifier in member_ids:
            raise ReleaseInputError("output contract contains an invalid or duplicate member id")
        member_ids.add(identifier)
        if emission not in {"always", "when_pdf", "external"}:
            raise ReleaseInputError(f"output contract member has an invalid emission: {identifier}")
        if not isinstance(item.get("label"), str) or not isinstance(item.get("gate"), str):
            raise ReleaseInputError(f"output contract member lacks label or gate: {identifier}")
        if not isinstance(item.get("ui_surface"), bool):
            raise ReleaseInputError(f"output contract member lacks ui_surface boolean: {identifier}")
        if emission == "external":
            if manifest_member is not None:
                raise ReleaseInputError(f"external output contract member must not name an emitted file: {identifier}")
        else:
            if not isinstance(manifest_member, str) or not manifest_member or manifest_member in member_paths:
                raise ReleaseInputError(f"output contract contains an invalid or duplicate manifest member: {identifier}")
            member_paths.add(manifest_member)

    ids: dict[str, str] = {}
    collections = {
        "owner": core.get("owners", []),
        "domain": capabilities["domains"],
        "capability": [entry for domain in capabilities["domains"] for entry in domain["entries"]],
        "gap": governance["gaps"],
        "decision": governance["decision_queue"],
        "opportunity": governance["opportunity_portfolio"]["items"],
        "horizon signal": horizon["signals"],
        "watch family": horizon["watch_families"],
    }
    for label, values in collections.items():
        if not isinstance(values, list):
            raise ReleaseInputError(f"curated {label} collection is not a list")
        for item in values:
            identifier = item.get("id") if isinstance(item, dict) else None
            if not isinstance(identifier, str) or not identifier:
                raise ReleaseInputError(f"curated {label} record lacks an id")
            if identifier in ids:
                raise ReleaseInputError(f"duplicate curated id {identifier!r} in {ids[identifier]} and {label}")
            ids[identifier] = label
    return ContentBundle(
        root,
        core,
        capabilities,
        governance,
        horizon,
        output_contract,
        receipts,
        raw_files,
    )
