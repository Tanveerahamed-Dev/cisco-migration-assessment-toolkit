"""Hosted-only six-case input/copy proof; never load in the raw timing process.

ATLAS_SOURCEVIEW_PROOF_{REPORT,SOURCE_ROOT,SOURCE,TREE,CASE} bind this plugin.
Only primitive counts/digests/public node IDs are emitted. Fixtures and builder
returns are unchanged. All input bytes are hashed as-is, never normalized.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

MEMBER = "tests/test_portable_source_view.py"
CASES = {
    "original": ("8c4b87d8bc149a30fcd05f5efcd123856a2778e6", "aa003b01248588220d22face7e8218f96a9ada84",
                 "d1a97a49cbf96bdcb6db9c0740c384b84e436c72d77e0571b3888e1e68dd2a6f", 6),
    "candidate": ("a7a8bf141637cd7d1be40260126b0cbbec071ecb", "139a46f044ee66d7a239f9e5b242ff8808f7e8c1",
                  "e21d92365fd5a18f361029aafd00d8a86c1afe15db7d1512ccc1906536f3e2e2", 1),
}
NODES = tuple(MEMBER + "::" + name for name in (
    "test_verified_code_view_never_stats_or_traverses_live_client_data",
    "test_source_census_refuses_unowned_content_before_returning_any_allowlist[raw-capture.bin]",
    "test_source_census_refuses_unowned_content_before_returning_any_allowlist[nested/capture.bin]",
    "test_source_census_refuses_unowned_content_before_returning_any_allowlist[unowned-empty/]",
    "test_default_staged_verification_still_refuses_client_data",
    "test_code_only_view_keeps_manifest_and_checksum_integrity_checks",
))
MAX_ENTRIES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 10_000, 64 * 1024 * 1024, 256 * 1024 * 1024
DATE = "2026-10-18T00:00:00+00:00"
_STATE = {"ready": False, "fd": None, "errors": [], "inputs": [], "teardowns": [], "outcomes": [],
          "selected": [],
          "builder_calls": 0, "subject": None, "builder_owner": None, "builder_wrapper": None,
          "template": None, "template_rows": None, "reference_rows": None, "paths": [],
          "base_temp": None, "root": None, "case": None, "source": None, "tree": None}
_WRITE, _CLOSE, _RUN = os.write, os.close, subprocess.run
_ENCODE = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False).encode


def _error(label):
    if len(_STATE["errors"]) < 32:
        _STATE["errors"].append(label)  # fixed labels only, never exception strings


def _ordinary(path, directory=False):
    metadata = path.lstat()
    if (path.resolve(strict=True) != path or stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or (not stat.S_ISDIR(metadata.st_mode) if directory else not stat.S_ISREG(metadata.st_mode))):
        raise ValueError("ordinary synthetic path required")
    if not directory and getattr(metadata, "st_nlink", 1) != 1:
        raise ValueError("single-link synthetic file required")
    return metadata


def _git(root, *arguments):
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0")
    result = _RUN(["git", "--no-replace-objects", "-c", "core.fsmonitor=false", "-C", str(root), *arguments],
                  env=environment, capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise ValueError("source guard refused")
    return result.stdout.decode("utf-8").strip()


def _guard():
    source, tree, digest, _builds = CASES[_STATE["case"]]
    root = _STATE["root"]
    if (_git(root, "rev-parse", "HEAD") != source or _git(root, "rev-parse", "HEAD^{tree}") != tree
            or _git(root, "status", "--porcelain", "--untracked-files=no")):
        raise ValueError("source guard refused")
    _ordinary(root / MEMBER)
    if hashlib.sha256((root / MEMBER).read_bytes()).hexdigest() != digest:
        raise ValueError("source file refused")


def _inventory(root):
    """Independent directory-inclusive byte census, excluding no member."""
    _ordinary(root, directory=True)
    if _STATE["base_temp"] is None or not root.is_relative_to(_STATE["base_temp"]):
        raise ValueError("pytest-owned root required")
    rows, stack, identities, total, empty_directories = [], [root], set(), 0, 0
    while stack:
        directory = stack.pop()
        children = sorted(directory.iterdir())
        if directory != root and not children:
            empty_directories += 1
        for path in children:
            if len(rows) >= MAX_ENTRIES:
                raise ValueError("inventory entry cap")
            metadata = path.lstat()
            relative = path.relative_to(root).as_posix()
            if (path.resolve(strict=True) != path or stat.S_ISLNK(metadata.st_mode)
                    or getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise ValueError("redirected synthetic member")
            if stat.S_ISDIR(metadata.st_mode):
                rows.append((relative, "directory", stat.S_IMODE(metadata.st_mode), None, None))
                stack.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                if getattr(metadata, "st_nlink", 1) != 1 or not metadata.st_ino:
                    raise ValueError("single ordinary file identity required")
                if metadata.st_size > MAX_FILE_BYTES or total + metadata.st_size > MAX_TOTAL_BYTES:
                    raise ValueError("inventory byte cap")
                with path.open("rb") as stream:
                    raw = stream.read(MAX_FILE_BYTES + 1)
                after = _ordinary(path)
                if ((after.st_mode, after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                        != (metadata.st_mode, metadata.st_dev, metadata.st_ino, metadata.st_size,
                            metadata.st_mtime_ns, metadata.st_ctime_ns) or len(raw) != metadata.st_size):
                    raise ValueError("synthetic member changed")
                total += len(raw)
                identities.add((metadata.st_dev, metadata.st_ino))
                rows.append((relative, "file", stat.S_IMODE(metadata.st_mode), len(raw), hashlib.sha256(raw).hexdigest()))
            else:
                raise ValueError("nonregular synthetic member")
    rows.sort()
    return tuple(rows), identities, {"inventory_sha256": hashlib.sha256(_ENCODE(rows).encode("utf-8")).hexdigest(),
                                     "files": len(identities), "directories": sum(row[1] == "directory" for row in rows),
                                     "empty_directories": empty_directories,
                                     "bytes": total, "single_links": True, "no_reparse_or_symlinks": True,
                                     "all_directory_entries_included": True, "content_normalization": "none"}


def _template_unchanged():
    rows, _identities, _summary = _inventory(_STATE["template"])
    if rows != _STATE["template_rows"]:
        raise ValueError("pristine template changed")


def pytest_configure(config):
    try:
        if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows"
                or sys.platform != "win32" or sys.version_info[:3] != (3, 12, 10)):
            raise ValueError("host refused")
        case = os.environ["ATLAS_SOURCEVIEW_PROOF_CASE"]
        if case not in CASES:
            raise ValueError("case refused")
        root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True) / "subject"
        requested = Path(os.environ["ATLAS_SOURCEVIEW_PROOF_SOURCE_ROOT"])
        temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        output = Path(os.environ["ATLAS_SOURCEVIEW_PROOF_REPORT"])
        _ordinary(root, directory=True)
        if (requested.absolute() != root or requested.resolve(strict=True) != root
                or output.absolute() != output.resolve() or not output.is_relative_to(temporary)
                or output.is_relative_to(root) or os.path.lexists(output)
                or os.environ.get("ATLAS_SOURCEVIEW_PROOF_SOURCE") != CASES[case][0]
                or os.environ.get("ATLAS_SOURCEVIEW_PROOF_TREE") != CASES[case][1]
                or os.environ.get("GIT_AUTHOR_DATE") != DATE or os.environ.get("GIT_COMMITTER_DATE") != DATE):
            raise ValueError("proof binding refused")
        _STATE.update(fd=os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOINHERIT, 0o600),
                      root=root, case=case, source=CASES[case][0], tree=CASES[case][1])
        _guard()
        _STATE["ready"] = True
    except Exception:
        _error("configuration_refused")


def pytest_collection_modifyitems(session, config, items):
    if not _STATE["ready"]:
        return
    try:
        if tuple(item.nodeid for item in items) != NODES:
            raise ValueError("exact six unchanged case IDs required")
        _STATE["selected"] = list(NODES)
        module = items[0].module
        if Path(module.__file__).resolve() != _STATE["root"] / MEMBER:
            raise ValueError("source module required")
        subject, original = module.subject, module.subject.build_portable_release

        def observed(*arguments, **keywords):
            _STATE["builder_calls"] += 1
            return original(*arguments, **keywords)

        _STATE.update(subject=subject, builder_owner=original, builder_wrapper=observed)
        subject.build_portable_release = observed
    except Exception:
        _error("collection_or_builder_binding_refused")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_fixture_setup(fixturedef, request):
    outcome = yield
    if (not _STATE["ready"] or outcome.excinfo is not None or fixturedef.baseid != MEMBER
            or fixturedef.argname not in ("installed", "pristine_installed")):
        return
    try:
        result = outcome.get_result()
        base = request.getfixturevalue("tmp_path_factory").getbasetemp().resolve(strict=True)
        _STATE["base_temp"] = base
        if not isinstance(result, Path) or result.resolve(strict=True) != result:
            raise ValueError("ordinary fixture root required")
        rows, identities, summary = _inventory(result)
        if fixturedef.argname == "pristine_installed":
            if _STATE["case"] != "candidate" or _STATE["template"] is not None:
                raise ValueError("one candidate template required")
            _STATE.update(template=result, template_rows=rows, template_inventory=summary)
            return
        if request.node.nodeid not in NODES or result != request.getfixturevalue("tmp_path") / "installed" / "Atlas":
            raise ValueError("private per-test destination required")
        if any(result == previous or result in previous.parents or previous in result.parents for previous in _STATE["paths"]):
            raise ValueError("distinct private copy required")
        _STATE["paths"].append(result)
        if _STATE["reference_rows"] is None:
            _STATE["reference_rows"] = rows
        if rows != _STATE["reference_rows"]:
            raise ValueError("full unnormalized per-case inputs differ")
        if _STATE["case"] == "candidate":
            template = _STATE["template"]
            if template is None or result == template or template in result.parents or result in template.parents:
                raise ValueError("separate pristine root required")
            pristine_rows, pristine_ids, _pristine_summary = _inventory(template)
            if pristine_rows != _STATE["template_rows"] or rows != pristine_rows or identities & pristine_ids:
                raise ValueError("pristine bytes or private identities differ")
        expected_builds = 1 if _STATE["case"] == "candidate" else len(_STATE["inputs"]) + 1
        if _STATE["builder_calls"] != expected_builds:
            raise ValueError("fixture build count before body differs")
        _STATE["inputs"].append({"nodeid": request.node.nodeid, **summary,
                                 "private_root": True, "matches_first_input": True,
                                 "builder_calls_before_body": _STATE["builder_calls"],
                                 "matches_pristine": _STATE["case"] == "candidate",
                                 "no_shared_pristine_identities": _STATE["case"] == "candidate"})
    except Exception:
        _error("fixture_census_refused")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    yield
    if not _STATE["ready"] or item.nodeid not in NODES:
        return
    try:
        if _STATE["case"] == "candidate":
            _template_unchanged()
        _STATE["teardowns"].append(item.nodeid)
    except Exception:
        _error("pristine_after_case_refused")


def pytest_runtest_logreport(report):
    if report.when == "call" and report.nodeid in NODES:
        _STATE["outcomes"].append({"nodeid": report.nodeid, "outcome": report.outcome})


def _emit(report):
    pending = (_ENCODE(report) + "\n").encode("utf-8")
    while pending:
        written = _WRITE(_STATE["fd"], pending)
        if written <= 0:
            raise OSError("proof report refused")
        pending = pending[written:]


def pytest_sessionfinish(session, exitstatus):
    if _STATE["fd"] is None:
        if exitstatus == 0:
            session.exitstatus = 1
        return
    try:
        _guard()
        if (_STATE["subject"] is None or _STATE["subject"].build_portable_release is not _STATE["builder_wrapper"]):
            raise ValueError("builder wrapper changed")
        if (_STATE["builder_calls"] != CASES[_STATE["case"]][3]
                or tuple(row["nodeid"] for row in _STATE["inputs"]) != NODES
                or tuple(_STATE["teardowns"]) != NODES
                or _STATE["outcomes"] != [{"nodeid": node, "outcome": "passed"} for node in NODES]):
            raise ValueError("proof denominator refused")
        if _STATE["case"] == "candidate":
            _template_unchanged()
    except Exception:
        _error("final_source_or_proof_denominator_refused")
    finally:
        if (_STATE["subject"] is not None
                and _STATE["subject"].build_portable_release is _STATE["builder_wrapper"]):
            _STATE["subject"].build_portable_release = _STATE["builder_owner"]
    report = {"status": "proved" if exitstatus == 0 and not _STATE["errors"] else "proof_refused",
              "source": _STATE["source"], "tree": _STATE["tree"], "case": _STATE["case"],
              "builder_calls": _STATE["builder_calls"], "expected_builder_calls": CASES[_STATE["case"]][3],
              "selected_count": len(_STATE["selected"]), "executed_count": len(_STATE["outcomes"]),
              "selected_nodeids": _STATE["selected"],
              "executed_nodeids": [row["nodeid"] for row in _STATE["outcomes"]],
              "inputs": _STATE["inputs"], "pristine_inventory": _STATE.get("template_inventory"),
              "pristine_unchanged_after_each_case": _STATE["case"] == "candidate" and not _STATE["errors"],
              "errors": _STATE["errors"], "pytest_exit_before_proof_decision": int(exitstatus),
              "limits": {"instrumented_proof_not_raw_timing": True, "all_input_bytes_unnormalized": True,
                         "file_timestamps_and_inode_values_not_content_digest": True,
                         "directory_names_and_modes_in_content_digest": True,
                         "fresh_single_link_files_and_no_shared_pristine_identities": True,
                         "no_assertion_gate_budget_timeout_or_gc_policy_changes": True,
                         "max_entries": MAX_ENTRIES, "max_file_bytes": MAX_FILE_BYTES,
                         "max_total_bytes": MAX_TOTAL_BYTES}}
    try:
        _emit(report)
    except Exception:
        _error("report_write_refused")
    if _STATE["errors"] and exitstatus == 0:
        session.exitstatus = 1


def pytest_unconfigure(config):
    if _STATE["fd"] is not None:
        _CLOSE(_STATE["fd"])
        _STATE["fd"] = None
