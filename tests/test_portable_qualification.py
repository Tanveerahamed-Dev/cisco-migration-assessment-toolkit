from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from portable.qualify_atlas import (
    _REDACTION_CANARIES,
    _python_absent,
    _run,
    _sanitize_warning_report,
    _scan_redaction_canaries,
)
from portable.release_contract import PortableReleaseError


def test_redaction_canary_scan_requires_marker_and_catches_plain_and_ooxml_payloads(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    marker = output / "Assessment_redacted.snapshot.json"
    marker.write_text(
        '{"mgmt_ip":"v4-n00001-h001.assesshub-redacted.invalid"}\n',
        encoding="utf-8",
    )
    evidence = _scan_redaction_canaries(output, _REDACTION_CANARIES)
    assert evidence["canary_literals_absent"] is True
    assert evidence["pseudonym_namespace_present"] is True

    planted = output / "planted.txt"
    planted.write_text(_REDACTION_CANARIES[0], encoding="utf-16-le")
    with pytest.raises(PortableReleaseError, match="canary.*survived"):
        _scan_redaction_canaries(output, _REDACTION_CANARIES)
    planted.unlink()

    document = output / "planted.docx"
    with zipfile.ZipFile(document, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", f"<root>{_REDACTION_CANARIES[2]}</root>")
    with pytest.raises(PortableReleaseError, match="canary.*survived"):
        _scan_redaction_canaries(output, _REDACTION_CANARIES)


def test_redaction_canary_scan_refuses_a_vacuous_clean_output(tmp_path: Path) -> None:
    (tmp_path / "empty.json").write_text("{}\n", encoding="ascii")
    with pytest.raises(PortableReleaseError, match="no expected pseudonym"):
        _scan_redaction_canaries(tmp_path, _REDACTION_CANARIES)


def test_warning_report_sanitizer_covers_case_slash_unc_and_device_paths() -> None:
    clean = _sanitize_warning_report(
        b"missing module from c:/BUILD/root/module.py\r\n",
        {r"C:\build\root"},
    )
    assert clean == "missing module from <BUILD_ROOT>/module.py\n"
    for planted in (
        br"remaining D:\private\module.py",
        br"remaining D:/private/module.py",
        br"remaining \\server\share\module.py",
        br"remaining \\?\C:\private\module.py",
    ):
        with pytest.raises(PortableReleaseError, match="absolute Windows path"):
            _sanitize_warning_report(planted, set())


def test_python_absence_probe_fails_closed_without_where_exe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SystemRoot", str(tmp_path / "missing-windows"))
    assert _python_absent({}) is False


def test_qualification_children_run_from_the_isolated_temp_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _run(["Atlas.exe", "--version"], environment={"TEMP": str(tmp_path)})
    assert observed["cwd"] == str(tmp_path.resolve(strict=True))
