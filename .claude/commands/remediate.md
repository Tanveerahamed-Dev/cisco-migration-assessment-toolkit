---
description: Self-healing (propose-only) — detect drift between a baseline and the current snapshot, route each regression to a specialist, and package a remediation MOP + rollback as a reviewable PR. Never a device write (D5).
argument-hint: "<baseline.snapshot.json> <current.snapshot.json>"
---
Run the **propose-only self-healing loop** on the drift between a baseline and the current snapshot (Phase 4).
The whole loop produces a **reviewable artifact** — never a device write, and the author never certifies its
own fix (proposer ≠ verifier).

1. **Identify the pair.** Two snapshot paths in `$ARGUMENTS` (baseline, current), or the last two
   `*.snapshot.json`. If there is only one snapshot, say so and stop (drift needs a baseline).
2. **Triage the drift (tested logic):**
   `python -m cisco_toolkit.self_healing <baseline.snapshot.json> <current.snapshot.json>`
   This returns the propose-only plan: each regression (health drop / coverage `clean→finding`) with a
   severity, a **root-cause owner**, a **MOP author**, an independent **verifier**, a remediation *intent*
   (never a command), a **rollback** (restore the baseline), and the NRFU acceptance. No drift → "nothing to
   remediate" (honest — it compares two snapshots; it is not an assertion the network is healthy). Stop there.
3. **Root-cause** each item: spawn its `root_cause_owner` (read-only) — `topology-reachability-analyst` for
   reachability/health/DC/SP, `config-security-auditor` for security-class findings. Ground the diagnosis in
   the evidence (cite the field/line).
4. **Author the remediation** with `mop-change-author`: a MOP with pre-checks, ordered steps, an explicit
   **rollback** (revert to the baseline), owners, and a maintenance window — as a **PR**, never executed. It
   may draw on `cisco_toolkit.analyze.compute_remediation_plan` for review-only config snippets.
5. **Define acceptance** with `nrfu-validator` (independent of the MOP author): the PRE/POST checks that
   confirm the regression is cleared and no new regression is introduced (`--compare` current → remediated).
6. **Present** the package as **PROPOSE-ONLY**: the PR + CAB request, severity-ordered, each item showing
   root-cause → MOP+rollback → NRFU acceptance. A human approves inside a CAB window; nothing is applied here.

Binding: read-only; no device writes; no `git push`/merge; propose-only. Every claim grounded in evidence;
"not observed" is never "healthy".
