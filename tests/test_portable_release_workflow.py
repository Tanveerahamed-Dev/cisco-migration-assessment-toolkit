from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from portable import release_contract


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "portable-release.yml"


def _assert_pip_owner_reconciliation(
    *,
    contract: dict,
    release_contract_version: str,
    pyproject_text: str,
    lock_text: str,
    workflow_text: str,
) -> None:
    expected = contract["pip"]
    assert expected == release_contract_version == "26.2.1"

    project = tomllib.loads(pyproject_text)
    dependency_groups = [
        ("project", project["project"].get("dependencies", [])),
        *project["project"]["optional-dependencies"].items(),
    ]
    pip_project_rows = []
    for group, rows in dependency_groups:
        try:
            requirements = [Requirement(row) for row in rows]
        except InvalidRequirement as error:
            raise AssertionError("project contains an invalid requirement") from error
        pip_project_rows.extend(
            (group, requirement)
            for requirement in requirements
            if canonicalize_name(requirement.name) == "pip"
        )
    assert len(pip_project_rows) == 1
    pip_group, pip_build = pip_project_rows[0]
    assert pip_group == "build"
    assert str(pip_build.specifier) == f"=={expected}"
    assert not pip_build.extras and pip_build.marker is None and pip_build.url is None

    locked_pip_versions = [
        version
        for name, version in re.findall(
            r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", lock_text, re.MULTILINE
        )
        if release_contract._distribution_name(name) == "pip"
    ]
    assert locked_pip_versions == [expected]

    workflow_pip_installs = []
    for raw_line in workflow_text.splitlines():
        if not re.search(r"\b(?:python\s+-m\s+)?pip\s+install\b", raw_line, re.IGNORECASE):
            continue
        try:
            tokens = shlex.split(raw_line.strip())
        except ValueError as error:
            raise AssertionError("workflow contains malformed shell syntax") from error
        lowered = [token.lower() for token in tokens]
        arguments = None
        for index in range(len(tokens)):
            if lowered[index : index + 4] == ["python", "-m", "pip", "install"]:
                arguments = tokens[index + 4 :]
                break
            if lowered[index : index + 2] == ["pip", "install"]:
                arguments = tokens[index + 2 :]
                break
        if arguments is None:
            continue
        for token in arguments:
            try:
                requirement = Requirement(token)
            except InvalidRequirement:
                continue
            if canonicalize_name(requirement.name) == "pip":
                workflow_pip_installs.append((raw_line.strip(), requirement))
    assert len(workflow_pip_installs) == 1
    workflow_line, workflow_pip = workflow_pip_installs[0]
    assert workflow_line == f"python -m pip install --upgrade 'pip=={expected}'"
    assert str(workflow_pip.specifier) == f"=={expected}"
    assert not workflow_pip.extras and workflow_pip.marker is None and workflow_pip.url is None


def test_hash_lock_and_toolchain_contract_reconcile() -> None:
    contract = json.loads((ROOT / "portable" / "toolchain.json").read_text(encoding="utf-8"))
    lock = (ROOT / "portable" / "windows-x64-requirements.lock").read_text(encoding="utf-8")
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    assert contract == {
        "schema": "atlas.portable-toolchain-contract/1",
        "platform": "windows-x64",
        "python": "3.12.10",
        "pip": "26.2.1",
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
    _assert_pip_owner_reconciliation(
        contract=contract,
        release_contract_version=release_contract.PIP_VERSION,
        pyproject_text=pyproject_text,
        lock_text=lock,
        workflow_text=workflow_text,
    )
    assert "pip" not in release_contract.EXPECTED_BUNDLED_PYTHON
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
    scope = release_contract._bundled_scope_frontend_packages(ROOT)
    assert len(scope) == release_contract.EXPECTED_BUNDLED_SCOPE_FRONTEND_COUNT
    assert release_contract.digest_object(scope) == (
        release_contract.EXPECTED_BUNDLED_SCOPE_FRONTEND_DIGEST)
    assert f"pyinstaller=={contract['pyinstaller']} " in lock
    assert "setuptools==84.0.0 " in lock
    assert "cyclonedx-python-lib==11.12.0 " in lock
    assert "jsonschema==4.26.0 " in lock
    assert "jsonschema-rs==0.58.4 " in lock
    assert "referencing==0.37.0 " in lock
    native_block = re.search(r"(?m)^jsonschema-rs==0\.58\.4 \\\n((?:[ \t].*\n)+)", lock)
    assert native_block is not None
    assert re.findall(r"--hash=sha256:([a-f0-9]{64})", native_block.group()) == [
        "803612a214ce5ccb2ceefe87b3cab4711a7d04694479b5a22f82cb509635d9cc"
    ]
    assert "jsonschema-specifications==2025.9.1 " in lock
    assert "--hash=sha256:" in lock
    assert "\r" not in lock


def _npm_resolve(packages: dict, dependent: str, name: str) -> str | None:
    """Node's resolution over a v3 lock: the nearest ``node_modules/<name>`` walking up from the
    dependent's install path."""
    base = dependent
    while True:
        candidate = f"{base}/node_modules/{name}" if base else f"node_modules/{name}"
        if candidate in packages:
            return candidate
        if not base:
            return None
        head, sep, _tail = base.rpartition("/node_modules/")
        base = head if sep else ""


def test_scope_inventory_covers_the_real_production_closure_of_the_atlas_scope_lock() -> None:
    """Requirement R-PB 3, against the real lock and an INDEPENDENT oracle: walk atlas-scope's
    runtime dependency graph from its root `dependencies` (dependencies, optional dependencies and
    required peers, resolved the way Node resolves them) and require every package reached to be in
    the release inventory. Every inventoried package the walk does not reach must be one the lock
    itself flags devOptional (disclosed over-inclusion of the same lock-derived rule the AssessHub
    SPA uses), never an unexplained extra."""
    lock = json.loads((ROOT / "atlas-scope" / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]
    root_dependencies = packages[""].get("dependencies", {})
    assert {"three", "postprocessing", "react", "react-dom", "zustand"} <= set(root_dependencies)
    reached: set[str] = set()
    pending = [("", name) for name in root_dependencies]
    while pending:
        dependent, name = pending.pop()
        resolved = _npm_resolve(packages, dependent, name)
        assert resolved is not None, (dependent, name)
        if resolved in reached:
            continue
        reached.add(resolved)
        package = packages[resolved]
        optional_peers = {peer for peer, meta in (package.get("peerDependenciesMeta") or {}).items()
                          if meta.get("optional")}
        for field in ("dependencies", "optionalDependencies", "peerDependencies"):
            for child in package.get(field) or {}:
                if field == "peerDependencies" and child in optional_peers:
                    continue
                if field == "optionalDependencies" and _npm_resolve(packages, resolved, child) is None:
                    continue
                pending.append((resolved, child))
    inventory = {row["install_path"]: row for row in release_contract._bundled_scope_frontend_packages(ROOT)}
    assert reached <= set(inventory), sorted(reached - set(inventory))
    for install_path in set(inventory) - reached:
        assert packages[install_path].get("devOptional") is True, install_path
    for install_path in reached:
        assert inventory[install_path]["version"] == packages[install_path]["version"]


@pytest.mark.parametrize(
    "mutated_owner",
    [
        "toolchain",
        "release_contract",
        "pyproject",
        "pyproject_alias",
        "pyproject_dev_alias",
        "lock",
        "workflow",
        "workflow_unpinned",
    ],
)
def test_each_portable_pip_owner_is_required_for_reconciliation(mutated_owner: str) -> None:
    contract = json.loads((ROOT / "portable" / "toolchain.json").read_text(encoding="utf-8"))
    release_contract_version = release_contract.PIP_VERSION
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock_text = (ROOT / "portable" / "windows-x64-requirements.lock").read_text(
        encoding="utf-8"
    )
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    original = (
        json.dumps(contract, sort_keys=True),
        release_contract_version,
        pyproject_text,
        lock_text,
        workflow_text,
    )

    if mutated_owner == "toolchain":
        contract["pip"] = "26.2.0"
    elif mutated_owner == "release_contract":
        release_contract_version = "26.2.0"
    elif mutated_owner == "pyproject":
        pyproject_text = pyproject_text.replace("pip==26.2.1", "pip==26.2.0")
    elif mutated_owner == "pyproject_alias":
        pyproject_text = pyproject_text.replace(
            'build = ["pip==26.2.1",',
            'build = ["pip==26.2.1", "Pip>=99",',
        )
    elif mutated_owner == "pyproject_dev_alias":
        pyproject_text = pyproject_text.replace(
            "dev = [\n",
            'dev = [\n    "Pip>=99",\n',
            1,
        )
    elif mutated_owner == "lock":
        lock_text = lock_text.replace("pip==26.2.1", "pip==26.2.0")
    elif mutated_owner == "workflow":
        workflow_text = workflow_text.replace("pip==26.2.1", "pip==26.2.0")
    else:
        workflow_text = workflow_text.replace(
            "python -m pip install --upgrade 'pip==26.2.1'",
            "python -m pip install --upgrade 'pip==26.2.1'\n"
            "          python -m pip install --upgrade pip",
        )

    assert (
        json.dumps(contract, sort_keys=True),
        release_contract_version,
        pyproject_text,
        lock_text,
        workflow_text,
    ) != original

    with pytest.raises(AssertionError):
        _assert_pip_owner_reconciliation(
            contract=contract,
            release_contract_version=release_contract_version,
            pyproject_text=pyproject_text,
            lock_text=lock_text,
            workflow_text=workflow_text,
        )


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
    assert 'gh release view "$DRAFT_TAG" --repo "$GITHUB_REPOSITORY"' in draft
    assert 'gh release create "$DRAFT_TAG" --repo "$GITHUB_REPOSITORY"' in draft
    assert 'gh release upload "$DRAFT_TAG" --repo "$GITHUB_REPOSITORY"' in draft
    assert "gh attestation verify" in draft
    assert "--signer-workflow" in draft and "--source-digest" in draft
    assert "--predicate-type 'https://cyclonedx.org/bom'" in draft
    assert "id: candidate" in draft
    assert "candidate ZIP denominator is not exactly one" in draft
    assert "candidate SBOM denominator is not exactly one" in draft
    assert "subject-path: ${{ steps.candidate.outputs.zip }}" in draft
    assert "sbom-path: ${{ steps.candidate.outputs.sbom }}" in draft
    assert not re.search(r"(?m)^\s*sbom-path:.*\*", draft)
    assert "actions/attest-sbom@" not in draft
    assert "--stdlib-only" in text
    assert "pip install" not in draft
    assert "protected-main checks not successful" in text
    assert "new draft release metadata differs from the exact source" in draft
    assert "uploaded draft release metadata differs from the exact source" in draft
    assert "targetCommitish" in draft and "publishedAt" in draft
    assert "tag_target=" not in draft
    assert 'releases/tags/${DRAFT_TAG}' not in draft
    assert "draft release asset readback differs" in draft
    verify_candidate = text.split("  verify_candidate:", 1)[1].split("  draft:", 1)[0]
    assert "ref: ${{ github.sha }}" in verify_candidate
    assert "ref: ${{ needs.portable.outputs.source_commit }}" not in verify_candidate
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


def _project_output(field: str) -> tuple[str, str]:
    from portable import atlas_bundle

    project = release_contract._NPM_INVENTORIES[field][0]
    outputs = [output for output in atlas_bundle.BUILD_OUTPUTS
               if output.rsplit("/", 1)[0] == project]
    assert len(outputs) == 1, outputs
    return project, outputs[0]


def test_shared_protocol_autocrlf_checkout_preserves_committed_byte_custody(tmp_path: Path) -> None:
    """The actual shared source must survive Windows checkout without relaxing its byte guard."""
    relative = "webapp/frontend/src/projectionEmbed.ts"
    committed = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{relative}"],
        cwd=ROOT, capture_output=True, check=True, timeout=30,
    ).stdout
    assert b"\n" in committed and b"\r" not in committed
    repository = tmp_path / "checkout"
    source = repository / relative
    source.parent.mkdir(parents=True)
    source.write_bytes(committed)
    (repository / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())

    def git(*arguments: str) -> bytes:
        return subprocess.run(
            ["git", *arguments], cwd=repository, capture_output=True, check=True, timeout=30,
        ).stdout

    git("init", "--quiet")
    git("config", "core.autocrlf", "true")
    git("config", "core.eol", "crlf")
    git("add", "--", ".gitattributes", relative)
    git("-c", "user.name=Byte custody test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Shared protocol checkout")
    assert git("cat-file", "blob", f"HEAD:{relative}") == committed
    source.unlink()
    git("checkout", "--", relative)
    assert source.read_bytes() == committed
    assert release_contract._shared_npm_source_receipts(repository, "atlas-scope/dist-hub") == {
        relative: {"bytes": len(committed), "sha256": hashlib.sha256(committed).hexdigest()},
    }

    # A checkout fix must not admit changed bytes, even if Git's index hides the edit.
    git("update-index", "--assume-unchanged", "--", relative)
    source.write_bytes(committed + b"// intentional custody mutation\n")
    assert git("diff", "--name-only", "HEAD", "--", relative) == b""
    with pytest.raises(release_contract.PortableReleaseError,
                       match="shared npm source bytes differ from committed blob"):
        release_contract._shared_npm_source_receipts(repository, "atlas-scope/dist-hub")


@pytest.mark.parametrize("field", sorted(release_contract._NPM_INVENTORIES))
def test_the_real_built_output_carries_bundler_runtime_packages_and_they_are_inventoried(
        field: str, tmp_path: Path) -> None:
    """W5-X5 against the REAL frontends: build each shipped output the way its npm script does
    (into a scratch tree that mirrors the repository layout), then derive the shipped-package set
    from a module-recording rebuild bound byte-for-byte to it. Vite's preload helper and Rolldown's
    runtime are in BOTH real builds although both packages are dev-only; the derived set beyond the
    production graph must be exactly the reviewed one (a new bundler-injected package must be
    reviewed before a release, as a production lock change already is)."""
    import shutil

    project, output = _project_output(field)
    project_root = ROOT.joinpath(*project.split("/"))
    vite = project_root / "node_modules" / "vite" / "bin" / "vite.js"
    node = shutil.which("node")
    if node is None or not vite.is_file():
        pytest.skip(f"{project}: node or its installed toolchain is absent (run npm ci there); the "
                    "built-output proof needs the real bundler, and nothing else can stand in for it")
    mirror = tmp_path / "mirror"
    shipped = mirror.joinpath(*output.split("/"))
    arguments = release_contract._vite_build_arguments(ROOT, output)
    built = subprocess.run(
        [node, str(vite), "build", *arguments, "--outDir", str(shipped), "--emptyOutDir",
         "--logLevel", "error"],
        cwd=project_root, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900, check=False,
    )
    assert built.returncode == 0, built.stderr[-4000:]
    attribution = release_contract._npm_build_attribution(
        ROOT, field, build_root=mirror, required=True)
    assert attribution["status"] == "built_module_graph_bound"
    assert attribution["output"] == output
    # every shipped file is accounted for by the graph: chunks by their modules, emitted assets
    # (the HTML shell, stylesheets) by the files they were made from; none is attributed by default
    assert attribution["files_without_modules"] == [], attribution["files_without_modules"]
    names = {row["name"] for row in attribution["additional_rows"]}
    assert {"vite", "rolldown"} <= names, attribution["additional_rows"]
    virtual = {
        module for package in attribution["packages"] for module in package["virtual_modules"]}
    assert {"vite/preload-helper.js", "rolldown/runtime.js"} <= virtual, virtual
    assert tuple(
        f"{row['install_path']}@{row['version']}" for row in attribution["additional_rows"]
    ) == release_contract.EXPECTED_BUILD_ONLY_NPM_PACKAGES[field]
    # every production package whose modules ship is in the production graph already
    production = {row["install_path"] for row in release_contract._npm_production_packages(ROOT, project)}
    attributed = {package["install_path"] for package in attribution["packages"]}
    assert attributed - production == {row["install_path"] for row in attribution["additional_rows"]}
    # the derivation never records a path outside the project (no home directory in a receipt)
    assert str(ROOT).replace("\\", "/").casefold() not in json.dumps(attribution).casefold()
