---
name: release-state
description: Current release baseline as of 2026-07-06 — latest tag v3.30.0, schema version frozen at 3.23.0, PR #293 merged post-tag needs no release
metadata:
  type: project
---

Release baseline as of 2026-07-06 (verify tags/pyproject live before acting — this is a snapshot):

- Latest tag: **v3.30.0**; `pyproject.toml` `[project] version` = **3.30.0** (tag and pyproject in sync, no pending bump).
- Schema version `cisco_toolkit.__version__` = **3.23.0** — DECOUPLED and frozen. Never bump it; doing so churns the golden snapshot (`tests/test_pipeline_golden.py`).
- Post-tag merge: **PR #293** (feat/second-brain-bridge, merge commit 37d68bc) merged 2026-07-06. Scope: agent-rig / knowledge-bridge only — `/retro` command, vault-guard PreToolUse hook, session-brief rot watch. **No engine change → no release needed for it.**

**Why:** Bumps happen only at release-tag time; #293 touches `.claude/` rig plumbing, not `cisco_toolkit/`, so it rides until the next engine-driven release.

**How to apply:** When the next release is cut, changes-since-last-tag start at v3.30.0 and include #293 in the narrative (rig-only, non-engine). Do not propose a release solely for #293.
