# 0002 — Batfish as an offline twin-verify for the CLI half (go/no-go spike)

**Date:** 2026-07-07 · **Status:** proposed — **GO (conditional)**; spike complete, adoption (installing the
service) is the operator's next step · **decision:** D9 of
`docs/autonomous-brain-plan-v4-final-2026-07-06.md` · **feeds:** the twin-verify step of
`cisco_toolkit/self_healing.py` (Phase 4)

## Context
Phase 4's self-healing loop proposes a remediation MOP, then wants an **independent, offline formal check**
that the fix clears the regression and introduces no new isolation — *before* it becomes a PR + CAB request.
Batfish is the candidate. This spike evaluates it against the D9 constraints: **CLI/SSH half only**, check
**parse-status per config**, and **ACI/vManage explicitly out of scope**.

## Findings (grounded)
1. **Offline by design — no egress.** Batfish never touches the live network; it builds a vendor-agnostic
   model from *config snapshots* and answers questions offline. It runs as a **Dockerized Java service**
   (ports 8888/9996/9997) driven by the `pybatfish` Python SDK. → Compatible with the no-egress doctrine:
   it is an **additive, offline** component (exactly what D9 sanctioned), not a network-reaching one.
2. **Cisco CLI coverage is real.** Supported: **IOS, IOS-XE, IOS-XR, NX-OS, ASA** (input = `show
   running-config`; `show run all` recommended for NX-OS). This is precisely the SSH `show`-text half.
3. **ACI / controllers: ZERO coverage.** The supported-platform list has **no** Cisco ACI/APIC, Catalyst
   SD-WAN/vManage, or any controller-based/intent fabric — Batfish parses *device configs*, not controller
   REST/intent. → **Confirms D9**: the JSON controller-REST half stays on the existing
   `_ARCH_COVERAGE_REGISTRY` detectors (`aci-*`, `sdwan-*`, `ise-*`, `fmc-*`); Batfish must never be implied
   to cover them.
4. **Parse-status is first-class (coverage-honest).** Batfish reports `initIssues` (parse/convert warnings
   with source line + parser context) and per-file parse status — so a config it only *partially* parsed is
   knowable. → Maps onto this repo's coverage-honesty doctrine: a verdict over a partially-parsed config
   must be disclosed as **"verified over the parsed subset,"** never a blanket pass (the 3-state abstention
   type gains a `PARSED_PARTIAL` cousin).
5. **`differentialReachability` is a natural twin-verify.** It finds flows treated differently between two
   snapshots; with `reachability` + ACL analysis it can guarantee a change has no unintended side-effects.
   → The remediation loop's exact need: `differentialReachability(current, remediated)` confirms the
   regression is cleared **and** no new isolation is opened.

## Decision — GO, conditional and bounded
**Adopt Batfish as an offline twin-verify for CLI-config remediations only**, wired as the
`twin-verify` step in `self_healing.propose_remediation`'s flow (between MOP authoring and PR+CAB):

- **In scope:** IOS/IOS-XE/IOS-XR/NX-OS/ASA `show run` configs; `differentialReachability` +
  `reachability` + ACL/filter analysis over `(current, proposed-remediation)`.
- **Parse-status gate (mandatory):** run `initIssues` first; if the touched configs are
  `PARTIALLY_UNRECOGNIZED`/`FAILED`, the twin-verify result is **disclosed as partial**, never a clean pass
  (coverage-honest — a model of an unparsed config proves nothing about the unparsed lines).
- **Proposer ≠ verifier still holds:** Batfish is a *second, formal* check, **not** a replacement for the
  independent `nrfu-validator`. A remediation is certified by NRFU on real evidence; Batfish is the offline
  pre-check that catches side-effects before the human/CAB.

## NO-GO boundaries
- **Never for ACI/vManage/controllers** (zero coverage) — those stay on the controller-REST detectors.
- **Never trust a verdict on a partially-parsed config** without disclosing the gap.
- **Never the sole verifier** — it does not observe the live post-change state; NRFU does.

## Cost / adoption note (operator's call)
The one real cost is operational weight: Batfish is a **running service** (Docker + Java + `pybatfish`),
heavier than Ollama. It is additive and offline, so the air-gapped attestation is unaffected (it would live
outside `cisco_toolkit/`, like `research_lane/`, or behind an optional, gracefully-degrading import — no
Batfish ⇒ twin-verify is simply skipped and disclosed, never silently "verified"). **Recommendation: GO** —
stand up the service in a spike branch, wire one real remediation through `differentialReachability`, and
confirm the parse-status gate fires on a deliberately-mangled config before trusting it.

## Sources
- [Batfish supported platforms](https://batfish.readthedocs.io/en/latest/supported_devices.html) ·
  [batfish/batfish (GitHub)](https://github.com/batfish/batfish) · [batfish.org](https://batfish.org/)
- [Interacting with Batfish / initIssues](https://batfish.readthedocs.io/en/latest/notebooks/interacting.html) ·
  [Forwarding-change validation (differentialReachability)](https://batfish.readthedocs.io/en/latest/notebooks/linked/introduction-to-forwarding-change-validation.html)
- [Analyzing ACLs & firewall rules](https://batfish.readthedocs.io/en/latest/notebooks/linked/analyzing-acls-and-firewall-rules.html) ·
  [Batfish use cases (TechTarget)](https://www.techtarget.com/searchnetworking/feature/Batfish-use-cases-for-network-validation-and-testing)
