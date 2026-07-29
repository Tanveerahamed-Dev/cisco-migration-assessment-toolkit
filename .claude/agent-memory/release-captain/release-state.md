---
name: release-state
description: How to read the release baseline from its OWNERS (git tags + pyproject) rather than from this file, plus the one durable rule — schema version 3.23.0 is frozen and never bumped.
metadata:
  type: project
---

**Read the baseline live. Do not trust a number written here.**

- Latest tag — owner: `git tag --sort=-v:refname | head -1`
- Release version — owner: `pyproject.toml` `[project] version` (must equal the latest tag; a
  difference means a bump is pending or a tag was missed)
- Changes since the last tag — owner: `git log <latest-tag>..HEAD --oneline`

**Why this file no longer states the numbers:** it used to. It recorded "latest tag **v3.30.0**;
pyproject = 3.30.0" and told the next release to start its changelog at v3.30.0 and carry PR #293
in the narrative as an unreleased post-tag merge. Both went stale silently: by 2026-07-29 the live
tag was **v3.31.0** (tagged 2026-07-18) and #293 (37d68bc) was already an ancestor of it — shipped,
not pending. Acting on the cached text would have started the changelog one whole release early and
re-announced work that had already gone out. A version number is exactly the kind of fact this repo
forbids caching without its owner (`docs/ssot.md`, Law 1): the owners above are one command each,
so there is no reason to hold a copy.

**The one durable fact (safe to state, because it is frozen by design):**

- Schema version `cisco_toolkit.__version__` = **3.23.0** — DECOUPLED from the release version and
  **frozen**. Never bump it; it churns the golden snapshot. `pyproject.toml` moves at tag time,
  this does not. If you ever find them equal, something is wrong.

**How to apply:** at release time, read tag + pyproject from the owners above, diff since the live
latest tag, and propose the bump. Rig-only changes under `.claude/` (commands, hooks, agent memory)
never justify a release on their own — they ride along with the next engine-driven one.
