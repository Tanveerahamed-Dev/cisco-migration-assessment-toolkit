"""Hosted installed-Vite, graph-package license and canonical inventory observations.

No npm/package code executes. The release inventory/attribution gates remain unchanged;
an observed inventory digest is review input, never a replacement acceptance pin.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import types

VERSION = "8.2.4"
GRAPH_PACKAGE = "react-force-graph-3d"
GRAPH_VERSION = "1.29.2"
GRAPH_INSTALL = "node_modules/" + GRAPH_PACKAGE
MANIFEST = "webapp/frontend/package.json"
LOCK = "webapp/frontend/package-lock.json"
PIPELINE = "master-reference/release/pipeline.py"
INVENTORY_OWNER = "portable/release_contract.py"
SCRIPT = ".github/scripts/frontend_candidate_materials.py"
TEST = ".github/scripts/test_frontend_candidate_materials.py"
INPUTS = (MANIFEST, LOCK, PIPELINE, INVENTORY_OWNER, SCRIPT, TEST, ".github/workflows/webapp-ci.yml")
# New byte-fact owner only: the independently reviewed 8.2.4 compiled carrier and
# notice text captured by hosted observer37611326103/job112759081151. Version->SRI
# stays owned by pipeline._VITE_BUNDLED_BRACES_REVIEWED, never duplicated here.
REVIEWED_MEMBERS = {
    "dist/node/chunks/node.js": "2c452d31c8ff4bf131e9e9b874037c9ac9bf2ad57b06cb9158cc2e6dab860cc0",
    "LICENSE.md": "387dd7baa307083401a27c58c362c30832f5ba1dba84f10cc22c33401523f45c",
}
MAX_FILE = 16 * 1024 * 1024


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    def constant(_):
        raise ValueError("Nonfinite JSON value")
    def finite_float(value):
        result = float(value)
        need(math.isfinite(result), "Nonfinite JSON value")
        return result
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant, parse_float=finite_float)


def ordinary(path):
    path = Path(path)
    need(path.resolve() == path.absolute(), "Indirect material path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= MAX_FILE, "Nonordinary or oversized material")
        pieces = []
        total = 0
        while total <= MAX_FILE:
            block = os.read(fd, min(65536, MAX_FILE + 1 - total))
            if not block:
                break
            pieces.append(block)
            total += len(block)
        after = os.fstat(fd)
        need(total == before.st_size and (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink)
             == (before.st_size, before.st_mtime_ns, before.st_ctime_ns, 1), "Material changed during bounded read")
        return b"".join(pieces)
    finally:
        os.close(fd)


def write_new(path, raw):
    need(len(raw) <= MAX_FILE and path.parent.resolve() == path.parent.absolute(), "Output bound/path invalid")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            need(written > 0, "Output write stalled")
            view = view[written:]
    finally:
        os.close(fd)


def emit(path, value):
    write_new(path, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())


def reviewed_carriers(source):
    """Admit the current literal/read-only-get owner profile, not a general Python sandbox."""
    module = ast.parse(source.decode("utf-8"))
    owner_name = "_VITE_BUNDLED_BRACES_REVIEWED"
    stores = [node for node in ast.walk(module) if isinstance(node, ast.Name)
              and node.id == "_VITE_BUNDLED_BRACES_REVIEWED" and isinstance(node.ctx, ast.Store)]
    assignments = [node for node in module.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "_VITE_BUNDLED_BRACES_REVIEWED" for target in node.targets)]
    need(len(stores) == 1 and len(assignments) == 1 and len(assignments[0].targets) == 1 and isinstance(assignments[0].value, ast.Dict),
         "Reviewed-carrier owner must have one literal assignment")
    parents = {child: node for node in ast.walk(module) for child in ast.iter_child_nodes(node)}
    target = assignments[0].targets[0]
    for node in ast.walk(module):
        # The real owner uses one literal declaration and direct read-only .get(version).
        # A subscript/attribute mutation, mutating method, getter escape or alias is outside
        # that reviewed shape. This does not attempt to sandbox arbitrary reflective Python.
        if isinstance(node, ast.Constant) and type(node.value) is str:
            need(owner_name not in node.value, "Reflective carrier-owner name use is not admitted")
        if not isinstance(node, ast.Name) or node.id != owner_name or node is target:
            continue
        attribute = parents.get(node)
        call = parents.get(attribute)
        need(isinstance(node.ctx, ast.Load) and isinstance(attribute, ast.Attribute) and attribute.value is node
             and attribute.attr == "get" and isinstance(attribute.ctx, ast.Load) and isinstance(call, ast.Call)
             and call.func is attribute and len(call.args) == 1 and not call.keywords, "Carrier owner mutation or alias escape is not admitted")
        context = parents.get(call)
        while context is not None and not isinstance(context, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            context = parents.get(context)
        need(isinstance(context, ast.FunctionDef) and context.name == "_vite_bundled_braces_carriers",
             "Carrier lookup escaped its current owner function")
    result = {}
    for key, value in zip(assignments[0].value.keys, assignments[0].value.values, strict=True):
        need(isinstance(key, ast.Constant) and type(key.value) is str and isinstance(value, ast.Constant)
             and type(value.value) is str and key.value not in result, "Ambiguous/computed carrier owner")
        sri = value.value
        need(re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", sri), "Carrier SRI is not canonical SHA-512")
        decoded = base64.b64decode(sri[7:], validate=True)
        need(len(decoded) == 64 and base64.b64encode(decoded).decode() == sri[7:], "Carrier SRI encoding differs")
        result[key.value] = sri
    need(VERSION in result, "Vite 8.2.4 is absent from the reviewed-carrier owner")
    return result


def validate_vite(manifest, lock, installed, observed_members, carriers):
    need(type(manifest) is dict and manifest.get("devDependencies", {}).get("vite") == VERSION, "Frontend Vite manifest pin differs")
    need(type(lock) is dict and lock.get("lockfileVersion") == 3 and type(lock.get("packages")) is dict, "Frontend lock structure differs")
    packages = lock["packages"]
    need(packages.get("", {}).get("devDependencies", {}).get("vite") == VERSION, "Root lock Vite pin differs")
    selected = packages.get("node_modules/vite", {})
    need(type(selected) is dict and selected.get("version") == VERSION and not selected.get("link")
         and selected.get("resolved") == f"https://registry.npmjs.org/vite/-/vite-{VERSION}.tgz", "Locked Vite distribution differs")
    need(VERSION in carriers and selected.get("integrity") == carriers[VERSION], "Lock SRI differs from the reviewed-carrier owner")
    need(type(installed) is dict and installed.get("name") == "vite" and installed.get("version") == VERSION
         and installed.get("license") == selected.get("license"), "Installed Vite package identity differs")
    need(set(observed_members) == set(REVIEWED_MEMBERS), "Installed byte-check member census differs")
    for name, expected in REVIEWED_MEMBERS.items():
        need(observed_members[name]["sha256"] == expected, "Installed reviewed Vite bytes differ: " + name)


def load_inventory_owner(admitted_source, path):
    # Compile the already admitted Python bytes, never reopen the path or read cached .pyc.
    # Only the current trusted inventory owner executes; no Vite/npm code is imported.
    need(type(admitted_source) is bytes and len(admitted_source) <= MAX_FILE, "Inventory owner requires bounded admitted bytes")
    name = "_frontend_materials_portable_owner"
    module = types.ModuleType(name)
    module.__file__ = str(path)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        exec(compile(admitted_source, str(path), "exec", dont_inherit=True), module.__dict__)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module


def observe_inventory(owner, admitted_lock, scratch_parent):
    # Give the existing owner exactly the admitted lock snapshot, at its expected
    # relative path. It must never reopen the mutable worktree lock for this observation.
    need(type(admitted_lock) is bytes and len(admitted_lock) <= MAX_FILE, "Inventory lock snapshot exceeds bound")
    strict_json(admitted_lock)
    need(owner._NPM_INVENTORIES["bundled_frontend"][0] == "webapp/frontend", "Canonical frontend project path changed")
    scratch = Path(tempfile.mkdtemp(prefix="frontend-inventory-input-", dir=scratch_parent))
    lock_path = scratch / LOCK
    lock_path.parent.mkdir(parents=True, mode=0o700)
    write_new(lock_path, admitted_lock)
    lock_path.chmod(0o400)
    need(ordinary(lock_path) == admitted_lock, "Private lock copy differs before owner read")
    # No second row projector, sorting rule, digest algorithm or acceptance pin.
    rows = owner._bundled_frontend_packages(scratch)
    digest = owner.digest_object(rows)
    need(ordinary(lock_path) == admitted_lock, "Private lock copy changed during owner read")
    expected_count, expected_digest = owner._reviewed_npm_inventory("bundled_frontend")
    return {"owner": "portable.release_contract._bundled_frontend_packages + digest_object", "rows": rows,
            "admitted_lock_copy": {"path": LOCK, "bytes": len(admitted_lock), "sha256": sha(admitted_lock), "read_only": True},
            "count": len(rows), "digest": digest, "current_reviewed_pin": {"count": expected_count, "digest": expected_digest},
            "matches_current_reviewed_pin": len(rows) == expected_count and digest == expected_digest,
            "pin_disposition": "Existing acceptance guards remain blocking; this observation does not change or waive them"}


def graph_package_census(package_root):
    """Bounded physical root census only; no descent into or execution of package code."""
    need(package_root.resolve() == package_root.absolute(), "Indirect installed graph package root")
    root_stat = package_root.lstat()
    need(stat.S_ISDIR(root_stat.st_mode), "Installed graph package root is not a directory")
    def identity(metadata):
        return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_nlink,
                metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)
    entries = {}
    with os.scandir(package_root) as iterator:
        for entry in iterator:
            need(len(entries) < 1024 and len(entry.name.encode("utf-8")) <= 255,
                 "Installed graph package root census exceeds observation bound")
            entries[entry.name] = identity(entry.stat(follow_symlinks=False))
    return {"root": identity(root_stat), "entries": entries}


def observe_graph_license(owner, root, manifest, lock):
    """Reuse the admitted portable license owner for this one installed candidate.

    Lock integrity is recorded, not claimed to be an independently verified tarball
    identity of the installed directory. Missing text is evidence for human review.
    """
    need(type(manifest) is dict and manifest.get("dependencies", {}).get(GRAPH_PACKAGE) == "^" + GRAPH_VERSION,
         "Graph manifest candidate differs")
    need(type(lock) is dict and lock.get("lockfileVersion") == 3 and type(lock.get("packages")) is dict,
         "Graph lock structure differs")
    packages = lock["packages"]
    need(packages.get("", {}).get("dependencies", {}).get(GRAPH_PACKAGE) == "^" + GRAPH_VERSION,
         "Graph root-lock candidate differs")
    selected = packages.get(GRAPH_INSTALL)
    need(type(selected) is dict and selected.get("version") == GRAPH_VERSION
         and not selected.get("link") and selected.get("dev") is not True
         and selected.get("resolved") == f"https://registry.npmjs.org/{GRAPH_PACKAGE}/-/{GRAPH_PACKAGE}-{GRAPH_VERSION}.tgz"
         and type(selected.get("license")) is str and type(selected.get("integrity")) is str,
         "Graph locked distribution identity differs")
    integrity = selected["integrity"]
    need(re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", integrity), "Graph lock integrity is not canonical SHA-512")
    need(base64.b64encode(base64.b64decode(integrity[7:], validate=True)).decode() == integrity[7:],
         "Graph lock integrity encoding differs")
    package_root = root / "webapp/frontend" / GRAPH_INSTALL
    before = graph_package_census(package_root)
    package_bytes = ordinary(package_root / "package.json")
    installed = strict_json(package_bytes)
    need(type(installed) is dict and installed.get("name") == GRAPH_PACKAGE
         and installed.get("version") == GRAPH_VERSION and installed.get("license") == selected["license"],
         "Installed graph package identity differs")
    files = []
    selected_bytes = {}
    total = 0
    for name in sorted(before["entries"], key=str.casefold):
        if not owner._license_filename(name):
            continue
        mode = before["entries"][name][2]
        if stat.S_ISDIR(mode):
            continue  # Same root-file denominator as third_party_notices; no recursion.
        need(stat.S_ISREG(mode), "Installed graph license entry is indirect or nonregular")
        need(len(files) < 32, "Installed graph license file census exceeds observation bound")
        raw = ordinary(package_root / name)
        total += len(raw)
        need(len(raw) <= 2 * 1024 * 1024 and total <= 8 * 1024 * 1024,
             "Installed graph license bytes exceed observation bound")
        payload = owner._license_payload(package_root / name, name, package_root)
        # Retain the owner's full original content/encoding, not a reconstructed notice.
        need(payload["path"] == name and payload["bytes"] == len(raw) and payload["sha256"] == sha(raw),
             "Installed graph license owner read differs from admitted bytes")
        encoding = payload["encoding"]
        recovered = (payload["content"].encode("utf-8") if encoding == "utf-8"
                     else base64.b64decode(payload["content"], validate=True) if encoding == "base64" else None)
        need(recovered == raw, "Installed graph license content differs from original bytes")
        files.append({**payload, "origin": "installed_package"})
        selected_bytes[name] = raw
    need(ordinary(package_root / "package.json") == package_bytes, "Installed graph package identity changed during observation")
    for name, raw in selected_bytes.items():
        need(ordinary(package_root / name) == raw, "Installed graph license changed during observation")
    need(graph_package_census(package_root) == before, "Installed graph package census changed during observation")
    nonempty = sum(bool(raw) for raw in selected_bytes.values())
    return {
        "schema": "installed_graph_license_observation/1",
        "status": "INSTALLED_LICENSE_TEXT_OBSERVED_REVIEW_REQUIRED" if nonempty else "INSTALLED_LICENSE_TEXT_ABSENT_REVIEW_REQUIRED",
        "owner": "portable.release_contract._license_filename + _license_payload",
        "package": GRAPH_PACKAGE, "install_path": "webapp/frontend/" + GRAPH_INSTALL,
        "manifest_spec": manifest["dependencies"][GRAPH_PACKAGE], "lock_identity": selected,
        "installed_identity": {key: installed[key] for key in ("name", "version", "license")},
        "installed_package_json": {"bytes": len(package_bytes), "sha256": sha(package_bytes)},
        "root_entry_names": sorted(before["entries"]), "license_files": files,
        "license_file_count": len(files), "nonempty_license_file_count": nonempty,
        "review_required": True, "license_acceptance": False, "fallback_consulted": False,
        "limits": "One installed package's root license-file observation; no fallback reuse, whole tarball integrity claim, whole portable notices/SBOM, compatibility or legal/release approval. Existing owner gates remain blocking.",
    }


def git(root, *args):
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args], capture_output=True, check=False, timeout=30)
    need(result.returncode == 0 and len(result.stdout) <= MAX_FILE, "Source Git read failed: " + args[0])
    return result.stdout


def source_identity(root, expected):
    need(re.fullmatch(r"[0-9a-f]{40}", expected or ""), "Full hosted source SHA required")
    head = git(root, "rev-parse", "HEAD").decode().strip()
    need(head == expected and git(root, "status", "--porcelain=v1", "--untracked-files=no") == b"", "Hosted checkout is not clean exact source")
    inputs = {}
    data = {}
    for path in INPUTS:
        raw = ordinary(root / path)
        need(raw == git(root, "cat-file", "blob", head + ":" + path), "Selected material is not its committed Git bytes: " + path)
        data[path] = raw
        inputs[path] = {"bytes": len(raw), "sha256": sha(raw), "git_blob": git(root, "rev-parse", head + ":" + path).decode().strip()}
    return {"commit": head, "tree": git(root, "rev-parse", "HEAD^{tree}").decode().strip(), "inputs": inputs}, data


def main():
    need(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
         and os.environ.get("RUNNER_OS") == "Linux" and os.environ.get("GITHUB_JOB") == "frontend", "GitHub-hosted frontend Linux execution required")
    need(len(sys.argv) == 1, "This fixed check takes no path/version/digest arguments")
    root = Path(__file__).resolve().parents[2]
    output = Path(os.environ["RUNNER_TEMP"]).resolve() / "frontend-candidate-materials"
    need(not output.exists() and not output.is_relative_to(root), "Fresh external evidence directory required")
    output.mkdir(mode=0o700)
    report = {"schema": "frontend_candidate_materials/1", "status": "INCOMPLETE_OR_FAILED", "source": None,
              "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"], "job": os.environ["GITHUB_JOB"],
              "installed_vite_matches_reviewed_bytes": False, "inventory_observed": False,
              "graph_license_observed": False, "errors": [],
              "review_required": True, "compatibility": False, "release_authority": False, "inventory_gate_waived": False,
              "limits": "Two selected installed Vite files plus package/lock identity and one installed graph-package license observation; not whole package/tarball integrity, security clearance, build attribution, notices/SBOM or compatibility. License review, compiled-braces and external-review BLOCK remain."}
    before = None
    try:
        before, source = source_identity(root, os.environ.get("GITHUB_SHA", ""))
        report["source"] = before
        emit(output / "source-before.json", before)
        manifest = strict_json(source[MANIFEST])
        lock = strict_json(source[LOCK])
        # Observe the canonical committed lock first so its complete rows survive a later byte-check failure.
        owner = load_inventory_owner(source[INVENTORY_OWNER], root / INVENTORY_OWNER)
        inventory = observe_inventory(owner, source[LOCK], output.parent)
        emit(output / "frontend-inventory.json", {"source": before, **inventory})
        print(json.dumps({"inventory": inventory}, sort_keys=True, allow_nan=False))
        report["inventory_observed"] = True
        report["matches_current_reviewed_inventory_pin"] = inventory["matches_current_reviewed_pin"]
        carriers = reviewed_carriers(source[PIPELINE])
        installed_root = root / "webapp/frontend/node_modules/vite"
        package_bytes = ordinary(installed_root / "package.json")
        installed = strict_json(package_bytes)
        observed = {}
        report["installed_identity_observed"] = {key: installed.get(key) for key in ("name", "version", "license")}
        report["installed_members_observed"] = observed
        for path in REVIEWED_MEMBERS:
            raw = ordinary(installed_root / path)
            observed[path] = {"bytes": len(raw), "sha256": sha(raw), "reviewed_sha256": REVIEWED_MEMBERS[path]}
        details = {"source": before, "reviewed_version": VERSION, "reviewed_sri_from_owner": carriers[VERSION],
                   "manifest_pin": manifest.get("devDependencies", {}).get("vite"),
                   "lock_identity": lock.get("packages", {}).get("node_modules/vite"),
                   "installed_identity": {key: installed.get(key) for key in ("name", "version", "license")},
                   "installed_package_json": {"bytes": len(package_bytes), "sha256": sha(package_bytes)}, "members": observed}
        emit(output / "installed-vite-observation.json", details)
        validate_vite(manifest, lock, installed, observed, carriers)
        # Re-read the installed ordinary files; source identity alone does not bind ignored node_modules.
        need(ordinary(installed_root / "package.json") == package_bytes, "Installed package identity changed")
        for path, row in observed.items():
            need(sha(ordinary(installed_root / path)) == row["sha256"], "Installed Vite member changed during observation")
        report["installed_vite_matches_reviewed_bytes"] = True
        graph_license = observe_graph_license(owner, root, manifest, lock)
        emit(output / "installed-graph-license-observation.json", {"source": before, **graph_license})
        report["graph_license_observed"] = True
        report["graph_license_status"] = graph_license["status"]
    except Exception as error:
        report["errors"].append(str(error))
    finally:
        try:
            after, _ = source_identity(root, os.environ.get("GITHUB_SHA", ""))
            need(before is not None and after == before, "Source changed during material observation")
            report["source_after"] = after
        except Exception as error:
            report["errors"].append("Final source binding: " + str(error))
        if not report["errors"] and report["installed_vite_matches_reviewed_bytes"] and report["inventory_observed"] and report["graph_license_observed"]:
            report["status"] = "MATERIALS_OBSERVED_REVIEW_REQUIRED"
        emit(output / "result.json", report)
        print(json.dumps(report, sort_keys=True, allow_nan=False))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
