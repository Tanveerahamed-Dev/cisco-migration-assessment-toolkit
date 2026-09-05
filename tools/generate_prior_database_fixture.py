"""Rebuild the synthetic AssessHub database fixture from an exact historical checkout.

This is maintainer tooling, never part of Atlas.exe. It imports only the historical
``webapp/backend/storage.py`` owner, creates synthetic rows through that release's public Store
API, normalizes timestamps, and emits a reviewable SQL dump with exact Git/source provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sqlite3
import subprocess
import tempfile
from pathlib import Path


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed")
    return result.stdout


def build_fixture(source: Path, expected_commit: str, output: Path) -> None:
    source = source.resolve(strict=True)
    commit = _git(source, "rev-parse", "HEAD^{commit}")
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    if commit != expected_commit:
        raise RuntimeError(f"historical checkout is {commit}, expected {expected_commit}")
    storage_bytes = _git_bytes(source, "show", "HEAD:webapp/backend/storage.py")

    with tempfile.TemporaryDirectory(prefix="atlas-prior-db-fixture-") as temporary:
        temporary_path = Path(temporary)
        storage_path = temporary_path / "storage.py"
        storage_path.write_bytes(storage_bytes)
        spec = importlib.util.spec_from_file_location("atlas_prior_storage_fixture", storage_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load historical storage owner")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        database = temporary_path / "assesshub.db"
        store = module.Store(database)
        campaign = store.create_campaign(
            "Release 3.32.1 fixture",
            "Synthetic prior-release migration evidence",
        )
        snapshot = store.add_snapshot(
            campaign["id"],
            "Prior snapshot",
            {
                "script_version": "3.32.1",
                "executive_brief": {"scale": {"n_devices": 1}},
                "devices": {"SYNTHETIC-1": {"hostname": "SYNTHETIC-1"}},
            },
            {"health": "synthetic"},
        )
        store.create_execution(
            snapshot["id"],
            {
                "label": "Prior run",
                "status": "completed",
                "started_at": "2026-08-03T17:00:00+00:00",
                "ended_at": "2026-08-03T17:01:00+00:00",
            },
        )
        store.close()
        connection = sqlite3.connect(database)
        connection.execute(
            "UPDATE campaigns SET created_at='2026-08-03T17:00:00+00:00'"
        )
        connection.execute(
            "UPDATE snapshots SET uploaded_at='2026-08-03T17:00:30+00:00'"
        )
        connection.commit()
        dump = "\n".join(connection.iterdump()) + "\n"
        connection.close()
    header = (
        "-- atlas.prior-database-fixture/1\n"
        f"-- source_commit={commit}\n"
        f"-- source_tree={tree}\n"
        f"-- storage_git_blob_sha256={hashlib.sha256(storage_bytes).hexdigest()}\n"
        "-- synthetic_data_only=true\n"
    )
    output.write_text(header + dump, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    build_fixture(Path(args.source), args.expected_commit, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
