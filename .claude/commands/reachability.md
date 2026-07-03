---
description: L1–L4 reachability, path, SPOF and blast-radius analysis over the assessed network (digital-twin reasoning, read-only).
argument-hint: [src dst | "what breaks if <NODE> fails" | "SPOFs"]
---
Answer a reachability / impact / blast-radius question about the assessed network.

QUESTION: $ARGUMENTS

Delegate to the **topology-reachability-analyst** subagent. Reason over the engine's reachability model (VRF/route/ACL/NAT/MTU/FHRP/addressing/trunk) and the blast-radius explorer — do not eyeball configs. Any what-if runs against a COPY of the model. Return a deterministic answer with the path / impacted set, and a concrete counterexample when a property fails (not a prose "looks fine"). If a model input is missing, say the analysis is bounded rather than assuming connectivity.
