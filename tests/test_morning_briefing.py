"""Regression guard for the morning briefing's two state counters (.claude/hooks/morning-briefing.sh).

The briefing is the "what to look at today" instrument, so a FALSE signal there costs attention every
morning and never self-corrects. Both counters guarded here previously inferred *state* from *prose*
in narrative documents:

- ``todos()`` scanned ``docs/**/*.md``. On 2026-07-26 it reported "4 TODO/FIXME across 2 file(s)"
  while the real code-debt count was **0** — three of the four came from a single sentence asserting
  the census is zero, and the fourth from a retro bullet using the word. Self-refuting by
  construction, and monotonically growing: every future retro mentioning "TODO" added one.
- ``open_items()`` scanned every ``docs/**/*.md`` including ``docs/log.md``. That log is append-only
  history, so one retro sentence naming ``REC-6`` reported it as an open engagement item forever,
  with no status check anywhere in the pipeline.

These tests run the real script against a hermetic fixture repo (the script ``cd``s to the git
toplevel, so a temp repo fully isolates it). Each asserts BOTH halves: the phantom is gone AND the
counter still fires on a genuine item — a test that only proved absence would pass against a counter
that had been disabled outright.
"""
import os
import re
import shutil
import subprocess

import pytest

_BASH = shutil.which("bash")
_GIT = shutil.which("git")
_ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True).stdout.strip() or None
_SCRIPT = os.path.join(".claude", "hooks", "morning-briefing.sh")

pytestmark = pytest.mark.skipif(
    not (_BASH and _GIT and _ROOT and os.path.exists(os.path.join(_ROOT, _SCRIPT))),
    reason="bash / git / briefing script unavailable")


def _fixture_repo(tmp_path):
    """A throwaway git repo carrying one of each: phantom marker, real marker, phantom item, real item."""
    subprocess.run([_GIT, "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "cisco_toolkit").mkdir()

    # PHANTOM debt: prose *about* markers — the exact self-refuting sentence that produced 3 hits.
    (tmp_path / "docs" / "architect-note.md").write_text(
        "## Gaps & debt\n"
        "- Marker census = 0 across scoped source "
        "(TODO/FIXME/HACK/XXX/stub/commented-out/bare-except all zero) - unusually disciplined.\n",
        encoding="utf-8")

    # PHANTOM open item: append-only narrative history naming a past item.
    (tmp_path / "docs" / "log.md").write_text(
        "# Session log\n\n"
        "## [2026-01-01] - a past session\n"
        "- Closed the optics gap; REC-6 was the driver and GI-4 was the gate.\n"
        "- !lesson something worth remembering. bridge-candidate\n",
        encoding="utf-8")

    # REAL open item: a live register that is NOT the log and NOT a briefing.
    (tmp_path / "docs" / "open-items.md").write_text(
        "# Live register\n\n- GI-9 - cable schedule freeze, OPEN.\n", encoding="utf-8")

    # REAL code debt: an actual marker in source.
    (tmp_path / "cisco_toolkit" / "real_module.py").write_text(
        "def f():\n    # TODO: genuine code debt, must still be counted\n    return 1\n",
        encoding="utf-8")

    # SELF-POISONING guard: a test file that is ABOUT markers necessarily contains them. This file
    # itself carries ~13. Including tests/ in the scan re-created the exact defect one directory
    # over, so the fixture plants one here and the counter must ignore it.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_about_markers.py").write_text(
        'def test_x():\n    # TODO FIXME XXX - a test ABOUT markers, not debt\n    assert 1\n',
        encoding="utf-8")
    return tmp_path


def _run(repo):
    env = dict(os.environ)
    env.pop("ASNE_BRIEF_MODE", None)
    p = subprocess.run([_BASH, os.path.join(_ROOT, _SCRIPT)], cwd=repo, env=env,
                       capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, f"briefing must stay fail-open; got {p.returncode}\n{p.stderr}"
    return p.stdout


def test_todo_counter_ignores_prose_and_still_counts_source(tmp_path):
    out = _run(_fixture_repo(tmp_path))
    m = re.search(r"\*\*TODO/FIXME\*\*: (\d+) across (\d+) file", out)
    assert m, f"TODO/FIXME line missing from briefing:\n{out}"
    n, files = int(m.group(1)), int(m.group(2))

    # The fixture holds exactly ONE countable marker (cisco_toolkit/real_module.py). The others are
    # phantoms: three inside a sentence saying the count is zero, and three in a tests/ file that is
    # ABOUT markers. Pre-fix this read 4 across 2; with tests/ wrongly included it read 13 across 1
    # against the real repo.
    assert (n, files) == (1, 1), (
        f"expected the single SHIPPING-SOURCE marker only, got {n} across {files} file(s). "
        "A count >1 means docs prose or tests/ is being counted as code debt again."
    )


def test_open_items_ignores_the_append_only_log_but_keeps_a_live_register(tmp_path):
    out = _run(_fixture_repo(tmp_path))

    # GI-9 lives in a real register -> must still be reported (proves the scanner is not just off).
    assert "GI-9" in out, f"a live register entry must still be surfaced:\n{out}"

    # REC-6 exists ONLY in docs/log.md (narrative history) -> must not be resurrected as open.
    assert "REC-6" not in out, (
        "REC-6 appears only in the append-only log; reporting it as an open engagement item is the "
        "monotonic false positive this guard exists to prevent"
    )
    # GI-4 is in the same log sentence — same rule, guards against an over-narrow REC-only fix.
    assert "GI-4" not in out, "GI- items in the append-only log must be excluded too, not just REC-"


def test_briefing_is_fail_open_on_a_bare_repo(tmp_path):
    """No docs/, no source, no pyproject — every metric degrades, nothing raises."""
    subprocess.run([_GIT, "init", "-q"], cwd=tmp_path, check=True)
    out = _run(tmp_path)
    assert "Morning briefing" in out
    assert "**TODO/FIXME**: 0 across 0 file(s)" in out
