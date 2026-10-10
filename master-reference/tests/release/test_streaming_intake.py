"""W64a streaming release intake: an identical family from bounded memory.

``cli build`` used to keep every compiler record group in memory, re-read every
chunk into memory for preservation, and build both ZIPs in memory.  W64a still
reads, scans and validates every group exactly as before, but retains only the
groups the release builders read, re-verifies every chunk on each re-read, and
writes both ZIPs entry by entry to disk.  These tests pin that:

- every release fixture builds a family byte-identical, receipt for receipt, to
  the pre-W64a in-memory release path.  Scope of that oracle: the packaging
  and serialization functions W64a replaced (canonical JSON, the generated-
  output scan, preservation, bundle receipts, ZIPs, the one-shot symbol index)
  are verbatim pre-W64a copies below, but the intake is W64a's own
  ``load_compiler_bundle`` with every group retained, so the oracle proves the
  family does not depend on retention or streaming, not that the intake equals
  the pre-W64a intake.  That is proven at full scale by the workflow's A/B
  step (the real pre-W64a files on the same compiler output) and, for refusals,
  by the exact-message cases here;
- the streamed ZIP equals the original in-memory ``deterministic_zip``;
- refusals on streamed groups keep their exact messages in both retention modes;
- a chunk changed after intake is refused before any output exists, while
  packaging, and on ``iter_records``;
- a duplicate stable ID inside unretained groups is refused;
- doubling the line bytes moves the intake's traced peak by less than 10 %,
  while the retain-everything control grows past that same bound;
- the one-shot canonical JSON of an astral-character index peaks near eight
  bytes per output byte, and the streamed symbol index stays far below that.

The repository fixtures come from ``test_release_pipeline.py``, loaded by path
under a private module name so their tests are not collected twice.
"""

from __future__ import annotations

import ast
import gc
import importlib.util
import io
import json
import random
import shutil
import stat
import sys
import tracemalloc
import zipfile
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

import release.compiler_bundle as compiler_bundle  # noqa: E402
import release.pipeline as release_pipeline  # noqa: E402
from atlas_privacy import FORBIDDEN_CONTENT_RULES, ForbiddenContentScan, forbidden_byte_findings  # noqa: E402
from release.compiler_bundle import REQUIRED_GROUPS, load_compiler_bundle  # noqa: E402
from release.model import (  # noqa: E402
    ReleaseInputError,
    VerifiedFile,
    canonical_json,
    canonical_json_text_pieces,
    collect_output_bytes,
    deterministic_zip,
    digest_object,
    entry_receipt,
    read_bytes,
    receipt,
    safe_relative,
    sha256_bytes,
    write_deterministic_zip,
)
from release.pipeline import RELEASE_RETAINED_GROUPS, ReleaseError, build_release  # noqa: E402


def _load_fixture_module() -> Any:
    path = Path(__file__).with_name("test_release_pipeline.py")
    spec = importlib.util.spec_from_file_location("_w64a_release_pipeline_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FIXTURES = _load_fixture_module()
_fixture_repo = _FIXTURES._fixture_repo
_declared_claim_compiler_fixture = _FIXTURES._declared_claim_compiler_fixture
_rewrite_chunk = _FIXTURES._rewrite_chunk
_rewrite_compiler_completeness = _FIXTURES._rewrite_compiler_completeness
_replace_group_fixture = _FIXTURES._replace_group_fixture
_all_files = _FIXTURES._all_files
_json = _FIXTURES._json
_write = _FIXTURES._write

assert RELEASE_RETAINED_GROUPS is not None
STREAMED_GROUPS = REQUIRED_GROUPS - RELEASE_RETAINED_GROUPS
ARCHIVES = ("atlas-master-reference-offline.zip", "atlas-master-reference-preservation.zip")
LINES_CHUNK = "chunks/lines/00000.json"


# ---------------------------------------------------------------------------
# The pre-W64a in-memory release path, verbatim: the oracle for byte identity.
# ---------------------------------------------------------------------------

_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def _pre_w64a_canonical_json(value: Any) -> bytes:
    """Verbatim pre-W64a ``release.model.canonical_json``."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _pre_w64a_forbidden_byte_findings(path: str, value: bytes) -> list[dict[str, Any]]:
    """Verbatim pre-W64a ``atlas_privacy.forbidden_byte_findings`` (whole-text scan)."""

    text = value.decode("utf-8", errors="ignore")
    findings: list[dict[str, Any]] = []
    for rule, pattern in FORBIDDEN_CONTENT_RULES:
        for match in pattern.finditer(text):
            findings.append({"path": path, "line": text.count("\n", 0, match.start()) + 1, "rule": rule})
    return findings


def _pre_w64a_deterministic_zip(entries: dict[str, bytes]) -> bytes:
    """Verbatim pre-W64a ``release.model.deterministic_zip``."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name in sorted(entries):
            safe_relative(name)
            info = zipfile.ZipInfo(name, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.flag_bits |= 0x800
            archive.writestr(info, entries[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue()


def _pre_w64a_compiler_preservation_entries(bundle: Any) -> dict[str, bytes]:
    """Verbatim pre-W64a ``release.pipeline._compiler_preservation_entries``."""

    entries: dict[str, bytes] = {"compiler/manifest.json": _pre_w64a_canonical_json(bundle.manifest)}
    expected: dict[str, dict[str, Any]] = {
        bundle.manifest["completeness"]["path"]: bundle.manifest["completeness"],
        bundle.manifest["graphify_metadata"]["path"]: bundle.manifest["graphify_metadata"],
        bundle.manifest["architecture_conformance"]["path"]: bundle.manifest["architecture_conformance"],
    }
    for group in bundle.manifest["groups"].values():
        for chunk in group["chunks"]:
            expected[chunk["path"]] = chunk
    if set(expected) | {"manifest.json"} != set(bundle.input_files):
        raise ReleaseInputError("compiler preservation allowlist differs from validated inputs")
    for relative, item in sorted(expected.items()):
        try:
            value = read_bytes(bundle.root, relative)
        except (OSError, ReleaseInputError):
            raise ReleaseInputError("compiler input could not be reread before preservation") from None
        if len(value) != item["bytes"] or sha256_bytes(value) != item["sha256"]:
            raise ReleaseInputError(f"compiler input changed before preservation: {relative}")
        entries[f"compiler/{relative}"] = value
    return entries


def _pre_w64a_bundle_receipt(entries: dict[str, bytes], source_commit: str, kind: str) -> bytes:
    """Verbatim pre-W64a ``release.pipeline._bundle_receipt``."""

    return _pre_w64a_canonical_json(
        {
            "schema_version": "1.0.0",
            "kind": kind,
            "source_commit": source_commit,
            "entries": [{"path": name, **receipt(value)} for name, value in sorted(entries.items())],
            "receipt_exclusion": "This receipt cannot include its own digest.",
        }
    )


def _pre_w64a_zip_artifact(root: Path, relative: str, entries: dict[str, bytes], role: str) -> dict[str, Any]:
    """The pre-W64a ``_artifact(target, name, deterministic_zip(entries), role)`` call."""

    assert all(type(value) is bytes for value in entries.values())
    return release_pipeline._artifact(root, relative, _pre_w64a_deterministic_zip(entries), role)


def _pre_w64a_symbol_index_artifact(root: Path, relative: str, value: Any, role: str) -> dict[str, Any]:
    """The pre-W64a ``_artifact(target, name, canonical_json(index), role)`` call."""

    return release_pipeline._artifact(root, relative, _pre_w64a_canonical_json(value), role)


def _build_pre_w64a(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    compiler: Path,
    output: Path,
    **options: Any,
) -> dict[str, Any]:
    """Build with every group retained and every replaced function pre-W64a."""

    with monkeypatch.context() as patch:
        patch.setattr(release_pipeline, "RELEASE_RETAINED_GROUPS", None)
        patch.setattr(release_pipeline, "canonical_json", _pre_w64a_canonical_json)
        patch.setattr(release_pipeline, "forbidden_byte_findings", _pre_w64a_forbidden_byte_findings)
        patch.setattr(release_pipeline, "_streamed_json_artifact", _pre_w64a_symbol_index_artifact)
        patch.setattr(release_pipeline, "_compiler_preservation_entries", _pre_w64a_compiler_preservation_entries)
        patch.setattr(release_pipeline, "verified_output_entries", collect_output_bytes)
        patch.setattr(release_pipeline, "_bundle_receipt", _pre_w64a_bundle_receipt)
        patch.setattr(release_pipeline, "_zip_artifact", _pre_w64a_zip_artifact)
        return build_release(repo, compiler, output, **options)


# ---------------------------------------------------------------------------
# Fixture helpers.
# ---------------------------------------------------------------------------


def _group_records(compiler: Path, group_name: str) -> list[dict[str, Any]]:
    manifest = json.loads((compiler / "manifest.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for chunk in manifest["groups"][group_name]["chunks"]:
        rows.extend(json.loads((compiler / chunk["path"]).read_text(encoding="utf-8"))["records"])
    return rows


def _write_rechunked_compiler(
    source: Path,
    target: Path,
    *,
    chunk_size: int,
    replacements: dict[str, list[dict[str, Any]]] | None = None,
) -> None:
    """Re-pack a canonical compiler output at another chunk size.

    The ledgers are copied unchanged; ``replacements`` swaps whole groups.
    Every chunk and the manifest stay canonical, so the result is accepted.
    """

    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    target.mkdir(parents=True)
    for name in ("completeness.json", "graphify-metadata.json", "architecture-conformance.json"):
        shutil.copyfile(source / name, target / name)
    groups: dict[str, Any] = {}
    for group_name in sorted(manifest["groups"]):
        rows = (replacements or {}).get(group_name)
        if rows is None:
            rows = _group_records(source, group_name)
        rows = sorted(rows, key=lambda row: str(row["id"]))
        size = 1 if group_name == "source_text" else chunk_size
        chunks: list[dict[str, Any]] = []
        slices = [rows[start : start + size] for start in range(0, len(rows), size)]
        for index, chunk_rows in enumerate(slices):
            envelope = {
                "schema_version": manifest["schema_version"],
                "record_type": group_name,
                "source_commit": manifest["source_commit"],
                "source_tree_digest": manifest["source_tree_digest"],
                "chunk_index": index,
                "chunk_count": len(slices),
                "record_count": len(chunk_rows),
                "records_digest": digest_object([row["id"] for row in chunk_rows]),
                "records": chunk_rows,
            }
            relative = f"chunks/{group_name}/{index:05d}.json"
            raw = canonical_json(envelope)
            _write(target / relative, raw)
            chunks.append(
                {"path": relative, "record_count": len(chunk_rows), "sha256": sha256_bytes(raw), "bytes": len(raw)}
            )
        groups[group_name] = {
            "record_count": len(rows),
            "chunk_count": len(chunks),
            "records_digest": digest_object([row["id"] for row in rows]),
            "chunks": chunks,
        }
    manifest["chunk_size"] = chunk_size
    manifest["groups"] = groups
    _json(target / "manifest.json", manifest)


def _rewrite_raw_chunk(compiler: Path, relative: str, raw: bytes) -> None:
    """Replace one chunk's bytes and re-bind its manifest receipt to them."""

    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    group_name = relative.split("/")[1]
    receipts = [chunk for chunk in manifest["groups"][group_name]["chunks"] if chunk["path"] == relative]
    assert len(receipts) == 1
    _write(compiler / relative, raw)
    receipts[0]["sha256"] = sha256_bytes(raw)
    receipts[0]["bytes"] = len(raw)
    _json(manifest_path, manifest)


def _change_one_byte(chunk: Path) -> None:
    """Change one digit of a line record, keeping the chunk's size."""

    raw = chunk.read_bytes()
    marker = b'"depth":0'
    index = raw.index(marker) + len(marker) - 1
    chunk.write_bytes(raw[:index] + b"1" + raw[index + 1 :])


def _archive_entries(raw: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


# ---------------------------------------------------------------------------
# Byte identity.
# ---------------------------------------------------------------------------


def _synthetic(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    repo, compiler = _fixture_repo(tmp_path)
    return repo, compiler, {}


def _synthetic_multichunk(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    repo, compiler = _fixture_repo(tmp_path)
    rechunked = tmp_path / "compiler-rechunked"
    _write_rechunked_compiler(compiler, rechunked, chunk_size=64)
    return repo, rechunked, {}


ASTRAL = "\U0001f4a3"


def _synthetic_astral(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    # One astral character in a retained, indexed record makes the canonical
    # symbol-index text four bytes per character, as on the real tree.
    repo, compiler = _fixture_repo(tmp_path)
    _replace_group_fixture(
        compiler,
        "datasets",
        [{"id": f"urn:atlas:dataset:{'a' * 24}", "path": f"data/{ASTRAL}.json", "format": f"json {ASTRAL}"}],
    )
    return repo, compiler, {}


def _synthetic_generated_pdf(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    pytest.importorskip("reportlab")
    pytest.importorskip("pypdf")
    repo, compiler = _fixture_repo(tmp_path)
    return repo, compiler, {"generate_pdf": True}


def _compiled_declared_claims_generated_pdf(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    pytest.importorskip("reportlab")
    pytest.importorskip("pypdf")
    repo, synthetic = _fixture_repo(tmp_path)
    return repo, _declared_claim_compiler_fixture(repo, synthetic), {"generate_pdf": True}


@pytest.mark.parametrize(
    "fixture",
    [
        _synthetic,
        _synthetic_multichunk,
        _synthetic_astral,
        _synthetic_generated_pdf,
        _compiled_declared_claims_generated_pdf,
    ],
    ids=[
        "synthetic",
        "synthetic-multichunk",
        "synthetic-astral",
        "synthetic-generated-pdf",
        "compiled-declared-claims-generated-pdf",
    ],
)
def test_every_release_fixture_builds_a_byte_identical_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture: Callable[[Path], tuple[Path, Path, dict[str, Any]]],
) -> None:
    repo, compiler, options = fixture(tmp_path)
    loaded: list[Any] = []
    real_loader = release_pipeline.load_compiler_bundle

    def recording_loader(*args: Any, **kwargs: Any) -> Any:
        bundle = real_loader(*args, **kwargs)
        loaded.append(bundle)
        return bundle

    monkeypatch.setattr(release_pipeline, "load_compiler_bundle", recording_loader)
    streamed, legacy = tmp_path / "streamed", tmp_path / "pre-w64a"
    streamed_observations: dict[str, Any] = {}
    legacy_observations: dict[str, Any] = {}
    streamed_manifest = build_release(repo, compiler, streamed, observations=streamed_observations, **options)
    legacy_manifest = _build_pre_w64a(monkeypatch, repo, compiler, legacy, observations=legacy_observations, **options)

    # The streamed build really streamed, and the oracle really retained all.
    assert [bundle.deferred_groups for bundle in loaded] == [STREAMED_GROUPS, frozenset()]
    assert "lines" in STREAMED_GROUPS and "source_text" in STREAMED_GROUPS
    # Every receipt equal: the manifest's, the census's and every member's bytes.
    assert streamed_manifest == legacy_manifest
    assert streamed_observations == legacy_observations
    streamed_files, legacy_files = _all_files(streamed), _all_files(legacy)
    assert sorted(streamed_files) == sorted(legacy_files)
    assert [name for name in sorted(streamed_files) if streamed_files[name] != legacy_files[name]] == []
    compiler_manifest = (compiler / "manifest.json").read_bytes()
    for archive_name in ARCHIVES:
        raw = streamed_files[archive_name]
        entries = _archive_entries(raw)
        # The streamed archive is exactly the in-memory builder over its entries.
        assert _pre_w64a_deterministic_zip(entries) == raw
        rows = json.loads(entries["bundle-receipt.json"])["entries"]
        assert {row["path"]: (row["sha256"], row["bytes"]) for row in rows} == {
            name: (sha256_bytes(value), len(value)) for name, value in entries.items() if name != "bundle-receipt.json"
        }
        compiler_entries = {name: value for name, value in entries.items() if name.startswith("compiler/")}
        assert compiler_entries.pop("compiler/manifest.json") == compiler_manifest
        assert compiler_entries == {
            name: (compiler / name.removeprefix("compiler/")).read_bytes() for name in compiler_entries
        }
        assert any(name.startswith("compiler/chunks/lines/") for name in compiler_entries)
    if fixture is _synthetic_astral:
        # The streamed symbol index really carried the astral character.
        assert ASTRAL in (streamed / "source-symbol-index.json").read_text(encoding="utf-8")


def test_streamed_zip_equals_the_in_memory_deterministic_zip(tmp_path: Path) -> None:
    payloads = {
        "a/empty.json": b"",
        "b/repetitive.json": b'{"k":"v"}\n' * 5_000,
        "c/incompressible.bin": random.Random(64).randbytes(3 * 1024 * 1024 + 17),
        "d/élève.md": "non-ASCII member name é\n".encode("utf-8"),
    }
    source = tmp_path / "source"
    entries: dict[str, bytes | VerifiedFile] = {}
    reference: dict[str, bytes] = {}
    for index, (name, value) in enumerate(sorted(payloads.items())):
        relative = f"chunks/{index:05d}.json"
        _write(source / relative, value)
        entries[f"file/{name}"] = VerifiedFile(
            source, relative, sha256_bytes(value), len(value), changed_message=f"changed: {relative}"
        )
        entries[f"memory/{name}"] = value
        reference[f"file/{name}"] = value
        reference[f"memory/{name}"] = value
    expected = _pre_w64a_deterministic_zip(reference)

    row = write_deterministic_zip(tmp_path / "out", "family.zip", entries)

    assert (tmp_path / "out" / "family.zip").read_bytes() == expected
    assert row == {"path": "family.zip", "sha256": sha256_bytes(expected), "bytes": len(expected)}
    assert deterministic_zip(entries) == expected
    assert deterministic_zip(reference) == expected
    assert {name: entry_receipt(value) for name, value in entries.items()} == {
        name: receipt(value) for name, value in reference.items()
    }
    with pytest.raises(ReleaseInputError, match=r"^release output already exists: family\.zip$"):
        write_deterministic_zip(tmp_path / "out", "family.zip", entries)

    # An entry changed after its verification is refused, never packed.
    changed = source / "chunks" / "00001.json"
    changed.write_bytes(changed.read_bytes()[:-1] + b"X")
    with pytest.raises(ReleaseInputError, match=r"^changed: chunks/00001\.json$"):
        write_deterministic_zip(tmp_path / "out", "changed.zip", entries)
    assert not (tmp_path / "out" / "changed.zip").exists()
    assert (tmp_path / "out" / "family.zip").read_bytes() == expected
    with pytest.raises(ReleaseInputError, match=r"^changed: chunks/00001\.json$"):
        deterministic_zip(entries)
    # An entry that disappeared is refused with its own message, or the
    # underlying read refusal when it declares none.
    (source / "chunks" / "00000.json").unlink()
    missing = VerifiedFile(
        source,
        "chunks/00000.json",
        sha256_bytes(b""),
        0,
        changed_message="changed",
        unreadable_message="entry could not be reread",
    )
    with pytest.raises(ReleaseInputError, match=r"^entry could not be reread$"):
        missing.read()
    with pytest.raises(ReleaseInputError, match=r"^missing required input chunks/00000\.json"):
        entries["file/a/empty.json"].read()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Retention boundary and re-reads.
# ---------------------------------------------------------------------------


def test_streamed_groups_are_validated_but_never_read_as_empty(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    full = load_compiler_bundle(compiler, repository_root=repo)
    streamed = load_compiler_bundle(compiler, retained_groups=RELEASE_RETAINED_GROUPS, repository_root=repo)

    assert full.deferred_groups == frozenset()
    assert streamed.deferred_groups == STREAMED_GROUPS
    assert set(streamed.records) == set(RELEASE_RETAINED_GROUPS)
    assert streamed.chunk_census == full.chunk_census
    assert streamed.input_files == full.input_files
    for group_name in sorted(RELEASE_RETAINED_GROUPS):
        assert streamed.records[group_name] == full.records[group_name]
    for group_name in sorted(REQUIRED_GROUPS):
        assert list(streamed.iter_records(group_name)) == full.records[group_name]
        assert list(full.iter_records(group_name)) == full.records[group_name]
    assert full.records["lines"]
    refusal = r"^compiler group was validated and streamed, not retained: {}; read it with iter_records$"
    for group_name in sorted(STREAMED_GROUPS):
        assert group_name not in streamed.records
        with pytest.raises(ReleaseInputError, match=refusal.format(group_name)):
            streamed.records[group_name]
        with pytest.raises(ReleaseInputError, match=refusal.format(group_name)):
            streamed.records.get(group_name, [])
    assert streamed.records.get("not-a-group", "absent") == "absent"
    with pytest.raises(KeyError):
        streamed.records["not-a-group"]
    with pytest.raises(ReleaseInputError, match=r"^requested compiler groups are absent: \['not-a-group'\]$"):
        list(streamed.iter_records("not-a-group"))

    pytest.importorskip("reportlab")
    from release import pdf_report

    # The PDF's line count comes from the validated manifest receipt.
    assert pdf_report._manifest_line_record_count(streamed) == len(full.records["lines"])


def test_iter_records_re_verifies_every_chunk_it_re_reads(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    bundle = load_compiler_bundle(compiler, retained_groups=RELEASE_RETAINED_GROUPS, repository_root=repo)
    chunk = compiler / LINES_CHUNK
    expected = json.loads(chunk.read_text(encoding="utf-8"))["records"]
    assert list(bundle.iter_records("lines")) == expected

    # The re-read binds to the receipt captured at intake, not to the mutable
    # manifest dictionary the bundle exposes.
    bundle.manifest["groups"]["lines"]["chunks"][0]["sha256"] = "0" * 64
    assert list(bundle.iter_records("lines")) == expected

    _change_one_byte(chunk)
    with pytest.raises(ReleaseInputError, match=rf"^compiler lines chunk receipt mismatch: {LINES_CHUNK}$"):
        list(bundle.iter_records("lines"))
    chunk.unlink()
    with pytest.raises(ReleaseInputError, match=r"^compiler lines chunk could not be read from its fixed owner path$"):
        list(bundle.iter_records("lines"))


def test_a_chunk_changed_after_intake_is_refused_before_any_output_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    real_loader = release_pipeline.load_compiler_bundle
    prepared: list[Path] = []
    real_prepare = release_pipeline.prepare_output

    def load_then_change(*args: Any, **kwargs: Any) -> Any:
        bundle = real_loader(*args, **kwargs)
        _change_one_byte(compiler / LINES_CHUNK)
        return bundle

    def recording_prepare(path: Path) -> Any:
        prepared.append(path)
        return real_prepare(path)

    monkeypatch.setattr(release_pipeline, "load_compiler_bundle", load_then_change)
    monkeypatch.setattr(release_pipeline, "prepare_output", recording_prepare)
    output = tmp_path / "release"
    with pytest.raises(ReleaseError) as refusal:
        build_release(repo, compiler, output)

    # The streaming verify pass refuses before the output directory exists.
    assert str(refusal.value) == f"compiler input changed before preservation: {LINES_CHUNK}"
    assert prepared == []
    assert not output.exists()
    assert not list(tmp_path.glob(".release.building-*"))


def test_a_chunk_changed_after_the_verify_pass_is_refused_while_packaging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    real_prepare = release_pipeline.prepare_output

    def prepare_then_change(path: Path) -> Any:
        staged = real_prepare(path)
        _change_one_byte(compiler / LINES_CHUNK)
        return staged

    monkeypatch.setattr(release_pipeline, "prepare_output", prepare_then_change)
    output = tmp_path / "release"
    with pytest.raises(ReleaseError) as refusal:
        build_release(repo, compiler, output)

    # The archive re-reads and re-checks the chunk as it writes it.
    assert str(refusal.value) == f"compiler input changed before preservation: {LINES_CHUNK}"
    assert not output.exists()
    assert not list(tmp_path.glob(".release.building-*"))


# ---------------------------------------------------------------------------
# Refusals on streamed groups: exact messages, both retention modes.
# ---------------------------------------------------------------------------


def _duplicate_line_coordinate(repo: Path, compiler: Path) -> None:
    def transform(envelope: dict[str, Any]) -> None:
        envelope["records"][1]["path"] = envelope["records"][0]["path"]
        envelope["records"][1]["line"] = envelope["records"][0]["line"]

    _rewrite_chunk(compiler, "lines", transform)


def _unmapped_line(repo: Path, compiler: Path) -> None:
    def transform(envelope: dict[str, Any]) -> None:
        envelope["records"][0]["structural_mapping_basis"] = "symbol_range"

    _rewrite_chunk(compiler, "lines", transform)


def _line_chunk_digest(repo: Path, compiler: Path) -> None:
    def transform(envelope: dict[str, Any]) -> None:
        envelope["records_digest"] = "0" * 64

    _rewrite_chunk(compiler, "lines", transform)


def _line_chunk_not_canonical(repo: Path, compiler: Path) -> None:
    envelope = json.loads((compiler / LINES_CHUNK).read_text(encoding="utf-8"))
    _rewrite_raw_chunk(compiler, LINES_CHUNK, json.dumps(envelope, indent=1, sort_keys=True).encode("utf-8"))


def _line_chunk_receipt(repo: Path, compiler: Path) -> None:
    _change_one_byte(compiler / LINES_CHUNK)


def _source_text_custody(repo: Path, compiler: Path) -> None:
    file_record = next(row for row in _group_records(compiler, "files") if row["path"] == "pyproject.toml")
    _replace_group_fixture(
        compiler,
        "source_text",
        [
            {
                "id": f"urn:atlas:source-text:{'a' * 24}",
                "file_id": file_record["id"],
                "path": file_record["path"],
                "encoding": "utf-8",
                "source_basis": "selected_commit_git_blob",
                "git_blob_oid": "0" * 40,
                "byte_count": file_record["size_bytes"],
                "content_digest": file_record["content_digest"],
                "line_count": 0,
                "lines": [],
            }
        ],
    )


_STREAMED_GROUP_REFUSALS = {
    "duplicate-line-coordinate": (
        _duplicate_line_coordinate,
        "compiler line denominator has an invalid or duplicate coordinate",
    ),
    "unmapped-line": (_unmapped_line, "compiler line records differ from the structural mapping invariant"),
    "line-chunk-digest": (_line_chunk_digest, f"compiler chunk record digest mismatch: {LINES_CHUNK}"),
    "line-chunk-not-canonical": (
        _line_chunk_not_canonical,
        f"compiler lines chunk is not canonical JSON: {LINES_CHUNK}",
    ),
    "line-chunk-receipt": (_line_chunk_receipt, f"compiler lines chunk receipt mismatch: {LINES_CHUNK}"),
    "source-text-custody": (_source_text_custody, "compiler source-text custody differs from file record"),
}


@pytest.mark.parametrize("case", sorted(_STREAMED_GROUP_REFUSALS))
def test_refusals_on_streamed_groups_keep_their_exact_messages(tmp_path: Path, case: str) -> None:
    mutate, message = _STREAMED_GROUP_REFUSALS[case]
    repo, compiler = _fixture_repo(tmp_path)
    mutate(repo, compiler)

    for retained in (None, RELEASE_RETAINED_GROUPS):
        with pytest.raises(ReleaseInputError) as refusal:
            load_compiler_bundle(compiler, retained_groups=retained, repository_root=repo)
        assert str(refusal.value) == message
    output = tmp_path / "release"
    with pytest.raises(ReleaseError) as release_refusal:
        build_release(repo, compiler, output)
    assert str(release_refusal.value) == message
    assert not output.exists()


def test_a_consistent_source_text_record_on_any_path_passes_custody(tmp_path: Path) -> None:
    """The positive control for the custody refusal: the same record, consistent, loads."""

    repo, compiler = _fixture_repo(tmp_path)
    file_record = next(row for row in _group_records(compiler, "files") if row["path"] == "pyproject.toml")
    raw = (repo / "pyproject.toml").read_bytes()
    record = {
        "id": f"urn:atlas:source-text:{'a' * 24}",
        "file_id": file_record["id"],
        "path": file_record["path"],
        "encoding": "utf-8",
        "source_basis": "selected_commit_git_blob",
        "git_blob_oid": file_record["git_blob_oid"],
        "byte_count": len(raw),
        "content_digest": sha256_bytes(raw),
        "line_count": 0,
        "lines": [],
    }
    assert file_record["content_digest"] == record["content_digest"]
    _replace_group_fixture(compiler, "source_text", [record])
    for retained in (None, RELEASE_RETAINED_GROUPS):
        bundle = load_compiler_bundle(compiler, retained_groups=retained, repository_root=repo)
        assert list(bundle.iter_records("source_text")) == [record]


# ---------------------------------------------------------------------------
# Duplicate stable IDs inside unretained groups.
# ---------------------------------------------------------------------------


def _duplicate_inside_lines(compiler: Path) -> str:
    rows = _group_records(compiler, "lines")
    rows[1]["id"] = rows[0]["id"]
    _replace_group_fixture(compiler, "lines", rows)
    return "compiler record order is not canonical: lines"


def _duplicate_between_lines_and_structured(compiler: Path) -> str:
    # Neither group is retained by the release, and neither is a validator
    # group: only the global stable-ID set can see this duplicate.
    line_id = _group_records(compiler, "lines")[0]["id"]
    _replace_group_fixture(compiler, "structured", [{"id": line_id}])
    return "compiler stable IDs are not unique across record groups"


def _duplicate_between_lines_and_structural_roots(compiler: Path) -> str:
    rows = _group_records(compiler, "lines")
    root_id = _group_records(compiler, "structural_entities")[0]["id"]
    assert all(row["id"] < root_id for row in rows)
    rows[-1]["id"] = root_id
    _replace_group_fixture(compiler, "lines", rows)
    return "compiler stable IDs are not unique across record groups"


@pytest.mark.parametrize(
    "duplicate",
    [_duplicate_inside_lines, _duplicate_between_lines_and_structured, _duplicate_between_lines_and_structural_roots],
    ids=["inside-lines", "lines-and-structured", "lines-and-structural-roots"],
)
def test_a_duplicate_stable_id_inside_unretained_groups_is_refused(
    tmp_path: Path,
    duplicate: Callable[[Path], str],
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    message = duplicate(compiler)
    for retained in (None, RELEASE_RETAINED_GROUPS):
        with pytest.raises(ReleaseInputError) as refusal:
            load_compiler_bundle(compiler, retained_groups=retained, repository_root=repo)
        assert str(refusal.value) == message
    with pytest.raises(ReleaseError) as release_refusal:
        build_release(repo, compiler, tmp_path / "release")
    assert str(release_refusal.value) == message


# ---------------------------------------------------------------------------
# Memory: peak independent of line bytes.
# ---------------------------------------------------------------------------

_PAD = "w64a_padding"


def _padded_lines(rows: list[dict[str, Any]], pad: int) -> list[dict[str, Any]]:
    padded = json.loads(json.dumps(rows))
    for row in padded:
        row["inputs_and_outputs"] = {_PAD: "p" * pad}
    return padded


def _traced_intake_peak(compiler: Path, retained: frozenset[str] | None) -> int:
    """The intake's traced peak above the memory already traced when it began."""

    gc.collect()
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        baseline, _ = tracemalloc.get_traced_memory()
        bundle = load_compiler_bundle(compiler, retained_groups=retained)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        if not was_tracing:
            tracemalloc.stop()
    assert bundle.chunk_census is not None
    del bundle
    return peak - baseline


def test_doubling_line_bytes_moves_the_streamed_intake_peak_by_less_than_ten_percent(tmp_path: Path) -> None:
    _repo, compiler = _fixture_repo(tmp_path)
    lines = _group_records(compiler, "lines")
    # A fixed retained payload, so the peak has a production-like baseline that
    # does not depend on line bytes (in production that is ``symbols``).
    datasets = [{"id": f"urn:atlas:dataset:{index:024x}", "format": "f" * 65_536} for index in range(256)]
    single, double = tmp_path / "single", tmp_path / "double"
    pad_single = 2_048
    pad_double = 2 * pad_single + 4_096
    for target, pad in ((single, pad_single), (double, pad_double)):
        _write_rechunked_compiler(
            compiler,
            target,
            chunk_size=16,
            replacements={"lines": _padded_lines(lines, pad), "datasets": datasets},
        )

    def line_bytes(root: Path) -> int:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        return sum(chunk["bytes"] for chunk in manifest["groups"]["lines"]["chunks"])

    # The precondition is measured, not assumed: the line group really doubles.
    assert line_bytes(double) >= 2 * line_bytes(single)
    assert len(lines) >= 1_000

    # Warm every lazy cache (tracked schema validator, regular expressions)
    # before anything is traced.
    load_compiler_bundle(single, retained_groups=RELEASE_RETAINED_GROUPS)
    streamed_single = _traced_intake_peak(single, RELEASE_RETAINED_GROUPS)
    streamed_double = _traced_intake_peak(double, RELEASE_RETAINED_GROUPS)
    retained_single = _traced_intake_peak(single, None)
    retained_double = _traced_intake_peak(double, None)

    assert abs(streamed_double - streamed_single) < streamed_single / 10, (streamed_single, streamed_double)
    # The control has teeth: retaining the line group, as the pre-W64a release
    # did, crosses the same bound when the line bytes double.
    assert retained_double > retained_single * 11 / 10, (retained_single, retained_double)


# ---------------------------------------------------------------------------
# The retention list matches its readers.
# ---------------------------------------------------------------------------


def test_every_literal_release_read_of_bundle_records_is_a_retained_group() -> None:
    """Every ``bundle.records[...]`` / ``.get(...)`` group literal in the release
    builders is retained.  A read of any other group fails closed at run time
    (``RetainedRecords``); this keeps such a reader from being added at all.
    """

    allowed_fallbacks = {
        # Reached only for a partial renderer-only bundle whose manifest has
        # no ``lines`` receipt; a loaded bundle always has one.
        ("pdf_report.py", "_manifest_line_record_count", "lines"),
    }
    reads: set[tuple[str, str, str]] = set()
    for path in sorted((MASTER_REFERENCE / "release").glob("*.py")):
        if path.name == "compiler_bundle.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                target: ast.AST | None = None
                key: ast.AST | None = None
                if isinstance(node, ast.Subscript):
                    target, key = node.value, node.slice
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and node.args
                ):
                    target, key = node.func.value, node.args[0]
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "records"
                    and isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                ):
                    reads.add((path.name, function.name, key.value))
    assert reads, "the scan found no record reads, so it scanned nothing"
    assert {read for read in reads if read[2] not in RELEASE_RETAINED_GROUPS} == allowed_fallbacks
    assert {read[2] for read in reads} - {"lines"} <= RELEASE_RETAINED_GROUPS


# ---------------------------------------------------------------------------
# Round 2: the symbol-index transient, bounded scans, guarded reads, snapshot.
# ---------------------------------------------------------------------------


def _astral_index(records: int, pad: int) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "source_commit": "0" * 40,
        "line_mapping": {"record_count": records, "records_digest": "1" * 64},
        "files": [],
        "symbols": [
            {
                "id": f"urn:atlas:symbol:{index:024x}",
                "decorators": [f"@pytest.mark.parametrize('glyph', ['{ASTRAL}'])"],
                "documentation": "d" * pad,
            }
            for index in range(records)
        ],
    }


def _traced_peak(call: Callable[[], Any]) -> int:
    """The traced peak of ``call`` above the memory already traced when it began."""

    gc.collect()
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        baseline, _ = tracemalloc.get_traced_memory()
        result = call()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        if not was_tracing:
            tracemalloc.stop()
    del result
    return peak - baseline


def test_the_symbol_index_multiplier_is_pinned_and_the_streamed_index_avoids_it(tmp_path: Path) -> None:
    index = _astral_index(4_000, 2_000)
    expected = _pre_w64a_canonical_json(index)
    size = len(expected)
    assert canonical_json(index) == expected
    assert "".join(canonical_json_text_pieces(index)).encode("utf-8") == expected

    # The ceiling model's index term: one-shot canonical JSON of a document
    # that carries one astral character peaks near eight bytes per output byte
    # (the encoder's four-byte-per-character accumulated text and its join).
    one_shot = _traced_peak(lambda: canonical_json(index))
    assert 4 * size < one_shot < 10 * size, (size, one_shot)
    assert 4 * size < _traced_peak(lambda: _pre_w64a_canonical_json(index)) < 10 * size

    # The streamed artifact writes, hashes and scans the same bytes piece by
    # piece and never holds the document, so that term is gone.
    rows: list[dict[str, Any]] = []
    out = tmp_path / "streamed"
    streamed = _traced_peak(
        lambda: rows.append(release_pipeline._streamed_json_artifact(out, "index.json", index, "index-role"))
    )
    assert streamed < size / 4, (size, streamed)
    assert (out / "index.json").read_bytes() == expected
    assert rows == [release_pipeline._artifact(tmp_path / "one-shot", "index.json", expected, "index-role")]
    assert rows[0]["sha256"] == sha256_bytes(expected) and rows[0]["bytes"] == size


def test_a_refused_streamed_document_keeps_the_one_shot_message_and_leaves_no_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "AKIA" + "Q" * 16
    index = {"files": [{"id": "a", "note": secret}], "symbols": [{"id": "b", "note": f"x {secret}"}]}
    with pytest.raises(ReleaseInputError) as one_shot:
        release_pipeline._artifact(tmp_path / "one-shot", "index.json", canonical_json(index), "role")
    with pytest.raises(ReleaseInputError) as streamed:
        release_pipeline._streamed_json_artifact(tmp_path / "streamed", "index.json", index, "role")
    assert (
        str(streamed.value)
        == str(one_shot.value)
        == ("generated-output privacy scan failed: index.json:1:aws_access_key, index.json:1:aws_access_key")
    )
    assert not (tmp_path / "streamed" / "index.json").exists()

    # A failure while removing the partial file never masks the refusal.
    def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("unlink refused")

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(ReleaseInputError, match="^generated-output privacy scan failed: "):
        release_pipeline._streamed_json_artifact(tmp_path / "masked", "index.json", index, "role")


_SECRETS = (
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
    "AKIA" + "A" * 16,
    "ASIA" + "Z9" * 8,
    "ghp_" + "a" * 36,
    "sk-" + "x" * 32,
    "sk-proj-" + "y_" * 20,
    "xoxb-" + "1-" * 12,
    "AIza" + "Q" * 35,
)
_NOISE = 'abAZ09_- "\n{}[],:é' + ASTRAL


def _adversarial_text(generator: random.Random) -> str:
    parts = []
    for _ in range(generator.randrange(1, 12)):
        if generator.random() < 0.4:
            secret = generator.choice(_SECRETS)
            if generator.random() < 0.3:
                cut = generator.randrange(len(secret))
                secret = secret[:cut] + generator.choice('",:\n{') + secret[cut:]
            parts.append(secret)
        else:
            parts.append("".join(generator.choice(_NOISE) for _ in range(generator.randrange(0, 20))))
    return "".join(parts)


def test_bounded_scans_return_exactly_the_whole_text_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    import atlas_privacy

    # The segmenting proof holds for exactly the reviewed rule sources.
    assert atlas_privacy._segmenting_reviewed() is True
    generator = random.Random(64)
    compared = 0
    for _ in range(2_000):
        text = _adversarial_text(generator)
        raw = text.encode("utf-8")
        if generator.random() < 0.3:
            raw = raw.replace(b"a", b"\xc3", 1)
        expected = _pre_w64a_forbidden_byte_findings("p", raw)
        monkeypatch.setattr(atlas_privacy, "_SCAN_SLICE_BYTES", generator.randrange(1, 40))
        assert forbidden_byte_findings("p", raw) == expected
        scan = ForbiddenContentScan("p")
        decoded = raw.decode("utf-8", errors="ignore")
        position = 0
        while position < len(decoded):
            step = generator.randrange(1, 15)
            scan.feed(decoded[position : position + step])
            position += step
        assert scan.finish() == expected
        compared += bool(expected)
    assert compared > 200, "too few cases with a finding to compare"

    # An unreviewed rule (here one that can match a separator) switches
    # segmenting off, so findings across a piece boundary are still found.
    import re

    extra = (*atlas_privacy.FORBIDDEN_CONTENT_RULES, ("colon_rule", re.compile(r"a:b")))
    monkeypatch.setattr(atlas_privacy, "FORBIDDEN_CONTENT_RULES", extra)
    assert atlas_privacy._segmenting_reviewed() is False
    scan = ForbiddenContentScan("p")
    for piece in ("xa:", "b\n", "a", ":b"):
        scan.feed(piece)
    assert scan.finish() == [
        {"path": "p", "line": 1, "rule": "colon_rule"},
        {"path": "p", "line": 2, "rule": "colon_rule"},
    ]


def test_a_verified_entry_is_refused_on_size_before_it_is_read(tmp_path: Path) -> None:
    import release.model as release_model

    source = tmp_path / "source"
    _write(source / "entry.json", b"0123456789")
    short = VerifiedFile(source, "entry.json", sha256_bytes(b"01234"), 5, changed_message="changed: entry.json")
    opened: list[str] = []
    real_open = Path.open

    def recording_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        opened.append(self.name)
        return real_open(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "open", recording_open)
        with pytest.raises(ReleaseInputError, match=r"^changed: entry\.json$"):
            short.read()
    assert opened == []
    exact = VerifiedFile(source, "entry.json", sha256_bytes(b"0123456789"), 10, changed_message="changed")
    assert exact.read() == b"0123456789"

    # The written archive is re-read through its own handle and must hold
    # exactly its entries.
    good = deterministic_zip({"a": b"1", "b": b"2"})
    release_model._verify_written_archive(io.BytesIO(good), {"a": b"1", "b": b"2"}, "x.zip")
    for entries, raw in (
        ({"a": b"1", "b": b"3"}, good),
        ({"a": b"1"}, good),
        ({"a": b"1", "b": b"2"}, good[:-30]),
    ):
        with pytest.raises(ReleaseInputError, match=r"^streamed archive differs from its entries: x\.zip$"):
            release_model._verify_written_archive(io.BytesIO(raw), entries, "x.zip")


def test_a_declared_line_record_count_must_equal_the_line_group(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    count = len(_group_records(compiler, "lines"))

    def declare(value: Any) -> Callable[[dict[str, Any]], None]:
        def transform(completeness: dict[str, Any]) -> None:
            completeness["parsing"]["line_records"] = value

        return transform

    _rewrite_compiler_completeness(compiler, declare(count))
    for retained in (None, RELEASE_RETAINED_GROUPS):
        load_compiler_bundle(compiler, retained_groups=retained, repository_root=repo)
    for value in (count + 1, count - 1, str(count), True):
        _rewrite_compiler_completeness(compiler, declare(value))
        for retained in (None, RELEASE_RETAINED_GROUPS):
            with pytest.raises(ReleaseInputError) as refusal:
                load_compiler_bundle(compiler, retained_groups=retained, repository_root=repo)
            assert str(refusal.value) == "compiler completeness line-record count differs from the line group"


def test_validators_cannot_read_a_group_they_do_not_hold() -> None:
    held = compiler_bundle._ValidatorRecords({"files": [{"id": "x"}]})
    assert held["files"] == held.get("files") == [{"id": "x"}]
    for group in ("source_text", "lines", "calls", "not-a-group"):
        refusal = rf"^compiler validator read a record group it does not hold: {group}$"
        with pytest.raises(ReleaseInputError, match=refusal):
            held[group]
        with pytest.raises(ReleaseInputError, match=refusal):
            held.get(group, [])


def test_every_literal_validator_read_is_a_held_group() -> None:
    tree = ast.parse((MASTER_REFERENCE / "release" / "compiler_bundle.py").read_text(encoding="utf-8"))
    reads: set[str] = set()
    for node in ast.walk(tree):
        target: ast.AST | None = None
        key: ast.AST | None = None
        if isinstance(node, ast.Subscript):
            target, key = node.value, node.slice
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
        ):
            target, key = node.func.value, node.args[0]
        if isinstance(target, ast.Name) and target.id == "records" and isinstance(key, ast.Constant):
            reads.add(str(key.value))
    assert reads, "the scan found no validator reads, so it scanned nothing"
    assert reads <= compiler_bundle._VALIDATION_RECORD_GROUPS, reads - compiler_bundle._VALIDATION_RECORD_GROUPS
    # The fixed-path source_text records are passed explicitly; they never
    # masquerade under the full group's name.
    assert "source_text" not in reads and "lines" not in reads


def test_preservation_binds_to_the_intake_snapshot(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    bundle = load_compiler_bundle(compiler, retained_groups=RELEASE_RETAINED_GROUPS, repository_root=repo)
    manifest_bytes = (compiler / "manifest.json").read_bytes()
    assert isinstance(bundle.chunk_receipts, MappingProxyType)
    assert isinstance(bundle.input_receipts, MappingProxyType)
    with pytest.raises(TypeError):
        bundle.input_receipts["chunks/lines/00000.json"] = ("0" * 64, 0)  # type: ignore[index]
    assert set(bundle.input_receipts) | {"manifest.json"} == set(bundle.input_files)

    # Tampering with the mutable manifest dictionary changes nothing preserved.
    bundle.manifest["groups"]["lines"]["chunks"][0]["sha256"] = "0" * 64
    bundle.manifest["schema_version"] = "tampered"
    entries = release_pipeline._compiler_preservation_entries(bundle)
    assert entries["compiler/manifest.json"] == manifest_bytes
    assert entries[f"compiler/{LINES_CHUNK}"].read() == (compiler / LINES_CHUNK).read_bytes()  # type: ignore[union-attr]
