"""Pure validation for task envelopes and completion receipts.

Validation observes Git and compiler state but never stages, commits, executes a
declared test, writes an artifact, contacts a device, or performs network I/O.
"""

from __future__ import annotations

import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from governance.architecture import load_contract, path_dispositions

from .git_state import _is_restricted, observe_git_state
from .model import ContinuityInputError, digest_object, safe_relative, sha256_bytes


PROTECTED_ACTIONS = frozenset({"device-write", "vault-write", "client-data-ingest", "public-publish"})
LOCAL_ACTIONS = frozenset(
    {
        "build-local-artifacts",
        "commit-git",
        "edit-repository",
        "read-repository",
        "run-tests",
        "stage-git",
    }
)

ENVELOPE_FIELDS = frozenset(
    {
        "allowed_actions",
        "allowed_owners",
        "allowed_paths",
        "authority",
        "baseline_commit",
        "baseline_tree",
        "expires_at",
        "id",
        "objective",
        "prohibited_actions",
        "required_tests",
        "schema_version",
    }
)
RECEIPT_FIELDS = frozenset(
    {
        "actions_performed",
        "actor_id",
        "artifacts",
        "baseline_commit",
        "baseline_tree",
        "changed_owners",
        "changed_paths",
        "completion_commit",
        "completion_tree",
        "conflicts",
        "diff_digest",
        "envelope_digest",
        "exceptions",
        "external_actions",
        "id",
        "schema_version",
        "tests",
    }
)


def _utc(value: object, field: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{field}:missing_or_invalid")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field}:invalid_timestamp")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        errors.append(f"{field}:must_be_utc")
        return None
    return parsed.astimezone(timezone.utc)


def _string_list(value: object, field: str, errors: list[str], *, nonempty: bool = True) -> list[str]:
    if (
        not isinstance(value, list)
        or (nonempty and not value)
        or any(not isinstance(item, str) or not item for item in value)
    ):
        errors.append(f"{field}:must_be_{'nonempty_' if nonempty else ''}string_list")
        return []
    if len(value) != len(set(value)):
        errors.append(f"{field}:duplicates")
    return list(value)


def _path_rules(value: object, errors: list[str]) -> list[str]:
    rows = _string_list(value, "allowed_paths", errors)
    result: list[str] = []
    for row in rows:
        try:
            result.append(safe_relative(row, allow_directory_prefix=True))
        except ContinuityInputError:
            errors.append(f"allowed_paths:unsafe:{row}")
    return result


def _path_allowed(path: str, rules: list[str]) -> bool:
    return any(path == rule or (rule.endswith("/") and path.startswith(rule)) for rule in rules)


def _contract(repository_root: Path) -> dict[str, Any]:
    path = repository_root / "master-reference" / "governance" / "architecture.json"
    if not path.is_file() or path.is_symlink():
        raise ContinuityInputError("tracked architecture contract is unavailable")
    return load_contract(path)


def _owners(repository_root: Path, paths: list[str]) -> tuple[list[str], list[str]]:
    contract = _contract(repository_root)
    owners: set[str] = set()
    errors: list[str] = []
    for path in paths:
        dispositions = path_dispositions(path, contract)
        if len(dispositions) != 1:
            errors.append(f"changed_path_owner_not_unique:{path}")
        else:
            owners.add(dispositions[0]["id"])
    return sorted(owners), errors


def _validate_envelope_fields(
    envelope: Mapping[str, Any], now: datetime
) -> tuple[list[str], list[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    unknown = sorted(set(envelope) - ENVELOPE_FIELDS)
    missing = sorted(ENVELOPE_FIELDS - set(envelope))
    errors.extend(f"envelope:unknown_field:{field}" for field in unknown)
    errors.extend(f"envelope:missing_field:{field}" for field in missing)
    if envelope.get("schema_version") != "1.0.0":
        errors.append("schema_version:unsupported")
    for field in ("id", "objective"):
        if not isinstance(envelope.get(field), str) or not str(envelope.get(field)).strip():
            errors.append(f"{field}:missing_or_invalid")
    for field, lengths in (("baseline_commit", {40, 64}), ("baseline_tree", {40, 64})):
        value = envelope.get(field)
        if (
            not isinstance(value, str)
            or len(value) not in lengths
            or any(char not in "0123456789abcdef" for char in value)
        ):
            errors.append(f"{field}:invalid_object_id")
    allowed_owners = _string_list(envelope.get("allowed_owners"), "allowed_owners", errors)
    allowed_paths = _path_rules(envelope.get("allowed_paths"), errors)
    allowed_actions = _string_list(envelope.get("allowed_actions"), "allowed_actions", errors)
    unknown_actions = sorted(set(allowed_actions) - LOCAL_ACTIONS - PROTECTED_ACTIONS)
    errors.extend(f"allowed_actions:unknown:{action}" for action in unknown_actions)
    errors.extend(
        f"protected_action_unwaivable:{action}" for action in sorted(set(allowed_actions) & PROTECTED_ACTIONS)
    )
    prohibited = _string_list(envelope.get("prohibited_actions"), "prohibited_actions", errors)
    errors.extend(
        f"protected_action_not_explicitly_prohibited:{action}" for action in sorted(PROTECTED_ACTIONS - set(prohibited))
    )
    tests = envelope.get("required_tests")
    if not isinstance(tests, list) or not tests:
        errors.append("required_tests:must_be_nonempty_list")
    else:
        test_ids: list[str] = []
        for index, test in enumerate(tests):
            if not isinstance(test, Mapping) or set(test) != {"id", "command"}:
                errors.append(f"required_tests:{index}:invalid_shape")
                continue
            if not isinstance(test.get("id"), str) or not test["id"]:
                errors.append(f"required_tests:{index}:id_invalid")
            else:
                test_ids.append(test["id"])
            if not isinstance(test.get("command"), str) or not test["command"].strip():
                errors.append(f"required_tests:{index}:command_invalid")
        if len(test_ids) != len(set(test_ids)):
            errors.append("required_tests:duplicate_id")
    authority = envelope.get("authority")
    if not isinstance(authority, Mapping) or set(authority) != {"actor_id", "grant_id", "granted_by"}:
        errors.append("authority:invalid_shape")
    else:
        for field in ("actor_id", "grant_id", "granted_by"):
            if not isinstance(authority.get(field), str) or not authority[field].strip():
                errors.append(f"authority:{field}:invalid")
    expiry = _utc(envelope.get("expires_at"), "expires_at", errors)
    if expiry is not None and expiry <= now:
        errors.append("authority:expired")
    if not errors and not allowed_paths:
        warnings.append("no_paths_authorized")
    return errors, warnings, allowed_paths, allowed_owners


def validate_task_envelope(
    envelope: Mapping[str, Any],
    repository_root: Path,
    compiler_bundle: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    errors, warnings, allowed_paths, allowed_owners = _validate_envelope_fields(envelope, moment)
    root = repository_root.resolve(strict=True)
    observed: dict[str, Any] | None = None
    baseline = envelope.get("baseline_commit")
    if isinstance(baseline, str) and len(baseline) in {40, 64}:
        try:
            observed = observe_git_state(root, baseline)
            errors.extend(observed["errors"])
            if observed["head_commit"] != baseline:
                errors.append("baseline_commit:stale_head")
            if observed["baseline_tree"] != envelope.get("baseline_tree"):
                errors.append("baseline_tree:mismatch")
            errors.extend(
                f"changed_path_outside_scope:{path}"
                for path in observed["changed_paths"]
                if not _path_allowed(path, allowed_paths)
            )
        except ContinuityInputError as exc:
            errors.append(f"git_state:{exc}")
    if compiler_bundle.source_commit != baseline:
        errors.append("compiler_bundle:not_bound_to_baseline_commit")
    if compiler_bundle.manifest.get("head_tree_oid") != envelope.get("baseline_tree"):
        errors.append("compiler_bundle:not_bound_to_baseline_tree")
    try:
        known_owners = {
            row["id"]
            for kind in ("components", "exclusions")
            for row in _contract(root).get(kind, [])
            if isinstance(row, Mapping) and isinstance(row.get("id"), str)
        }
        errors.extend(f"allowed_owner_unknown:{owner}" for owner in allowed_owners if owner not in known_owners)
    except ContinuityInputError as exc:
        errors.append(f"ownership_contract:{exc}")
    return {
        "schema_version": "1.0.0",
        "validation_type": "task_envelope",
        "status": "valid" if not errors else "invalid",
        "envelope_digest": digest_object(dict(envelope)),
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "observed_git": None
        if observed is None
        else {
            "baseline_commit": observed["baseline_commit"],
            "baseline_tree": observed["baseline_tree"],
            "head_commit": observed["head_commit"],
            "head_tree": observed["head_tree"],
            "changed_paths": observed["changed_paths"],
            "diff_digest": observed["diff_digest"],
        },
        "protected_actions": sorted(PROTECTED_ACTIONS),
        "side_effects": "none",
    }


def _artifact_errors(repository_root: Path, artifacts: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(artifacts, list):
        return ["artifacts:must_be_list"]
    seen: set[str] = set()
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, Mapping) or set(artifact) != {"path", "sha256"}:
            errors.append(f"artifacts:{index}:invalid_shape")
            continue
        try:
            relative = safe_relative(artifact.get("path"))
        except ContinuityInputError:
            errors.append(f"artifacts:{index}:unsafe_path")
            continue
        if relative in seen:
            errors.append(f"artifacts:{index}:duplicate_path")
        seen.add(relative)
        if _is_restricted(relative):
            errors.append(f"artifacts:{index}:restricted_path")
            continue
        path = repository_root.joinpath(*PurePosixPath(relative).parts)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            errors.append(f"artifacts:{index}:missing")
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            errors.append(f"artifacts:{index}:not_regular")
            continue
        before = path.stat(follow_symlinks=False)
        value = path.read_bytes()
        after = path.stat(follow_symlinks=False)
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            errors.append(f"artifacts:{index}:changed_while_read")
        expected = artifact.get("sha256")
        if not isinstance(expected, str) or expected != sha256_bytes(value):
            errors.append(f"artifacts:{index}:digest_mismatch")
    return errors


def validate_completion_receipt(
    receipt: Mapping[str, Any],
    envelope: Mapping[str, Any],
    repository_root: Path,
    compiler_bundle: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    envelope_errors, warnings, allowed_paths, allowed_owners = _validate_envelope_fields(envelope, moment)
    errors = [f"envelope:{error}" for error in envelope_errors]
    unknown = sorted(set(receipt) - RECEIPT_FIELDS)
    missing = sorted(RECEIPT_FIELDS - set(receipt))
    errors.extend(f"receipt:unknown_field:{field}" for field in unknown)
    errors.extend(f"receipt:missing_field:{field}" for field in missing)
    if receipt.get("schema_version") != "1.0.0":
        errors.append("receipt:schema_version_unsupported")
    if receipt.get("envelope_digest") != digest_object(dict(envelope)):
        errors.append("receipt:envelope_digest_mismatch")
    for field in ("baseline_commit", "baseline_tree"):
        if receipt.get(field) != envelope.get(field):
            errors.append(f"receipt:{field}_mismatch")
    authority = envelope.get("authority")
    expected_actor = authority.get("actor_id") if isinstance(authority, Mapping) else None
    if receipt.get("actor_id") != expected_actor:
        errors.append("receipt:actor_not_authorized")

    root = repository_root.resolve(strict=True)
    observed: dict[str, Any] | None = None
    baseline = envelope.get("baseline_commit")
    if isinstance(baseline, str) and len(baseline) in {40, 64}:
        try:
            observed = observe_git_state(root, baseline)
            errors.extend(observed["errors"])
            exact = {
                "completion_commit": observed["head_commit"],
                "completion_tree": observed["head_tree"],
                "diff_digest": observed["diff_digest"],
                "changed_paths": observed["changed_paths"],
            }
            for field, expected in exact.items():
                if receipt.get(field) != expected:
                    errors.append(f"receipt:{field}_mismatch")
            errors.extend(
                f"changed_path_outside_scope:{path}"
                for path in observed["changed_paths"]
                if not _path_allowed(path, allowed_paths)
            )
            owners, owner_errors = _owners(root, observed["changed_paths"])
            errors.extend(owner_errors)
            if receipt.get("changed_owners") != owners:
                errors.append("receipt:changed_owners_mismatch")
            errors.extend(f"changed_owner_outside_scope:{owner}" for owner in owners if owner not in allowed_owners)
            if compiler_bundle.source_commit != observed["head_commit"]:
                errors.append("compiler_bundle:not_bound_to_completion_commit")
            if compiler_bundle.manifest.get("head_tree_oid") != observed["head_tree"]:
                errors.append("compiler_bundle:not_bound_to_completion_tree")
            clean = observe_git_state(root, observed["head_commit"])
            if clean["changed_paths"]:
                errors.append("completion_worktree:not_clean")
        except ContinuityInputError as exc:
            errors.append(f"git_state:{exc}")

    actions = _string_list(receipt.get("actions_performed"), "actions_performed", errors, nonempty=False)
    allowed_actions = set(envelope.get("allowed_actions") or [])
    errors.extend(f"receipt:action_outside_scope:{action}" for action in actions if action not in allowed_actions)
    errors.extend(f"protected_action_unwaivable:{action}" for action in sorted(set(actions) & PROTECTED_ACTIONS))
    tests = receipt.get("tests")
    required = {
        str(item.get("id")): str(item.get("command"))
        for item in envelope.get("required_tests", [])
        if isinstance(item, Mapping)
    }
    seen_tests: dict[str, Mapping[str, Any]] = {}
    if not isinstance(tests, list):
        errors.append("receipt:tests_must_be_list")
    else:
        for index, test in enumerate(tests):
            if not isinstance(test, Mapping) or set(test) != {"command", "exit_code", "id"}:
                errors.append(f"receipt:tests:{index}:invalid_shape")
                continue
            identifier = test.get("id")
            if not isinstance(identifier, str) or identifier in seen_tests:
                errors.append(f"receipt:tests:{index}:id_invalid_or_duplicate")
                continue
            seen_tests[identifier] = test
        for identifier, command in required.items():
            test = seen_tests.get(identifier)
            if test is None:
                errors.append(f"receipt:required_test_missing:{identifier}")
            elif test.get("command") != command:
                errors.append(f"receipt:required_test_command_mismatch:{identifier}")
            elif test.get("exit_code") != 0:
                errors.append(f"receipt:required_test_failed:{identifier}")
    conflicts = receipt.get("conflicts")
    if not isinstance(conflicts, list) or any(not isinstance(item, str) for item in conflicts):
        errors.append("receipt:conflicts_must_be_string_list")
    elif conflicts:
        errors.append("receipt:unresolved_conflicts")
    external = _string_list(receipt.get("external_actions"), "external_actions", errors, nonempty=False)
    errors.extend(f"protected_action_unwaivable:{action}" for action in sorted(set(external) & PROTECTED_ACTIONS))
    errors.extend(
        f"receipt:external_action_outside_scope:{action}" for action in external if action not in allowed_actions
    )
    exceptions = receipt.get("exceptions")
    if not isinstance(exceptions, list):
        errors.append("receipt:exceptions_must_be_list")
    else:
        for index, exception in enumerate(exceptions):
            if not isinstance(exception, Mapping) or set(exception) != {"action", "expires_at", "reason"}:
                errors.append(f"receipt:exceptions:{index}:invalid_shape")
                continue
            action = exception.get("action")
            if action in PROTECTED_ACTIONS:
                errors.append(f"protected_action_exception_forbidden:{action}")
            if action not in allowed_actions:
                errors.append(f"receipt:exceptions:{index}:action_outside_scope")
            expiry = _utc(exception.get("expires_at"), f"receipt:exceptions:{index}:expires_at", errors)
            if expiry is not None and expiry <= moment:
                errors.append(f"receipt:exceptions:{index}:expired")
            if not isinstance(exception.get("reason"), str) or not exception["reason"].strip():
                errors.append(f"receipt:exceptions:{index}:reason_invalid")
    errors.extend(_artifact_errors(root, receipt.get("artifacts")))
    return {
        "schema_version": "1.0.0",
        "validation_type": "completion_receipt",
        "status": "valid" if not errors else "invalid",
        "receipt_digest": digest_object(dict(receipt)),
        "envelope_digest": digest_object(dict(envelope)),
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "observed_git": None
        if observed is None
        else {
            "baseline_commit": observed["baseline_commit"],
            "baseline_tree": observed["baseline_tree"],
            "completion_commit": observed["head_commit"],
            "completion_tree": observed["head_tree"],
            "changed_paths": observed["changed_paths"],
            "diff_digest": observed["diff_digest"],
        },
        "protected_actions": sorted(PROTECTED_ACTIONS),
        "side_effects": "none",
    }
