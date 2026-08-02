"""Client evidence must be un-committable — the UNION of two independently-developed guards.

Merged 2026-08-02 from an add/add conflict: two branches wrote a file of this name for the same
concern and neither knew about the other. The test sets are DISJOINT and both survive, because they
guard different halves of the same boundary:

  * engine OUTPUT (this file's first half, `_ignored*` helpers) — a free-choice `--output <name>.xlsx`
    writes ~12 siblings beside it, so an ignore rule keyed on the default `Migration_Assessment_*`
    name left every other run fully committable.
  * capture INPUT and local state (second half, `_is_ignored` helper) — the registered command
    families under an arbitrary `--collection-dir`, the collection metadata sidecars, and the
    AssessHub database.

The second half is the structurally stronger of the two and is worth reading first: it derives the
capture set by parsing the engine's own `COMMANDS_*` lists with `ast`, so a newly added capture
command cannot silently fall outside the ignore contract. The first half still uses a curated artifact
list, which is the weaker form this repository's review repeatedly warns about — it is kept because it
covers a different producer (`docmeta.CLI_ARTIFACT_SUFFIX` output siblings), not because the shape is
good. Deriving it from `docmeta` the way the second half derives captures from `COMMANDS_*` is the
obvious next improvement.

Both halves use git itself as the oracle rather than re-implementing .gitignore semantics, and both
assert in BOTH directions — a rule broad enough to catch everything can also swallow the fixtures the
repository legitimately tracks.

Helper names are deliberately left distinct (`_ignored`/`_ignored_many` vs `_git`/`_is_ignored`,
`_ROOT` vs `ROOT`) rather than unified: they were written independently, and collapsing them here
would be an unreviewed refactor riding in on a merge commit.
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

import pytest


# ---------------------------------------------------------------- engine OUTPUT artifacts
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ignored(path: str) -> bool:
    """git's own answer — never a re-implementation of gitignore semantics."""
    return subprocess.run(["git", "check-ignore", "--no-index", "-q", path],
                          cwd=_ROOT, capture_output=True).returncode == 0


def _ignored_many(paths):
    """Which of *paths* git considers ignored — ONE subprocess, same flags as `_ignored`.

    The per-path form spawns `git check-ignore` once per file. Over the whole index (600+ tracked
    files) that is 600+ process creations, and on Windows process creation is expensive enough that
    this single test measured ~51 s — the second-slowest in the suite. `--stdin` answers the same
    question in one call; `-z` keeps paths with spaces or non-ASCII bytes intact, which the
    line-split form would have mangled.

    Semantics are git's own either way: check-ignore prints the paths it considers ignored and exits
    1 when none match, so an empty result is a real "none", not a swallowed error. `_ignored` is kept
    for the single-path callers and is what `test_the_probe_itself_discriminates` guards — if these
    two ever disagreed, that test still pins the per-path answer.
    """
    if not paths:
        return []
    proc = subprocess.run(["git", "check-ignore", "--no-index", "--stdin", "-z"],
                          cwd=_ROOT, input="\0".join(paths) + "\0",
                          capture_output=True, text=True)
    # 0 = some matched, 1 = none matched. Anything else is a real failure and must not read as clean.
    assert proc.returncode in (0, 1), (
        f"git check-ignore --stdin failed (rc={proc.returncode}): {proc.stderr[:200]}"
    )
    return [p for p in proc.stdout.split("\0") if p]


# Named for the engine artifact each one stands for, so a failure says WHICH deliverable leaks.
_CLIENT_ARTIFACTS = [
    "AcmeBank_Q1.snapshot.json",                    # the parsed estate, every device
    "AcmeBank_Q1.run_manifest.json",                # chain-of-custody for the above
    "AcmeBank_Q1.phase_timings.json",
    "AcmeBank_Q1_mop.docx",                         # the change plan
    "AcmeBank_Q1_design.docx",
    "AcmeBank_Q1_crd.docx",
    "AcmeBank_Q1_engagement.docx",
    "AcmeBank_Q1_archreview.docx",
    "AcmeBank_Q1_ops_handbook.docx",
    "AcmeBank_Q1_runbook.docx",
    "AcmeBank_Q1_deck.pptx",
    "AcmeBank_Q1_explorer.html",
    "AcmeBank_Q1_IP_CROSSWALK.xlsx",                # pseudonym -> real IP; must never travel
    "out/Acme_design.docx",                         # a nested output directory
    "Migration_Assessment_NEWCLIENT.snapshot.json",  # not the AUTOFILLED prefix
    "captures/sw1/show_running-config.txt",         # raw capture: credentials live here
    "evidence/show_version.txt",
    "Client_Q3.xlsx",
    "custom/Migration_Diff_custom.xlsx",
    "custom/Migration_Diff_custom.xlsx.precert.json",
    "custom/Migration_Trend_custom.xlsx",
    "custom/assessment.precert-readiness.json",
    "captures/sw1_capture_meta.json",
    "captures/sw1/device_info.json",
    "captures/sw1/command_index.json",
    "controller/moquery_-c_fvTenant.txt",
    "controller/ers_config_networkdevice.txt",
    "controller/dataservice_device.txt",
    "controller/api_fmc_devices.txt",
    "cloud/aws_ec2_describe-instances.txt",
    "firewall/get_system_ha_status.txt",
    "client-inputs/devices-prod.json",
    "private-inputs/requirements.json",
    "engagements/site-a/golden-config.txt",
    ".claude/settings.before-ultracode.json",
]

# What the repo legitimately tracks and a broad rule could swallow.
_MUST_STAY_VISIBLE = [
    "tests/golden/snapshot.json",
    "webapp/sample_data/sample_fleet.snapshot.json",
    "cisco_toolkit/blast_radius_explorer.html",
]


@pytest.mark.parametrize("artifact", _CLIENT_ARTIFACTS)
def test_engine_output_cannot_be_committed_whatever_the_run_was_named(artifact):
    assert _ignored(artifact), (
        f"{artifact} is NOT git-ignored — a `git add -A` would commit client evidence. "
        "The rule must match the artifact SHAPE, not one run's name prefix.")


@pytest.mark.parametrize("tracked", _MUST_STAY_VISIBLE)
def test_the_fixtures_the_repo_tracks_are_not_swallowed(tracked):
    """Refute the fix: a rule broad enough to catch every client artifact must not hide the pinned
    fixtures. Without the negations this fails, which is the whole risk of widening these rules."""
    assert os.path.isfile(os.path.join(_ROOT, tracked)), f"{tracked} vanished"
    assert not _ignored(tracked), f"{tracked} is git-ignored — the repo tracks it"


def test_no_tracked_file_anywhere_became_ignored():
    """The general form of the check above, over the WHOLE index rather than three names I thought
    of. A widening that hides a tracked file is a silent loss the next clone inherits."""
    tracked = subprocess.run(["git", "ls-files"], cwd=_ROOT,
                             capture_output=True, text=True).stdout.split("\n")
    tracked = [f for f in tracked if f.strip() and os.path.isfile(os.path.join(_ROOT, f))]
    assert len(tracked) > 400, f"index looks wrong ({len(tracked)} files) — this test would be vacuous"
    lost = _ignored_many(tracked)
    assert not lost, f"{len(lost)} TRACKED file(s) are now git-ignored: {lost[:10]}"


def test_the_probe_itself_discriminates():
    """Guard the guard: `git check-ignore` must actually answer both ways here, or every assertion
    above is decoration. `.venv/` is ignored by this repo; this source file is not."""
    assert _ignored(".venv/x"), "check-ignore never reports ignored — the probe is inert"
    assert not _ignored("tests/test_r8_client_evidence_is_ignored.py")


def test_frontend_distribution_remains_packagable():
    assert not _ignored("webapp/frontend/dist/index.html")


# ---------------------------------------------------------------- capture INPUT + local state
ROOT = Path(__file__).resolve().parents[1]
ENTRY_MODULE = ROOT / "COLLECT_PARSE_V3_23_0.py"
_REQUIRED_COMMAND_LISTS = {
    "COMMANDS_NXOS",
    "COMMANDS_IOS",
    "COMMANDS_ARISTA",
    "COMMANDS_JUNIPER",
    "COMMANDS_CLOUD",
    "COMMANDS_FORTINET",
}
_COLLECTION_SIDECARS = ("device_info.json", "command_index.json", "_capture_meta.json")


def _git() -> str:
    git = shutil.which("git")
    assert git is not None, "git is required to verify the repository's ignore contract"
    return git


def _is_ignored(path: str) -> bool:
    proc = subprocess.run(
        [_git(), "check-ignore", "--no-index", "--quiet", "--", path],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode in (0, 1), (
        f"git check-ignore failed for {path!r}: rc={proc.returncode}; "
        f"stdout={proc.stdout!r}; stderr={proc.stderr!r}"
    )
    return proc.returncode == 0


def _ignored_paths(paths: Iterable[str]) -> set[str]:
    requested = tuple(paths)
    # NUL-separated (`-z`) and BINARY, not newline-separated text. In text mode Python translates
    # "\n" to "\r\n" on Windows when writing to the pipe, so git receives `...show_version.txt\r`,
    # matches nothing, and this oracle reports every path as NOT ignored. Measured on this box:
    #   --stdin  (text, newline)  -> rc=1, 0 of 2 matched
    #   -z --stdin (bytes, NUL)   -> rc=0, 2 of 2 matched
    #   feeding an explicit trailing "\r" reproduces the miss exactly, which is the proof.
    # It fails CLOSED -- an unignored verdict makes these tests shout rather than pass wrongly -- but
    # it made the whole batch contract unusable on Windows. The sibling commit that normalized git's
    # OUTPUT backslashes fixed the return direction; this is the input direction.
    proc = subprocess.run(
        [_git(), "check-ignore", "--no-index", "-z", "--stdin"],
        cwd=ROOT,
        input=b"".join(path.encode("utf-8") + b"\x00" for path in requested),
        check=False,
        capture_output=True,
    )
    assert proc.returncode in (0, 1), (
        f"git check-ignore -z --stdin failed: rc={proc.returncode}; "
        f"stdout={proc.stdout!r}; stderr={proc.stderr!r}"
    )
    # Git for Windows emits native backslashes for batch results even when stdin used POSIX paths.
    # The ignore decision is path-separator agnostic; normalize before comparing with requested paths.
    return {p.decode("utf-8").replace("\\", "/") for p in proc.stdout.split(b"\x00") if p}


def _registered_capture_filenames() -> tuple[str, ...]:
    tree = ast.parse(ENTRY_MODULE.read_text(encoding="utf-8"), filename=str(ENTRY_MODULE))
    found_lists: set[str] = set()
    filenames: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.startswith("COMMANDS_"):
            continue
        try:
            commands = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError):
            continue  # e.g. computed COMMANDS_ALL; the literal source lists are audited below
        if not isinstance(commands, list) or not all(isinstance(command, str) for command in commands):
            continue
        found_lists.add(target.id)
        for command in commands:
            filename = (
                command.replace(" ", "_")
                .replace("|", "_")
                .replace("^", "")
                .replace("/", "_")
                + ".txt"
            )
            filenames.add(filename)

    missing_lists = sorted(_REQUIRED_COMMAND_LISTS - found_lists)
    assert not missing_lists, f"registered command lists were not statically auditable: {missing_lists}"
    assert len(filenames) >= 100, f"unexpectedly small capture registry: {len(filenames)} filenames"
    return tuple(sorted(filenames))


_REGISTERED_CAPTURE_FILENAMES = _registered_capture_filenames()


# The original 17 shapes reproduced during the whole-repository review: the generated default,
# common custom collection roots, explicit client-evidence roots, an ordinary capture under an
# arbitrary root, and the persistent AssessHub database sidecar.
_CLIENT_ARTIFACTS = (
    "migration_collection_20260730_182700/CORE-1/show_running-config.txt",
    "collection/CORE-1/show_version.txt",
    "collections/ACME/CORE-1/show_version.txt",
    "collection_acme/CORE-1/show_version.txt",
    "collections_acme/CORE-1/show_version.txt",
    "client_data/ACME/snapshot.json",
    "client-data/ACME/snapshot.json",
    "client_evidence/ACME/CORE-1/show_version.txt",
    "client-evidence/ACME/CORE-1/show_version.txt",
    "evidence/ACME/CORE-1/show_version.txt",
    "captures/ACME/CORE-1/show_version.txt",
    "raw_collection/ACME/CORE-1/show_version.txt",
    "raw-collection/ACME/CORE-1/show_version.txt",
    "raw_evidence/ACME/CORE-1/show_version.txt",
    "raw-evidence/ACME/CORE-1/show_version.txt",
    "arbitrary_export/CORE-1/show_version.txt",
    "webapp/data/assesshub.db-wal",
)


@pytest.mark.parametrize("path", _CLIENT_ARTIFACTS)
def test_original_client_evidence_shapes_are_ignored(path: str) -> None:
    assert _is_ignored(path), f"client evidence is commit-visible: {path}"


def test_every_registered_capture_is_ignored_under_an_arbitrary_root() -> None:
    paths = tuple(
        f"customer-chosen-output/CORE-1/{filename}"
        for filename in _REGISTERED_CAPTURE_FILENAMES
    )
    missing = sorted(set(paths) - _ignored_paths(paths))
    assert not missing, f"registered client captures are commit-visible: {missing}"


def test_collection_metadata_sidecars_are_ignored_under_an_arbitrary_root() -> None:
    paths = tuple(f"customer-chosen-output/CORE-1/{name}" for name in _COLLECTION_SIDECARS)
    missing = sorted(set(paths) - _ignored_paths(paths))
    assert not missing, f"collection metadata is commit-visible: {missing}"


@pytest.mark.parametrize(
    "path",
    (
        "webapp/data/assesshub.db",
        "webapp/data/assesshub.db-shm",
        "webapp/data/assesshub.sqlite",
        "webapp/data/assesshub.sqlite-wal",
        "webapp/data/assesshub.sqlite3",
        "webapp/data/assesshub.sqlite3-shm",
    ),
)
def test_assesshub_database_and_sidecars_are_ignored(path: str) -> None:
    assert _is_ignored(path), f"client snapshot database is commit-visible: {path}"


def test_reviewable_registered_test_fixtures_are_not_hidden() -> None:
    paths = tuple(f"tests/fixtures/{filename}" for filename in _REGISTERED_CAPTURE_FILENAMES)
    hidden = sorted(_ignored_paths(paths))
    assert not hidden, f"synthetic registered test fixtures were over-ignored: {hidden}"


def test_reviewable_collection_metadata_test_fixtures_are_not_hidden() -> None:
    paths = tuple(f"tests/fixtures/{name}" for name in _COLLECTION_SIDECARS)
    hidden = sorted(_ignored_paths(paths))
    assert not hidden, f"synthetic collection metadata was over-ignored: {hidden}"


def test_normal_source_and_document_paths_remain_visible() -> None:
    for path in (
        "cisco_toolkit/data/port_registry.tsv.gz",
        "cisco_toolkit/eoldb.py",
        "tests/test_redact_collection.py",
        "docs/client-evidence-handling.md",
        "webapp/data/README.md",
    ):
        assert not _is_ignored(path), f"legitimate repository content was over-ignored: {path}"
