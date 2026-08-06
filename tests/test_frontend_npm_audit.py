"""Fail-closed contracts for the one reviewed frontend npm audit exception."""

from __future__ import annotations

import copy
import importlib.util
import json
from collections import Counter
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / ".github" / "scripts" / "verify_frontend_npm_audit.py"
    spec = importlib.util.spec_from_file_location("_frontend_npm_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _allowed_vulnerability(module):
    return copy.deepcopy(module._EXEMPT_VULNERABILITY)


def _other_vulnerability(module, name="other-package", severity="high"):
    record = _allowed_vulnerability(module)
    record["name"] = name
    record["severity"] = severity
    record["isDirect"] = False
    record["via"][0]["source"] += 1
    record["via"][0]["name"] = name
    record["via"][0]["dependency"] = name
    record["via"][0]["title"] = "Different reviewed advisory"
    record["via"][0]["url"] = "https://github.com/advisories/GHSA-xxxx-yyyy-zzzz"
    record["via"][0]["severity"] = severity
    record["via"][0]["range"] = ">=1 <2"
    record["range"] = ">=1 <2"
    record["nodes"] = [f"node_modules/{name}"]
    return record


def _report(vulnerabilities):
    counts = Counter(
        vulnerability["severity"] for vulnerability in vulnerabilities.values()
    )
    return {
        "auditReportVersion": 2,
        "vulnerabilities": vulnerabilities,
        "metadata": {
            "vulnerabilities": {
                "info": counts["info"],
                "low": counts["low"],
                "moderate": counts["moderate"],
                "high": counts["high"],
                "critical": counts["critical"],
                "total": len(vulnerabilities),
            },
            "dependencies": {
                "prod": 51,
                "dev": 225,
                "optional": 53,
                "peer": 8,
                "peerOptional": 0,
                "total": 275,
            },
        },
    }


def _validated(module, report):
    return module.parse_audit_report(json.dumps(report).encode("utf-8"))


def _frontend_fixture(tmp_path: Path):
    module = _module()
    repository = tmp_path / "repository"
    frontend = repository / "webapp" / "frontend"
    source = frontend / "src"
    source.mkdir(parents=True)
    (repository / ".design-sync").mkdir()
    package = {
        "name": "fixture-frontend",
        "private": True,
        "engines": {"node": module._CURRENT_NODE_CONTRACT},
        "dependencies": dict(module._CURRENT_FRONTEND_CONTRACT),
        "devDependencies": dict(module._CURRENT_DEV_CONTRACT),
    }
    packages = {
        "": {
            "dependencies": dict(module._CURRENT_FRONTEND_CONTRACT),
            "devDependencies": dict(module._CURRENT_DEV_CONTRACT),
        }
    }
    for name, version in {
        **module._CURRENT_FRONTEND_CONTRACT,
        **module._CURRENT_DEV_CONTRACT,
    }.items():
        packages[f"node_modules/{name}"] = {"version": version}
    lock = {
        "name": "fixture-frontend",
        "lockfileVersion": 3,
        "requires": True,
        "packages": packages,
    }
    (frontend / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (frontend / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    (source / "main.tsx").write_text(
        'import { BrowserRouter, Routes } from "react-router";\n',
        encoding="utf-8",
    )
    return module, frontend, package, lock


def test_audit_policy_accepts_clean_report_without_using_exception():
    module = _module()
    report = _validated(module, _report({}))

    decision = module.evaluate_audit_report(report, 0)

    assert not decision.exemption_used
    assert "without an exception" in decision.message


def test_audit_policy_accepts_only_the_exact_reviewed_direct_rsc_advisory():
    module = _module()
    allowed = _allowed_vulnerability(module)
    report = _validated(module, _report({"react-router": allowed}))

    decision = module.evaluate_audit_report(report, 1)

    assert decision.exemption_used
    assert "GHSA-qwww-vcr4-c8h2" in decision.message
    assert allowed["isDirect"] is True
    assert allowed["via"][0]["range"] == ">=7.12.0 <8.3.0"
    assert allowed["range"] == "7.12.0 - 8.2.0"
    assert allowed["fixAvailable"] == {
        "name": "react-router",
        "version": "8.3.0",
        "isSemVerMajor": True,
    }


def test_audit_exception_review_window_is_inclusive_and_then_fails_closed():
    module = _module()

    module.assert_exception_review_current(date(2026, 11, 6))
    with pytest.raises(module.FrontendAuditError, match="expired on 2026-11-06"):
        module.assert_exception_review_current(date(2026, 11, 7))


def test_audit_toolchain_accepts_only_exact_reviewed_node_and_npm(monkeypatch):
    module = _module()
    versions = {
        "Node": module._EXPECTED_NODE_VERSION,
        "npm": module._EXPECTED_NPM_VERSION,
    }
    monkeypatch.setattr(
        module,
        "_read_tool_version",
        lambda _command, label: versions[label],
    )

    module.assert_audit_toolchain()

    versions["Node"] = "v24.6.0"
    with pytest.raises(module.FrontendAuditError, match="reviewed audit toolchain"):
        module.assert_audit_toolchain()


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(returncode=2, stdout=b"", stderr=b"tool failed"),
        SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
        SimpleNamespace(returncode=0, stdout=b"20.20.2 extra\n", stderr=b""),
    ],
)
def test_audit_tool_version_reader_fails_closed(monkeypatch, result):
    module = _module()
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: result)

    with pytest.raises(module.FrontendAuditError):
        module._read_tool_version(("node", "--version"), "Node")


def test_main_checks_expiry_before_audit_even_when_registry_would_be_clean(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    monkeypatch.setattr(module, "assert_spa_only_exception_contract", lambda _root: None)

    def expired():
        raise module.FrontendAuditError("review expired on 2026-11-06")

    monkeypatch.setattr(module, "assert_exception_review_current", expired)
    monkeypatch.setattr(
        module,
        "_run_npm_audit",
        lambda _root: pytest.fail("audit ran after the review deadline failed"),
    )

    assert module.main(["--frontend-root", str(tmp_path)]) == 1
    assert "review expired" in capsys.readouterr().err


def test_main_refuses_to_audit_under_an_unreviewed_toolchain(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    monkeypatch.setattr(module, "assert_spa_only_exception_contract", lambda _root: None)
    monkeypatch.setattr(module, "assert_exception_review_current", lambda: None)

    def unreviewed_toolchain():
        raise module.FrontendAuditError("unreviewed Node/npm pair")

    monkeypatch.setattr(module, "assert_audit_toolchain", unreviewed_toolchain)
    monkeypatch.setattr(
        module,
        "_run_npm_audit",
        lambda _root: pytest.fail("audit ran under an unreviewed toolchain"),
    )

    assert module.main(["--frontend-root", str(tmp_path)]) == 1
    assert "unreviewed Node/npm pair" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        (
            "transitive",
            lambda record: record.__setitem__("isDirect", False),
        ),
        (
            "different advisory",
            lambda record: record["via"][0].__setitem__(
                "url", "https://github.com/advisories/GHSA-xxxx-yyyy-zzzz"
            ),
        ),
        (
            "different range",
            lambda record: record["via"][0].__setitem__("range", ">=7 <9"),
        ),
        (
            "extra advisory",
            lambda record: record["via"].append("another-package"),
        ),
        (
            "fix shape changed",
            lambda record: record["fixAvailable"].__setitem__(
                "version", "8.3.1"
            ),
        ),
    ],
)
def test_audit_policy_rejects_any_drift_in_reviewed_exception(label, mutate):
    module = _module()
    record = _allowed_vulnerability(module)
    mutate(record)
    report = _validated(module, _report({"react-router": record}))

    with pytest.raises(module.FrontendAuditError, match="no longer exactly matches"):
        module.evaluate_audit_report(report, 1)


@pytest.mark.parametrize("severity", ["high", "critical"])
def test_audit_policy_rejects_every_additional_blocking_vulnerability(severity):
    module = _module()
    report = _validated(
        module,
        _report(
            {
                "react-router": _allowed_vulnerability(module),
                "other-package": _other_vulnerability(module, severity=severity),
            }
        ),
    )

    with pytest.raises(module.FrontendAuditError, match="other-package"):
        module.evaluate_audit_report(report, 1)


def test_audit_policy_preserves_npm_high_threshold_for_lower_findings():
    module = _module()
    report = _validated(
        module,
        _report(
            {
                "react-router": _allowed_vulnerability(module),
                "moderate-package": _other_vulnerability(
                    module, name="moderate-package", severity="moderate"
                ),
            }
        ),
    )

    assert module.evaluate_audit_report(report, 1).exemption_used


def test_audit_policy_cannot_hide_high_advisory_behind_lower_package_severity():
    module = _module()
    record = _other_vulnerability(
        module, name="malformed-package", severity="moderate"
    )
    record["via"][0]["severity"] = "critical"
    report = _validated(module, _report({"malformed-package": record}))

    with pytest.raises(module.FrontendAuditError, match="malformed-package"):
        module.evaluate_audit_report(report, 1)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not JSON",
        b"[]",
        json.dumps({"auditReportVersion": 2}).encode("utf-8"),
    ],
)
def test_audit_policy_rejects_empty_malformed_or_partial_output(raw):
    module = _module()

    with pytest.raises(module.FrontendAuditError):
        module.parse_audit_report(raw)


def test_audit_policy_rejects_schema_drift_and_metadata_disagreement():
    module = _module()
    unexpected = _report({})
    unexpected["newNpmField"] = True
    with pytest.raises(module.FrontendAuditError, match="unexpected audit report keys"):
        _validated(module, unexpected)

    inconsistent = _report({"react-router": _allowed_vulnerability(module)})
    inconsistent["metadata"]["vulnerabilities"]["high"] = 0
    with pytest.raises(module.FrontendAuditError, match="count disagrees"):
        _validated(module, inconsistent)


@pytest.mark.parametrize(
    ("report", "exit_code"),
    [
        (_report({}), 1),
        (_report({}), 2),
    ],
)
def test_audit_policy_rejects_unexpected_npm_exit_status(report, exit_code):
    module = _module()

    with pytest.raises(module.FrontendAuditError, match="exit status disagrees"):
        module.evaluate_audit_report(_validated(module, report), exit_code)


def test_spa_contract_accepts_only_current_locked_browser_stack(tmp_path):
    module, frontend, _, _ = _frontend_fixture(tmp_path)

    module.assert_spa_only_exception_contract(frontend)


def test_repository_spa_contract_scans_the_current_complete_source_tree():
    module = _module()

    module.assert_spa_only_exception_contract(ROOT / "webapp" / "frontend")


def test_spa_contract_expires_on_router_or_platform_contract_change(tmp_path):
    module, frontend, package, _ = _frontend_fixture(tmp_path)
    package["dependencies"]["react-router"] = "8.3.0"
    (frontend / "package.json").write_text(json.dumps(package), encoding="utf-8")

    with pytest.raises(module.FrontendAuditError, match="exception expired"):
        module.assert_spa_only_exception_contract(frontend)


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        ("src/entry.rsc.tsx", "export default function Entry() {}\n"),
        ("src/dist/server.ts", 'const mode = "RSC";\n'),
        (
            "src/server.ts",
            'import { unstable_matchRSCServerRequest } from "react-router";\n',
        ),
        (
            "src/server.ts",
            'import { RSCStaticRouter } from "react-router";\n',
        ),
    ],
)
def test_spa_contract_rejects_any_rsc_filename_or_api(relative, source, tmp_path):
    module, frontend, _, _ = _frontend_fixture(tmp_path)
    path = frontend / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")

    with pytest.raises(module.FrontendAuditError, match="RSC usage"):
        module.assert_spa_only_exception_contract(frontend)


@pytest.mark.parametrize("dependency", ["@react-router/dev", "@vitejs/plugin-rsc"])
def test_spa_contract_rejects_rsc_capable_dependencies(tmp_path, dependency):
    module, frontend, package, _ = _frontend_fixture(tmp_path)
    package["devDependencies"][dependency] = "7.18.2"
    (frontend / "package.json").write_text(json.dumps(package), encoding="utf-8")

    with pytest.raises(module.FrontendAuditError, match="RSC-capable dependencies"):
        module.assert_spa_only_exception_contract(frontend)


def test_spa_contract_scans_valid_empty_source_but_rejects_project_npmrc(tmp_path):
    module, frontend, _, _ = _frontend_fixture(tmp_path)
    (frontend / "src" / "empty.ts").write_bytes(b"")
    module.assert_spa_only_exception_contract(frontend)

    (frontend / ".npmrc").write_text("registry=https://example.invalid/\n", encoding="utf-8")
    with pytest.raises(module.FrontendAuditError, match=r"\.npmrc"):
        module.assert_spa_only_exception_contract(frontend)


def test_spa_contract_scans_reviewed_external_design_sources(tmp_path):
    module, frontend, _, _ = _frontend_fixture(tmp_path)
    provider = frontend.parents[1] / ".design-sync" / "providers" / "demo.tsx"
    provider.parent.mkdir()
    provider.write_text('const serverMode = "RSC";\n', encoding="utf-8")

    with pytest.raises(module.FrontendAuditError, match="RSC usage"):
        module.assert_spa_only_exception_contract(frontend)


def test_spa_contract_rejects_relative_modules_outside_reviewed_roots(tmp_path):
    module, frontend, _, _ = _frontend_fixture(tmp_path)
    outside = frontend.parents[1] / "other" / "module.ts"
    outside.parent.mkdir()
    outside.write_text("export const value = 1;\n", encoding="utf-8")
    (frontend / "src" / "main.tsx").write_text(
        'import { value } from "../../../other/module";\n', encoding="utf-8"
    )

    with pytest.raises(module.FrontendAuditError, match="escapes the reviewed"):
        module.assert_spa_only_exception_contract(frontend)


def test_spa_contract_rejects_linked_source_directories(tmp_path):
    module, frontend, _, _ = _frontend_fixture(tmp_path)
    external = frontend.parents[1] / "linked-source"
    external.mkdir()
    link = frontend / "src" / "linked"
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(module.FrontendAuditError, match="source directory links"):
        module.assert_spa_only_exception_contract(frontend)


def test_npm_audit_uses_public_registry_complete_lock_and_clean_config(
    monkeypatch, tmp_path
):
    module = _module()
    captured = {}
    monkeypatch.setenv("NPM_CONFIG_REGISTRY", "https://example.invalid/")
    monkeypatch.setenv("npm_config_omit", "dev")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module._run_npm_audit(tmp_path) == (b"{}", 0)

    command = captured["command"]
    assert f"--registry={module._NPM_REGISTRY}" in command
    assert "--offline=false" in command
    for group in ("prod", "dev", "optional", "peer"):
        assert f"--include={group}" in command
    environment = captured["kwargs"]["env"]
    assert environment["NPM_CONFIG_REGISTRY"] == module._NPM_REGISTRY
    assert environment["NPM_CONFIG_USERCONFIG"] == module.os.devnull
    assert environment["NPM_CONFIG_GLOBALCONFIG"] == module.os.devnull
    assert "npm_config_omit" not in environment


def test_npm_audit_operational_failure_is_fatal(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=2, stdout=b"", stderr=b"registry unavailable"
        ),
    )

    with pytest.raises(module.FrontendAuditError, match="registry unavailable"):
        module._run_npm_audit(tmp_path)


def test_dependency_audit_workflow_uses_policy_without_force_or_failure_swallowing():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    dependency_job = workflow.split("\n  dependency-audit:", 1)[1].split(
        "\n  package:", 1
    )[0]

    assert (
        "python ../../.github/scripts/verify_frontend_npm_audit.py"
        in dependency_job
    )
    assert "npm audit --audit-level=high" not in dependency_job
    assert "npm audit fix" not in workflow
    assert "npm ci --ignore-scripts" in dependency_job
    assert 'node-version: "20.20.2"' in dependency_job
    assert "continue-on-error" not in dependency_job
    assert "|| true" not in dependency_job
