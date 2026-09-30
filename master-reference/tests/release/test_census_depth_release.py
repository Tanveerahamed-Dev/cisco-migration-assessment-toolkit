"""Release-side census depth: a named BLOCK and an undiminished privacy scan.

An identity-depth file has no ``source_text`` chunk, so the release's
local-identity chunk scan would never see its bytes.  The bundle reader must
read those bytes from Git and apply the same rule, and the release manifest
must carry the declaration's BLOCK category while any file is deferred.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

import release.compiler_bundle as compiler_bundle  # noqa: E402
from compiler import compile_repository  # noqa: E402
from compiler.policy import census_depth_declaration_receipts  # noqa: E402
from release.model import ReleaseInputError  # noqa: E402
from release.pipeline import census_depth_release_gate  # noqa: E402


CENSUS_DEPTH_BLOCK_CODE = "census_depth_identity_line_projection_deferred"
CONTENT_FILES = (
    "atlas-core.json",
    "capability-catalog.json",
    "delivery-governance.json",
    "open-horizon-register.json",
    "output-contract.json",
)


def _git(repo: Path, *arguments: str) -> None:
    process = subprocess.run(
        ["git", "-c", "core.quotepath=false", *arguments],
        cwd=repo,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace"))


def _write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _repository(tmp_path: Path, extra: dict[str, str]) -> Path:
    repo = tmp_path / "census-depth-repo"
    repo.mkdir(parents=True)
    _write(repo / "README.md", b"# Census depth fixture\n")
    for name in CONTENT_FILES:
        _write(repo / "master-reference" / "content" / name, (MASTER_REFERENCE / "content" / name).read_bytes())
    _write(
        repo / "master-reference" / "governance" / "consequential-claim-contract.json",
        (MASTER_REFERENCE / "governance" / "consequential-claim-contract.json").read_bytes(),
    )
    contract = {
        "schema_version": "2.0.0",
        "python_import_roots": [],
        "internal_module_prefixes": [],
        "components": [
            {"id": "repository", "paths": ["README.md", "master-reference/", "tools/"]},
            {"id": "scope", "paths": ["atlas-scope/"]},
        ],
        "exclusions": [],
        "allowed_edges": [],
        "forbidden_edges": [],
        "runtime_phases": [{"id": "compile", "order": 1, "required": False}],
        "synthetic_runtime_traces": [
            {
                "id": "fixture",
                "events": [{"phase": "compile", "status": "passed", "receipt_id": "synthetic:fixture:compile"}],
            }
        ],
    }
    _write(
        repo / "master-reference" / "governance" / "architecture.json",
        (json.dumps(contract, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    for relative, text in extra.items():
        _write(repo.joinpath(*relative.split("/")), text.encode("utf-8"))
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "user.name", "Atlas Test")
    _git(repo, "config", "user.email", "atlas@example.invalid")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-qm", "census depth fixture")
    return repo


def _local_marker(repo: Path) -> str:
    # The fixture's own absolute checkout path, assembled at run time: the
    # exact shape of the local-identity markers the release scan refuses.
    return repo.resolve().as_posix()


def test_identity_depth_bytes_get_the_same_local_identity_scan_as_chunked_bytes(tmp_path: Path) -> None:
    clean = _repository(tmp_path / "clean", {"atlas-scope/src/app.ts": "export const clean = 1;\n"})
    clean_output = tmp_path / "clean-compiler"
    compile_repository(clean, clean_output)
    bundle = compiler_bundle.load_compiler_bundle(clean_output, repository_root=clean)
    assert bundle.completeness["census_depth"]["identity_depth_files"] == 1

    outcomes: dict[str, str] = {}
    for label, path in (("full", "tools/marker.ts"), ("identity", "atlas-scope/src/marker.ts")):
        root = tmp_path / label
        root.mkdir()
        text = f'export const where = "{_local_marker(root.resolve() / "census-depth-repo")}/notes";\n'
        repo = _repository(root, {path: text, "atlas-scope/src/app.ts": "export const clean = 1;\n"})
        output = tmp_path / f"{label}-compiler"
        compile_repository(repo, output)
        files = {row["path"]: row for row in _files(output)}
        assert files[path]["census_depth"] == label
        with pytest.raises(ReleaseInputError) as caught:
            compiler_bundle.load_compiler_bundle(output, repository_root=repo)
        message = str(caught.value)
        assert _local_marker(repo) not in message
        outcomes[label] = message
    assert "compiler chunk privacy scan failed: rule=local_repository_path" in outcomes["full"]
    assert "compiler identity-depth source privacy scan failed: rule=local_repository_path" in outcomes["identity"]


def _files(output: Path) -> list[dict[str, object]]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    records: list[dict[str, object]] = []
    for receipt in manifest["groups"]["files"]["chunks"]:
        records.extend(json.loads((output / receipt["path"]).read_text(encoding="utf-8"))["records"])
    return records


def test_bundle_refuses_identity_bytes_that_differ_from_their_file_record(tmp_path: Path) -> None:
    repo = _repository(tmp_path, {"atlas-scope/src/app.ts": "export const clean = 1;\n"})
    output = tmp_path / "compiler"
    compile_repository(repo, output)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    from compiler.model import canonical_json, sha256_bytes

    receipt = manifest["groups"]["files"]["chunks"][0]
    envelope = json.loads((output / receipt["path"]).read_text(encoding="utf-8"))
    for row in envelope["records"]:
        if row["path"] == "atlas-scope/src/app.ts":
            row["size_bytes"] = int(row["size_bytes"]) + 1
    raw = canonical_json(envelope)
    (output / receipt["path"]).write_bytes(raw)
    receipt.update({"bytes": len(raw), "sha256": sha256_bytes(raw)})
    (output / "manifest.json").write_bytes(canonical_json(manifest))
    with pytest.raises(ReleaseInputError, match="identity-depth source differs from its file record"):
        compiler_bundle.load_compiler_bundle(output, repository_root=repo)


def test_release_gate_names_the_declared_block_category() -> None:
    declaration = census_depth_declaration_receipts()[0]
    active = {
        **declaration,
        "tracked_files": 400,
        "text_files": 400,
        "privacy_scanned_text_files": 400,
        "deferred_nonblank_lines": 1234,
    }
    gate, limits = census_depth_release_gate(
        {"census_depth": {"declarations": [active], "block_categories": [CENSUS_DEPTH_BLOCK_CODE]}}
    )
    assert gate == f"BLOCK:{CENSUS_DEPTH_BLOCK_CODE}"
    assert len(limits) == 1
    assert CENSUS_DEPTH_BLOCK_CODE in limits[0]
    assert declaration["prefix"] in limits[0]
    assert declaration["follow_up_owner"] in limits[0]
    assert "not projected" in limits[0]

    idle = {**declaration, "tracked_files": 0}
    assert census_depth_release_gate({"census_depth": {"declarations": [idle], "block_categories": []}}) == (
        "passed_full_depth",
        [],
    )
    with pytest.raises(ReleaseInputError):
        census_depth_release_gate({"census_depth": {"declarations": [active], "block_categories": []}})
    with pytest.raises(ReleaseInputError):
        census_depth_release_gate({})


def test_release_registries_require_the_census_depth_gate_and_invariant() -> None:
    assert "every_tracked_text_file_line_censused" in compiler_bundle.REQUIRED_ACCEPTANCE_GATES
    assert (
        "every_identity_depth_file_declared_privacy_scanned_and_unprojected"
        in compiler_bundle.REQUIRED_STRUCTURAL_INVARIANTS
    )
