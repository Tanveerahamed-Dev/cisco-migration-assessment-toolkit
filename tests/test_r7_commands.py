"""Mechanical guards for `.claude/commands/` — the slash-command instruction layer.

These files are executable in every sense that matters: when a user types `/assess` or
`/audit`, the file's text becomes the operating directive for an agent that holds Bash and
can reach production network gear. They carry no imports and no call sites, so nothing else
in the suite pins them; a renamed agent, a renamed engine flag or a deleted guardrail rots
silently and only surfaces mid-engagement, in front of the user.

Everything here is matched WHITESPACE-NORMALISED so re-wrapping a paragraph (these are prose
files — re-wraps are routine) cannot un-pin an assertion.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
COMMANDS = REPO / ".claude" / "commands"
AGENTS = REPO / ".claude" / "agents"
ENGINE = REPO / "COLLECT_PARSE_V3_23_0.py"

COMMAND_FILES = sorted(COMMANDS.glob("*.md"))
OWNED_PROSE = COMMAND_FILES + sorted((REPO / ".claude" / "output-styles").glob("*.md"))


def norm(text: str) -> str:
    """Collapse every run of whitespace to a single space, so a re-wrap cannot un-pin a phrase."""
    return re.sub(r"\s+", " ", text)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_command_corpus_is_present() -> None:
    """Guard the guards: if the glob silently returns nothing, every test below is vacuous."""
    assert len(COMMAND_FILES) >= 14, f"expected the command corpus, found {COMMAND_FILES}"
    assert (AGENTS / "deliverable-qa-reviewer.md").is_file(), "agent roster not found"


# --------------------------------------------------------------------------------------
# Stale references: every agent / flag / module / path a command names must EXIST.
# --------------------------------------------------------------------------------------

# This roster is named by role suffix (assessment-analyst, config-security-auditor,
# design-author, mop-change-author, nrfu-validator, deliverable-qa-reviewer,
# release-captain, topology-reachability-analyst). Requiring the hyphen keeps prose like
# "the authoring agents" or "MOP author" out of the match set.
AGENT_REF = re.compile(r"\b[a-z][a-z-]*-(?:analyst|auditor|author|validator|reviewer|captain)\b")


@pytest.mark.parametrize("path", OWNED_PROSE, ids=lambda p: p.name)
def test_every_referenced_agent_exists(path: Path) -> None:
    """A command that delegates to a renamed agent fails at the worst moment — mid-engagement."""
    roster = {p.stem for p in AGENTS.glob("*.md")}
    for name in sorted(set(AGENT_REF.findall(read(path)))):
        assert name in roster, (
            f"{path.name} delegates to '{name}', which is not in .claude/agents/ "
            f"(roster: {sorted(roster)})"
        )


def test_engine_flags_named_in_commands_exist() -> None:
    """`/assess` and `/deliverables` spell out real `cisco-assess` argv — pin it to the argparse."""
    real = set(re.findall(r'"(--[a-z0-9-]+)"', read(ENGINE)))
    assert "--no-collect" in real, "engine flag scan found nothing — the regex has rotted"
    for name in ("assess.md", "deliverables.md"):
        cited = set(re.findall(r"(--[a-z][a-z0-9-]+)", read(COMMANDS / name)))
        missing = sorted(cited - real)
        assert not missing, f"{name} names engine flags that do not exist: {missing}"


@pytest.mark.parametrize("path", COMMAND_FILES, ids=lambda p: p.name)
def test_python_m_module_paths_resolve(path: Path) -> None:
    """`python -m cisco_toolkit.<mod>` must name a module that is actually on disk."""
    for mod in sorted(set(re.findall(r"python -m (cisco_toolkit\.[a-z_]+)", read(path)))):
        target = REPO / (mod.replace(".", "/") + ".py")
        assert target.is_file(), f"{path.name} invokes `{mod}`, but {target} does not exist"


# Gitignored by design, so a clean clone / worktree / CI carries none of it. Exempt from the
# "cited path resolves" sweep, with the reason recorded rather than silently skipped.
GITIGNORED_BY_DESIGN = {
    "docs/quality/query_log.jsonl",  # append-only real-query log, owner-machine (docs/ssot.md)
}

CITED_PATH = re.compile(
    r"(?:docs|tests|cisco_toolkit|portable|webapp|\.claude|\.github)"
    r"/[\w./-]+\.(?:md|jsonl|yaml|yml|py|sh|xlsx|json)"
)


@pytest.mark.parametrize("path", OWNED_PROSE, ids=lambda p: p.name)
def test_cited_repo_paths_resolve(path: Path) -> None:
    """A command citing a renamed doc sends the agent to a file that is not there."""
    for cited in sorted(set(CITED_PATH.findall(read(path)))):
        if "<" in cited or cited in GITIGNORED_BY_DESIGN:
            continue  # a dated/templated placeholder, or gitignored by design
        assert (REPO / cited).exists(), f"{path.name} cites {cited}, which does not exist"


# --------------------------------------------------------------------------------------
# Doctrine: a command must not instruct behaviour its own stated constraint forbids.
# --------------------------------------------------------------------------------------


def test_audit_forbids_implicit_live_collection() -> None:
    """`/audit` declares itself read-only; read-only must exclude a live SSH collection.

    The defect this pins: the command declared "Read-only -- propose, don't remediate" while
    its argument-hint offered a bare `device` as a target and its body never said
    `--no-collect`. A bare `cisco-assess` SSHes to live gear, so `/audit sw-core-01` reads as
    explicit instruction to collect -- satisfying every word of the stated constraint while
    touching production. CLAUDE.md: "a bare `cisco-assess` SSHes to live gear -- only run a
    live collection when explicitly asked."
    """
    body = norm(read(COMMANDS / "audit.md"))
    assert "--no-collect" in body, "/audit lost its offline re-analysis instruction"
    assert "Read-only also means **no live collection**" in body, (
        "/audit lost the guardrail separating 'read-only' from 'no live collection'"
    )
    hint = next(ln for ln in read(COMMANDS / "audit.md").splitlines()
                if ln.startswith("argument-hint:"))
    assert "device" not in hint, (
        f"/audit argument-hint again offers a live device as a target: {hint!r}"
    )


DEVICE_WRITE = ("write to the device", "write to devices", "apply the config",
                "push the config", "configure the device")
# Most hits are PROHIBITIONS ("do not write to devices") -- the guardrail, not the defect. Only
# an unnegated occurrence is an instruction to write.
NEGATION = re.compile(r"(?:\bnot\b|\bnever\b|\bno\b|\bn't\b)[^.;]{0,40}$")


@pytest.mark.parametrize("path", COMMAND_FILES, ids=lambda p: p.name)
def test_no_command_instructs_a_device_write(path: Path) -> None:
    """Read-only by default is Law: no command may tell an agent to configure or push to gear."""
    body = norm(read(path)).lower()
    for forbidden in DEVICE_WRITE:
        for m in re.finditer(re.escape(forbidden), body):
            lead = body[max(0, m.start() - 60):m.start()]
            assert NEGATION.search(lead), (
                f"{path.name} instructs a device write (unnegated): "
                f"...{body[max(0, m.start() - 60):m.end() + 20]}..."
            )


def test_qa_keeps_the_proposer_verifier_wedge() -> None:
    """`/qa` must keep declaring the provenance pair — it is what makes the CLI able to refuse."""
    body = norm(read(COMMANDS / "qa.md"))
    assert "--authored-by" in body and "--reviewed-by" in body
    assert "it must not be the agent that authored them" in body


def test_architect_plan_scorecard_record_declares_provenance() -> None:
    """`/architect-plan` §9 must stamp the row it mints, not just record it.

    `--authored-by` / `--reviewed-by` are OPTIONAL to the CLI (`check_independence` only
    refuses when BOTH are non-empty and equal), so `--record <file>` alone lands a row with no
    independence evidence -- and `judge_provenance` then returns '' so the APPROVE is marked
    provisional. §9 exists to make a doctrine-3 claim; unstamped, that claim goes unrecorded.
    """
    body = norm(read(COMMANDS / "architect-plan.md"))
    assert "--record <file> --authored-by main --reviewed-by deliverable-qa-reviewer" in body, (
        "architect-plan §9 records a QA row without the proposer!=verifier provenance pair"
    )


def test_architect_plan_prior_art_is_enumerated_live() -> None:
    """The prior-art list is a work order; frozen, it silently drops everything added later.

    Written 2026-07-10 naming "ADRs 0001-0003", it now misses 0004 (Atlas), 0005 (Cognee -- a
    REJECT decision inside this command's own default brain-layer scope) and 0006, plus its own
    prior master plan. Worker R reconciles exactly what this list names.
    """
    raw = read(COMMANDS / "architect-plan.md")
    body = norm(raw)
    assert "ENUMERATE IT LIVE" in body, "architect-plan froze its prior-art list again"
    assert "every ADR in `docs/decisions/`" in body
    assert "reads the eight prior plan documents + ADRs 0001–0003" not in body, (
        "Dimension R still hands Worker R a frozen ADR range"
    )
    # The seed list is provably stale: more ADRs exist than it names. If that ever stops being
    # true this assertion should be revisited, not deleted.
    adrs = {p.name for p in (REPO / "docs" / "decisions").glob("[0-9][0-9][0-9][0-9]-*.md")}
    assert len(adrs) > 3, f"expected the ADR set to have outgrown the seed list, found {adrs}"


def test_council_does_not_overclaim_offline() -> None:
    """`/council` selects `config-security-auditor`, whose charter mandates a PSIRT WebSearch.

    A flat "no external fetch" is therefore a claim the command cannot keep; the seam must stay
    named so an air-gapped run is told to close it.
    """
    body = norm(read(COMMANDS / "council.md"))
    assert "no external fetch." not in body, "/council overclaims: it spawns a WebSearch agent"
    assert "config-security-auditor" in body and "WebSearch" in body
