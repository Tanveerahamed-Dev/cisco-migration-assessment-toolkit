"""Check or rebuild Atlas Release 1's inspectable compatibility capsule.

The default operation is read-only. It reconstructs every output in a temporary directory from
the approved Git tree and refuses byte drift. ``--update`` replaces committed generated assets
only after the entire staged result, including the pinned retrospective replay, succeeds.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


APPROVED_HEAD = "08f745ff7e12ff14ec84dee500b016292870aaa5"
SOURCE_BUNDLE_RESOURCE = "atlas-r1-source-bundle.json"
MANIFEST_RESOURCE = "atlas-r1-executable-bundle.json"
BEFORE_RESOURCE = "atlas-r1-retrospective-before.json"
AFTER_RESOURCE = "atlas-r1-retrospective-after.json"
COMPARISON_RESOURCE = "atlas-r1-retrospective-comparison.json"
SOURCE_CHUNK_BYTES = 512 * 1024
COMPARISON_DIGEST = "e92dbe997b92b3c6d1e3017408ac1a32e7364e14f61edd9202a67d9710a87c70"
COMPARISON_BYTES = 51_678
BEFORE_RAW = (
    b'{"collected_at":"2026-08-22T00:00:00.000000Z","devices":{"leaf-1":{}},'
    b'"script_version":"V3.23.0"}'
)
AFTER_RAW = (
    b'{"collected_at":"2026-08-22T00:05:00.000000Z","devices":{"leaf-1":{}},'
    b'"script_version":"V3.23.0"}'
)

_REFERENCE_RUNTIME_PROFILE = {
    "cache_tag": "cpython-312",
    "external_distributions": [
        {"name": "defusedxml", "version": "0.7.1"},
        {"name": "lxml", "version": "6.1.1"},
        {"name": "numpy", "version": "2.5.1"},
        {"name": "openpyxl", "version": "3.1.5"},
        {"name": "pillow", "version": "12.3.0"},
        {"name": "setuptools", "version": "83.0.0"},
    ],
    "implementation": "CPython",
    "platform_machine": "AMD64",
    "platform_system": "Windows",
    "version": "3.12.10",
}

_VECTOR_DRIVER = r'''\
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
from cisco_toolkit import protocol_assurance as pa
from cisco_toolkit.comparison import compare_bound_pair

before_raw = Path(sys.argv[2]).read_bytes()
after_raw = Path(sys.argv[3]).read_bytes()

def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()

def binding(raw, snapshot_id, label):
    return {
        "source": pa.OFFLINE_FILE_SOURCE,
        "sha256": digest(raw),
        "bytes": len(raw),
        "snapshot_id": snapshot_id,
        "campaign_id": 701,
        "engagement_id": "ENG-R1-COMPAT",
        "label": label,
        "script_version": "V3.23.0",
    }

comparison = compare_bound_pair(
    pa.bind_snapshot_json_bytes(before_raw),
    pa.bind_snapshot_json_bytes(after_raw),
    before_binding=binding(before_raw, 1001, "before.json"),
    after_binding=binding(after_raw, 1002, "after.json"),
    change_intent=None,
    path_intents=None,
    l2_failure_trial=None,
)
Path(sys.argv[4]).write_bytes(pa.canonical_json_bytes(dict(comparison)))
'''


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(raw: bytes) -> str:
    return "sha256:" + _sha256(raw)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _git(repository: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=repository)


def _approved_package_files(repository: Path) -> dict[str, bytes]:
    names = _git(
        repository,
        "ls-tree",
        "-r",
        "--name-only",
        APPROVED_HEAD,
        "--",
        "cisco_toolkit",
    ).decode("utf-8", "strict").splitlines()
    python_paths = {name for name in names if name.endswith(".py")}
    module_paths = {
        name.removeprefix("cisco_toolkit/").removesuffix(".py").replace("/", "."): name
        for name in python_paths
    }
    module_paths[""] = "cisco_toolkit/__init__.py"
    selected_modules: set[str] = set()
    pending = ["", "comparison", "protocol_assurance"]
    while pending:
        module = pending.pop()
        if module in selected_modules or module not in module_paths:
            continue
        selected_modules.add(module)
        path = module_paths[module]
        raw = _git(repository, "show", f"{APPROVED_HEAD}:{path}")
        tree = ast.parse(raw.decode("utf-8-sig"), filename=path)
        for node in ast.walk(tree):
            candidates: list[str] = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    parent = module.split(".")[:-node.level]
                    base = ".".join([*parent, *([node.module] if node.module else [])])
                elif node.module == "cisco_toolkit":
                    base = ""
                elif (node.module or "").startswith("cisco_toolkit."):
                    base = (node.module or "").removeprefix("cisco_toolkit.")
                else:
                    continue
                candidates.append(base)
                candidates.extend(".".join(filter(None, (base, item.name))) for item in node.names)
            elif isinstance(node, ast.Import):
                for item in node.names:
                    if item.name == "cisco_toolkit":
                        candidates.append("")
                    elif item.name.startswith("cisco_toolkit."):
                        candidates.append(item.name.removeprefix("cisco_toolkit."))
            pending.extend(candidate for candidate in candidates if candidate in module_paths)

    selected_paths = {module_paths[module] for module in selected_modules}
    selected_paths.update(name for name in names if not name.endswith(".py"))
    return {
        path: _git(repository, "show", f"{APPROVED_HEAD}:{path}")
        for path in sorted(selected_paths)
    }


def _source_bundle(files: dict[str, bytes]) -> bytes:
    entries = []
    for path, raw in files.items():
        chunks = [
            base64.b64encode(raw[offset:offset + SOURCE_CHUNK_BYTES]).decode("ascii")
            for offset in range(0, len(raw), SOURCE_CHUNK_BYTES)
        ]
        entries.append({
            "bytes": len(raw),
            "content_base64_chunks": chunks,
            "path": path,
            "sha256": _digest(raw),
        })
    return _canonical({
        "approved_head": APPROVED_HEAD,
        "chunk_encoding": "BASE64_RFC4648_512_KIB_RAW_CHUNKS",
        "files": entries,
        "schema": "atlas.release1-source-bundle/1",
    })


def _extract(files: dict[str, bytes], root: Path) -> None:
    for relative, raw in files.items():
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def _manifest(source_bundle_raw: bytes, files: dict[str, bytes]) -> bytes:
    paths = list(files)
    python_count = sum(path.endswith(".py") for path in paths)
    return _canonical({
        "adapter_authority": "AUDIT_ONLY",
        "approved_head": APPROVED_HEAD,
        "execution_contract": {
            "ambient_current_atlas_imports_permitted": False,
            "canonical_output": "release1 protocol_assurance.canonical_json_bytes",
            "interpreter_mode": "ISOLATED_-I_FIXED_DRIVER",
            "module_path_policy": "PINNED_EXTRACTED_SOURCE_ROOT_FIRST",
            "network_required": False,
            "timeout_seconds": 60,
        },
        "historical_fixture_state": (
            "NO_AUTHENTICATED_R1_COMPARISON_AND_SOURCE_PAIR_FOUND_IN_REPOSITORY"
        ),
        "r2_promotion_eligible": False,
        "retrospective_conformance_vector": {
            "after_resource": AFTER_RESOURCE,
            "after_source_bytes": len(AFTER_RAW),
            "after_source_sha256": _digest(AFTER_RAW),
            "before_resource": BEFORE_RESOURCE,
            "before_source_bytes": len(BEFORE_RAW),
            "before_source_sha256": _digest(BEFORE_RAW),
            "canonical_comparison_bytes": COMPARISON_BYTES,
            "canonical_comparison_resource": COMPARISON_RESOURCE,
            "canonical_comparison_sha256": f"sha256:{COMPARISON_DIGEST}",
            "historical_receipt": False,
        },
        "runtime_profile": _REFERENCE_RUNTIME_PROFILE,
        "schema": "atlas.release1-executable-bundle/1",
        "semantic_anchor_authority_state": "ACCOUNTABLE_OWNER_APPROVAL_REQUIRED",
        "source_bundle_bytes": len(source_bundle_raw),
        "source_bundle_file_count": len(files),
        "source_bundle_resource": SOURCE_BUNDLE_RESOURCE,
        "source_bundle_scope": (
            "Static transitive local-import closure of comparison and protocol_assurance plus all "
            "package data from the approved Release 1 Git tree."
        ),
        "source_bundle_sha256": _digest(source_bundle_raw),
        "source_closure": {
            "algorithm": "PYTHON_AST_LOCAL_IMPORT_TRANSITIVE_PLUS_ALL_PACKAGE_DATA/1",
            "package_data_file_count": len(files) - python_count,
            "path_set_sha256": _digest(_canonical(paths)),
            "python_source_file_count": python_count,
            "roots": ["cisco_toolkit.comparison", "cisco_toolkit.protocol_assurance"],
        },
    })


def _stage(repository: Path, root: Path) -> dict[str, bytes]:
    files = _approved_package_files(repository)
    source_bundle_raw = _source_bundle(files)
    runtime_root = root / "runtime"
    _extract(files, runtime_root)
    before = root / BEFORE_RESOURCE
    after = root / AFTER_RESOURCE
    comparison = root / COMPARISON_RESOURCE
    before.write_bytes(BEFORE_RAW)
    after.write_bytes(AFTER_RAW)
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            _VECTOR_DRIVER,
            str(runtime_root),
            str(before),
            str(after),
            str(comparison),
        ],
        cwd=root,
        check=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    comparison_raw = comparison.read_bytes()
    if len(comparison_raw) != COMPARISON_BYTES or _sha256(comparison_raw) != COMPARISON_DIGEST:
        raise RuntimeError("Release 1 retrospective comparison vector drifted")
    return {
        SOURCE_BUNDLE_RESOURCE: source_bundle_raw,
        MANIFEST_RESOURCE: _manifest(source_bundle_raw, files),
        BEFORE_RESOURCE: BEFORE_RAW,
        AFTER_RESOURCE: AFTER_RAW,
        COMPARISON_RESOURCE: comparison_raw,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--update",
        action="store_true",
        help="replace generated resources after every staged proof succeeds",
    )
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    data = repository / "cisco_toolkit" / "data"
    with tempfile.TemporaryDirectory(prefix="atlas-r1-build-") as temporary:
        outputs = _stage(repository, Path(temporary))
    if args.update:
        for name, raw in outputs.items():
            (data / name).write_bytes(raw)
        return 0
    drift = [
        name
        for name, raw in outputs.items()
        if not (data / name).is_file() or (data / name).read_bytes() != raw
    ]
    if drift:
        raise RuntimeError(
            "Release 1 generated resources drifted: " + ", ".join(sorted(drift))
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
