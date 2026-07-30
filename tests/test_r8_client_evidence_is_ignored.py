"""Regression guard for raw client evidence and local AssessHub state.

The collector intentionally keeps raw command captures because they are the evidence source for
``--no-collect``, compare, and trend runs. Those captures can include complete running-configs with
SNMP communities, TACACS/RADIUS keys, enable secrets, VPN pre-shared keys, addresses, serials, and
other client data. A custom ``--collection-dir`` must therefore be just as difficult to commit as the
default ``migration_collection_*`` directory.

Use Git itself as the oracle rather than approximating .gitignore semantics in Python. ``--no-index``
also evaluates paths that do not exist and paths that happen to be tracked, which makes this test
portable and side-effect free.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _is_ignored(path: str) -> bool:
    git = shutil.which("git")
    assert git is not None, "git is required to verify the repository's ignore contract"
    proc = subprocess.run(
        [git, "check-ignore", "--no-index", "--quiet", "--", path],
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


# The 17 shapes reproduced during the whole-repository review: the generated default, common custom
# collection roots, explicit client-evidence roots, a sensitive command capture under an arbitrary
# root, and the persistent AssessHub database sidecar.
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
    "arbitrary_export/CORE-1/show_running-config.txt",
    "webapp/data/assesshub.db-wal",
)


@pytest.mark.parametrize("path", _CLIENT_ARTIFACTS)
def test_client_evidence_shapes_are_ignored(path: str) -> None:
    assert _is_ignored(path), f"client evidence is commit-visible: {path}"


@pytest.mark.parametrize(
    "filename",
    (
        "show_run.txt",
        "show_startup-config.txt",
        "show_configuration.txt",
        "show_tech-support.txt",
        "show_crypto_key_mypubkey_rsa.txt",
        "show_snmp_community.txt",
        "show_tacacs_server.txt",
        "show_radius_statistics.txt",
    ),
)
def test_sensitive_command_captures_are_ignored_under_an_arbitrary_root(filename: str) -> None:
    assert _is_ignored(f"customer-chosen-output/CORE-1/{filename}")


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


@pytest.mark.parametrize(
    "path",
    (
        "tests/fixtures/show_running-config.txt",
        "tests/fixtures/show_run.txt",
        "tests/fixtures/show_startup-config.txt",
        "tests/fixtures/show_configuration.txt",
        "tests/fixtures/show_tech-support.txt",
        "tests/fixtures/show_crypto_key.txt",
        "tests/fixtures/show_snmp.txt",
        "tests/fixtures/show_tacacs.txt",
        "tests/fixtures/show_radius.txt",
    ),
)
def test_reviewable_synthetic_test_fixtures_are_not_hidden(path: str) -> None:
    assert not _is_ignored(path), f"synthetic test fixture was over-ignored: {path}"


def test_normal_source_and_document_paths_remain_visible() -> None:
    for path in (
        "cisco_toolkit/data/port_registry.tsv.gz",
        "cisco_toolkit/eoldb.py",
        "tests/test_redact_collection.py",
        "docs/client-evidence-handling.md",
        "webapp/data/README.md",
    ):
        assert not _is_ignored(path), f"legitimate repository content was over-ignored: {path}"
