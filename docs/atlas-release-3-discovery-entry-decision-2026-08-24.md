# Atlas Release 3 Discovery Entry Decision

Date: 2026-08-24

State: `DISCOVERY_PLANNING_ONLY`

Machine authority: none

Promotion effect: none

## Decision

Begin Release 3 discovery and planning while preserving every unresolved Release 2 dependency. This decision permits requirements work, dependency mapping, candidate-intake research, fixtures, threat models, evaluation design, and explicitly non-authoritative prototypes. It does not authorize a Release 3 product capability, machine feasibility verdict, candidate selection, `TRANSLATION_CHECKED` compilation, limited preview, qualification, promotion, shipment, or GA claim.

The administrative Release 2 campaign close is recorded in `docs/atlas-release-2-administrative-closeout-2026-08-24.md`. That closeout is not evidence that R2.0 completed or that QCP-001 qualified.

## Discovery mission

Define the smallest evidence-closed Release 3 product slice that can challenge gateway-handoff migration candidates without outrunning the qualified semantics needed to interpret or compile them.

The target user moment remains **Break This Plan**: an architect supplies a current-state comparator and bounded migration candidates; Atlas exposes assumptions, counterexamples, unresolved evidence, and the best admissible next observation. During discovery, every output is explanatory or test-only. Atlas must not choose a candidate or emit a positive machine readiness result.

## Allowed and held work

| Allowed now | Held behind explicit authority |
|---|---|
| Confirm the problem statement, target user, user moment, and decision workflow. | Machine feasibility or eligibility verdicts. |
| Define Requirement, Candidate, Decision, Defeater, Counterexample, and Transition Program information models. | Candidate selection or machine ranking. |
| Map QDP-001 assumptions to existing R2 structural/verifier contracts. | `TRANSLATION_CHECKED` QDP-001-to-QCP-001 compilation. |
| Research bounded challenger, witness, certificate, completeness, and abstention semantics. | Treating uncertified search exhaustion as positive support. |
| Design candidate intake, evidence plans, safe probe admissibility, threat models, fixtures, and evaluation criteria. | Activating QDP-001 limited preview. |
| Build clearly labeled non-authoritative prototypes that cannot mint a gate result. | Qualification, promotion, shipment, or GA. |
| Record routed-access or EVPN ideas as `UNQUALIFIED_CANDIDATE` context. | QDP-002/QDP-003 feasibility, selection, ranking, or compilation. |

## Dependency ledger

This ledger is mandatory input to every R3 discovery artifact. A downstream artifact may narrow its scope, but it may not omit a relevant row or convert a blocked dependency into an assumption of success.

| ID | Dependency | Verified state at entry | Discovery use allowed | Held result |
|---|---|---|---|---|
| `R3-DEP-001` | Stable R2 case schema and structural verifier semantics | Substantial R2.0 experimental checkpoint exists; R2.0 freeze is blocked. | Map fields, identities, invalidation, and gate vocabulary; create draft fixtures. | No preview or authoritative compilation. |
| `R3-DEP-002` | Deferred R2.1-R2.5 engineering and operator workflow | Transition identity/persistence, executable obligation integration, pair-bound acquisition and trials, decision workspace/operator surfaces, and portable case/verifier work are all deferred and unqualified. | Specify interfaces, dependencies, UX questions, and non-promoting fixtures while preserving each missing owner explicitly. | No assumption that the R2.0 structural checkpoint supplies persistence, acquisition, operator usability, portable-case behavior, or a field-ready workflow. |
| `R3-DEP-003` | Qualified QCP-001 v1 and exact applicability denominator | `EXPERIMENTAL` / `CONTRACT_ONLY`; no signed qualification receipt. | Explore only the proposed gateway-handoff grammar and explicitly label unqualified assumptions. | No feasibility verdict, selection, `TRANSLATION_CHECKED`, or QDP-001 preview. |
| `R3-DEP-004` | Complete runtime/crypto closure for the activated verifier and packs | Runtime inventory v1 is `PARTIAL_NONPORTABLE_PROTOTYPE`; protocol v1 cannot express complete closure. | Threat-model runtime and pack boundaries; design future evidence interfaces. | No authoritative execution or portable-verifier claim. |
| `R3-DEP-005` | Representative workload, approved budgets, trust/key custody, and detached signed review | All absent; numeric values are proposals and protective guards only. | Specify the exact authority inputs R3 would consume. | No promotion-bearing execution or positive completeness claim. |
| `R3-DEP-006` | Selected R2 source and independent provenance | Selected commit/tree are null; source binding is same-checkout self-check only. | Keep discovery artifacts source-referenced and replaceable. | No claim that R3 is built on a selected qualified R2 release. |
| `R3-DEP-007` | One-generation Graphify and Obsidian evidence over final integrated source | Current protected graph is stale/cross-generation; canonical refresh is held. | Use the reviewed coherent seed and direct source only as navigation, with corpus limitations visible. | No graph-based proof of absence or final relation/memory receipt. |
| `R3-DEP-008` | QCP-002 Routed Access-Block Migration | Not implemented or qualified. | Capture routed-access requirements and risks as research context only. | QDP-002 remains blocked; no L2/L3 boundary selection or compilation. |
| `R3-DEP-009` | QDP-002 design qualification | Not implemented or qualified. | Define later acceptance questions without capability claims. | `ARCHITECTURE_DECISION_ASSURANCE_GA` remains prohibited. |
| `R3-DEP-010` | QCP-003/QDP-003 EVPN semantics | Not implemented or qualified. | Record EVPN ideas only as `UNQUALIFIED_CANDIDATE`. | No EVPN feasibility, ranking, selection, or compilation. |
| `R3-DEP-011` | Legal/IP and redistribution authority for verifier/pack bytes | Repository remains proprietary; no accountable carve-out or redistribution decision is recorded. | Model packaging choices and decision inputs. | No open-source, unrestricted redistribution, or sealed-binary right claim. |

## Discovery workstreams

### 1. Problem and user workflow

- Validate the decision checkpoint where an architect needs to understand why a superficially safe target may contain an unsafe intermediate state.
- Separate the non-selectable current-state comparator from selectable migration candidates.
- Define the human decision and rejected-alternative lineage without adding an autonomous `GO` state.

### 2. Information-model discovery

- Draft the R3.0 objects: Requirement, Candidate, Architecture Decision, Assumption, Defeater, Counterexample, Transition Program, and invalidation edges.
- Require owner, source class, exact scope, freshness/expiry, evidence references, and dependency identifiers on every consequential object.
- Keep human-only requirements explicitly unresolved until an accountable owner records disposition.

### 3. Candidate-intake boundary

- Treat the current Design Advisor output as candidate seed zero, never as the selected architecture.
- Define structured external candidate import while preserving opaque fields that the activated Design Pack cannot interpret.
- Require prose-only candidates to remain visibly not machine-evaluated.

### 4. Bounded challenge semantics

- Separate replayable counterexample witnesses from checked no-counterexample certificates, trusted exhaustive completeness receipts, uncertified search exhaustion, `NOT_EVALUABLE`, and `MODEL_CONFLICT`.
- Allow a refutation only after the trusted witness checker replays the exact witness against the pinned model and bounds.
- Keep uncertified exhaustion advisory and mapped to `EVIDENCE_INCOMPLETE`.

### 5. Evidence-directed refinement

- Define the admissibility gate for safe, authorized observations before any ranking.
- Rank only within an allowed risk tier and state the declared candidate/outcome set, privilege, cost, and elapsed-time assumptions.
- Require every proposed probe to state how each possible result changes the named uncertainty, including failed or inconclusive acquisition.

### 6. Translation-boundary research

- Map a selected-candidate digest, requirements, profiles, source state, and bound envelope to a partial-order Transition Program.
- Define fixtures for dropped requirements, widened mutations, lost observation barriers, missing rollback edges, and inconsistent target composition.
- Keep every result `TRANSLATION_NOT_ESTABLISHED` or test-only until `R3-DEP-001`, `R3-DEP-002`, and `R3-DEP-003` are genuinely satisfied and a trusted checker is activated.

### 7. Threat model and evaluation design

- Model malicious or erroneous candidate generators, solvers, documents, stale evidence, cross-case evidence teleportation, candidate-set narrowing, unbounded search, and result laundering through UI copy.
- Pre-register fixtures for safe endpoints with an unsafe middle, contradictory hard requirements, unsupported semantics, unqualified candidates, stale dependencies, and adverse evidence monotonicity.
- Define operator evidence for understanding blockers and next observations without requiring raw JSON.

## Required prototype banner

Every R3 prototype created during this discovery phase must display or emit all of the following:

```text
R3 DISCOVERY PROTOTYPE — NON-AUTHORITATIVE
qualification_state=EXPERIMENTAL
promotion_eligible=false
feasibility_verdict=null
selected_candidate=null
translation_checked=false
preview_eligible=false
```

A prototype must be unable to mint one of the four authoritative machine-gate states. If it needs gate-shaped data for a fixture, that data must be explicitly synthetic and test-only.

## Discovery exit criteria

Discovery is complete only when the repository contains reviewed, mutually consistent artifacts for:

1. The bounded QDP-001 problem statement and target user moment.
2. A versioned R3 dependency ledger that reconciles to current R2 owners.
3. Draft R3.0 information models and invalidation rules.
4. Candidate-intake and unqualified-field behavior.
5. Challenger result taxonomy, witness/certificate trust boundaries, and abstention mapping.
6. Evidence-probe admissibility and ranking semantics.
7. Translation-check fixture design without a positive compiler claim.
8. Threat model, negative fixtures, operator acceptance evidence, risks, rollback for prototype work, and kill/pivot criteria.
9. A fresh accountable decision on whether any R3 implementation beyond non-promoting scaffolding may begin.

Meeting these criteria authorizes a decision review, not implementation, preview, qualification, or shipment.

## Immediate discovery questions

1. Which QDP-001 fields are already expressible by the current R2 structural contract, and which are merely strategy prose?
2. What is the smallest candidate grammar that differs in ordering, coexistence, observation barriers, and rollback without implying unqualified routing or application semantics?
3. Which counterexample witnesses can be replayed by a small checker without admitting a solver into the trusted computing base?
4. What exact evidence makes a proposed observation safe and authorized before information gain is considered?
5. Which dependency changes must invalidate a Candidate, Architecture Decision, Transition Program, or projection?
6. What operator study would demonstrate that blockers and next-evidence requests are understandable without raw JSON?

## Governance and GitHub tracking

The single planned authority-debt issue title is:

`Atlas roadmap R3 start gate - R2 closed incomplete; authority debt preserved`

The issue must link the remote R2 closeout evidence, retain the dependency ledger, and remain open while R3 discovery proceeds. It must not be used as evidence that Release 2 landed or that Release 3 crossed a product gate.
