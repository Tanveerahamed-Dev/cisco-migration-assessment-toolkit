"""Regression guard for raw client evidence and local AssessHub state.

The collector intentionally keeps raw command captures because they are the evidence source for
``--no-collect``, compare, and trend runs. Those captures can include complete running-configs with
credentials and keys, but ordinary inventory, neighbor, ARP, MAC, logging, and platform captures are
client data too. A custom ``--collection-dir`` must therefore be just as difficult to commit as the
default ``migration_collection_*`` directory.

Use Git itself as the oracle rather than approximating .gitignore semantics in Python. ``--no-index``
also evaluates paths that do not exist and paths that happen to be tracked, which makes this test
portable and side-effect free. The registered command lists are parsed with ``ast`` rather than
importing the engine, so adding a new capture command cannot silently fall outside the ignore contract.
"""
from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRY_MODULE = ROOT / "COLLECT_PARSE_V3_23_0.py"
_REQUIRED_COMMAND_LISTS = {
    "COMMANDS_NXOS",
    "COMMANDS_IOS",
    "COMMANDS_ARISTA",
    "COMMANDS_JUNIPER",
    "COMMANDS_CLOUD",
    "COMMANDS_FORTINET",
}
_COLLECTION_SIDECARS = ("device_info.json", "command_index.json", "_capture_meta.json")


def _git() -> str:
    git = shutil.which("git")
    assert git is not None, "git is required to verify the repository's ignore contract"
    return git


def _is_ignored(path: str) -> bool:
    proc = subprocess.run(
        [_git(), "check-ignore", "--no-index", "--quiet", "--", path],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode in (0, 1), (
        f"git check-ignore failed for {path!r}: rc={proc.returncode}; "
        f"stdout={proc.stdout!r}; stderr={proc.stderr!r}"
    )
    return proc.returncode == 0


def _ignored_paths(paths: Iterable[str]) -> set[str]:
    requested = tuple(paths)
    proc = subprocess.run(
        [_git(), "check-ignore", "--no-index", "--stdin"],
        cwd=ROOT,
        input="".join(f"{path}\n" for path in requested),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode in (0, 1), (
        f"git check-ignore --stdin failed: rc={proc.returncode}; "
        f"stdout={proc.stdout!r}; stderr={proc.stderr!r}"
    )
    return set(proc.stdout.splitlines())


def _registered_capture_filenames() -> tuple[str, ...]:
    tree = ast.parse(ENTRY_MODULE.read_text(encoding="utf-8"), filename=str(ENTRY_MODULE))
    found_lists: set[str] = set()
    filenames: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.startswith("COMMANDS_"):
            continue
        try:
            commands = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError):
            continue  # e.g. computed COMMANDS_ALL; the literal source lists are audited below
        if not isinstance(commands, list) or not all(isinstance(command, str) for command in commands):
            continue
        found_lists.add(target.id)
        for command in commands:
            filename = (
                command.replace(" ", "_")
                .replace("|", "_")
                .replace("^", "")
                .replace("/", "_")
                + ".txt"
            )
            filenames.add(filename)

    missing_lists = sorted(_REQUIRED_COMMAND_LISTS - found_lists)
    assert not missing_lists, f"registered command lists were not statically auditable: {missing_lists}"
    assert len(filenames) >= 100, f"unexpectedly small capture registry: {len(filenames)} filenames"
    return tuple(sorted(filenames))


_REGISTERED_CAPTURE_FILENAMES = _registered_capture_filenames()


# The original 17 shapes reproduced during the whole-repository review: the generated default,
# common custom collection roots, explicit client-evidence roots, an ordinary capture under an
# arbitrary root, and the persistent AssessHub database sidecar.
_CLIENT_ARTIFACTS = (
    "migration_collection_20260730_182700/CORE-1/show_running-config.txt",
    "collection/CORE-1/show_version.txt",
    "collections/ACME/CORE-1/show_version.txt",
    "collection_acme/CORE-1/show_version.txt",
    "collections_acme/CORE-1/show_version.txt",
    "client_data/ACME/snapshot.json",
    "client-data/ACME/snapshot.json",
    "client_evidence/ACME/CORE-1/show_version.txt",
    "client-evidence/ACME/CORE-1/show_version.txt",
    "evidence/ACME/CORE-1/show_version.txt",
    "captures/ACME/CORE-1/show_version.txt",
    "raw_collection/ACME/CORE-1/show_version.txt",
    "raw-collection/ACME/CORE-1/show_version.txt",
    "raw_evidence/ACME/CORE-1/show_version.txt",
    "raw-evidence/ACME/CORE-1/show_version.txt",
    "arbitrary_export/CORE-1/show_version.txt",
    "webapp/data/assesshub.db-wal",
)


@pytest.mark.parametrize("path", _CLIENT_ARTIFACTS)
def test_original_client_evidence_shapes_are_ignored(path: str) -> None:
    assert _is_ignored(path), f"client evidence is commit-visible: {path}"


def test_every_registered_capture_is_ignored_under_an_arbitrary_root() -> None:
    paths = tuple(
        f"customer-chosen-output/CORE-1/{filename}"
        for filename in _REGISTERED_CAPTURE_FILENAMES
    )
    missing = sorted(set(paths) - _ignored_paths(paths))
    assert not missing, f"registered client captures are commit-visible: {missing}"


def test_collection_metadata_sidecars_are_ignored_under_an_arbitrary_root() -> None:
    paths = tuple(f"customer-chosen-output/CORE-1/{name}" for name in _COLLECTION_SIDECARS)
    missing = sorted(set(paths) - _ignored_paths(paths))
    assert not missing, f"collection metadata is commit-visible: {missing}"


@pytest.mark.parametrize(
    "path",
    (
        "webapp/data/assesshub.db",
        "webapp/data/assesshub.db-shm",
        "webapp/data/assesshub.sqlite",
        "webapp/data/assesshub.sqlite-wal",
        "webapp/data/assesshub.sqlite3",
        "webapp/data/assesshub.sqlite3-shm",
    ),
)
def test_assesshub_database_and_sidecars_are_ignored(path: str) -> None:
    assert _is_ignored(path), f"client snapshot database is commit-visible: {path}"


def test_reviewable_registered_test_fixtures_are_not_hidden() -> None:
    paths = tuple(f"tests/fixtures/{filename}" for filename in _REGISTERED_CAPTURE_FILENAMES)
    hidden = sorted(_ignored_paths(paths))
    assert not hidden, f"synthetic registered test fixtures were over-ignored: {hidden}"


def test_reviewable_collection_metadata_test_fixtures_are_not_hidden() -> None:
    paths = tuple(f"tests/fixtures/{name}" for name in _COLLECTION_SIDECARS)
    hidden = sorted(_ignored_paths(paths))
    assert not hidden, f"synthetic collection metadata was over-ignored: {hidden}"


def test_normal_source_and_document_paths_remain_visible() -> None:
    for path in (
        "cisco_toolkit/data/port_registry.tsv.gz",
        "cisco_toolkit/eoldb.py",
        "tests/test_redact_collection.py",
        "docs/client-evidence-handling.md",
        "webapp/data/README.md",
    ):
        assert not _is_ignored(path), f"legitimate repository content was over-ignored: {path}"
