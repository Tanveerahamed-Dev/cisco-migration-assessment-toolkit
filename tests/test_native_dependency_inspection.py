"""Synthetic complete-wheel controls, never a real producer/licence admission."""

import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest

from portable import native_dependency as dependency
from portable.native_origin import NativeRefusal


DIST = "proxy_tools-0.1.0.dist-info/"
SOURCE = b"# Synthetic package; no upstream code or licence acceptance.\n"
LICENSE = b"SYNTHETIC LICENCE FIXTURE ONLY\n"


def wheel(*, changes=None, record_changes=None):
    files = {
        "proxy_tools/__init__.py": SOURCE,
        DIST + "licenses/LICENSE": LICENSE,
        DIST + "METADATA": b"Metadata-Version: 2.4\nName: proxy_tools\nVersion: 0.1.0\nLicense: MIT\nLicense-File: LICENSE\n\n",
        DIST + "WHEEL": b"Wheel-Version: 1.0\nGenerator: synthetic\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n",
        DIST + "top_level.txt": b"proxy_tools\n",
    }
    files.update(changes or {})
    record = {path: ["sha256=" + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode(),
                     str(len(raw))] for path, raw in files.items()}
    record[DIST + "RECORD"] = ["", ""]
    record.update(record_changes or {})
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerows([path, *value] for path, value in sorted(record.items()))
    files[DIST + "RECORD"] = text.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, raw in sorted(files.items()):
            archive.writestr(path, raw)
    return output.getvalue()


def inspect(raw, monkeypatch):
    # Exercise the structural inspector on an explicitly synthetic source. This
    # does not replace the real pinned source hash or admit any actual wheel.
    monkeypatch.setattr(dependency, "PROXY_SOURCE_SHA256", hashlib.sha256(SOURCE).hexdigest())
    return dependency.inspect_proxy_wheel(raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                                          applicable_license_sha256=hashlib.sha256(LICENSE).hexdigest())


def test_structural_result_explicitly_grants_no_producer_legal_release_or_publication_authority(monkeypatch):
    result = inspect(wheel(), monkeypatch)
    assert result["producer_identity"] == "NOT_VERIFIED"
    assert result["license_acceptance"] == "NOT_VERIFIED"
    assert result["immutable_release"] == "NOT_VERIFIED"
    assert result["production_authority"] == "NOT_GRANTED"
    assert len(result["members"]) == 6


@pytest.mark.parametrize("path", [
    "startup.pth", "sitecustomize.py", "unexpected/__init__.py", "proxy_tools/native.pyd",
    "proxy_tools-0.1.0.data/scripts/launch", "../escape.py", DIST + "entry_points.txt",
])
def test_even_record_listed_extra_code_hooks_scripts_or_packages_refuse(path, monkeypatch):
    with pytest.raises(NativeRefusal):
        inspect(wheel(changes={path: b"unexpected synthetic member"}), monkeypatch)


@pytest.mark.parametrize("name,value", [
    ("Name", "another-package"), ("Version", "0.1.1"),
    ("Requires-Dist", "unexpected==1"), ("Provides-Extra", "unexpected"), ("Requires-Python", ">=4"),
])
def test_dependency_metadata_must_match_the_source_package(name, value, monkeypatch):
    metadata = b"Metadata-Version: 2.4\nName: proxy_tools\nVersion: 0.1.0\nLicense: MIT\nLicense-File: LICENSE\n"
    metadata += f"{name}: {value}\n\n".encode()
    with pytest.raises(NativeRefusal):
        inspect(wheel(changes={DIST + "METADATA": metadata}), monkeypatch)


@pytest.mark.parametrize("path,raw", [
    ("proxy_tools/__init__.py", b"changed-source"), (DIST + "licenses/LICENSE", b"different attribution"),
    (DIST + "top_level.txt", b"proxy_tools\nother\n"),
    (DIST + "WHEEL", b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: cp312-cp312-win_amd64\n\n"),
])
def test_source_license_and_pure_python_tag_refuse_drift(path, raw, monkeypatch):
    with pytest.raises(NativeRefusal):
        inspect(wheel(changes={path: raw}), monkeypatch)


def test_record_hashes_and_sizes_cover_the_complete_closed_file_set(monkeypatch):
    with pytest.raises(NativeRefusal):
        inspect(wheel(record_changes={"proxy_tools/__init__.py": ["sha256=wrong", "0"]}), monkeypatch)


@pytest.mark.parametrize("carrier", ["prefix", "suffix", "duplicate"])
def test_unindexed_or_duplicate_carriers_are_not_hidden_by_a_matching_selected_digest(carrier, monkeypatch):
    raw = wheel()
    if carrier == "prefix":
        raw = b"unindexed" + raw
    elif carrier == "suffix":
        raw += b"unindexed"
    else:
        output = io.BytesIO(raw)
        with zipfile.ZipFile(output, "a") as archive:
            archive.writestr("proxy_tools/__init__.py", SOURCE)
        raw = output.getvalue()
    with pytest.raises(NativeRefusal):
        inspect(raw, monkeypatch)


def test_current_dependency_record_is_held_and_preserves_the_source_license_conflict():
    root = Path(__file__).resolve().parents[1]
    record = json.loads((root / "portable/native_dependency_inputs.json").read_text(encoding="utf-8"))
    assert record["status"] == "HELD"
    assert record["proxy_tools"]["source_sha256"] == dependency.PROXY_SDIST_SHA256
    assert record["proxy_tools"]["package_source"]["sha256"] == dependency.PROXY_SOURCE_SHA256
    assert record["proxy_tools"]["metadata_license_declaration"] == "MIT"
    assert record["proxy_tools"]["package_source"]["header_license_declaration"] == "BSD"
    assert record["proxy_tools"]["standalone_license_present"] is False
    assert record["proxy_tools"]["accepted_wheel"] is None
    assert record["producer_authority"] == record["publication_authority"] == "NOT_GRANTED"
