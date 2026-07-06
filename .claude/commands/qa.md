---
description: Independent, adversarial QA of the generated deliverables — cross-document consistency, one-source-of-truth, hallucinated state, gate-readiness.
argument-hint: [deliverable set | directory | stem]
---
Run an independent QA pass over the deliverables.

ARTIFACTS: $ARGUMENTS

Delegate to the **deliverable-qa-reviewer** subagent (independence matters — it must not be the agent that authored them). It should try to DISPROVE: reconcile every shared fact (device counts, VLANs, IPs, health verdicts, finding counts) to one source; flag any device fact not traceable to the snapshot/collection; catch any not-collected axis presented as healthy; confirm each artifact's upstream gate input exists; **render the DOCX/PDF to page images to eyeball the figures and confirm the TOC built** — text extraction is blind to raster, so a diagram can carry a stale/contradictory label while every grep-able string is correct (figures/TOC unrenderable in-env → report UN-VERIFIED, never silently APPROVE); and **reconcile the whole set to one baseline** — a sibling deliverable (LLD/MOP/NRFU) still on an older version or a retired architecture than the HLD is a blocking drift finding a single-document pass never catches. Return a per-artifact APPROVE / BLOCK verdict with findings (location | claimed | source-of-truth | severity). It returns findings only — the authoring agents fix.
