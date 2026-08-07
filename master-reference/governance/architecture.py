"""Executable architecture ownership, static-edge, and phase conformance.

The contract deliberately distinguishes static source evidence from runtime
truth.  A resolved import or an import-bound call is a *possible dependency*;
it is never labelled as an observed runtime edge.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


CONTRACT_PATH = Path(__file__).with_name("architecture.json")
_TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json")


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("architecture contract must be a JSON object")
    return value


def _matches_rule(path: str, prefix: object) -> bool:
    if not isinstance(prefix, str) or not prefix:
        return False
    candidate = PurePosixPath(path).as_posix()
    if prefix.endswith("/"):
        return candidate == prefix.rstrip("/") or candidate.startswith(prefix)
    return candidate == prefix


def path_dispositions(path: str, contract: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    """Return every explicit component/exclusion rule matching ``path``.

    Rules are intentionally not precedence based.  A broad rule and a more
    specific rule matching the same path are ambiguous and therefore invalid.
    This keeps ownership changes reviewable instead of hiding them behind a
    longest-prefix convention.
    """

    rows: list[dict[str, str]] = []
    for kind, collection in (
        ("component", contract.get("components", [])),
        ("exclusion", contract.get("exclusions", [])),
    ):
        if not isinstance(collection, list):
            continue
        for rule in collection:
            if not isinstance(rule, Mapping):
                continue
            identifier = rule.get("id")
            paths = rule.get("paths", [])
            if not isinstance(identifier, str) or not isinstance(paths, list):
                continue
            if any(_matches_rule(path, prefix) for prefix in paths):
                rows.append({"kind": kind, "id": identifier})
    return tuple(sorted(rows, key=lambda row: (row["kind"], row["id"])))


def component_for_path(path: str, contract: Mapping[str, Any]) -> str | None:
    matches = path_dispositions(path, contract)
    if len(matches) != 1 or matches[0]["kind"] != "component":
        return None
    return matches[0]["id"]


def validate_path_dispositions(
    paths: Iterable[str], contract: Mapping[str, Any]
) -> tuple[tuple[str, ...], tuple[dict[str, str], ...]]:
    errors: list[str] = []
    rows: list[dict[str, str]] = []
    seen = set()
    for raw_path in sorted(str(item) for item in paths):
        path = PurePosixPath(raw_path).as_posix()
        if path in seen:
            errors.append(f"path:{path}:duplicate_census_entry")
            continue
        seen.add(path)
        matches = path_dispositions(path, contract)
        if not matches:
            errors.append(f"path:{path}:unmapped")
            continue
        if len(matches) != 1:
            labels = ",".join(f"{row['kind']}:{row['id']}" for row in matches)
            errors.append(f"path:{path}:ambiguous:{labels}")
            continue
        disposition = matches[0]
        rows.append({"path": path, "kind": disposition["kind"], "id": disposition["id"]})
    return tuple(sorted(set(errors))), tuple(rows)


def validate_contract(contract: Mapping[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    components = contract.get("components")
    exclusions = contract.get("exclusions")
    if not isinstance(components, list) or not components:
        errors.append("contract:components_missing")
        components = []
    if not isinstance(exclusions, list):
        errors.append("contract:exclusions_missing")
        exclusions = []
    identifiers: dict[str, str] = {}
    for kind, rows in (("component", components), ("exclusion", exclusions)):
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                errors.append(f"contract:{kind}:{index}:not_object")
                continue
            identifier = row.get("id")
            if not isinstance(identifier, str) or not identifier:
                errors.append(f"contract:{kind}:{index}:id_missing")
                continue
            if identifier in identifiers:
                errors.append(f"contract:duplicate_disposition_id:{identifier}")
            identifiers[identifier] = kind
            paths = row.get("paths")
            if not isinstance(paths, list) or not paths or any(
                not isinstance(path, str) or not path for path in paths
            ):
                errors.append(f"contract:{kind}:{identifier}:paths_invalid")
    component_ids = {str(row.get("id")) for row in components if isinstance(row, Mapping)}
    for index, row in enumerate(contract.get("allowed_edges", [])):
        if not isinstance(row, list) or len(row) != 2 or any(item not in component_ids for item in row):
            errors.append(f"contract:allowed_edge:{index}:invalid")
    for index, row in enumerate(contract.get("forbidden_edges", [])):
        if (
            not isinstance(row, Mapping)
            or row.get("from") not in component_ids
            or row.get("to") not in component_ids
        ):
            errors.append(f"contract:forbidden_edge:{index}:invalid")
    phases = contract.get("runtime_phases")
    if not isinstance(phases, list) or not phases:
        errors.append("contract:runtime_phases_missing")
    else:
        phase_ids: set[str] = set()
        orders: set[int] = set()
        for index, phase in enumerate(phases):
            if not isinstance(phase, Mapping):
                errors.append(f"contract:runtime_phase:{index}:not_object")
                continue
            identifier, order = phase.get("id"), phase.get("order")
            if not isinstance(identifier, str) or not identifier or identifier in phase_ids:
                errors.append(f"contract:runtime_phase:{index}:id_invalid")
            if not isinstance(order, int) or order <= 0 or order in orders:
                errors.append(f"contract:runtime_phase:{index}:order_invalid")
            if isinstance(identifier, str):
                phase_ids.add(identifier)
            if isinstance(order, int):
                orders.add(order)
    return tuple(sorted(set(errors)))


def validate_static_edges(
    edges: Iterable[Mapping[str, Any]], contract: Mapping[str, Any]
) -> tuple[str, ...]:
    allowed = {tuple(row) for row in contract.get("allowed_edges", []) if isinstance(row, list)}
    forbidden = {
        (row["from"], row["to"]): row.get("reason", "forbidden")
        for row in contract.get("forbidden_edges", [])
        if isinstance(row, Mapping) and "from" in row and "to" in row
    }
    components = {
        row["id"]
        for row in contract.get("components", [])
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    errors: list[str] = []
    for index, edge in enumerate(edges):
        source = edge.get("from_component")
        target = edge.get("to_component")
        dynamic = edge.get("classification") == "expected_dynamic"
        if source not in components:
            errors.append(f"edge:{index}:unknown_source:{source}")
            continue
        if target not in components:
            errors.append(f"edge:{index}:unknown_target:{target}")
            continue
        if (source, target) in forbidden:
            errors.append(f"edge:{index}:forbidden:{source}->{target}")
        elif source != target and (source, target) not in allowed and not dynamic:
            errors.append(f"edge:{index}:undeclared:{source}->{target}")
    return tuple(sorted(set(errors)))


def validate_runtime_trace(
    trace: Iterable[Mapping[str, Any]], contract: Mapping[str, Any]
) -> tuple[str, ...]:
    phases = {
        row["id"]: row
        for row in contract.get("runtime_phases", [])
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    events = list(trace)
    errors: list[str] = []
    seen: dict[str, Mapping[str, Any]] = {}
    previous_order = 0
    for index, event in enumerate(events):
        phase = event.get("phase")
        if phase not in phases:
            errors.append(f"trace:{index}:unknown_phase:{phase}")
            continue
        if phase in seen:
            errors.append(f"trace:{index}:duplicate_phase:{phase}")
        seen[str(phase)] = event
        order = int(phases[str(phase)]["order"])
        if order < previous_order:
            errors.append(f"trace:{index}:phase_out_of_order:{phase}")
        previous_order = max(previous_order, order)
        status = event.get("status")
        if status not in {"passed", "failed", "abstained", "skipped"}:
            errors.append(f"trace:{index}:status_invalid:{phase}")
        if status == "passed" and not event.get("receipt_id"):
            errors.append(f"trace:{index}:pass_without_receipt:{phase}")

    missing_required: list[str] = []
    for phase, row in phases.items():
        if row.get("required") and phase not in seen:
            missing_required.append(phase)
            errors.append(f"trace:required_phase_missing:{phase}")

    barriers = [
        int(phases[phase]["order"])
        for phase, event in seen.items()
        if phases[phase].get("required") and event.get("status") != "passed"
    ]
    barriers.extend(int(phases[phase]["order"]) for phase in missing_required)
    if barriers:
        first_barrier = min(barriers)
        for phase, event in seen.items():
            if int(phases[phase]["order"]) > first_barrier and event.get("status") == "passed":
                errors.append(f"trace:downstream_pass_after_required_failure:{phase}")
    return tuple(sorted(set(errors)))


def _normal_path(value: str) -> str | None:
    normalized = posixpath.normpath(value.replace("\\", "/"))
    if normalized in {"", "."} or normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
        return None
    return normalized


def _candidate_modules(base: str, *, typescript: bool) -> tuple[str, ...]:
    if typescript:
        candidates = [base]
        if not PurePosixPath(base).suffix:
            candidates.extend(f"{base}{suffix}" for suffix in _TS_EXTENSIONS)
            candidates.extend(f"{base}/index{suffix}" for suffix in _TS_EXTENSIONS)
        return tuple(candidates)
    return (f"{base}.py", f"{base}/__init__.py")


def _resolve_import(
    source_path: str,
    module: str,
    language: str,
    tracked_paths: set[str],
    contract: Mapping[str, Any],
) -> tuple[str, ...]:
    typescript = language in {"javascript", "jsx", "typescript", "tsx"}
    bases: list[str] = []
    if typescript:
        if module.startswith("."):
            joined = _normal_path(posixpath.join(posixpath.dirname(source_path), module))
            if joined:
                bases.append(joined)
        else:
            aliases = contract.get("typescript_aliases", {})
            if isinstance(aliases, Mapping):
                for prefix, replacement in sorted(aliases.items(), key=lambda row: -len(str(row[0]))):
                    if isinstance(prefix, str) and isinstance(replacement, str) and module.startswith(prefix):
                        joined = _normal_path(replacement + module[len(prefix) :])
                        if joined:
                            bases.append(joined)
                        break
    else:
        leading = len(module) - len(module.lstrip("."))
        bare = module[leading:]
        module_path = bare.replace(".", "/")
        if leading:
            package = list(PurePosixPath(source_path).parent.parts)
            climb = leading - 1
            if climb <= len(package):
                anchor = package[: len(package) - climb]
                joined = _normal_path("/".join([*anchor, module_path]) if module_path else "/".join(anchor))
                if joined:
                    bases.append(joined)
        else:
            roots = contract.get("python_import_roots", [""])
            if isinstance(roots, list):
                for root in roots:
                    if isinstance(root, str):
                        joined = _normal_path(posixpath.join(root, module_path))
                        if joined:
                            bases.append(joined)
    candidates = {
        candidate
        for base in bases
        for candidate in _candidate_modules(base, typescript=typescript)
        if candidate in tracked_paths
    }
    if not candidates:
        # PEP 420 namespace packages have no ``__init__.py``.  Represent the
        # package directory as a virtual static target only when the tracked
        # tree contains members beneath it; component ownership is resolved
        # from the same explicit path-prefix contract as regular files.
        candidates.update(
            f"{base}/"
            for base in bases
            if any(path.startswith(f"{base}/") for path in tracked_paths)
        )
    return tuple(sorted(candidates))


def _is_internal_import(module: str, language: str, contract: Mapping[str, Any]) -> bool:
    if module.startswith("."):
        return True
    prefixes = contract.get("internal_module_prefixes", [])
    return isinstance(prefixes, list) and any(
        isinstance(prefix, str) and (module == prefix or module.startswith(prefix + ".") or module.startswith(prefix + "/"))
        for prefix in prefixes
    )


def build_architecture_conformance(
    *,
    paths: Sequence[str],
    file_languages: Mapping[str, str],
    imports: Iterable[Mapping[str, Any]],
    calls: Iterable[Mapping[str, Any]],
    contract: Mapping[str, Any],
    source_commit: str,
    source_tree_digest: str,
) -> dict[str, Any]:
    """Build a deterministic, source-bound conformance receipt."""

    contract_errors = list(validate_contract(contract))
    disposition_errors, disposition_rows = validate_path_dispositions(paths, contract)
    errors = contract_errors + list(disposition_errors)
    disposition_by_path = {row["path"]: row for row in disposition_rows}
    tracked_paths = set(paths)
    static_edges: list[dict[str, Any]] = []
    import_targets: dict[tuple[str, str], tuple[str, ...]] = {}

    sorted_imports = sorted(imports, key=lambda row: str(row.get("id", "")))
    for imported in sorted_imports:
        source_path = str(imported.get("path") or "")
        module = imported.get("module")
        if source_path not in tracked_paths or not isinstance(module, str) or not module or module == "<dynamic>":
            continue
        source_disposition = disposition_by_path.get(source_path)
        # Tests, history, and explicitly excluded support files remain
        # accounted for by disposition, but their imports do not define the
        # deployed architecture.
        if source_disposition is None or source_disposition["kind"] == "exclusion":
            continue
        language = str(file_languages.get(source_path) or "")
        targets = _resolve_import(source_path, module, language, tracked_paths, contract)
        if len(targets) > 1:
            errors.append(f"import:{imported.get('id')}:ambiguous_target:{','.join(targets)}")
            continue
        if not targets:
            if _is_internal_import(module, language, contract):
                errors.append(f"import:{imported.get('id')}:unresolved_internal:{module}")
            continue
        target_path = targets[0]
        target_disposition = disposition_by_path.get(target_path)
        if target_disposition is None and target_path.endswith("/"):
            matches = path_dispositions(target_path, contract)
            if len(matches) == 1:
                target_disposition = {
                    "path": target_path,
                    "kind": matches[0]["kind"],
                    "id": matches[0]["id"],
                }
        if source_disposition is None or target_disposition is None:
            continue
        if source_disposition["kind"] == "exclusion" or target_disposition["kind"] == "exclusion":
            continue
        edge = {
            "evidence_id": str(imported.get("id")),
            "kind": "resolved_static_import",
            "source_path": source_path,
            "target_path": target_path,
            "from_component": source_disposition["id"],
            "to_component": target_disposition["id"],
            "classification": "static_structure_only",
            "runtime_observed": False,
        }
        static_edges.append(edge)
        names = imported.get("names")
        binding_names: set[str] = set()
        if isinstance(imported.get("alias"), str) and imported.get("alias"):
            binding_names.add(str(imported["alias"]))
        if isinstance(names, list):
            binding_names.update(str(name).split(" as ")[-1].strip() for name in names if str(name).strip())
        if imported.get("kind") != "from_import":
            binding_names.add(module.lstrip(".").split(".")[0].split("/")[0])
        for name in binding_names:
            if name:
                import_targets[(source_path, name)] = targets

    for call in sorted(calls, key=lambda row: str(row.get("id", ""))):
        source_path = str(call.get("path") or "")
        callee = str(call.get("callee") or "")
        binding = callee.split(".", 1)[0]
        targets = import_targets.get((source_path, binding), ())
        if len(targets) != 1:
            continue
        target_path = targets[0]
        source_disposition = disposition_by_path.get(source_path)
        target_disposition = disposition_by_path.get(target_path)
        if (
            source_disposition is None
            or target_disposition is None
            or source_disposition["kind"] != "component"
            or target_disposition["kind"] != "component"
        ):
            continue
        static_edges.append(
            {
                "evidence_id": str(call.get("id")),
                "kind": "import_bound_static_call_candidate",
                "source_path": source_path,
                "target_path": target_path,
                "from_component": source_disposition["id"],
                "to_component": target_disposition["id"],
                "classification": "static_structure_only",
                "runtime_observed": False,
            }
        )

    static_edges.sort(
        key=lambda row: (
            row["source_path"],
            row["target_path"],
            row["kind"],
            row["evidence_id"],
        )
    )
    errors.extend(validate_static_edges(static_edges, contract))
    trace_receipts: list[dict[str, Any]] = []
    synthetic_traces = contract.get("synthetic_runtime_traces", [])
    if not isinstance(synthetic_traces, list) or not synthetic_traces:
        errors.append("contract:synthetic_runtime_traces_missing")
    else:
        for index, item in enumerate(synthetic_traces):
            if not isinstance(item, Mapping) or not isinstance(item.get("events"), list):
                errors.append(f"synthetic_trace:{index}:invalid")
                continue
            trace_id = str(item.get("id") or index)
            trace_errors = validate_runtime_trace(item["events"], contract)
            errors.extend(f"synthetic_trace:{trace_id}:{error}" for error in trace_errors)
            trace_receipts.append(
                {
                    "id": trace_id,
                    "event_count": len(item["events"]),
                    "events_digest": _digest(item["events"]),
                    "passed": not trace_errors,
                    "errors": list(trace_errors),
                    "evidence_class": "synthetic_contract_trace_not_runtime_observation",
                }
            )

    unique_errors = sorted(set(errors))
    ownership_counts = {"component": 0, "exclusion": 0}
    for row in disposition_rows:
        ownership_counts[row["kind"]] += 1
    core = {
        "schema_version": "1.0.0",
        "source_commit": source_commit,
        "source_tree_digest": source_tree_digest,
        "contract_digest": _digest(contract),
        "status": "passed" if not unique_errors else "failed",
        "evidence_class": "static_and_synthetic_conformance_not_runtime_truth",
        "runtime_observed": False,
        "tracked_path_count": len(paths),
        "disposition_count": len(disposition_rows),
        "disposition_counts": ownership_counts,
        "disposition_digest": _digest(disposition_rows),
        "static_edge_count": len(static_edges),
        "static_edges_digest": _digest(static_edges),
        "static_edges": static_edges,
        "synthetic_runtime_traces": trace_receipts,
        "errors": unique_errors,
        "limitations": [
            "Resolved imports establish static dependency candidates, not runtime execution.",
            "Import-bound call candidates are name-based and do not assert dynamic dispatch.",
            "Synthetic phase traces validate contract behavior, not a production run.",
        ],
    }
    return {**core, "receipt_digest": _digest(core)}
