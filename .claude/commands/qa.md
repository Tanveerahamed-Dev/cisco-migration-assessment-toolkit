---
description: Independent, adversarial QA of the generated deliverables — cross-document consistency, one-source-of-truth, hallucinated state, gate-readiness.
argument-hint: [deliverable set | directory | stem]
---
Run an independent QA pass over the deliverables.

ARTIFACTS: $ARGUMENTS

Delegate to the **deliverable-qa-reviewer** subagent (independence matters — it must not be the agent that authored them). It should try to DISPROVE: reconcile every shared fact (device counts, VLANs, IPs, health verdicts, finding counts) to one source; flag any device fact not traceable to the snapshot/collection; catch any not-collected axis presented as healthy; confirm each artifact's upstream gate input exists. Return a per-artifact APPROVE / BLOCK verdict with findings (location | claimed | source-of-truth | severity). It returns findings only — the authoring agents fix.
