from __future__ import annotations

from copy import deepcopy
import io
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from portable import qualify_atlas
from portable.qualify_atlas import (
    _REDACTION_CANARIES,
    _python_absent,
    _run,
    _sanitize_warning_report,
    _scan_redaction_canaries,
    _saved_plan_document_evidence,
    _saved_plan_record,
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


def _saved_plan_subject():
    assessment = {"source": "persisted snapshots.snapshot_json blob", "sha256": "sha256:" + "a" * 64,
                  "bytes": 100, "snapshot_id": 1, "campaign_id": 1,
                  "engagement_id": "urn:example:qualification", "label": "Synthetic", "script_version": "3.23.0"}
    requirements = {"fabric_operating_model": "aci", "convergence_budget_ms": 0,
                    "constraints": ["RC8 offline qualification"]}
    plan = {"schema": "atlas.saved_plan/1", "assessment": deepcopy(assessment), "revision": 1,
            "selection_id": 3, "sha256": "sha256:" + "b" * 64, "status": "UNAPPROVED_DRAFT",
            "projection": {"requirements": deepcopy(requirements)}}
    return assessment, requirements, plan


def _saved_plan_docx(text: str, *, target: str = "word/document.xml", main_type: str | None = None) -> bytes:
    word = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    document = ET.Element(word + "document")
    paragraph = ET.SubElement(ET.SubElement(document, word + "body"), word + "p")
    ET.SubElement(ET.SubElement(paragraph, word + "r"), word + "t").text = text
    content = ET.Element("{http://schemas.openxmlformats.org/package/2006/content-types}Types")
    ET.SubElement(content, "{http://schemas.openxmlformats.org/package/2006/content-types}Override", {
        "PartName": "/word/document.xml", "ContentType": main_type or
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    })
    relationships = ET.Element("{http://schemas.openxmlformats.org/package/2006/relationships}Relationships")
    ET.SubElement(relationships, "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship", {
        "Id": "rId1", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
        "Target": target,
    })
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in (("word/document.xml", document), ("[Content_Types].xml", content),
                            ("_rels/.rels", relationships)):
            archive.writestr(name, ET.tostring(value, encoding="utf-8"))
    return output.getvalue()


def _saved_plan_download():
    assessment, _, plan = _saved_plan_subject()
    lines = ["UNAPPROVED DRAFT", f"Original assessment SHA-256: {assessment['sha256']}",
             f"Selected plan SHA-256: {plan['sha256']}", "Revision 1 · Selection 3"]
    headers = {"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               "x-atlas-assessment-sha256": assessment["sha256"], "x-atlas-plan-revision": "1",
               "x-atlas-plan-sha256": plan["sha256"], "x-atlas-plan-selection": "3"}
    return assessment, plan, lines, headers


def test_saved_plan_document_proof_reads_valid_main_docx_and_exact_visible_identity():
    assessment, plan, lines, headers = _saved_plan_download()
    payload = _saved_plan_docx("\n".join(lines))
    evidence = _saved_plan_document_evidence(payload, headers, "mop", assessment, plan)
    assert evidence["bytes"] == len(payload)
    assert evidence["assessment_sha256"] == assessment["sha256"]
    assert evidence["plan_sha256"] == plan["sha256"]
    assert evidence["selection_id"] == 3
    assert evidence["unapproved_draft"] is True


@pytest.mark.parametrize("field", ["x-atlas-assessment-sha256", "x-atlas-plan-revision",
                                   "x-atlas-plan-sha256", "x-atlas-plan-selection", "content-type"])
def test_saved_plan_download_refuses_wrong_http_identity_even_when_docx_text_is_right(field):
    assessment, plan, lines, headers = _saved_plan_download()
    headers[field] = "wrong"
    with pytest.raises(PortableReleaseError, match="headers or bytes differ"):
        _saved_plan_document_evidence(_saved_plan_docx("\n".join(lines)), headers, "mop", assessment, plan)


@pytest.mark.parametrize("line", range(4))
def test_saved_plan_download_refuses_missing_visible_provenance_even_with_right_headers(line):
    assessment, plan, lines, headers = _saved_plan_download()
    del lines[line]
    with pytest.raises(PortableReleaseError, match="visible source, plan or unapproved provenance"):
        _saved_plan_document_evidence(_saved_plan_docx("\n".join(lines)), headers, "nrfu", assessment, plan)


@pytest.mark.parametrize("change", ["not_zip", "wrong_relationship", "wrong_main_type"])
def test_saved_plan_download_refuses_a_fake_docx_with_matching_http_identity(change):
    assessment, plan, lines, headers = _saved_plan_download()
    payload = _saved_plan_docx("\n".join(lines), target="other.xml" if change == "wrong_relationship" else "word/document.xml",
                               main_type="text/plain" if change == "wrong_main_type" else None)
    if change == "not_zip":
        payload = b"not a document"
    with pytest.raises(PortableReleaseError, match="DOCX"):
        _saved_plan_document_evidence(payload, headers, "mop", assessment, plan)


@pytest.mark.parametrize("change", ["boolean_zero", "lost_constraint", "changed_source_type", "wrong_fabric",
                                    "missing_projection", "invalid_plan_digest", "boolean_revision"])
def test_saved_plan_record_refuses_lost_or_respelt_operator_inputs_and_identity(change):
    assessment, requirements, plan = _saved_plan_subject()
    _saved_plan_record(plan, assessment, requirements)
    if change == "boolean_zero":
        plan["projection"]["requirements"]["convergence_budget_ms"] = False
    elif change == "lost_constraint":
        plan["projection"]["requirements"]["constraints"] = []
    elif change == "changed_source_type":
        plan["assessment"]["snapshot_id"] = True
    elif change == "wrong_fabric":
        plan["projection"]["requirements"]["fabric_operating_model"] = "nxos-evpn"
    elif change == "missing_projection":
        plan["projection"] = None
    elif change == "invalid_plan_digest":
        plan["sha256"] = "sha256:short"
    else:
        plan["revision"] = True
    with pytest.raises(PortableReleaseError, match="source, selection or zero requirement"):
        _saved_plan_record(plan, assessment, requirements)


@pytest.mark.parametrize("body_fails", [False, True])
def test_saved_plan_server_drains_large_child_output_and_retains_bounded_failure_tail(
    tmp_path, monkeypatch, capsys, body_fails,
):
    """A real child fills more than a pipe buffer before its simulated health can answer.

    This source test runs on the hosted suite. It substitutes only the executable/HTTP boundary,
    not the output sink or process cleanup, and makes no claim of frozen application acceptance.
    """
    ready = tmp_path / "child-ready.txt"
    state = {}
    real_popen = subprocess.Popen
    real_stop = qualify_atlas.build_atlas._stop_server
    code = (
        "import pathlib,sys,time; "
        "sys.stdout.buffer.write(b'x'*(2*1024*1024)); "
        "sys.stdout.write('\\nsynthetic server diagnostic sentinel\\n'); sys.stdout.flush(); "
        "ready=pathlib.Path(sys.argv[1]); pending=ready.with_name(ready.name+'.pending'); "
        "pending.write_text('ready',encoding='ascii'); pending.replace(ready); time.sleep(30)"
    )

    def start(_command, **kwargs):
        state["output"] = kwargs["stdout"]
        state["nonce"] = kwargs["env"]["ASSESSHUB_INSTANCE_NONCE"]
        state["process"] = real_popen([sys.executable, "-I", "-B", "-c", code, str(ready)], **kwargs)
        return state["process"]

    def health(_request, timeout):
        assert timeout == 3
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "large child stdout blocked before its readiness marker"
        return io.BytesIO(json.dumps({"instance_nonce": state["nonce"]}).encode())

    def stop(process):
        if hasattr(state["output"], "closed"):
            assert not state["output"].closed, "output sink closed before the child was stopped"
        real_stop(process)
        state["stopped"] = True

    monkeypatch.setattr(qualify_atlas.subprocess, "Popen", start)
    monkeypatch.setattr(qualify_atlas.urllib.request, "urlopen", health)
    monkeypatch.setattr(qualify_atlas.build_atlas, "_stop_server", stop)
    monkeypatch.setattr(qualify_atlas, "_port", lambda: 8479)
    environment = {**os.environ, "TEMP": str(tmp_path)}

    def journey():
        with qualify_atlas._saved_plan_server(tmp_path / "Atlas.exe", tmp_path / "data" / "hub.db", environment):
            assert ready.read_text(encoding="ascii") == "ready"
            if body_fails:
                raise RuntimeError("synthetic field request failed")

    if body_fails:
        with pytest.raises(RuntimeError, match="synthetic field request failed"):
            journey()
    else:
        journey()
    assert state["stopped"] is True
    assert state["process"].poll() is not None
    assert state["output"].closed
    error = capsys.readouterr().err
    if body_fails:
        assert "synthetic server diagnostic sentinel" in error
        assert "final 4096 bytes" in error
        assert len(error) < 8192
    else:
        assert "offline saved-plan server log" not in error
