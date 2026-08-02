"""No engine output can be committed by accident, whatever the operator named the run.

`.gitignore` excluded client evidence by NAME: `migration_collection_*/` and
`Migration_Assessment_AUTOFILLED_*`. But the engine takes a free-choice `--output <name>.xlsx` —
CLAUDE.md's own documented invocation — and writes ~12 siblings beside it
(`docmeta.CLI_ARTIFACT_SUFFIX` plus `.snapshot.json` / `.run_manifest.json` / `.phase_timings.json`).
Any run not named with that one prefix was fully committable. Measured before the fix:

    AcmeBank_Q1.snapshot.json             -> committable
    AcmeBank_Q1_mop.docx                  -> committable
    captures/sw1/show_running-config.txt  -> committable

The last is the one that matters: a running-config carries SNMP communities, TACACS keys, enable
secrets and VPN PSKs — exactly what `--redact-collection` exists to scrub. One `git add -A` is all it
takes, and this repo has already had `git add -A` sweep in files nobody intended.

This is the "guard written for a NAMED subset instead of the STRUCTURAL class" pattern the review
found repeatedly (an API guard keyed on a path prefix; a read-only check keyed on method names). Here
the blast radius is client-confidential data in git history, which is not undoable by a later commit.

Both directions are asserted, because a rule broad enough to catch everything can also swallow the
fixtures the repo legitimately tracks.
"""

from __future__ import annotations

import os
import subprocess

import pytest

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
