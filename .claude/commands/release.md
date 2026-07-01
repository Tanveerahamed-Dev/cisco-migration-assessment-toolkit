---
description: Guided release cut — summarize changes since the last tag, propose the version, prepare the pyproject bump + changelog, and hand you the exact git/gh steps.
argument-hint: [target version | "since last tag"]
---
Prepare a release (you run the git/gh steps; I prepare and verify).

REQUEST: $ARGUMENTS

Delegate to the **release-captain** subagent. Hard rules: bump `pyproject.toml [project] version` ONLY now (at release-tag time); NEVER touch the decoupled schema version `cisco_toolkit.__version__` ("3.23.0") — it would churn the golden. Summarize merged changes since the last tag, propose the next `vX.Y.Z`, prepare the version bump + the `COLLECT_PARSE_V3_23_0.md` changelog entry, then give me the exact, step-by-step git + gh commands to run (I'm new to PRs — spell each one out). Do NOT commit, push, tag, or open the PR yourself unless I explicitly tell you to.
