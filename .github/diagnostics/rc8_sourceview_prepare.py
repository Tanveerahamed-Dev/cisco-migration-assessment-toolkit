"""Prepare one frozen, unsigned source-view fixture counterfactual on fresh GHA Windows.

Both cases construct the same candidate objects with an external index. Only
candidate detaches the hosted subject at that commit. No public ref is written,
no project code is executed, and synthetic test Git dates are not set here.
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
MEMBER = "tests/test_portable_source_view.py"
OLD_SHA = "d1a97a49cbf96bdcb6db9c0740c384b84e436c72d77e0571b3888e1e68dd2a6f"
NEW_SHA = "e21d92365fd5a18f361029aafd00d8a86c1afe15db7d1512ccc1906536f3e2e2"
DATA_SHA = "a4acad6bcefc29dae6c7bbe803fc43394314b9b34f0efbea33793572220611d6"
DATA_KEYS = {"format", "base_source", "base_tree", "path", "mode", "source_sha256", "candidate_sha256", "old", "new"}
METADATA = {
    "author_name": "Atlas diagnostic", "committer_name": "Atlas diagnostic",
    "author_email": "atlas-diagnostic@users.noreply.github.com",
    "committer_email": "atlas-diagnostic@users.noreply.github.com",
    "author_date": "2026-10-18T00:00:00+00:00", "committer_date": "2026-10-18T00:00:00+00:00",
    "message": "diagnostic: source-view fixture template counterfactual\n",
}
RECIPE_KEYS = set(METADATA) | {"base_source", "base_tree", "candidate_source", "candidate_tree", "candidate_data_sha256"}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hex(value, length=40):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value) is None:
        raise ValueError("digest refused")
    return value


def _ordinary(path, directory=False):
    metadata = path.lstat()
    if (path.resolve(strict=True) != path or stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or (not stat.S_ISDIR(metadata.st_mode) if directory else not stat.S_ISREG(metadata.st_mode))):
        raise ValueError("ordinary path refused")
    if not directory and getattr(metadata, "st_nlink", 1) != 1:
        raise ValueError("multiply linked file refused")
    return metadata


def _environment():
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0", GIT_ATTR_NOSYSTEM="1")
    return environment


def _git(root, environment, *arguments, data=None):
    options = ["--no-pager", "--no-replace-objects", "-c", "core.hooksPath=" + environment["ATLAS_SOURCEVIEW_HOOKS"],
               "-c", "commit.gpgsign=false", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
               "-c", "core.autocrlf=false", "-c", "core.eol=lf", "-c", "core.attributesFile=" + os.devnull]
    result = subprocess.run(["git", *options, "-C", str(root), *arguments], env=environment, input=data,
                            capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise ValueError("git refused")
    return result.stdout


def _text(root, environment, *arguments, data=None):
    return _git(root, environment, *arguments, data=data).decode("utf-8").strip()


def _host(subject, output):
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows"
            or sys.platform != "win32" or sys.version_info[:3] != (3, 12, 10)
            or not sys.flags.isolated or not sys.flags.dont_write_bytecode):
        raise ValueError("host refused")
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    root = workspace / "subject"
    if subject.absolute() != root or subject.resolve(strict=True) != root:
        raise ValueError("fresh hosted subject required")
    _ordinary(root, directory=True)
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    _ordinary(temporary, directory=True)
    if (output.absolute() != output.resolve() or not output.is_relative_to(temporary)
            or output.is_relative_to(root) or os.path.lexists(output) or not output.parent.is_dir()):
        raise ValueError("fresh external receipt required")
    github_output = Path(os.environ["GITHUB_OUTPUT"])
    _ordinary(github_output)
    if not github_output.is_relative_to(temporary):
        raise ValueError("runner output refused")
    return root, temporary, github_output


def _guard(root, environment, source, tree):
    git = root / ".git"
    _ordinary(git, directory=True)
    _ordinary(git / "index")
    _ordinary(git / "objects", directory=True)
    _ordinary(git / "config")
    if re.search(r"(?mi)^\s*\[\s*(?:include|includeif|filter)(?:\s|\])", (git / "config").read_text(encoding="utf-8")):
        raise ValueError("external Git includes or filters refused")
    if any(os.path.lexists(path) for path in (
        git / "index.lock", git / "objects/info/alternates", git / "info/grafts", git / "info/sparse-checkout",
    )):
        raise ValueError("Git indirection refused")
    for arguments, expected in (
        (("--show-toplevel",), root), (("--absolute-git-dir",), git),
        (("--path-format=absolute", "--git-common-dir"), git),
        (("--path-format=absolute", "--git-path", "index"), git / "index"),
    ):
        if Path(_text(root, environment, "rev-parse", *arguments)).resolve() != expected:
            raise ValueError("Git location refused")
    if (_text(root, environment, "rev-parse", "--show-object-format") != "sha1"
            or _text(root, environment, "rev-parse", "HEAD") != source
            or _text(root, environment, "rev-parse", "HEAD^{tree}") != tree
            or _git(root, environment, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored")):
        raise ValueError("clean source refused")
    if any(row and not row.startswith(b"H ") for row in _git(root, environment, "ls-files", "-v", "-z").split(b"\0")):
        raise ValueError("hidden index state refused")


def _data(raw):
    if _sha(raw) != DATA_SHA:
        raise ValueError("frozen candidate data refused")
    value = json.loads(raw)
    if type(value) is not dict or set(value) != DATA_KEYS or any(type(v) is not str for v in value.values()):
        raise ValueError("candidate schema refused")
    if (value["format"] != "atlas-rc8-sourceview-candidate/1" or value["base_source"] != BASE
            or value["base_tree"] != BASE_TREE or value["path"] != MEMBER or value["mode"] != "100644"
            or value["source_sha256"] != OLD_SHA or value["candidate_sha256"] != NEW_SHA):
        raise ValueError("candidate identity refused")
    old, new = value["old"].encode("utf-8"), value["new"].encode("utf-8")
    if _sha(old) != OLD_SHA or _sha(new) != NEW_SHA:
        raise ValueError("full-file bytes refused")
    before, after = ast.parse(old), ast.parse(new)
    if ([ast.dump(n) for n in ast.walk(before) if isinstance(n, ast.Assert)]
            != [ast.dump(n) for n in ast.walk(after) if isinstance(n, ast.Assert)]):
        raise ValueError("assertion preservation refused")
    if ([ast.dump(n) for n in before.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
            != [ast.dump(n) for n in after.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]):
        raise ValueError("test identity preservation refused")
    return old, new


def _recipe(raw):
    recipe = json.loads(raw)
    if type(recipe) is not dict or set(recipe) != RECIPE_KEYS or any(type(v) is not str for v in recipe.values()):
        raise ValueError("recipe schema refused")
    if (recipe["base_source"] != BASE or recipe["base_tree"] != BASE_TREE
            or recipe["candidate_data_sha256"] != DATA_SHA
            or any(recipe[key] != value for key, value in METADATA.items())):
        raise ValueError("recipe identity refused")
    _hex(recipe["candidate_source"])
    _hex(recipe["candidate_tree"])
    return recipe


@contextmanager
def _temporary(temporary, environment):
    directory = Path(tempfile.mkdtemp(prefix="rc8-sourceview-", dir=temporary))
    hooks = directory / "hooks"
    hooks.mkdir()
    try:
        yield directory, {**environment, "ATLAS_SOURCEVIEW_HOOKS": str(hooks)}
    finally:
        for name in ("index", "index.lock"):
            path = directory / name
            if os.path.lexists(path):
                _ordinary(path)
                path.unlink()
        _ordinary(hooks, directory=True)
        hooks.rmdir()  # refuses unexpected contents; never sweeps unknown files
        directory.rmdir()


def _commit_bytes(recipe):
    headers = [f"tree {recipe['candidate_tree']}", f"parent {BASE}"]
    for role in ("author", "committer"):
        stamp = int(datetime.fromisoformat(recipe[role + "_date"]).timestamp())
        headers.append(f"{role} {recipe[role + '_name']} <{recipe[role + '_email']}> {stamp} +0000")
    return ("\n".join(headers) + "\n\n" + recipe["message"]).encode("utf-8")


def _construct(root, environment, directory, recipe, old, new):
    _ordinary(root / MEMBER)
    listing = _text(root, environment, "ls-tree", BASE, "--", MEMBER)
    if re.fullmatch(r"100644 blob [0-9a-f]{40}\t" + re.escape(MEMBER), listing) is None:
        raise ValueError("base mode refused")
    if _git(root, environment, "cat-file", "blob", BASE + ":" + MEMBER) != old or (root / MEMBER).read_bytes() != old:
        raise ValueError("base full-file bytes refused")
    indexed = {**environment, "GIT_INDEX_FILE": str(directory / "index")}
    _git(root, indexed, "read-tree", BASE)
    blob = _hex(_text(root, environment, "hash-object", "-w", "--stdin", "--no-filters", data=new))
    _git(root, indexed, "update-index", "--cacheinfo", f"100644,{blob},{MEMBER}")
    tree = _hex(_text(root, indexed, "write-tree"))
    if tree != recipe["candidate_tree"]:
        raise ValueError("candidate tree refused")
    identities = {"GIT_" + key.upper(): value for key, value in METADATA.items() if key != "message"}
    commit = _hex(_text(root, {**environment, **identities}, "commit-tree", tree, "-p", BASE,
                        "-F", "-", data=METADATA["message"].encode("utf-8")))
    if commit != recipe["candidate_source"] or _git(root, environment, "cat-file", "commit", commit) != _commit_bytes(recipe):
        raise ValueError("unsigned commit bytes refused")
    if _git(root, environment, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", BASE, commit) != (MEMBER + "\0").encode():
        raise ValueError("single-file diff refused")
    if (_text(root, environment, "ls-tree", commit, "--", MEMBER) != f"100644 blob {blob}\t{MEMBER}"
            or _git(root, environment, "cat-file", "blob", commit + ":" + MEMBER) != new):
        raise ValueError("candidate mode or bytes refused")
    return commit, tree


def _outputs(path, source, tree):
    _ordinary(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOINHERIT)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("runner output changed")
        pending = f"source={_hex(source)}\ntree={_hex(tree)}\n".encode("ascii")
        while pending:
            written = os.write(descriptor, pending)
            if written <= 0:
                raise OSError("runner output refused")
            pending = pending[written:]
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("subject", "candidate-json", "recipe", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--case", choices=("original", "candidate"), required=True)
    arguments = parser.parse_args()
    try:
        root, temporary, github_output = _host(arguments.subject, arguments.output)
    except Exception:
        print('{"status":"host_guard_refused"}')
        return 1
    report = {"status": "preparation_refused", "stage": "data_guard", "case": arguments.case,
              "base_source": BASE, "base_tree": BASE_TREE, "path": MEMBER,
              "scope": "ephemeral unsigned runner candidate; no published Git ref",
              "limits": {"no_project_execution": True, "no_test_git_dates_set": True,
                         "no_assertion_gate_budget_timeout_or_gc_policy_change": True}}
    try:
        data_raw, recipe_raw = arguments.candidate_json.read_bytes(), arguments.recipe.read_bytes()
        old, new = _data(data_raw)
        recipe = _recipe(recipe_raw)
        report.update(candidate_data_sha256=_sha(data_raw), recipe_sha256=_sha(recipe_raw),
                      candidate_source=recipe["candidate_source"], candidate_tree=recipe["candidate_tree"])
        with _temporary(temporary, _environment()) as (directory, environment):
            report["stage"] = "base_guard"
            _guard(root, environment, BASE, BASE_TREE)
            report["stage"] = "fresh_subject_lf_normalization"
            _git(root, environment, "config", "--local", "core.autocrlf", "false")
            _git(root, environment, "config", "--local", "core.eol", "lf")
            _git(root, environment, "rm", "--cached", "-r", "--", ".")
            _git(root, environment, "reset", "--hard", BASE)
            _guard(root, environment, BASE, BASE_TREE)
            report["guarded_fresh_checkout_lf_normalized"] = True
            report["stage"] = "construct_objects_with_external_index"
            candidate, candidate_tree = _construct(root, environment, directory, recipe, old, new)
            _guard(root, environment, BASE, BASE_TREE)
            report["stage"] = "select_and_verify"
            source, tree = BASE, BASE_TREE
            if arguments.case == "candidate":
                _git(root, environment, "checkout", "--detach", candidate)
                source, tree = candidate, candidate_tree
            _guard(root, environment, source, tree)
            _ordinary(root / MEMBER)
            actual = (root / MEMBER).read_bytes()
            if actual != (new if arguments.case == "candidate" else old):
                raise ValueError("selected full-file bytes refused")
            report.update(actual_source=source, actual_tree=tree, actual_file_sha256=_sha(actual),
                          base_file_sha256=OLD_SHA, candidate_file_sha256=NEW_SHA,
                          mode="100644", single_path_diff_verified=True, one_base_parent_verified=True,
                          raw_unsigned_commit_verified=True, clean_after_selection=True)
        report["stage"] = "emit_outputs"
        _outputs(github_output, source, tree)
        report.update(status="prepared", stage="complete")
        exit_code = 0
    except Exception:
        exit_code = 1  # fixed stage only; no command stderr, paths, source or exception values
    try:
        with arguments.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, sort_keys=True, indent=2)
            stream.write("\n")
    except OSError:
        print('{"status":"receipt_write_refused"}')
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
