"""Ratchet the repository's shared Claude/Codex context contract.

These assertions intentionally cover tracked instruction text: the behavior being
protected is what a fresh agent is told before it touches the codebase.
"""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_root_agents_bootstraps_codex_into_shared_owners() -> None:
    text = _read("AGENTS.md")

    for owner in ("CLAUDE.md", "docs/ssot.md", "docs/quality/learnings.md"):
        assert owner in text, f"AGENTS.md no longer points Codex at {owner}"
    assert "Codex does not automatically" in text
    assert "Cross-agent state is synchronized only" in text
    assert "Current owner code, tests, manifests" in text


def test_ssot_does_not_make_claude_memory_the_cross_agent_owner() -> None:
    text = _read("docs/ssot.md")
    state_row = next(
        line
        for line in text.splitlines()
        if "Project decisions / current cross-agent state" in line
    )
    doctrine_row = next(
        line for line in text.splitlines() if "Operating doctrine / PPDIOO" in line
    )

    assert "live Git" in state_row
    assert "platform-specific caches, never the sole owner" in state_row
    assert "root `AGENTS.md`" in state_row
    assert "shared owner for every agent surface" in doctrine_row
    assert "Codex enters through root `AGENTS.md`" in doctrine_row


@pytest.mark.parametrize(
    ("path", "required", "spent_instruction"),
    [
        (
            "docs/atlas-p3-plan-2026-07-21.md",
            "Status (reconciled 2026-08-07): SHIPPED",
            "awaiting owner approval before implementation",
        ),
        (
            "docs/session-closeout-2026-07-23.md",
            "HISTORICAL ARCHIVE",
            "use this file as the current work queue",
        ),
        (
            "docs/autonomous-brain-plan-v4-final-2026-07-06.md",
            "Implementation-status reconciliation (2026-08-07)",
            "single highest-impact next build",
        ),
        (
            "docs/remaining-work-plan-2026-07-08.md",
            "Phase 0a — citation grounding",
            "2 remaining citations",
        ),
        (
            "docs/architect-master-plan-2026-07-10.md",
            "Implementation-status reconciliation (2026-08-07)",
            "this plan becomes the active work-plan index",
        ),
        (
            "docs/orchestration-best-roadmap.md",
            "Status reconciliation (2026-08-07",
            "Nothing here is implemented yet",
        ),
        (
            "docs/review-findings-2026-07-28.md",
            "That handoff is closed and is not a continuation plan",
            "for the live, loss-preserving checkpoint",
        ),
    ],
)
def test_dated_records_cannot_reassert_spent_work(
    path: str, required: str, spent_instruction: str
) -> None:
    text = _read(path)

    assert required in text
    assert spent_instruction not in text


def test_claude_shared_context_describes_current_hook_semantics() -> None:
    text = _read("CLAUDE.md")

    assert "Closed carried questions, retained for context" in text
    assert "~1,800 test functions" not in text
    assert "All are fail-open" not in text
    assert "blocks on an observed test failure or timeout" in text
    assert "Codex does not execute these Claude hooks automatically" in text

    hook = _read(".claude/hooks/verify-green.sh")
    assert "A pytest timeout is" in hook
    assert "still RED and exits 2" in hook
    assert "fail OPEN on timeout" not in hook
