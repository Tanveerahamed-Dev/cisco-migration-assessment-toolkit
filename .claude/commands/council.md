---
description: Grounded council — verify a consequential claim with N independent, refute-first domain lenses (selected by architecture_coverage) and take the majority. No debate (D8).
argument-hint: "<claim to verify>"
---
Run a **grounded council** on the claim in `$ARGUMENTS` — the proposer≠verifier doctrine widened to a panel
(Phase 3 / D8 of the autonomous-brain plan). The lenses are the **domain packs the evidence selects**, run
**independently and refute-first**, aggregated by **majority — no debate, no cross-critique**.

1. **Identify the claim + snapshot.** The claim is `$ARGUMENTS`. Use the latest `*.snapshot.json` (or the one
   under discussion). If there is no claim, ask for one and stop.
2. **Plan the lenses (tested logic — don't eyeball it):**
   `python -m cisco_toolkit.council plan "$ARGUMENTS" <snapshot.json>`
   This returns the lenses selected by `architecture_coverage` (DC/Enterprise/SP/Security packs, findings
   first), each with a refute-first, evidence-grounded prompt. If no domain applies it returns a 3-sample
   general evidence lens (an N-sample self-consistency panel).
3. **Spawn each lens INDEPENDENTLY** with the Agent tool, in a **single message** (parallel), each getting
   ONLY its own prompt from step 2. Map to a read-only analyst where it fits — Security lens →
   `config-security-auditor`; topology/DC/SP reachability → `topology-reachability-analyst`; current-state →
   `assessment-analyst`; else a read-only general-purpose agent. **D8 is binding: a lens must never see
   another lens's verdict — no debate, no deliberation, no reconciling.** Each returns a
   `VERDICT=<SUPPORT|REFUTE|UNCERTAIN>` line + one counterexample/evidence line.
4. **Aggregate (refute-first majority):**
   `python -m cisco_toolkit.council aggregate <verdict1> <verdict2> …`
   SUPPORT only on a **strict majority of all lenses**; anything short — a tie, an uncertain plurality, a
   zero-lens council — is **REFUTE** (the consequential output is not certified). The CLI exits 3 when not
   certified.
5. **Report** the council verdict, the tally (support/refute/uncertain, N), and — verbatim — the refuters'
   counterexamples (those are the reasons; surface them, don't average them away). If REFUTE, the claim is
   **not certified** — say so plainly and list what must change to clear it.

Read-only throughout: no device writes, no external fetch. Ground every lens verdict in collected evidence
(cite the field/line); "not observed" is never "healthy".
