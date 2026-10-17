"""Prepare one exact, unsigned, runner-only AST-lifetime counterfactual.

Both cases construct identical objects through an external alternate index.
Only ``both`` detaches the fresh hosted subject at the recipe commit. No refs
are published; no reset, test execution, dependency setup or source import occurs.
"""

import argparse
import ast
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

BASE = "8c4b87d8bc149a30fcd05f5efcd123856a2778e6"
BASE_TREE = "aa003b01248588220d22face7e8218f96a9ada84"
HELPERS = {"tests/client_artifact_census.py": "_load_file", "tests/test_impact_consumers.py": "_units"}
METADATA = {
    "author_name": "Atlas diagnostic", "committer_name": "Atlas diagnostic",
    "author_email": "atlas-diagnostic@users.noreply.github.com",
    "committer_email": "atlas-diagnostic@users.noreply.github.com",
    "author_date": "2026-10-17T00:00:00+00:00", "committer_date": "2026-10-17T00:00:00+00:00",
    "message": "diagnostic: AST visitor disposal counterfactual\n",
}
RECIPE_KEYS = set(METADATA) | {"base_source", "base_tree", "candidate_source", "candidate_tree", "changes_sha256"}
CHANGE_KEYS = {"path", "function", "source_sha256", "old", "new", "candidate_sha256"}
GIT_OPTIONS = ["--no-replace-objects", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
               "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
               "-c", "core.autocrlf=false", "-c", "core.eol=lf", "-c", "core.attributesFile=/dev/null"]


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _hex(value, length=40):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value) is None:
        raise ValueError("invalid digest")
    return value


def _environment():
    # In particular, discard inherited GIT_DIR/WORK_TREE/INDEX_FILE/object/replace/config selectors.
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
                       GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0", GIT_ATTR_NOSYSTEM="1")
    return environment


def _git(root, environment, *arguments, data=None):
    result = subprocess.run(["git", *GIT_OPTIONS, "-C", str(root), *arguments], env=environment,
                            input=data, capture_output=True, timeout=60, check=False)
    if result.returncode != 0:
        raise ValueError("git command refused")  # never expose command output or machine paths
    return result.stdout


def _text(root, environment, *arguments):
    return _git(root, environment, *arguments).decode("utf-8").strip()


def _host(subject, output):
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
            or sys.platform != "linux"):
        raise ValueError("hosted Linux required")
    release = Path("/etc/os-release").read_text(encoding="utf-8")
    if not any(line in ('ID=ubuntu', 'ID="ubuntu"') for line in release.splitlines()):
        raise ValueError("Ubuntu required")
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    expected = workspace / "subject"
    if subject.absolute() != expected or subject.resolve(strict=True) != expected:
        raise ValueError("only the fresh hosted subject is writable")
    if not expected.is_dir() or expected.is_symlink():
        raise ValueError("ordinary subject required")
    if output.is_relative_to(expected) or output.exists():
        raise ValueError("fresh external receipt required")
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    if not runner_temp.is_dir() or runner_temp.is_relative_to(expected):
        raise ValueError("external runner temp required")
    github_output = Path(os.environ["GITHUB_OUTPUT"])
    if (github_output.is_symlink() or not github_output.resolve(strict=True).is_relative_to(runner_temp)
            or not stat.S_ISREG(github_output.stat().st_mode)):
        raise ValueError("ordinary runner output file required")
    return expected, runner_temp, github_output


def _guard_repository(root, environment, source, tree):
    git_directory = root / ".git"
    if git_directory.is_symlink() or not git_directory.is_dir():
        raise ValueError("fresh repository directory required")
    index = git_directory / "index"
    if index.is_symlink() or not stat.S_ISREG(index.lstat().st_mode) or index.resolve() != index:
        raise ValueError("ordinary subject index required")
    if os.path.lexists(git_directory / "index.lock"):
        raise ValueError("pre-existing subject index lock refused")
    objects = git_directory / "objects"
    if objects.is_symlink() or not objects.is_dir() or objects.resolve() != objects:
        raise ValueError("ordinary subject object directory required")
    if any(os.path.lexists(path) for path in (objects / "info" / "alternates", git_directory / "info" / "grafts")):
        raise ValueError("alternate object or graft metadata refused")
    if Path(_text(root, environment, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("subject root mismatch")
    if Path(_text(root, environment, "rev-parse", "--absolute-git-dir")).resolve() != git_directory:
        raise ValueError("external Git directory refused")
    if Path(_text(root, environment, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve() != git_directory:
        raise ValueError("external common directory refused")
    if Path(_text(root, environment, "rev-parse", "--path-format=absolute", "--git-path", "index")).resolve() != index:
        raise ValueError("external subject index refused")
    if _text(root, environment, "rev-parse", "--show-object-format") != "sha1":
        raise ValueError("object format mismatch")
    if (_text(root, environment, "rev-parse", "HEAD") != source
            or _text(root, environment, "rev-parse", "HEAD^{tree}") != tree):
        raise ValueError("source identity mismatch")
    if _git(root, environment, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
        raise ValueError("subject is not clean")


def _recipe(raw, changes_raw):
    recipe = json.loads(raw)
    if type(recipe) is not dict or set(recipe) != RECIPE_KEYS or any(type(value) is not str for value in recipe.values()):
        raise ValueError("recipe schema")
    if recipe["base_source"] != BASE or recipe["base_tree"] != BASE_TREE:
        raise ValueError("base recipe mismatch")
    if any(recipe[key] != value for key, value in METADATA.items()):
        raise ValueError("commit metadata mismatch")
    _hex(recipe["candidate_source"])
    _hex(recipe["candidate_tree"])
    _hex(recipe["changes_sha256"], 64)
    if _sha256(changes_raw) != recipe["changes_sha256"]:
        raise ValueError("changes document identity")
    return recipe


def _members(root, environment, changes_raw):
    changes, result, seen = json.loads(changes_raw), [], set()
    if type(changes) is not list or len(changes) != len(HELPERS):
        raise ValueError("two helper changes required")
    for change in changes:
        if type(change) is not dict or set(change) != CHANGE_KEYS or any(type(v) is not str for v in change.values()):
            raise ValueError("change schema")
        relative, function = change["path"], change["function"]
        if relative not in HELPERS or function != HELPERS[relative] or relative in seen:
            raise ValueError("helper allowlist mismatch")
        seen.add(relative)
        path = root / relative
        if path.resolve(strict=True) != path or not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("regular member required")
        listing = _text(root, environment, "ls-tree", BASE, "--", relative)
        if re.fullmatch(r"100644 blob [0-9a-f]{40}\t" + re.escape(relative), listing) is None:
            raise ValueError("base member mode")
        original = path.read_bytes()
        if _git(root, environment, "cat-file", "blob", f"{BASE}:{relative}") != original:
            raise ValueError("worktree member differs from base blob")
        if _sha256(original) != _hex(change["source_sha256"], 64):
            raise ValueError("original full-file digest")
        text = original.decode("utf-8")
        if text.count(change["old"]) != 1:
            raise ValueError("old snippet occurrence")
        owners = [node for node in ast.parse(text).body if type(node) is ast.FunctionDef and node.name == function]
        if len(owners) != 1 or ast.get_source_segment(text, owners[0]) != change["old"].rstrip("\r\n"):
            raise ValueError("whole original helper required")
        for field in ("old", "new"):
            nodes = ast.parse(change[field]).body
            if (len(nodes) != 1 or type(nodes[0]) is not ast.FunctionDef
                    or nodes[0].name != function or nodes[0].decorator_list):
                raise ValueError("one undecorated helper required")
        candidate = text.replace(change["old"], change["new"], 1).encode("utf-8")
        if _sha256(candidate) != _hex(change["candidate_sha256"], 64):
            raise ValueError("candidate full-file digest")
        ast.parse(candidate)
        result.append((relative, original, candidate))
    return sorted(result)


@contextmanager
def _alternate_index(runner_temp, environment):
    directory = Path(tempfile.mkdtemp(prefix="rc8-ast-index-", dir=runner_temp))
    index = directory / "index"
    try:
        yield {**environment, "GIT_INDEX_FILE": str(index)}
    finally:
        # Only our fresh index/lock files; never recursively sweep unexpected contents.
        for name in ("index", "index.lock"):
            path = directory / name
            if os.path.lexists(path):
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise ValueError("unexpected temporary index member")
                path.unlink()
        directory.rmdir()


def _commit_bytes(recipe):
    headers = [f"tree {recipe['candidate_tree']}", f"parent {BASE}"]
    for role in ("author", "committer"):
        stamp = int(datetime.fromisoformat(recipe[f"{role}_date"]).timestamp())
        headers.append(f"{role} {recipe[f'{role}_name']} <{recipe[f'{role}_email']}> {stamp} +0000")
    return ("\n".join(headers) + "\n\n" + recipe["message"]).encode("utf-8")


def _construct(root, environment, runner_temp, recipe, members):
    with _alternate_index(runner_temp, environment) as indexed:
        _git(root, indexed, "read-tree", BASE)
        for relative, _original, candidate in members:
            blob = _hex(_text_with_input(root, environment, candidate, "hash-object", "-w", "--stdin", "--no-filters"))
            _git(root, indexed, "update-index", "--cacheinfo", f"100644,{blob},{relative}")
        tree = _hex(_text(root, indexed, "write-tree"))
    if tree != recipe["candidate_tree"]:
        raise ValueError("candidate tree mismatch")
    identities = {"GIT_" + key.upper(): recipe[key] for key in METADATA if key != "message"}
    commit = _hex(_text_with_input(root, {**environment, **identities}, recipe["message"].encode("utf-8"),
                                  "commit-tree", tree, "-p", BASE, "-F", "-"))
    if commit != recipe["candidate_source"]:
        raise ValueError("candidate commit mismatch")
    if _git(root, environment, "cat-file", "commit", commit) != _commit_bytes(recipe):
        raise ValueError("raw parent, unsigned metadata or message mismatch")
    paths = _git(root, environment, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", BASE, commit)
    if paths.decode("utf-8").split("\0") != [relative for relative, _, _ in members] + [""]:
        raise ValueError("candidate diff scope")
    for relative, _original, candidate in members:
        listing = _text(root, environment, "ls-tree", commit, "--", relative)
        if re.fullmatch(r"100644 blob [0-9a-f]{40}\t" + re.escape(relative), listing) is None:
            raise ValueError("candidate member mode")
        if _git(root, environment, "cat-file", "blob", f"{commit}:{relative}") != candidate:
            raise ValueError("candidate member bytes")
    return commit, tree


def _text_with_input(root, environment, data, *arguments):
    return _git(root, environment, *arguments, data=data).decode("ascii").strip()


def _emit_outputs(path, source, tree):
    payload = f"source={_hex(source)}\ntree={_hex(tree)}\n".encode("ascii")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("runner output type changed")
        while payload:
            written = os.write(descriptor, payload)
            if written <= 0:
                raise OSError("output write refused")
            payload = payload[written:]
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("subject", "changes", "recipe", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--case", required=True, choices=("original", "both"))
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    try:
        root, runner_temp, github_output = _host(arguments.subject, output)
    except Exception:
        print('{"status":"host_guard_refused"}')
        return 1  # no receipt or repository writes when host/target/output admission fails
    report = {"status": "preparation_error", "stage": "host_guard", "case": arguments.case,
              "base_source": BASE, "base_tree": BASE_TREE,
              "scope": "ephemeral runner candidate; no GitHub ref created or published",
              "limits": {"diagnostic_only": True, "no_acceptance_from_controller_status": True,
                         "no_assertion_gate_budget_timeout_timed_rule_or_gc_policy_change": True}}
    try:
        environment = _environment()
        report["stage"] = "base_guard"
        _guard_repository(root, environment, BASE, BASE_TREE)
        changes_raw, recipe_raw = arguments.changes.read_bytes(), arguments.recipe.read_bytes()
        report["stage"] = "recipe_and_members"
        recipe = _recipe(recipe_raw, changes_raw)
        members = _members(root, environment, changes_raw)
        report.update(candidate_source=recipe["candidate_source"], candidate_tree=recipe["candidate_tree"],
                      changes_sha256=_sha256(changes_raw), recipe_sha256=_sha256(recipe_raw))
        report["stage"] = "construct_objects_with_alternate_index"
        candidate, candidate_tree = _construct(root, environment, runner_temp, recipe, members)
        _guard_repository(root, environment, BASE, BASE_TREE)
        report["stage"] = "select_and_verify_source"
        source, tree = BASE, BASE_TREE
        if arguments.case == "both":
            _git(root, environment, "checkout", "--detach", candidate)
            source, tree = candidate, candidate_tree
        _guard_repository(root, environment, source, tree)
        files = []
        for relative, original, changed in members:
            actual = (root / relative).read_bytes()
            if actual != (changed if arguments.case == "both" else original):
                raise ValueError("selected full-file bytes")
            files.append({"path": relative, "base_sha256": _sha256(original),
                          "candidate_sha256": _sha256(changed), "actual_sha256": _sha256(actual), "mode": "100644"})
        report.update(actual_source=source, actual_tree=tree, files=files,
                      diff_paths=[relative for relative, _, _ in members],
                      raw_unsigned_commit_verified=True, one_base_parent_verified=True, clean_after_selection=True)
        report["stage"] = "emit_guarded_source_outputs"
        _emit_outputs(github_output, source, tree)
        report.update(status="prepared", stage="complete")
        exit_code = 0
    except Exception:
        exit_code = 1  # fixed stage only: no Git stderr, command, machine path or source content
    try:
        if output.is_relative_to(root):
            raise ValueError("receipt inside subject")
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, sort_keys=True, indent=2)
            stream.write("\n")
    except (OSError, ValueError):
        print('{"status":"receipt_write_refused"}')
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
