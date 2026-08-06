"""Executable contract for AssessHub's Node 24 / React 19 platform."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "webapp" / "frontend"
NODE_GUARD = FRONTEND / "scripts" / "verify-node.mjs"
NODE = shutil.which("node")

NODE_ENGINE = ">=24.18.0 <25"
HOSTED_NODE = "24.19.0"
RUNTIME_PACKAGES = {
    "react": "19.2.8",
    "react-dom": "19.2.8",
    "react-router": "8.3.0",
}
DEVELOPMENT_PACKAGES = {
    "@types/node": "24.13.3",
    "@types/react": "19.2.18",
    "@types/react-dom": "19.2.4",
    "@vitejs/plugin-react": "6.0.5",
    "vite": "8.2.1",
}


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _job(path, name):
    """Return one top-level workflow job without depending on a YAML library."""
    lines = path.read_text(encoding="utf-8").splitlines()
    marker = f"  {name}:"
    try:
        start = lines.index(marker)
    except ValueError as error:
        raise AssertionError(f"{path.name} has no {name!r} job") from error
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.fullmatch(r"  [A-Za-z0-9_-]+:\s*", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def _assert_guard_precedes_install(job, label):
    guard = job.find("verify:node")
    install = re.search(r"\bnpm(?:\s+--prefix\s+\S+)?\s+ci\b", job)
    assert guard >= 0, f"{label} does not execute the Node platform guard"
    assert install, f"{label} has no locked npm install for the guard to protect"
    assert guard < install.start(), f"{label} installs packages before checking its Node runtime"


def test_frontend_manifest_and_lock_pin_the_migrated_platform_exactly():
    manifest = _json(FRONTEND / "package.json")
    lock = _json(FRONTEND / "package-lock.json")
    locked_root = lock["packages"][""]

    assert manifest["engines"]["node"] == NODE_ENGINE
    assert locked_root["engines"]["node"] == NODE_ENGINE
    assert manifest["scripts"]["verify:node"] == "node scripts/verify-node.mjs"

    for name, version in RUNTIME_PACKAGES.items():
        assert manifest["dependencies"][name] == version
        assert locked_root["dependencies"][name] == version
        assert lock["packages"][f"node_modules/{name}"]["version"] == version
    for name, version in DEVELOPMENT_PACKAGES.items():
        assert manifest["devDependencies"][name] == version
        assert locked_root["devDependencies"][name] == version
        assert lock["packages"][f"node_modules/{name}"]["version"] == version


@pytest.mark.skipif(not NODE, reason="Node is unavailable")
def test_node_guard_accepts_only_the_exact_manifest_contract_and_stable_node_24_range():
    module_url = NODE_GUARD.as_uri()

    def probe(engine, runtime):
        source = (
            f"import {{ assertNodePlatform }} from {json.dumps(module_url)};"
            "try {"
            f"assertNodePlatform({{manifestEngine:{json.dumps(engine)},runtimeVersion:{json.dumps(runtime)}}});"
            "} catch (error) { console.error(error.message); process.exit(1); }"
        )
        return subprocess.run(
            [NODE, "--input-type=module", "--eval", source],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
            timeout=30,
        )

    for version in ("24.18.0", "v24.19.0", "24.999.999"):
        result = probe(NODE_ENGINE, version)
        assert result.returncode == 0, result.stderr

    rejected = (
        (NODE_ENGINE, "24.17.999"),
        (NODE_ENGINE, "23.99.99"),
        (NODE_ENGINE, "25.0.0"),
        (NODE_ENGINE, "24.19.0-rc.1"),
        (NODE_ENGINE, "24.19"),
        (">=24 <25", "24.19.0"),
    )
    for engine, version in rejected:
        result = probe(engine, version)
        assert result.returncode != 0, f"guard accepted engines={engine!r}, runtime={version!r}"
        assert result.stderr.strip()


def test_hosted_frontend_jobs_pin_node_and_guard_before_installing():
    workflows = {
        ".github/workflows/ci.yml": ("dependency-audit", "package"),
        ".github/workflows/release.yml": ("release",),
        ".github/workflows/webapp-ci.yml": ("frontend", "e2e", "visual"),
    }
    for relative_path, jobs in workflows.items():
        path = ROOT / relative_path
        for name in jobs:
            job = _job(path, name)
            label = f"{path.name}:{name}"
            assert job.count("uses: actions/setup-node@") == 1, label
            assert job.count(f'node-version: "{HOSTED_NODE}"') == 1, label
            _assert_guard_precedes_install(job, label)


def test_self_hosted_frontend_jobs_fail_before_install_on_an_unsupported_node():
    workflows = {
        ".github/workflows/main-selfhosted.yml": "frontend",
        ".github/workflows/release-selfhosted.yml": "release",
    }
    for relative_path, name in workflows.items():
        path = ROOT / relative_path
        _assert_guard_precedes_install(_job(path, name), f"{path.name}:{name}")


def test_dependency_audit_is_ordinary_strict_npm_audit_without_an_exception_wrapper():
    workflow = ROOT / ".github" / "workflows" / "ci.yml"
    dependency_audit = _job(workflow, "dependency-audit")
    audit_lines = [line.strip() for line in dependency_audit.splitlines() if "npm audit" in line]

    assert audit_lines == ["npm audit --audit-level=high"]
    assert "--registry=https://registry.npmjs.org/" in dependency_audit
    assert "--offline=false" in dependency_audit
    assert "--include=prod --include=dev --include=optional --include=peer" in dependency_audit
    assert "NPM_CONFIG_USERCONFIG: /dev/null" in dependency_audit
    assert "NPM_CONFIG_GLOBALCONFIG: /dev/null" in dependency_audit
    assert "verify_frontend_npm_audit" not in dependency_audit
    assert "npm audit fix" not in dependency_audit
    assert "GHSA-qwww-vcr4-c8h2" not in dependency_audit
    assert not (ROOT / ".github" / "scripts" / "verify_frontend_npm_audit.py").exists()
    assert not (ROOT / "tests" / "test_frontend_npm_audit.py").exists()
