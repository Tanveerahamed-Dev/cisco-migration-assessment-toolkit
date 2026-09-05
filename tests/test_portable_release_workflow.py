from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from portable import release_contract


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "portable-release.yml"


def test_hash_lock_and_toolchain_contract_reconcile() -> None:
    contract = json.loads((ROOT / "portable" / "toolchain.json").read_text(encoding="utf-8"))
    lock = (ROOT / "portable" / "windows-x64-requirements.lock").read_text(encoding="utf-8")
    assert contract == {
        "schema": "atlas.portable-toolchain-contract/1",
        "platform": "windows-x64",
        "python": "3.12.14",
        "pip": "25.3",
        "pyinstaller": "6.22.2",
        "node": "v24.19.0",
        "npm": "11.16.0",
        "npm_tarball": {
            "url": "https://registry.npmjs.org/npm/-/npm-11.16.0.tgz",
            "sha512_base64": "A74XL8OxmcegZDMWPkWb5bEQppg8HdYwW3rBD2sPoS4UQHVajfaxBkqyzLeJ3wR0kZ+5xoTjItxXaF7eIXUsyw==",
            "sha512_hex": "03be172fc3b199c7a06433163e459be5b110a6983c1dd6305b7ac10f6b0fa12e1440755a8df6b1064ab2ccb789df0474919fb9c684e322dc57685ede21752ccb",
        },
        "dependency_install": "python -m pip install --require-hashes --only-binary=:all: -r portable/windows-x64-requirements.lock",
        "frontend_install": "npm ci --ignore-scripts",
        "authority": "version and hash pins constrain the build; they do not establish publisher identity or field qualification",
    }
    assert {
        "python": release_contract.PYTHON_VERSION,
        "pip": release_contract.PIP_VERSION,
        "pyinstaller": release_contract.PYINSTALLER_VERSION,
        "node": release_contract.NODE_VERSION,
        "npm": release_contract.NPM_VERSION,
    } == {key: contract[key] for key in ("python", "pip", "pyinstaller", "node", "npm")}
    assert contract["npm_tarball"]["sha512_hex"] == release_contract.NPM_TARBALL_SHA512_HEX
    assert contract["npm_tarball"]["sha512_base64"] == release_contract.NPM_TARBALL_SHA512_BASE64
    locked_versions = {
        release_contract._distribution_name(match.group(1)): match.group(2)
        for match in re.finditer(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", lock, re.MULTILINE)
    }
    assert {
        name: locked_versions[name] for name in release_contract.EXPECTED_BUNDLED_PYTHON
    } == release_contract.EXPECTED_BUNDLED_PYTHON
    frontend = release_contract._bundled_frontend_packages(ROOT)
    assert len(frontend) == release_contract.EXPECTED_BUNDLED_FRONTEND_COUNT
    assert release_contract.digest_object(frontend) == release_contract.EXPECTED_BUNDLED_FRONTEND_DIGEST
    assert f"pyinstaller=={contract['pyinstaller']} " in lock
    assert "setuptools==84.0.0 " in lock
    assert "cyclonedx-python-lib==11.12.0 " in lock
    assert "jsonschema==4.26.0 " in lock
    assert "jsonschema-specifications==2025.9.1 " in lock
    assert "pip==25.3 " in lock
    assert "--hash=sha256:" in lock
    assert "\r" not in lock


def test_portable_workflow_separates_untrusted_build_from_draft_write_authority() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in text and "workflow_dispatch:" in text
    portable = text.split("  portable:", 1)[1].split("  draft:", 1)[0]
    draft = text.split("  draft:", 1)[1]
    assert "contents: read" in portable
    assert "contents: write" not in portable
    assert "id-token: write" not in portable
    assert "contents: write" in draft and "attestations: write" in draft
    assert "github.event_name == 'workflow_dispatch'" in draft
    assert "portable.build_release" in portable
    assert "--require-hashes --only-binary=:all:" in portable
    assert "npm install --global" not in portable
    assert "npm tarball SHA-512 mismatch" in portable
    assert text.count("git config core.autocrlf false") == 2
    assert text.count("git rm --cached -r --quiet .") == 2
    assert "python -m pytest -q -p no:cacheprovider" in text
    gate = text.split("  gate:", 1)[1].split("  portable:", 1)[0]
    assert "contents: write" not in gate and "id-token: write" not in gate
    assert "--release-dir" in portable
    assert "atlas-portable-release\\portable-controller.json" not in portable
    assert "--draft --prerelease" in draft
    assert "never overwrites release assets" in draft
    assert "gh attestation verify" in draft
    assert "--signer-workflow" in draft and "--source-digest" in draft
    assert "--predicate-type 'https://cyclonedx.org/bom'" in draft
    assert "actions/attest-sbom@" not in draft
    assert "--stdlib-only" in text
    assert "pip install" not in draft
    assert "protected-main checks not successful" in text
    assert "created draft tag does not resolve to the exact source" in draft
    assert "draft release asset readback differs" in draft
    assert "${{ inputs.draft_tag }}'" not in draft
    for match in re.finditer(r"uses:\s+[^\s]+@([^\s#]+)", text):
        assert re.fullmatch(r"[0-9a-f]{40}", match.group(1)), match.group(0)


def test_archive_release_workflows_create_drafts_only() -> None:
    for name in ("release.yml", "release-selfhosted.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        command = text.split("gh release create", 1)[1]
        assert "--draft" in command
    hosted = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "!contains(github.ref_name, '-rc.')" in hosted


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell 5.1 syntax gate")
@pytest.mark.parametrize("name", ["make_stick.ps1", "sign_release.ps1", "verify_signatures.ps1"])
def test_portable_powershell_scripts_parse_on_windows_powershell(name: str) -> None:
    path = ROOT / "portable" / name
    command = f"$null=[scriptblock]::Create((Get-Content -Raw -LiteralPath '{path}'))"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_signing_machinery_requires_explicit_identity_sha256_and_rfc3161() -> None:
    sign = (ROOT / "portable" / "sign_release.ps1").read_text(encoding="ascii")
    verify = (ROOT / "portable" / "verify_signatures.ps1").read_text(encoding="ascii")
    for token in ("Thumbprint", "/fd SHA256", "/tr $TimestampUrl", "/td SHA256", "/pa /all /tw"):
        assert token in sign
    assert "TEST_SIGNATURE_NOT_TRUSTED" in sign
    assert "SignedBundle" in sign and "fresh path disjoint" in sign
    assert "pre-sign manifest" in sign
    assert "Get-AuthenticodeSignature" in sign and "Get-AuthenticodeSignature" in verify
    assert "Cert:\\CurrentUser\\My" in sign
    assert "Cert:\\LocalMachine\\My" not in sign
    assert "$VerifyOs = '2:10.0.0'" in sign and "$VerifyOs = '2:10.0.0'" in verify
    assert "/o $VerifyOs" in sign and "/o $VerifyOs" in verify
    assert "promotion_eligible = $false" in sign
    for token in (
        "portable-member-manifest.json",
        "manifest_sha256",
        "member_set_digest",
        "executable_member_count",
        "signtool_policy_valid",
        "publisher_subject",
        "publisher_thumbprint",
        "timestamp_verified",
        "signing_lane_certificate_store = 'CurrentUser\\My'",
        "promotion_effect = 'NONE'",
    ):
        assert token in verify
    assert "BEGIN PRIVATE KEY" not in sign + verify
