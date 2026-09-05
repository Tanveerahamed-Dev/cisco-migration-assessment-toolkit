"""Run Graphify 0.9.51 with three reviewed producer corrections in memory.

Graphifyy 0.9.51's JSON extractor emits ``extends`` edges for every array-valued
property.  Its report summary also counts structural-only communities as shown,
although its navigation and sections exclude them.  Its incremental rebuild also
ignores ``built_at_commit`` when comparing unchanged topology, so a merge commit
with the same tree as its PR head cannot acquire an exact current-commit stamp.  This launcher
accepts only the reviewed upstream extractor, reporter, and rebuild bytes, applies
those three bounded producer corrections in memory, verifies every result, and rebinds the
live 0.9.51 aliases before Graphify's CLI is entered.
Because parallel AST workers reload the on-disk module, the launcher also owns
``GRAPHIFY_MAX_WORKERS=1`` and rejects command-line worker overrides.

This is deliberately a narrow compatibility guard, not verification of the full
Graphify wheel or its transitive dependencies.  The installed package is never
modified.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import inspect
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

GUARD_CONTRACT = "graphify-producer-overlays/5"
DIST_NAME = "graphifyy"
EXPECTED_VERSION = "0.9.51"
EXTRACTOR_MODULE = "graphify.extractors.json_config"
EXTRACTOR_RELATIVE_PATH = "graphify/extractors/json_config.py"
EXPECTED_SOURCE_BYTES = 9_723
EXPECTED_SOURCE_SHA256 = "d15ea6d9b48cc71e73615c44c72808562ad4a1dbc82d5a340e3ad0c2fb4fc945"
EXPECTED_PATCHED_BYTES = 9_744
EXPECTED_PATCHED_SHA256 = "cb6b660bd2dee3f58e9007d0eac27883cd3bb3fe5d8136c13e8d83b92b90e011"
REPORT_MODULE = "graphify.report"
REPORT_RELATIVE_PATH = "graphify/report.py"
EXPECTED_REPORT_SOURCE_BYTES = 14_395
EXPECTED_REPORT_SOURCE_SHA256 = "382d844327181b652bbcd3ebd9cc3f2ab63bbce30e6eb5da80ced2b1575d1d0a"
EXPECTED_REPORT_PATCHED_BYTES = 14_393
EXPECTED_REPORT_PATCHED_SHA256 = "b6855a4111f7aec351022fc0d7ed96359216eb3b48c307ea025b8b41ef600bb9"
WATCH_MODULE = "graphify.watch"
WATCH_RELATIVE_PATH = "graphify/watch.py"
EXPECTED_WATCH_SOURCE_BYTES = 95_869
EXPECTED_WATCH_SOURCE_SHA256 = "664547629cb659f3b0fa7209f8461acfd1b96985caf87944591dadb0c9f0e93d"
EXPECTED_REBUILD_SOURCE_BYTES = 42_104
EXPECTED_REBUILD_SOURCE_SHA256 = "4c1283138dfb003bf7cd768c2ba6fb94d2ae6869d0d8b4ac42cc54253163be18"
EXPECTED_REBUILD_PATCHED_BYTES = 43_131
EXPECTED_REBUILD_PATCHED_SHA256 = "87aa8d48e1b4f5c45ab9e779688bd280a752609983262fc3502db8a8ce76cb75"
WORKER_ENV = "GRAPHIFY_MAX_WORKERS"
GUARDED_MAX_WORKERS = "1"
REFRESH_RECEIPT_CONTRACT = "atlas-graphify-refresh/2"
REFRESH_RECEIPT_PATH = Path("graphify-out/.guarded_refresh.json")
_ACTIVE_GUARD_RECEIPT: dict[str, Any] | None = None

_SOURCE_SENTINEL = b'            elif val.type == "array":'
_PATCHED_SENTINEL = b'            elif val.type == "array" and key == "extends":'
_REPORT_SOURCE_SENTINEL = b"    shown_count = len(communities) - thin_count_summary"
_REPORT_PATCHED_SENTINEL = b"    shown_count = len(non_empty) - thin_count_summary"
_REBUILD_COMMIT_SOURCE_SENTINEL = (
    b"        commit = _git_head(cwd=watch_root)\n"
    b"        result = extract(\n"
)
_REBUILD_COMMIT_PATCHED_SENTINEL = (
    b"        commit = _git_head(cwd=watch_root)\n"
    b'        if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is None:\n'
    b'            print("[graphify watch] Rebuild failed: current Git HEAD is unavailable or malformed.", file=sys.stderr)\n'
    b"            return False\n"
    b"        result = extract(\n"
)
_REBUILD_TOPOLOGY_SOURCE_SENTINEL = (
    b"        candidate_topology = _topology_from_graph(G)\n"
    b"        if existing_graph_data:\n"
)
_REBUILD_TOPOLOGY_PATCHED_SENTINEL = (
    b"        candidate_topology = _topology_from_graph(G)\n"
    b"        commit_only_refresh = False\n"
    b"        if existing_graph_data:\n"
)
_REBUILD_FAST_SOURCE_SENTINEL = b"            if same_topology:\n"
_REBUILD_FAST_PATCHED_SENTINEL = (
    b"            commit_only_refresh = (\n"
    b"                same_topology\n"
    b'                and existing_graph_data.get("built_at_commit") != commit\n'
    b"            )\n"
    b"            if (\n"
    b"                same_topology\n"
    b"                and not commit_only_refresh\n"
    b"                and _guard_fast_noop_ready(out, commit)\n"
    b"            ):\n"
)
_REBUILD_FINAL_SOURCE_SENTINEL = b"        no_change = same_graph and same_report\n"
_REBUILD_FINAL_PATCHED_SENTINEL = (
    b"        if commit_only_refresh and not (same_graph and same_report):\n"
    b"            graph_tmp.unlink(missing_ok=True)\n"
    b"            print(\n"
    b'                "[graphify watch] Commit-field refresh refused because graph/report bytes beyond their commit fields changed.",\n'
    b"                file=sys.stderr,\n"
    b"            )\n"
    b"            return False\n"
    b"        no_change = (\n"
    b"            same_graph\n"
    b"            and same_report\n"
    b"            and not commit_only_refresh\n"
    b"            and _guard_fast_noop_ready(out, commit)\n"
    b"        )\n"
)
_MAX_REVIEWED_SOURCE_BYTES = 131_072
_MAX_GRAPH_BYTES = 512 * 1024 * 1024
_MAX_REPORT_BYTES = 16 * 1024 * 1024
_MAX_GIT_OUTPUT_BYTES = 8 * 1024 * 1024
_GRAPH_COMMIT_LINE = re.compile(
    rb'(?m)^  "built_at_commit": "([0-9a-f]{40}|[0-9a-f]{64})"\r?$'
)
_REPORT_COMMIT_LINE = re.compile(
    rb"(?m)^- Built from commit: `([0-9a-f]{8})`\r?$"
)

_ERROR_MESSAGES = {
    "G001": "graphifyy distribution metadata is unavailable",
    "G002": "graphifyy version is not the reviewed 0.9.51 release",
    "G003": "a reviewed Graphify source path is unavailable or ambiguous",
    "G004": "the Graphify bytes do not match the reviewed 0.9.51 sources",
    "G005": "an in-memory correction does not match the reviewed result",
    "G006": "an imported Graphify path or alias topology is unexpected",
    "G007": "an in-memory Graphify overlay could not be installed",
    "G008": "the guard failed unexpectedly",
    "G009": "--probe does not accept additional arguments",
    "G010": "the guard owns single-process AST extraction; --max-workers is not accepted",
    "G011": "only update, watch, and code-only extract are guarded producer commands",
    "G012": "extract requires an explicit local path and --code-only",
    "G013": "the guarded producer command contains an unsupported option or argument",
    "G014": "the guard requires Python 3.12+, isolated mode, and bytecode writes disabled (-I -B)",
    "G015": "the effective producer root must be local, whole-repository, and not a linked worktree",
    "G016": "update and watch require an established graph.json in the canonical checkout",
    "G017": "the guarded refresh receipt request is invalid or unavailable",
    "G018": "another guarded Graphify producer already owns this output root",
    "G019": "the tree-equivalent Graphify commit-field rebind was refused",
}

_JSON_SUFFIX_VARIANTS = frozenset(
    "." + "".join(char.upper() if mask & (1 << index) else char for index, char in enumerate("json"))
    for mask in range(1 << len("json"))
)


class GuardFailure(RuntimeError):
    """A bounded, user-safe guard failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _native_long_path(path: Path) -> str:
    """Use extended-length spelling for deep generated output on Windows."""

    value = str(path)
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def _read_stable_source(path: Path) -> bytes:
    """Read one small regular file without a stat/read race."""

    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise GuardFailure("G003")
            payload = handle.read(_MAX_REVIEWED_SOURCE_BYTES + 1)
            after = os.fstat(handle.fileno())
    except GuardFailure:
        raise
    except (OSError, ValueError) as exc:
        raise GuardFailure("G003") from exc

    if (
        len(payload) > _MAX_REVIEWED_SOURCE_BYTES
        or len(payload) != after.st_size
        or _stat_identity(before) != _stat_identity(after)
    ):
        raise GuardFailure("G004")
    return payload


def _locate_reviewed_source(distribution: Any, relative_path: str) -> Path:
    try:
        version = distribution.version
    except Exception as exc:  # metadata providers are external to this repository
        raise GuardFailure("G001") from exc
    if version != EXPECTED_VERSION:
        raise GuardFailure("G002")

    try:
        files = distribution.files
        matches = [
            item
            for item in (files or ())
            if str(item).replace("\\", "/") == relative_path
        ]
        if len(matches) != 1:
            raise GuardFailure("G003")
        path = Path(distribution.locate_file(matches[0])).resolve(strict=True)
    except GuardFailure:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise GuardFailure("G003") from exc
    return path


def _locate_extractor(distribution: Any) -> Path:
    return _locate_reviewed_source(distribution, EXTRACTOR_RELATIVE_PATH)


def _locate_report(distribution: Any) -> Path:
    return _locate_reviewed_source(distribution, REPORT_RELATIVE_PATH)


def _locate_watch(distribution: Any) -> Path:
    return _locate_reviewed_source(distribution, WATCH_RELATIVE_PATH)


def _verified_patch(source: bytes) -> bytes:
    if (
        len(source) != EXPECTED_SOURCE_BYTES
        or _sha256(source) != EXPECTED_SOURCE_SHA256
        or source.count(_SOURCE_SENTINEL) != 1
        or source.count(_PATCHED_SENTINEL) != 0
    ):
        raise GuardFailure("G004")

    patched = source.replace(_SOURCE_SENTINEL, _PATCHED_SENTINEL, 1)
    if (
        len(patched) != EXPECTED_PATCHED_BYTES
        or _sha256(patched) != EXPECTED_PATCHED_SHA256
        or patched.count(_SOURCE_SENTINEL) != 0
        or patched.count(_PATCHED_SENTINEL) != 1
    ):
        raise GuardFailure("G005")
    return patched


def _verified_report_patch(source: bytes) -> bytes:
    if (
        len(source) != EXPECTED_REPORT_SOURCE_BYTES
        or _sha256(source) != EXPECTED_REPORT_SOURCE_SHA256
        or source.count(_REPORT_SOURCE_SENTINEL) != 1
        or source.count(_REPORT_PATCHED_SENTINEL) != 0
    ):
        raise GuardFailure("G004")

    patched = source.replace(_REPORT_SOURCE_SENTINEL, _REPORT_PATCHED_SENTINEL, 1)
    if (
        len(patched) != EXPECTED_REPORT_PATCHED_BYTES
        or _sha256(patched) != EXPECTED_REPORT_PATCHED_SHA256
        or patched.count(_REPORT_SOURCE_SENTINEL) != 0
        or patched.count(_REPORT_PATCHED_SENTINEL) != 1
    ):
        raise GuardFailure("G005")
    return patched


def _verified_rebuild_patch(source: bytes) -> bytes:
    if (
        len(source) != EXPECTED_REBUILD_SOURCE_BYTES
        or _sha256(source) != EXPECTED_REBUILD_SOURCE_SHA256
        or source.count(_REBUILD_COMMIT_SOURCE_SENTINEL) != 1
        or source.count(_REBUILD_COMMIT_PATCHED_SENTINEL) != 0
        or source.count(_REBUILD_TOPOLOGY_SOURCE_SENTINEL) != 1
        or source.count(_REBUILD_TOPOLOGY_PATCHED_SENTINEL) != 0
        or source.count(_REBUILD_FAST_SOURCE_SENTINEL) != 1
        or source.count(_REBUILD_FAST_PATCHED_SENTINEL) != 0
        or source.count(_REBUILD_FINAL_SOURCE_SENTINEL) != 1
        or source.count(_REBUILD_FINAL_PATCHED_SENTINEL) != 0
    ):
        raise GuardFailure("G004")

    patched = source.replace(
        _REBUILD_COMMIT_SOURCE_SENTINEL,
        _REBUILD_COMMIT_PATCHED_SENTINEL,
        1,
    )
    patched = patched.replace(
        _REBUILD_TOPOLOGY_SOURCE_SENTINEL,
        _REBUILD_TOPOLOGY_PATCHED_SENTINEL,
        1,
    )
    patched = patched.replace(
        _REBUILD_FAST_SOURCE_SENTINEL,
        _REBUILD_FAST_PATCHED_SENTINEL,
        1,
    )
    patched = patched.replace(
        _REBUILD_FINAL_SOURCE_SENTINEL,
        _REBUILD_FINAL_PATCHED_SENTINEL,
        1,
    )
    if (
        len(patched) != EXPECTED_REBUILD_PATCHED_BYTES
        or _sha256(patched) != EXPECTED_REBUILD_PATCHED_SHA256
        or patched.count(_REBUILD_COMMIT_SOURCE_SENTINEL) != 0
        or patched.count(_REBUILD_COMMIT_PATCHED_SENTINEL) != 1
        or patched.count(_REBUILD_TOPOLOGY_SOURCE_SENTINEL) != 0
        or patched.count(_REBUILD_TOPOLOGY_PATCHED_SENTINEL) != 1
        or patched.count(_REBUILD_FAST_SOURCE_SENTINEL) != 0
        or patched.count(_REBUILD_FAST_PATCHED_SENTINEL) != 1
        or patched.count(_REBUILD_FINAL_SOURCE_SENTINEL) != 0
        or patched.count(_REBUILD_FINAL_PATCHED_SENTINEL) != 1
    ):
        raise GuardFailure("G005")
    return patched


def _module_file(module: types.ModuleType) -> Path:
    try:
        return Path(module.__file__).resolve(strict=True)  # type: ignore[arg-type]
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise GuardFailure("G006") from exc


def _prepare_overlay(
    *,
    distribution_getter: Callable[[str], Any] | None = None,
    module_importer: Callable[[str], types.ModuleType] | None = None,
) -> dict[str, Any]:
    """Verify the installed source and install the corrected module in this process."""

    get_distribution = distribution_getter or importlib.metadata.distribution
    import_module = module_importer or importlib.import_module
    try:
        distribution = get_distribution(DIST_NAME)
    except importlib.metadata.PackageNotFoundError as exc:
        raise GuardFailure("G001") from exc
    except Exception as exc:  # keep probe output fixed and bounded
        raise GuardFailure("G001") from exc

    source_path = _locate_extractor(distribution)
    report_source_path = _locate_report(distribution)
    watch_source_path = _locate_watch(distribution)
    source = _read_stable_source(source_path)
    report_source = _read_stable_source(report_source_path)
    watch_source = _read_stable_source(watch_source_path)
    if (
        len(watch_source) != EXPECTED_WATCH_SOURCE_BYTES
        or _sha256(watch_source) != EXPECTED_WATCH_SOURCE_SHA256
    ):
        raise GuardFailure("G004")
    patched = _verified_patch(source)
    report_patched = _verified_report_patch(report_source)

    try:
        original_module = import_module(EXTRACTOR_MODULE)
        extractors_package = import_module("graphify.extractors")
        models_module = import_module("graphify.extractors.models")
        extract_facade = import_module("graphify.extract")
        graphify_package = import_module("graphify")
        original_report_module = import_module(REPORT_MODULE)
        original_watch_module = import_module(WATCH_MODULE)
    except Exception as exc:
        raise GuardFailure("G006") from exc

    # Imports may have read the installed module. Recheck the same file before
    # any alias is changed or the Graphify CLI is allowed to run.
    if (
        _module_file(original_module) != source_path
        or _read_stable_source(source_path) != source
        or _module_file(original_report_module) != report_source_path
        or _read_stable_source(report_source_path) != report_source
        or _module_file(original_watch_module) != watch_source_path
        or _read_stable_source(watch_source_path) != watch_source
    ):
        raise GuardFailure("G006")

    original_extract_json = getattr(original_module, "extract_json", None)
    dispatch = getattr(extract_facade, "_DISPATCH", None)
    language_extractors = getattr(extractors_package, "LANGUAGE_EXTRACTORS", None)
    cache_bypass_suffixes = getattr(extract_facade, "_JS_CACHE_BYPASS_SUFFIXES", None)
    original_generate = getattr(original_report_module, "generate", None)
    original_rebuild_code = getattr(original_watch_module, "_rebuild_code", None)
    if (
        not callable(original_extract_json)
        or getattr(extractors_package, "json_config", None) is not original_module
        or getattr(extractors_package, "extract_json", None) is not original_extract_json
        or not isinstance(language_extractors, dict)
        or language_extractors.get("json") is not original_extract_json
        or getattr(extract_facade, "extract_json", None) is not original_extract_json
        or not isinstance(dispatch, dict)
        or dispatch.get(".json") is not original_extract_json
        or not isinstance(cache_bypass_suffixes, set)
        or getattr(models_module, "_JS_CACHE_BYPASS_SUFFIXES", None) is not cache_bypass_suffixes
        or getattr(graphify_package, "report", None) is not original_report_module
        or not callable(original_generate)
        or not callable(original_rebuild_code)
    ):
        raise GuardFailure("G006")

    overlay = types.ModuleType(EXTRACTOR_MODULE)
    overlay.__file__ = str(source_path)
    overlay.__package__ = "graphify.extractors"
    overlay.__loader__ = None
    overlay.__spec__ = importlib.util.spec_from_loader(
        EXTRACTOR_MODULE, loader=None, origin=str(source_path)
    )
    try:
        code = compile(patched.decode("utf-8", errors="strict"), str(source_path), "exec")
        exec(code, overlay.__dict__)
        corrected_extract_json = overlay.extract_json
    except Exception as exc:
        raise GuardFailure("G007") from exc
    if not callable(corrected_extract_json):
        raise GuardFailure("G007")

    report_overlay = types.ModuleType(REPORT_MODULE)
    report_overlay.__file__ = str(report_source_path)
    report_overlay.__package__ = "graphify"
    report_overlay.__loader__ = None
    report_overlay.__spec__ = importlib.util.spec_from_loader(
        REPORT_MODULE, loader=None, origin=str(report_source_path)
    )
    try:
        report_code = compile(
            report_patched.decode("utf-8", errors="strict"),
            str(report_source_path),
            "exec",
        )
        exec(report_code, report_overlay.__dict__)
        corrected_generate = report_overlay.generate
    except Exception as exc:
        raise GuardFailure("G007") from exc
    if not callable(corrected_generate):
        raise GuardFailure("G007")

    try:
        rebuild_source = inspect.getsource(original_rebuild_code).encode("utf-8")
        original_rebuild_signature = inspect.signature(original_rebuild_code)
    except (OSError, TypeError) as exc:
        raise GuardFailure("G006") from exc
    rebuild_patched = _verified_rebuild_patch(rebuild_source)
    try:
        rebuild_code = compile(
            rebuild_patched.decode("utf-8", errors="strict"),
            str(watch_source_path),
            "exec",
        )
        exec(rebuild_code, original_watch_module.__dict__)
        original_watch_module._guard_fast_noop_ready = _fast_noop_ready
        corrected_rebuild_code = original_watch_module._rebuild_code
        corrected_rebuild_signature = inspect.signature(corrected_rebuild_code)
    except Exception as exc:
        raise GuardFailure("G007") from exc
    if (
        not callable(corrected_rebuild_code)
        or corrected_rebuild_code is original_rebuild_code
        or corrected_rebuild_signature != original_rebuild_signature
    ):
        raise GuardFailure("G007")

    # Rebind every public/live 0.9.51 function alias. The dispatcher mapping is
    # the extraction owner; the others keep direct imports coherent.
    sys.modules[EXTRACTOR_MODULE] = overlay
    extractors_package.json_config = overlay
    extractors_package.extract_json = corrected_extract_json
    language_extractors["json"] = corrected_extract_json
    extract_facade.extract_json = corrected_extract_json
    dispatch[".json"] = corrected_extract_json
    original_report_module.generate = corrected_generate

    # 0.9.51's AST cache namespace identifies only the package version/schema,
    # not these corrected extractor bytes. Never read or write ambiguous JSON
    # entries; preserve them on disk for reversibility and re-extract JSON here.
    # Dispatch case-folds suffixes, while the cache bypass in 0.9.51 compares
    # the raw suffix. Cover all ASCII case variants so FOO.JSON cannot replay
    # an ambiguous entry that foo.json would bypass.
    cache_bypass_suffixes.update(_JSON_SUFFIX_VARIANTS)

    if not (
        sys.modules.get(EXTRACTOR_MODULE) is overlay
        and extractors_package.json_config is overlay
        and extractors_package.extract_json is corrected_extract_json
        and language_extractors.get("json") is corrected_extract_json
        and extract_facade.extract_json is corrected_extract_json
        and dispatch.get(".json") is corrected_extract_json
        and _JSON_SUFFIX_VARIANTS.issubset(cache_bypass_suffixes)
        and getattr(models_module, "_JS_CACHE_BYPASS_SUFFIXES", None) is cache_bypass_suffixes
        and original_report_module.generate is corrected_generate
        and original_watch_module._rebuild_code is corrected_rebuild_code
        and getattr(original_watch_module, "_guard_fast_noop_ready", None)
        is _fast_noop_ready
    ):
        raise GuardFailure("G007")

    return {
        "aliases": 5,
        "ast_cache": "bypass-json-casefold",
        "contract": GUARD_CONTRACT,
        "extractor": EXTRACTOR_RELATIVE_PATH,
        "max_workers": int(GUARDED_MAX_WORKERS),
        "patched_sha256": EXPECTED_PATCHED_SHA256,
        "report": REPORT_RELATIVE_PATH,
        "report_aliases": 1,
        "report_patched_sha256": EXPECTED_REPORT_PATCHED_SHA256,
        "report_source_sha256": EXPECTED_REPORT_SOURCE_SHA256,
        "rebuild_commit_policy": "rewrite_only_when_head_differs_and_non_commit_graph_report_match",
        "rebuild_fast_noop_policy": "current_complete_receipt_exact_graph_report",
        "rebuild_patched_sha256": EXPECTED_REBUILD_PATCHED_SHA256,
        "rebuild_source_sha256": EXPECTED_REBUILD_SOURCE_SHA256,
        "source_sha256": EXPECTED_SOURCE_SHA256,
        "status": "pass",
        "tree_equivalent_rebind_policy": "prior_receipted_ancestor_equal_tree_commit_fields_only",
        "version": EXPECTED_VERSION,
        "watch": WATCH_RELATIVE_PATH,
        "watch_aliases": 1,
        "watch_source_sha256": EXPECTED_WATCH_SOURCE_SHA256,
    }


def _run_graphify(arguments: Sequence[str]) -> int:
    try:
        graphify_main = importlib.import_module("graphify.__main__").main
    except Exception as exc:
        raise GuardFailure("G006") from exc

    previous_argv = sys.argv
    sys.argv = ["graphify", *arguments]
    try:
        result = graphify_main()
    finally:
        sys.argv = previous_argv
    return result if isinstance(result, int) else 0


def _print_failure(failure: GuardFailure) -> None:
    message = _ERROR_MESSAGES.get(failure.code, _ERROR_MESSAGES["G008"])
    print(
        f"graphify-guard: {failure.code}: {message}; no Graphify command was run.",
        file=sys.stderr,
    )


def _invocation_isolated() -> bool:
    """Attest the process boundary used to exclude repo/user-site shadowing."""

    return bool(
        sys.version_info >= (3, 12)
        and hasattr(Path, "is_junction")
        and sys.flags.isolated
        and sys.dont_write_bytecode
    )


@contextmanager
def _controlled_environment(root: Path | None = None):
    """Neutralize ambient controls and repo-local executable lookup."""

    prefixes = ("GRAPHIFY_", "GIT_")
    inherited = {
        key: value for key, value in os.environ.items() if key.startswith(prefixes)
    }
    inherited_path = os.environ.get("PATH")
    inherited_no_current = os.environ.get("NoDefaultCurrentDirectoryInExePath")
    excluded_roots = {Path.cwd().resolve(strict=True)}
    if root is not None:
        excluded_roots.add(root)
    for key in inherited:
        os.environ.pop(key, None)
    os.environ[WORKER_ENV] = GUARDED_MAX_WORKERS
    os.environ["GIT_NO_REPLACE_OBJECTS"] = "1"
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    sanitized_path = []
    for entry in (inherited_path or "").split(os.pathsep):
        if not entry:
            continue
        candidate = Path(entry)
        if not candidate.is_absolute():
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if any(resolved == excluded or excluded in resolved.parents for excluded in excluded_roots):
            continue
        sanitized_path.append(str(resolved))
    os.environ["PATH"] = os.pathsep.join(sanitized_path)
    if os.name == "nt":
        os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"
    try:
        yield
    finally:
        # Also remove controls the upstream CLI may have added during this run.
        for key in tuple(os.environ):
            if key.startswith(prefixes):
                os.environ.pop(key, None)
        os.environ.update(inherited)
        if inherited_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = inherited_path
        if inherited_no_current is None:
            os.environ.pop("NoDefaultCurrentDirectoryInExePath", None)
        else:
            os.environ["NoDefaultCurrentDirectoryInExePath"] = inherited_no_current


def _is_local_path(argument: str) -> bool:
    """Reject URL/UNC-shaped producer roots; drive and relative paths stay valid."""

    return bool(argument) and "://" not in argument and not argument.startswith(("//", "\\\\"))


def _producer_root(arguments: Sequence[str]) -> Path:
    if arguments[0] == "update":
        value = next(argument for argument in arguments[1:] if not argument.startswith("-"))
    else:
        value = arguments[1]
    try:
        root = Path(value).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise GuardFailure("G015") from exc
    if not root.is_dir() or str(root).replace("\\", "/").startswith("//"):
        raise GuardFailure("G015")
    # Default output must remain under the same effective local root. Resolve
    # existing symlinks/junctions; reject even a broken symlink explicitly.
    output = root / "graphify-out"
    if output.is_symlink() or output.is_junction():
        raise GuardFailure("G015")
    if output.exists():
        try:
            resolved_output = output.resolve(strict=True)
            resolved_output.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise GuardFailure("G015") from exc
        if str(resolved_output).replace("\\", "/").startswith("//"):
            raise GuardFailure("G015")
        stack = [output]
        while stack:
            directory = stack.pop()
            try:
                entries = tuple(os.scandir(_native_long_path(directory)))
            except OSError as exc:
                raise GuardFailure("G015") from exc
            for entry in entries:
                child = Path(entry.path)
                if child.is_symlink() or child.is_junction():
                    raise GuardFailure("G015")
                try:
                    # DirEntry's cached Windows stat can report st_nlink=0 for
                    # ordinary files; a fresh path stat reports the real count.
                    info = os.stat(_native_long_path(child), follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                        raise GuardFailure("G015")
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(child)
                except OSError as exc:
                    raise GuardFailure("G015") from exc
    if arguments[0] in {"update", "watch"} and not (
        output / "graph.json"
    ).is_file():
        raise GuardFailure("G016")

    # Standard Git main checkouts own a .git directory at the exact producer
    # root. A linked worktree owns a .git file; a nested root finds an ancestor
    # marker. Avoid launching Git here: on Windows, CreateProcess can resolve a
    # repo-local git.exe ahead of the trusted installation.
    marker = root / ".git"
    if marker.is_symlink() or marker.is_junction() or marker.is_file():
        raise GuardFailure("G015")
    commondir = marker / "commondir"
    if marker.is_dir() and (
        commondir.exists() or commondir.is_symlink() or commondir.is_junction()
    ):
        raise GuardFailure("G015")
    if not marker.is_dir() and any((parent / ".git").exists() for parent in root.parents):
        raise GuardFailure("G015")
    grafts = marker / "info" / "grafts"
    if grafts.exists() or grafts.is_symlink() or grafts.is_junction():
        raise GuardFailure("G015")
    return root


@contextmanager
def _producer_lock(root: Path):
    """Hold one OS-backed nonblocking lock for every producer touching this root."""

    output = root / "graphify-out"
    lock_path = output / ".guarded_producer.lock"
    try:
        output.mkdir(exist_ok=True)
        if output.is_symlink() or output.is_junction() or output.resolve(strict=True) != output:
            raise GuardFailure("G015")
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
    except GuardFailure:
        raise
    except OSError as exc:
        raise GuardFailure("G018") from exc

    locked = False
    try:
        opened = os.fstat(descriptor)
        named = os.stat(lock_path, follow_symlinks=False)
        if (
            lock_path.is_symlink()
            or lock_path.is_junction()
            or not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            or opened.st_nlink != 1
        ):
            raise GuardFailure("G015")
        if opened.st_size < 1:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
    except GuardFailure:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise GuardFailure("G018") from exc

    try:
        yield
    finally:
        if locked:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(descriptor)
        except OSError:
            pass


def _canonical_arguments(arguments: Sequence[str], root: Path) -> list[str]:
    """Pass Graphify the same canonical root that the guard actually checked."""

    canonical = list(arguments)
    if canonical[0] == "update":
        index = next(
            index for index, argument in enumerate(canonical[1:], start=1)
            if not argument.startswith("-")
        )
    else:
        index = 1
    canonical[index] = str(root)
    return canonical


def _attested_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    attested = dict(receipt)
    attested["bytecode_writes"] = "disabled"
    attested["environment"] = "graphify-git-path-sanitized"
    attested["git_replace_objects"] = "disabled"
    attested["git_optional_locks"] = "disabled"
    attested["isolated"] = True
    attested["python"] = ".".join(str(part) for part in sys.version_info[:3])
    return attested


def _refresh_receipt_path(argument: str) -> Path:
    try:
        root = Path.cwd().resolve(strict=True)
        expected = root / REFRESH_RECEIPT_PATH
        candidate = Path(os.path.abspath(argument))
        if os.path.normcase(str(candidate)) != os.path.normcase(str(expected)):
            raise GuardFailure("G017")
        parent = candidate.parent
        if (
            not parent.is_dir()
            or parent.is_symlink()
            or parent.is_junction()
            or parent.resolve(strict=True) != expected.parent
            or candidate.is_symlink()
        ):
            raise GuardFailure("G017")
    except GuardFailure:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise GuardFailure("G017") from exc
    return candidate


def _valid_head(head: Any) -> bool:
    return isinstance(head, str) and len(head) in {40, 64} and head == head.lower() and all(
        character in "0123456789abcdef" for character in head
    )


def _git_output(
    root: Path, *arguments: str, stdin_payload: bytes | None = None
) -> bytes:
    try:
        if stdin_payload is not None and len(stdin_payload) > _MAX_GIT_OUTPUT_BYTES:
            raise GuardFailure("G017")
        root = root.resolve(strict=True)
        git_marker = root / ".git"
        git_dir = git_marker.resolve(strict=True)
        if (
            not git_dir.is_dir()
            or git_marker.is_symlink()
            or git_marker.is_junction()
            or os.path.normcase(str(git_dir))
            != os.path.normcase(str(git_marker))
        ):
            raise GuardFailure("G017")
        commondir = git_marker / "commondir"
        if commondir.exists() or commondir.is_symlink() or commondir.is_junction():
            raise GuardFailure("G017")
        executable_name = shutil.which("git")
        if not executable_name:
            raise GuardFailure("G017")
        executable = Path(executable_name).resolve(strict=True)
        if (
            not executable.is_file()
            or executable.is_symlink()
            or executable.is_junction()
            or executable == root
            or root in executable.parents
        ):
            raise GuardFailure("G017")
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        environment["GIT_NO_REPLACE_OBJECTS"] = "1"
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        config_arguments = (
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
        )
        completed = subprocess.run(
            [
                str(executable),
                f"--git-dir={git_dir}",
                f"--work-tree={root}",
                *config_arguments,
                *arguments,
            ],
            cwd=root,
            stdin=subprocess.DEVNULL if stdin_payload is None else None,
            input=stdin_payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            check=False,
            timeout=15,
        )
    except GuardFailure:
        raise
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise GuardFailure("G017") from exc
    if (
        completed.returncode != 0
        or len(completed.stdout) > _MAX_GIT_OUTPUT_BYTES
        or len(completed.stderr) > _MAX_GIT_OUTPUT_BYTES
    ):
        raise GuardFailure("G017")
    return completed.stdout


def _current_git_snapshot(root: Path) -> tuple[str, str, str]:
    try:
        top_level = _git_output(root, "rev-parse", "--show-toplevel").decode(
            "utf-8", errors="strict"
        ).strip()
        absolute_git_dir = _git_output(
            root, "rev-parse", "--absolute-git-dir"
        ).decode("utf-8", errors="strict").strip()
        expected_root = root.resolve(strict=True)
        expected_git_dir = expected_root / ".git"
        if (
            Path(top_level).resolve(strict=True) != expected_root
            or Path(absolute_git_dir).resolve(strict=True) != expected_git_dir
        ):
            raise GuardFailure("G017")
        head = _git_output(root, "rev-parse", "--verify", "HEAD").decode(
            "ascii", errors="strict"
        ).strip()
    except GuardFailure:
        raise
    except (OSError, RuntimeError, UnicodeDecodeError, ValueError) as exc:
        raise GuardFailure("G017") from exc
    if not _valid_head(head):
        raise GuardFailure("G017")
    hidden_index_state = False
    for option in ("-t", "-v"):
        tagged = _git_output(root, "ls-files", option, "-z")
        records = tagged.split(b"\0")
        if records[-1:] != [b""]:
            raise GuardFailure("G017")
        for record in records[:-1]:
            if len(record) < 3 or record[1:2] != b" ":
                raise GuardFailure("G017")
            if record[:1] != b"H":
                hidden_index_state = True
    if hidden_index_state:
        raise GuardFailure("G017")
    tracked_paths, index_unsafe = _tracked_index_scope(root)
    if index_unsafe or _tracked_paths_have_active_filters(root, tracked_paths):
        raise GuardFailure("G017")
    status = _git_output(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    return head, "dirty" if status else "clean", _sha256(status)


def _current_git_identity(root: Path) -> tuple[str, str]:
    head, state, _status_digest = _current_git_snapshot(root)
    return head, state


def _tracked_index_scope(root: Path) -> tuple[bytes, bool]:
    rows = _git_output(root, "ls-files", "--stage", "-z").split(b"\0")
    if rows[-1:] != [b""]:
        raise GuardFailure("G017")
    paths: list[bytes] = []
    unsafe = False
    for row in rows[:-1]:
        try:
            header, path = row.split(b"\t", 1)
            mode, oid, stage = header.split(b" ")
            oid_text = oid.decode("ascii", errors="strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise GuardFailure("G017") from exc
        if (
            not path
            or len(mode) != 6
            or any(character not in b"01234567" for character in mode)
            or not _valid_head(oid_text)
            or stage != b"0"
        ):
            raise GuardFailure("G017")
        unsafe = unsafe or mode == b"160000"
        paths.append(path)
    return b"\0".join(paths) + (b"\0" if paths else b""), unsafe


def _tracked_paths_have_active_filters(root: Path, paths: bytes) -> bool:
    for cached in (False, True):
        arguments = ["check-attr", "-z"]
        if cached:
            arguments.append("--cached")
        arguments.extend(("--stdin", "filter"))
        payload = _git_output(root, *arguments, stdin_payload=paths)
        fields = payload.split(b"\0")
        if fields[-1:] != [b""] or (len(fields) - 1) % 3:
            raise GuardFailure("G017")
        for index in range(0, len(fields) - 1, 3):
            path, attribute, value = fields[index : index + 3]
            if not path or attribute != b"filter":
                raise GuardFailure("G017")
            if value not in {b"unspecified", b"unset"}:
                return True
    return False


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise ValueError("duplicate or invalid JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _refresh_receipt_payload(
    *,
    phase: str,
    head: str,
    state: str,
    guard_receipt: dict[str, Any],
    receipt_path: Path,
    prior: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    if phase not in {"pending", "complete"} or state not in {"clean", "dirty"}:
        raise GuardFailure("G017")
    if not _valid_head(head):
        raise GuardFailure("G017")
    payload: dict[str, Any] = {
        "contract": REFRESH_RECEIPT_CONTRACT,
        "guard": guard_receipt,
        "head": head,
        "phase": phase,
        "root": str((root or Path.cwd()).resolve(strict=True)),
        "state": state,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if phase == "pending" and prior is not None:
        payload["prior"] = prior
    if phase == "complete":
        graph_identity, built_at_commit = _graph_snapshot(
            receipt_path.parent / "graph.json"
        )
        if built_at_commit != head:
            raise GuardFailure("G017")
        payload["graph"] = graph_identity
        report_identity, report_commit = _report_snapshot(
            receipt_path.parent / "GRAPH_REPORT.md"
        )
        if report_commit != head[:8]:
            raise GuardFailure("G017")
        payload["report"] = report_identity
    return payload


def _read_stable_payload(path: Path, maximum_bytes: int) -> bytes:
    try:
        if path.is_symlink() or path.is_junction():
            raise GuardFailure("G017")
        chunks: list[bytes] = []
        total = 0
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise GuardFailure("G017")
            while chunk := handle.read(1024 * 1024):
                total += len(chunk)
                if total > maximum_bytes:
                    raise GuardFailure("G017")
                chunks.append(chunk)
            after = os.fstat(handle.fileno())
        named = os.stat(path, follow_symlinks=False)
    except GuardFailure:
        raise
    except OSError as exc:
        raise GuardFailure("G017") from exc
    if (
        _stat_identity(before) != _stat_identity(after)
        or not stat.S_ISREG(named.st_mode)
        or named.st_nlink != 1
        or (after.st_dev, after.st_ino) != (named.st_dev, named.st_ino)
        or (after.st_size, after.st_mtime_ns) != (named.st_size, named.st_mtime_ns)
    ):
        raise GuardFailure("G017")
    return b"".join(chunks)


def _file_identity(path: Path, maximum_bytes: int) -> dict[str, Any]:
    payload = _read_stable_payload(path, maximum_bytes)
    return {"sha256": _sha256(payload), "size": len(payload)}


def _graph_commit(payload: bytes) -> str:
    try:
        graph = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
        built_at_commit = graph.get("built_at_commit")
    except (AttributeError, RecursionError, UnicodeDecodeError, ValueError) as exc:
        raise GuardFailure("G017") from exc
    if not isinstance(graph, dict) or not isinstance(built_at_commit, str):
        raise GuardFailure("G017")
    if not _valid_head(built_at_commit):
        raise GuardFailure("G017")
    return built_at_commit


def _graph_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    payload = _read_stable_payload(path, _MAX_GRAPH_BYTES)
    built_at_commit = _graph_commit(payload)
    return {"sha256": _sha256(payload), "size": len(payload)}, built_at_commit


def _graph_identity(path: Path) -> dict[str, Any]:
    return _graph_snapshot(path)[0]


def _report_commit_match(payload: bytes) -> re.Match[bytes]:
    matches = list(_REPORT_COMMIT_LINE.finditer(payload))
    if len(matches) != 1:
        raise GuardFailure("G017")
    return matches[0]


def _report_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    payload = _read_stable_payload(path, _MAX_REPORT_BYTES)
    match = _report_commit_match(payload)
    return (
        {"sha256": _sha256(payload), "size": len(payload)},
        match.group(1).decode("ascii", errors="strict"),
    )


def _report_stamp_ready(output: Path, commit: Any) -> bool:
    if not _valid_head(commit):
        return False
    try:
        _identity, short_commit = _report_snapshot(output / "GRAPH_REPORT.md")
    except GuardFailure:
        return False
    return short_commit == commit[:8]


def _fast_noop_ready(output: Path, commit: Any) -> bool:
    """Authorize upstream's no-op only from a current complete v2 receipt."""

    if not _valid_head(commit) or _ACTIVE_GUARD_RECEIPT is None:
        return False
    try:
        root = output.parent.resolve(strict=True)
        if _current_git_identity(root) != (commit, "clean"):
            return False
        prior = _validated_prior_complete(
            output / ".guarded_refresh.json", _ACTIVE_GUARD_RECEIPT
        )
        return bool(prior is not None and prior["head"] == commit)
    except (GuardFailure, OSError, RuntimeError, ValueError):
        return False


def _write_refresh_receipt(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as exc:
        raise GuardFailure("G017") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_refresh_receipt(path: Path) -> dict[str, Any] | None:
    try:
        payload = _read_stable_payload(path, 16_384)
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (GuardFailure, RecursionError, UnicodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _same_json_identity(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's ``True == 1`` coercion."""
    try:
        return json.dumps(left, allow_nan=False, sort_keys=True, separators=(",", ":")) == json.dumps(
            right, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError):
        return False


def _same_receipt_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare top-level receipt identity while excluding its event timestamp."""

    return _same_json_identity(
        {key: value for key, value in left.items() if key != "updated_at"},
        {key: value for key, value in right.items() if key != "updated_at"},
    )


def _valid_file_identity(value: Any) -> bool:
    return bool(
        isinstance(value, dict)
        and set(value) == {"sha256", "size"}
        and isinstance(value.get("sha256"), str)
        and len(value["sha256"]) == 64
        and all(character in "0123456789abcdef" for character in value["sha256"])
        and isinstance(value.get("size"), int)
        and not isinstance(value.get("size"), bool)
        and value["size"] >= 0
    )


def _valid_prior_identity(value: Any, guard_receipt: dict[str, Any]) -> bool:
    return bool(
        isinstance(value, dict)
        and set(value) == {"graph", "guard", "head", "report"}
        and _valid_head(value.get("head"))
        and _valid_file_identity(value.get("graph"))
        and isinstance(value.get("guard"), dict)
        and _same_json_identity(value["guard"], guard_receipt)
        and _valid_file_identity(value.get("report"))
    )


def _validated_pending_prior(
    path: Path,
    *,
    head: str,
    state: str,
    guard_receipt: dict[str, Any],
    root: Path,
) -> dict[str, Any] | None:
    """Preserve an exact pending transaction so a partial rebind can retry."""

    actual = _read_refresh_receipt(path)
    prior = actual.get("prior") if isinstance(actual, dict) else None
    if not _valid_prior_identity(prior, guard_receipt):
        return None
    expected = _refresh_receipt_payload(
        phase="pending",
        head=head,
        state=state,
        guard_receipt=guard_receipt,
        receipt_path=path,
        prior=prior,
        root=root,
    )
    try:
        updated_at = datetime.fromisoformat(actual["updated_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if updated_at.tzinfo is None or not _same_receipt_identity(actual, expected):
        return None
    return prior


def _validated_prior_complete(
    path: Path, guard_receipt: dict[str, Any]
) -> dict[str, Any] | None:
    actual = _read_refresh_receipt(path)
    if actual is None or set(actual) != {
        "contract",
        "graph",
        "guard",
        "head",
        "phase",
        "report",
        "root",
        "state",
        "updated_at",
    }:
        return None
    if (
        actual.get("contract") != REFRESH_RECEIPT_CONTRACT
        or actual.get("phase") != "complete"
        or actual.get("state") != "clean"
        or not isinstance(actual.get("guard"), dict)
        or not _same_json_identity(actual["guard"], guard_receipt)
        or not _valid_head(actual.get("head"))
        or not _valid_file_identity(actual.get("graph"))
        or not _valid_file_identity(actual.get("report"))
        or not isinstance(actual.get("root"), str)
        or "\x00" in actual["root"]
        or not Path(actual["root"]).is_absolute()
        or str(actual["root"]).replace("\\", "/").startswith("//")
    ):
        return None
    try:
        updated_at = datetime.fromisoformat(actual["updated_at"])
        graph_identity, built_at_commit = _graph_snapshot(path.parent / "graph.json")
        report_identity, report_commit = _report_snapshot(
            path.parent / "GRAPH_REPORT.md"
        )
    except (GuardFailure, KeyError, TypeError, ValueError):
        return None
    if (
        updated_at.tzinfo is None
        or built_at_commit != actual["head"]
        or report_commit != actual["head"][:8]
        or graph_identity != actual["graph"]
        or report_identity != actual["report"]
    ):
        return None
    return {
        "graph": graph_identity,
        "guard": guard_receipt,
        "head": built_at_commit,
        "report": report_identity,
    }


def _git_object_id(root: Path, revision: str) -> str:
    try:
        value = _git_output(root, "rev-parse", "--verify", revision).decode(
            "ascii", errors="strict"
        ).strip()
    except (UnicodeDecodeError, ValueError) as exc:
        raise GuardFailure("G019") from exc
    if not _valid_head(value):
        raise GuardFailure("G019")
    return value


def _tree_equivalent_ancestor(root: Path, prior: str, current: str) -> bool:
    grafts = root / ".git" / "info" / "grafts"
    if grafts.exists() or grafts.is_symlink() or grafts.is_junction():
        return False
    try:
        merge_base = _git_output(root, "merge-base", prior, current).decode(
            "ascii", errors="strict"
        ).strip()
        if merge_base != prior:
            return False
        return _git_object_id(root, f"{prior}^{{tree}}") == _git_object_id(
            root, f"{current}^{{tree}}"
        )
    except (GuardFailure, UnicodeDecodeError, ValueError):
        return False


def _write_exclusive_bytes(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_pair_transactionally(
    replacements: Sequence[tuple[Path, bytes, bytes]]
) -> None:
    """Publish exact target bytes; a pending receipt makes a split retryable."""

    temporaries: list[tuple[Path, Path]] = []
    try:
        for target, original, replacement in replacements:
            temporary = target.with_name(f".{target.name}.{os.getpid()}.rebind")
            _write_exclusive_bytes(temporary, replacement)
            temporaries.append((target, temporary))
        for target, original, _replacement in replacements:
            maximum = (
                _MAX_GRAPH_BYTES if target.name == "graph.json" else _MAX_REPORT_BYTES
            )
            if _read_stable_payload(target, maximum) != original:
                raise OSError("rebind source changed before replacement")
        for target, temporary in temporaries:
            os.replace(temporary, target)
        for target, _original, replacement in replacements:
            maximum = (
                _MAX_GRAPH_BYTES if target.name == "graph.json" else _MAX_REPORT_BYTES
            )
            if _read_stable_payload(target, maximum) != replacement:
                raise OSError("rebind verification failed")
    except (GuardFailure, OSError, ValueError) as exc:
        # os.replace is atomic per file, not across the pair.  Do not improvise
        # a lossy rollback.  The still-pending v2 receipt preserves the exact
        # prior identity, and the next guarded run accepts only an exact
        # prior/target state for each file before completing the transition.
        raise GuardFailure("G019") from exc
    finally:
        for _target, temporary in temporaries:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _payload_identity(payload: bytes) -> dict[str, Any]:
    return {"sha256": _sha256(payload), "size": len(payload)}


def _transition_target_payload(
    payload: bytes,
    *,
    pattern: re.Pattern[bytes],
    prior_stamp: bytes,
    target_stamp: bytes,
    prior_identity: dict[str, Any],
    graph: bool,
) -> bytes:
    """Recognize only exact prior/target bytes and derive the exact target."""

    if len(prior_stamp) != len(target_stamp):
        raise GuardFailure("G019")
    matches = list(pattern.finditer(payload))
    if len(matches) != 1 or matches[0].group(1) not in {prior_stamp, target_stamp}:
        raise GuardFailure("G019")
    start, end = matches[0].span(1)
    prior_payload = payload
    if matches[0].group(1) == target_stamp and target_stamp != prior_stamp:
        prior_payload = payload[:start] + prior_stamp + payload[end:]
    if _payload_identity(prior_payload) != prior_identity:
        raise GuardFailure("G019")
    prior_matches = list(pattern.finditer(prior_payload))
    if len(prior_matches) != 1 or prior_matches[0].group(1) != prior_stamp:
        raise GuardFailure("G019")
    start, end = prior_matches[0].span(1)
    target_payload = prior_payload[:start] + target_stamp + prior_payload[end:]
    if graph:
        try:
            if (
                _graph_commit(prior_payload) != prior_stamp.decode("ascii")
                or _graph_commit(target_payload) != target_stamp.decode("ascii")
            ):
                raise GuardFailure("G019")
        except (GuardFailure, UnicodeDecodeError) as exc:
            raise GuardFailure("G019") from exc
    return target_payload


def _maybe_tree_equivalent_rebind(
    root: Path, arguments: Sequence[str], guard_receipt: dict[str, Any]
) -> bool:
    if not arguments or arguments[0] != "update" or "--force" in arguments:
        return False
    output = root / "graphify-out"
    receipt_path = output / ".guarded_refresh.json"
    graph_path = output / "graph.json"
    report_path = output / "GRAPH_REPORT.md"
    pending = _read_refresh_receipt(receipt_path)
    prior = pending.get("prior") if isinstance(pending, dict) else None
    if not _valid_prior_identity(prior, guard_receipt):
        return False
    head, state = _current_git_identity(root)
    if state != "clean":
        return False
    if prior["head"] == head:
        return False
    expected_pending = _refresh_receipt_payload(
        phase="pending",
        head=head,
        state="clean",
        guard_receipt=guard_receipt,
        receipt_path=receipt_path,
        prior=prior,
        root=root,
    )
    try:
        pending_updated_at = datetime.fromisoformat(pending["updated_at"])
    except (KeyError, TypeError, ValueError):
        return False
    if (
        not isinstance(pending, dict)
        or pending_updated_at.tzinfo is None
        or not _same_receipt_identity(pending, expected_pending)
    ):
        return False
    if not _tree_equivalent_ancestor(root, prior["head"], head):
        return False

    if (
        len(prior["head"]) != len(head)
        or not _valid_file_identity(prior["graph"])
        or not _valid_file_identity(prior["report"])
    ):
        raise GuardFailure("G019")
    try:
        graph_bytes = _read_stable_payload(graph_path, _MAX_GRAPH_BYTES)
        report_bytes = _read_stable_payload(report_path, _MAX_REPORT_BYTES)
        rebound_graph = _transition_target_payload(
            graph_bytes,
            pattern=_GRAPH_COMMIT_LINE,
            prior_stamp=prior["head"].encode("ascii"),
            target_stamp=head.encode("ascii"),
            prior_identity=prior["graph"],
            graph=True,
        )
        rebound_report = _transition_target_payload(
            report_bytes,
            pattern=_REPORT_COMMIT_LINE,
            prior_stamp=prior["head"][:8].encode("ascii"),
            target_stamp=head[:8].encode("ascii"),
            prior_identity=prior["report"],
            graph=False,
        )
    except GuardFailure as exc:
        raise GuardFailure("G019") from exc
    if _current_git_identity(root) != (head, "clean"):
        raise GuardFailure("G019")
    replacements = tuple(
        replacement
        for replacement in (
            (graph_path, graph_bytes, rebound_graph),
            (report_path, report_bytes, rebound_report),
        )
        if replacement[1] != replacement[2]
    )
    if replacements:
        _replace_pair_transactionally(replacements)
    print(
        "[graphify guard] rebound tree-equivalent graph/report commit fields; "
        "all non-commit bytes were preserved."
    )
    return True


def _handle_refresh_receipt(
    arguments: Sequence[str], guard_receipt: dict[str, Any], root: Path
) -> int:
    mode, path_arg, head, state = arguments
    path = _refresh_receipt_path(path_arg)
    if not _valid_head(head) or state not in {"clean", "dirty"}:
        raise GuardFailure("G017")
    actual_head, actual_state = _current_git_identity(root)
    if head != actual_head or state != actual_state:
        raise GuardFailure("G017")
    if mode == "--receipt-status":
        if state != "clean":
            return 1
        expected = _refresh_receipt_payload(
            phase="complete",
            head=head,
            state=state,
            guard_receipt=guard_receipt,
            receipt_path=path,
            root=root,
        )
        actual = _read_refresh_receipt(path)
        if actual is None:
            return 1
        try:
            updated_at = datetime.fromisoformat(actual["updated_at"])
        except (KeyError, TypeError, ValueError):
            return 1
        if updated_at.tzinfo is None:
            return 1
        # Timestamp is evidentiary but not part of the freshness identity.
        return 0 if _same_receipt_identity(actual, expected) else 1
    if mode == "--receipt-complete":
        # Completion is a transition, not an independently mintable assertion.
        # The Stop hook must first have recorded the exact pending snapshot before
        # it entered Graphify.  This is local hook bookkeeping (not a signature),
        # but it prevents an accidental/partial finalizer from blessing arbitrary
        # graph bytes without the transaction's pre-mutation marker.
        pending = _read_refresh_receipt(path)
        if pending is None:
            raise GuardFailure("G017")
        expected_pending = _refresh_receipt_payload(
            phase="pending",
            head=head,
            state=state,
            guard_receipt=guard_receipt,
            receipt_path=path,
            prior=pending.get("prior") if isinstance(pending, dict) else None,
            root=root,
        )
        try:
            pending_updated_at = datetime.fromisoformat(pending["updated_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GuardFailure("G017") from exc
        if pending_updated_at.tzinfo is None or not _same_receipt_identity(
            pending, expected_pending
        ):
            raise GuardFailure("G017")

    phase = "pending" if mode == "--receipt-pending" else "complete"
    prior = None
    if phase == "pending":
        prior = _validated_prior_complete(path, guard_receipt)
        if prior is None:
            prior = _validated_pending_prior(
                path,
                head=head,
                state=state,
                guard_receipt=guard_receipt,
                root=root,
            )
    payload = _refresh_receipt_payload(
        phase=phase,
        head=head,
        state=state,
        guard_receipt=guard_receipt,
        receipt_path=path,
        prior=prior,
        root=root,
    )
    _write_refresh_receipt(path, payload)
    return 0


def _validate_arguments(arguments: Sequence[str]) -> None:
    """Keep the guarded surface offline, local, and exact for Graphifyy 0.9.51."""

    if not arguments or arguments[0] not in {"update", "watch", "extract"}:
        raise GuardFailure("G011")

    command = arguments[0]
    if command == "update":
        roots = []
        positional = 0
        for argument in arguments[1:]:
            if argument == "--force":
                continue
            if argument.startswith("-"):
                raise GuardFailure("G013")
            positional += 1
            roots.append(argument)
        if positional != 1:
            raise GuardFailure("G013")
        if not _is_local_path(roots[0]):
            raise GuardFailure("G013")
        return

    if command == "watch":
        if len(arguments) != 2 or arguments[1].startswith("-"):
            raise GuardFailure("G013")
        if not _is_local_path(arguments[1]):
            raise GuardFailure("G013")
        return

    # ``extract`` auto-selects an LLM backend when API keys exist. Keep only a
    # closed local AST surface and require the explicit no-semantic flag. In
    # particular, do not expose --allow-partial, --force, --no-gitignore, live
    # database/global destinations, or output indirection through this guard.
    if (
        len(arguments) < 2
        or arguments[1].startswith("-")
        or not _is_local_path(arguments[1])
    ):
        raise GuardFailure("G012")
    code_only = False
    no_value_options = {"--code-only", "--no-cluster"}
    index = 2
    while index < len(arguments):
        argument = arguments[index]
        if argument in no_value_options:
            code_only = code_only or argument == "--code-only"
            index += 1
            continue
        raise GuardFailure("G013")
    if not code_only:
        raise GuardFailure("G012")


def main(argv: Sequence[str] | None = None) -> int:
    global _ACTIVE_GUARD_RECEIPT

    arguments = list(sys.argv[1:] if argv is None else argv)
    producer_root: Path | None = None
    receipt_modes = {"--receipt-status", "--receipt-pending", "--receipt-complete"}
    receipt_mode = bool(arguments and arguments[0] in receipt_modes)
    identity_mode = arguments == ["--identity"]
    if not _invocation_isolated():
        failure = GuardFailure("G014")
        _print_failure(failure)
        return 2
    if arguments and arguments[0] == "--probe" and len(arguments) != 1:
        failure = GuardFailure("G009")
        _print_failure(failure)
        return 2
    if receipt_mode and len(arguments) != 4:
        failure = GuardFailure("G017")
        _print_failure(failure)
        return 2
    if arguments and arguments[0] == "--identity" and not identity_mode:
        failure = GuardFailure("G017")
        _print_failure(failure)
        return 2
    if any(arg == "--max-workers" or arg.startswith("--max-workers=") for arg in arguments):
        failure = GuardFailure("G010")
        _print_failure(failure)
        return 2
    if receipt_mode or identity_mode:
        try:
            producer_root = _producer_root(["update", "."])
        except GuardFailure as failure:
            _print_failure(failure)
            return 2
    elif arguments != ["--probe"]:
        try:
            _validate_arguments(arguments)
            producer_root = _producer_root(arguments)
            arguments = _canonical_arguments(arguments, producer_root)
        except GuardFailure as failure:
            _print_failure(failure)
            return 2

    with _controlled_environment(producer_root):
        try:
            receipt = _prepare_overlay()
        except GuardFailure as failure:
            _print_failure(failure)
            return 2
        except Exception:
            _print_failure(GuardFailure("G008"))
            return 2

        attested = _attested_receipt(receipt)
        _ACTIVE_GUARD_RECEIPT = attested
        if arguments == ["--probe"]:
            print(json.dumps(attested, sort_keys=True, separators=(",", ":")))
            return 0
        if identity_mode:
            try:
                if producer_root is None:
                    raise GuardFailure("G015")
                head, state, status_digest = _current_git_snapshot(producer_root)
                print(f"{head}\t{state}\t{status_digest}")
                return 0
            except GuardFailure as failure:
                _print_failure(failure)
                return 2
        if receipt_mode:
            try:
                if producer_root is None:
                    raise GuardFailure("G015")
                with _producer_lock(producer_root):
                    return _handle_refresh_receipt(arguments, attested, producer_root)
            except GuardFailure as failure:
                _print_failure(failure)
                return 2
        try:
            if producer_root is None:
                raise GuardFailure("G015")
            with _producer_lock(producer_root):
                if arguments[0] in {"update", "watch"}:
                    _current_git_identity(producer_root)
                if _maybe_tree_equivalent_rebind(producer_root, arguments, attested):
                    return 0
                return _run_graphify(arguments)
        except GuardFailure as failure:
            _print_failure(failure)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
