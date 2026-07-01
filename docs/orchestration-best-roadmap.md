# Orchestration-peer & Trust — a grounded roadmap from the Itential · NetClaw · NetCopilot teardowns

Distilled from three adversarially-verified deep-research teardowns ([product-teardowns.md](research/product-teardowns.md) §4–6),
produced by a **39-agent, multi-domain parallel wave** (per product: identity probe + 4–5 web-research facet agents →
a schema-enforced distill → one adversarial refuter **per candidate idea**, each grounding "do we already have it?" in
graphify + real code). The wave's verdicts were then **independently re-refuted by the orchestrator**: every load-bearing
"already-shipped → CUT" claim was re-checked against `file:line`, the riskiest identity (`netcopilot-labs/netcopilot`) was
confirmed by a direct README fetch, and one missing verdict (`golden-config-drift`) was adjudicated by hand.

Every item below obeys the three non-negotiables — **fully offline / no egress, read-only, coverage-honest (no overclaim)** —
and anything that only works as a **cloud-LLM, device-write, or live-polling** mechanism was **cut, not adopted** (we take the
*concept, output format, or data model*, re-implemented deterministically on the snapshot).

> **Status — what is BUILT vs PROPOSED (read this first).** This whole roadmap is **PROPOSED design**: each item's `file:line`
> is the **landing site** where it would go (verified to exist), NOT an existing feature. Nothing here is implemented yet — the
> user asked for *the plan*. The companion already-shipped roadmap is [universal-best-roadmap.md](universal-best-roadmap.md)
> (the Transit AI · SmartyMe · NotebookLM distillation, W1/W2/W3 — largely DONE). This document is its sequel for the
> **automation/orchestration/AI-copilot** peer set.

---

## The thesis — where these three sit relative to us

The wave verified that **none of the three shares our combination**, and that each sharpens us from a different angle:

| Product | What it is | Relation to us | What we borrow (mechanism **rejected**, concept **kept**) |
|---|---|---|---|
| **Itential** | SaaS-first low-code automation/**orchestration**; writes/pushes config; agentic layer (FlowAI) calls an external LLM | **Doctrinal INVERSE** → *complementary*: we are the read-only **verifier upstream of an actuator** like Itential, not a cheaper Itential | command-template **assertion grammar**, golden-config **inheritance tree + weighted grade**, **Evidence Package**, JSON **conformance**, pre/post+rollback **transition discipline** |
| **NetClaw** | OSS autonomous net-eng **AI coworker** (Claude-powered); 113 markdown skills; **writes**, incl. live BGP/OSPF peering | **Clean ANTITHESIS** → strong *foil*: cloud-LLM-mandatory, device-writing, non-deterministic | **intent↔observed reconcile** taxonomy, **GAIT** immutable transcript, **Constitution** build-gate, **DefenseClaw** negative-test taxonomy, **HEARTBEAT** checks-as-data |
| **NetCopilot** | OSS read-only **source-of-truth + grounding** layer; deterministic collect→parse→rules→findings→**Neo4j graph→MCP→LLM** | **Doctrinal TWIN** (independently arrived at read-only + deterministic-truth/AI-explains) → validates our thesis; we differ by being **zero-egress (no LLM in the analysis path), with the deliverable + RIB→FIB + compliance + 40-detector layer it lacks** | persisted **queryable network-graph** export, **offline file-drop reconcile**, **Trust & Sovereignty** framing, the **completeness-census-as-product** pitch |

**The unifying transferable theme.** All three (plus the NetBrain/Aviz/NetBox/Cisco-AgenticOps adjacents the wave pulled in)
are converging on the same four ideas — and each is **doctrine-neutral** once we strip the cloud/write/LLM mechanism:

1. **Checks-as-data** — externalize assertions/conformance into committed, versioned packs evaluated deterministically.
2. **External reconcile** — ingest an offline declared source-of-truth and diff intent-vs-observed (we only reconcile *internally* today).
3. **Change-safety certification** — make the MOP *provably* change-safe from existing evidence (we already own the engine: `fib.py`).
4. **Evidence & trust spine** — a canonical evidence package, a sealed chain-of-custody manifest, and a *re-derived* (falsifiable) zero-egress attestation.

> **Positioning sentence to adopt:** *the only fully air-gapped, read-only, coverage-honest L1–L4 assessment + migration
> platform that turns collected evidence into committed, deterministically-evaluated assertions, reconciles them against your
> declared source-of-truth, and certifies a cutover change-safe — every claim cited, every blind spot declared, zero data ever
> leaving the operator's air gap. The read-only verifier that belongs **upstream** of any actuator (Itential), is the
> **deterministic** answer to the AI coworker (NetClaw), and is the **zero-egress, deliverable-grade** superset of the
> source-of-truth copilot (NetCopilot).*

---

## Wave A — Checks-as-data (the marquee convergence)
The single idea all three products + NetBrain converge on, and our clearest whitespace: our detectors are **hard-coded
`compute_*` in `analyze.py`/`design_advisor.py`** with **no rule engine and no externalized check format**. Turn NRFU / pre-post /
heartbeat into committed **data**, evaluated offline over the snapshot, each result cited and 3-state-abstaining.

| # | Item | Grounding (landing site, verified) | Effort |
|---|------|-----------|--------|
| **A1** | **`assertions.py` — deterministic offline state-assertion check-pack** (the NRFU/pre-post engine). A committed **JSON** pack (no PyYAML dep — repo has none) of `{command, rules[]}` where each rule is typed `contains / !contains / contains1 / regex / !regex / comparison`, with `severity ∈ {error,warning,info}`, regex flags, and AND/OR pass logic — the 1:1 offline analog of Itential's Command-Template grammar. Evaluated over **already-collected snapshot text** (never a live device); a check whose source command was **not collected → `[NOT OBSERVED]`** via `ssot.abstention_reason` (the coverage-honest fit, by construction). | new `cisco_toolkit/assertions.py` → `snap['state_assertions']`; consumed in `--compare` (NRFU) next to `fib.py:332`; new `excel.py` sheet | **L** |
| **A2** | **`compute_assertion_catalog(snap)` — read-only Assertion Catalog projector.** Fold the EXISTING addressable objects (`design_blueprint.decisions`, `architecture_coverage.classes`, the `_d_*` decisions) into one unified, framework-tagged catalog of `{intent_id, plain-language assertion, evidence fields, severity, status: pass|fail|[NOT OBSERVED]}`. ~70 % already exists — this is a thin **unification/projection**, not new infra (the wave correctly CUT the "promote every detector to a registry" framing). | `cisco_toolkit/design_advisor.py:4659` (new projector after `compute_architecture_coverage`, reusing `_ARCH_COVERAGE_REGISTRY` + `design_blueprint.decisions`) | **S–M** |
| **A3** | **`heartbeat.py` — declarative drift digest across two snapshots.** A user-editable `heartbeat.yaml/json` of health invariants (`{name, subject=published-key-path, assert}`) **re-evaluated across TWO snapshots** → `HELD / CHANGED / UNVERIFIABLE` (uncollected subject ⇒ UNVERIFIABLE via `ssot.abstention_reason`), each cited. NetClaw's HEARTBEAT *polls live* (egress — **rejected**); we salvage only the checks-as-spec idea and run it over stored snapshots. Reuses the A1 evaluator. | new `cisco_toolkit/heartbeat.py` consumed in the `--compare`/`--trend` flow (`html.py:438`/`:177`) | **M** |

**Doctrine guards (A):** JSON not YAML (zero new dep); evaluate the **static snapshot only**, never a device; a rule whose backing
command is absent renders `[NOT OBSERVED]`, **never a silent pass** (the false-health class); ship A1 with a *byte-match verifier*
that demotes any citation that doesn't resolve in the snapshot (guards the recurring format-fidelity defect).

## Wave B — External source-of-truth reconcile (close the internal-only gap)
Verified gap: `ssot.reconcile()` ([ssot.py:149](../cisco_toolkit/ssot.py:149)) checks **published-canonical vs raw-derivation
INTERNALLY** — it does **not** ingest an external declared inventory. Both NetClaw (`netbox-reconcile`) and NetCopilot/Aviz
(connector layer) do intent-vs-observed; their live API connectors are **egress (rejected)**, but the **file-drop** half is air-gapped.

| # | Item | Grounding (landing site, verified) | Effort |
|---|------|-----------|--------|
| **B1** | **`external_import.py` — offline file-drop inventory adapter.** Drop a CMDB/NetBox/Nautobot/IPAM export (CSV/XLSX — `openpyxl` already a dep) into a folder; normalize to `{host, model, serial, mgmt_ip, site, …}` rows behind an **opt-in `--import-inventory <file>`** flag (mirrors the `rest_collect` opt-in posture). Reads a file, never a network. | new `cisco_toolkit/external_import.py`; flag at `COLLECT_PARSE_V3_23_0.py` (`load_devices` is JSON-only at `:1035`) | **M** |
| **B2** | **`ssot.reconcile_external()` / `reconcile_intent()` — intent-vs-observed diff + the UNVERIFIABLE 5th state.** A **NEW** function beside `reconcile` (do NOT overload the internal one): diff the imported intent vs the parsed snapshot, emit a fixed **named drift taxonomy** (e.g. `IP_DRIFT / MISSING_DEVICE / UNDOCUMENTED_DEVICE / VLAN_MISMATCH / CABLE_MISMATCH`) **plus `UNVERIFIABLE`** (intent says X exists but that device was never collected — NetClaw's blind spot becomes our coverage-honest 5th state via `abstention_reason`). New workbook sheet + explorer panel. | `cisco_toolkit/ssot.py:269` (after the `reconcile/audit/summary` block) + new `excel.py` sheet + `blast_radius_explorer.html` panel | **M** |

**Doctrine guard (B):** import is **read-only file ingest**; reconcile **writes nothing to devices**; an intent entry whose
observed side was never collected is `UNVERIFIABLE`, **never a fabricated match or a silent miss**.

## Wave C — Change-safety certification (we already own the engine — this is packaging)
Itential pre/post+rollback, NetBrain "Triple Defense", and NetClaw's Batfish pre-change all certify a change is safe. We are
**already the offline Batfish peer** (`fib.py` RIB→FIB + `reachability_diff`, live in `--compare`). Borrow only the **packaging**.

| # | Item | Grounding (landing site, verified) | Effort |
|---|------|-----------|--------|
| **C1** | **`precert.py` — Pre-Change Validation Certificate** (named PPDIOO gate artifact). A one-page deliverable binding the EXISTING `fib.reachability_delta` to a specific candidate change: *"flows X,Y,Z preserved; segmentation invariant S holds; N flows change state (each cited `old_status → new_status`); M inconclusive (blind spot)."* Do **not** re-propose the engine. | new `cisco_toolkit/precert.py` (the `crd.py` generator pattern) consuming `fib.py:424` `reachability_delta`; wired into `--compare` | **M** |
| **C2** | **Change-Defense Ledger — label existing MOP sections as 3 gates.** In `mop.py`, emit a per-wave ledger that LABELS the already-generated sections as **PRE** (`§x.3` baseline + fib/SPOF/golden-drift) / **DURING** (`§x.5` per-step success criteria) / **POST** (`§x.6` validation, `--compare` reachability delta) + an offline **rollback-readiness** assertion. Pure fusion/output-format; rejects NetBrain's auto-remediation/auto-rollback (device writes). | `cisco_toolkit/mop.py:592` (new sub-section before `§x.7`), reusing `fib.py:332` + `html.py:118` | **S** |
| **C3** | **MOP-safety invariant as a build-gate.** A per-wave structural invariant the engine can prove: **every wave with a procedure MUST carry ≥1 verify (`§x.6`) AND a rollback (`§x.7`)** — a change step with no failure path is a **build-gate FAIL** (coverage-honesty as a build gate, mirroring `doctrine_invariants`). Drops Itential's literal "per-task edge" (no per-step change-classification in our data model). | new `mop_safety_invariants` in `cisco_toolkit/doctrine.py:22` + pytest gate `tests/test_mop_safety_gate.py`; reads `mop.py:178` step tuples + `:569` validation section | **M** |

## Wave D — Evidence & trust spine (the distinctive, doctrine-amplifying program)
Itential's **Evidence Package**, NetClaw's **GAIT** immutable transcript, and every competitor's **sovereignty** pitch converge
on "make integrity & provenance a first-class, surfaced artifact." We already cite per-claim provenance — this packages it.

| # | Item | Grounding (landing site, verified) | Effort |
|---|------|-----------|--------|
| **D1** | **`evidence.py` `build_evidence_package(snap)` — canonical machine-readable run record.** A thin **assembler** (no recompute) over data already in the snapshot: one audit row per finding `{device, standard/check, finding, severity, source_command + line-citation, run timestamp, schema version, per-detector status: ran / abstained-not-collected}`. Itential's "what was remediated / by whom / before-after config" are write-side artifacts we **don't** emit (we propose change in a PR) — disarmed by construction. New workbook sheet; reconciled in `ssot`. | new `cisco_toolkit/evidence.py` → `snap['evidence_package']`, assembled near the `.snapshot.json` write in `COLLECT_PARSE_V3_23_0.py`; rows from `analyze.py:3155` (`compute_migration_punchlist`) + `:3080` (`compute_framework_coverage`) | **M** |
| **D2** | **Sealed chain-of-custody — upgrade the DEAD `build_run_manifest` stub.** `build_run_manifest` ([COLLECT_PARSE_V3_23_0.py:1135](../COLLECT_PARSE_V3_23_0.py:1135)) is **defined but never called** (verified: zero call-sites). Upgrade it into the offline, deterministic answer to GAIT: `schema_version` (`cisco_toolkit.__version__`), `devices_file_sha256`, `collected_at` + `generated_at`, the full `ssot.abstention_reason` ledger, and a **per-artifact `sha256`** (reuse `file_sha256` at `:1126`). Emit it + test it. `hashlib` is stdlib; determinism is the point. | upgrade `COLLECT_PARSE_V3_23_0.py:1135`, emit after the snapshot write; reuse `file_sha256:1126`, `ssot.abstention_reason` (`ssot.py:127`) | **M** |
| **D3** | **`attestation.py` `run_egress_attestation()` — the falsifiable Trust & Sovereignty panel.** Re-derive the guard outcomes **at build time** (re-walk `cisco_toolkit/*.py` network imports + re-scan the SSH/REST send-path with the **same AST/regex as the pytest guard**) → `{read_only, no_egress, no_llm: PASS/FAIL, evidence}`. Render a "Trust & Sovereignty" panel on the explorer + workbook cover + HLD front matter. **Binding guard: it must RE-DERIVE, never hardcode a PASS badge** (a static badge is the SmartyMe/vendor self-attestation our doctrine forbids). | new `cisco_toolkit/attestation.py`; consumers `html.py` (explorer panel), `excel.py` (cover), `design.py:204` (front matter); re-uses the guard logic in `tests/test_readonly_and_no_egress.py:110` | **M** |

## Wave E — Conformance over committed baselines (novel + extends golden)
We already ship **golden-config drift** (`compute_golden_drift`, [analyze.py:4228](../cisco_toolkit/analyze.py:4228) — supplied
file **and** fleet-majority consensus baseline, dossier axis + Excel sheet). Itential adds two genuinely-missing pieces.

| # | Item | Grounding (landing site, verified) | Effort |
|---|------|-----------|--------|
| **E1** | **Extend `compute_golden_drift` in place** — add `extra[]` (bidirectional cited delta: *extra* config present beyond golden, not just *missing*), an **ordered** ACL/route-policy comparator (sequence-sensitive sections), and an optional role→platform→site **inheritance tree** over the baseline (Itential's hierarchical model). Feed the delta into `mop.py`/`crd.py` as a human-owned change block with `rollback = inverse delta`. No new module. | `cisco_toolkit/analyze.py:4228` (extend) → `mop.py`/`crd.py`; `excel.py:1718` sheet | **M** |
| **E2** | **`compute_json_conformance` — JSONPath rule-eval over controller-REST snapshots.** We parse Cisco ACI/APIC + Catalyst SD-WAN/vManage into the snapshot (`parse.py` `parse_aci_*`/`parse_sdwan_*`) but have **NO conformance layer over that JSON** (JSONPath = 0 hits in-tree). Add a deterministic, **offline**, self-contained JSONPath evaluator that grades a controller-JSON region (ACI `fvTenant/fvBD/fvAEPg/fvCtx`; vManage `devices/control-connections/OMP`) against a **Git-committed baseline** — the doctrine-safe rule subset (`required/disallowed/ignored`, severity, identifier-key array matching, local regex value-match). Forbid any "fetch baseline from URL"/live-controller compare. | new `compute_json_conformance` beside `compute_golden_drift` at `analyze.py:4228` (NOT a new `golden.py`); shares the archreview grade | **L** |

## Wave F — Cheap doctrine gates (S, fast — tighten the moat)
| # | Item | Grounding (landing site, verified) | Effort |
|---|------|-----------|--------|
| **F1** | **Named no-egress/no-write negative-test taxonomy** (DefenseClaw's 6 categories recast as **build-time** asserts, not a runtime sandbox): group the existing read-only + no-egress import-walk + redact guards into named classes **Secret-exfil / Command-C2 / Sensitive-path / Trust-exploit**, and add the **write-path** negative tests we lack. | new `tests/test_no_egress_taxonomy.py` wrapping `tests/test_readonly_and_no_egress.py` + `tests/test_redact_e2e.py` | **S** |
| **F2** | **Narrow artifact-coherence gate** — a pytest that asserts cross-surface **render parity** on the specific KNOWN-aligned tuples only. **CUT** the universal "every `compute_*` on all its surfaces" registry: the ~40 computes, 12 explorer `HASH_MODES`, and 24 webapp `SECTION_LABELS` are **deliberately non-aligned** (verified) — a universal gate would false-fail. | new `tests/test_surface_coherence.py` (sibling of `tests/test_explorer_fib_ssot.py`) | **S** |
| **F3** | **Centralize the true policy magnitudes** — gather the ~7 real policy numbers (`_PORT_UTIL_HOT`, `_LARGE_L2_VLANS`, `_QOS_DROP_*`, `_WAVE_CAP`, …, [design_advisor.py:35](../cisco_toolkit/design_advisor.py:35)) into one `_POLICY` block + a `POLICY_VERSION`, and cite the band id in the finding. **Reject** the "thresholds.yaml lift" framing (the "~24 scattered magic numbers" premise is wrong — most are structural gates, and the true magnitudes are already named constants). | `cisco_toolkit/design_advisor.py:35` | **S** |
| **F4** | **Wire the existing conformance grade into `--trend`** — the weighted Pass/Review/Fail grade + abstention-excluded denominator is **already shipped** in `archreview.py:1003`; the only residual is exposing its history in the trend flow. | `cisco_toolkit/archreview.py:1003` → `--trend` (`html.py:438`) | **S** |

---

## Top 5 to do first (best impact-per-effort)
1. **D2 — sealed run-manifest chain-of-custody (M).** Upgrade dead code → tamper-evident provenance; cheapest high-trust win, and the offline/deterministic answer to NetClaw's GAIT.
2. **C1 — Pre-Change Validation Certificate (M).** Packages our marquee `fib` what-if as a named PPDIOO gate artifact — high client value, the engine already exists.
3. **A1 — `assertions.py` checks-as-data engine (L).** The biggest new capability and the convergence point of all three teardowns; turns NRFU/pre-post from prose into committed, cited, abstaining data.
4. **B1+B2 — external source-of-truth reconcile (M).** Closes a real, verified gap (`reconcile` is internal-only) with the coverage-honest `UNVERIFIABLE` 5th state; opt-in, doctrine-safe.
5. **D3 — zero-egress attestation panel (M).** Turns the moat into a surfaced, **re-derived** (falsifiable) claim — the differentiator every competitor gestures at but none can make.

## Cut (already shipped, or doctrine — the wave + the re-refutation were right)
- **`weighted-review-grade`** — already FULL: weighted score + grade bands + `n_not_assessable` exclusion at `archreview.py:996-1033`. *Salvage: F4 (--trend) only.*
- **`sot-gaps-census`** (completeness census as a panel) — already shipped end-to-end: `compute_collection_completeness` ([analyze.py:1065](../cisco_toolkit/analyze.py:1065)) + explorer panel. **CUT.**
- **`why-this-finding-trace`** — already shipped: Causal-Flow v2 `drawCausality()` ([blast_radius_explorer.html:7371](../cisco_toolkit/blast_radius_explorer.html:7371)) is exactly the uniform click-to-expand evidence trail, on explorer + webapp, with the precision tier. **CUT.**
- **`golden-config-drift` base** (fleet-derived baseline) — already shipped: the auto-derived **majority/consensus** mode of `compute_golden_drift` ([analyze.py:4228](../cisco_toolkit/analyze.py:4228)). Only E1's *extensions* survive. **CUT** (the wave's 8th NetCopilot idea, adjudicated by the orchestrator after its verdict failed the schema retry-cap).
- **`persisted-network-graph` (full Neo4j/MCP)** — **deferred/thin-sliced.** Adopt only an OFFLINE, dependency-free `snap['network_graph']` serialization of the already-computed `build_network_model` ([analyze.py:434](../cisco_toolkit/analyze.py:434)); **reject** the Neo4j server + MCP-export edge (egress + a heavyweight dep), and note the explorer already visualizes the graph. Low priority.
- **Mechanisms rejected wholesale (cloud/LLM/write/poll):** Itential FlowAI + MCP-to-LLM + config-push; NetClaw live BGP/OSPF peering, LLM-summarized non-deterministic analysis, `NETCLAW_LAB_MODE` write-bypass, GCF token-compression; NetCopilot's cloud-LLM-default consumption path + RAG-for-LLM + MCP-agent-export. We keep their **concepts, formats, and data models**, never their actuation/inference mechanism.

## Methodology & provenance (for the audit trail)
- **39 agents**, 2.7 M subagent tokens, 696 tool-uses, ~73 min. Per product: identity probe + 4–5 facet researchers → schema distill → one adversarial refuter **per idea** (graphify + code grounded). One verify agent hit the StructuredOutput retry cap (`golden-config-drift`) → adjudicated by the orchestrator.
- **Independent re-refutation (orchestrator):** the riskiest identity (`netcopilot-labs/netcopilot`, a 3-day-old ~6★ repo) was **confirmed by a direct README fetch**; the five load-bearing "already-shipped → CUT" claims were re-verified against `file:line`; the `golden-config` whitespace assumption was **caught and corrected** (it is HAVE, not gap).
- **Coverage-honest caveats:** "NetCopilot" as an exact name is **ambiguous and immature** (the wave folded in the broader copilot category — Aviz, NetBox Copilot, NetBrain, Cisco AgenticOps); two verify agents wrongly asserted the repo "does not exist" (refuted here). Treat star counts and "13/113-skill" figures as **self-reported**, not benchmarked.

---

# v2 expansion — the full-landscape wave (Batfish · Forward · IP Fabric · NetBrain · Ansible · NetBox/Nautobot · Infrahub · SuzieQ · Selector · Aviz · Oxidized/RANCID)

A second, larger wave (**61 agents**, 4.4 M tokens, ~102 min: 15 products × 2 primary-source facets → per-category distill → per-idea adversarial verify → a completeness critic) widened the teardown from the 3 automation peers to the **whole assurance / SoT / AIOps field**, hunting only for ideas *beyond* Waves A–F. It returned **27 new candidate ideas** (24 auto-verified + 3 orchestrator-adjudicated), all re-grounded at `file:line`. See [product-teardowns.md](research/product-teardowns.md) §7 for the per-product teardowns.

> **✅ Built test-first this session (additive new modules, uncommitted, full suite green — exit 0; engines done, deliverable-wiring is the next step):**
> | Item | Module | Tests | Runtime proof on real [HISTORY-REDACTED] data |
> |---|---|---|---|
> | **G1 · WIRED** | [`aclcheck.py`](../cisco_toolkit/aclcheck.py) → workbook **'ACL Shadow Analysis'** sheet + `snap['acl_line_reachability']` | 10 | 301 ACLs/3 507 rules → 35 dead lines; refuted to **0 counterexamples** over 3 840 packets |
> | **A1+H1** | [`assertions.py`](../cisco_toolkit/assertions.py) | 11 | fhrp→fail, framework→not_observed on the 253-device snapshot |
> | **K1** | [`capture_integrity.py`](../cisco_toolkit/capture_integrity.py) | 7 | synthetic (raw-capture data-gated, W3-3) |
> | **I2 · WIRED** | [`feature_compliance.py`](../cisco_toolkit/feature_compliance.py) → workbook **'Feature Compliance'** sheet + `snap['feature_compliance']` | 4 | real golden-drift → 8 features × 712 drift rows (snmp 93, aaa 79) |
> | **D2/J4 · WIRED** | [`manifest.py`](../cisco_toolkit/manifest.py) → pipeline emits `<out>.run_manifest.json` (Phase 39, upgraded the dead `build_run_manifest`) | 5 | deterministic hash-chain; tamper-detected; real pipeline emits + verifies the sealed manifest |
> | **B · WIRED** | [`external_import.py`](../cisco_toolkit/external_import.py) → opt-in `--import-inventory FILE` (CSV/XLSX) → **'SoT Reconcile'** sheet + `snap['external_reconcile']` | 6 | 304 declared vs 303 observed → **50 UNVERIFIABLE** (the real never-collected set); pipeline-proven (ghost→MISSING + observed→UNDOCUMENTED) |
> | **G4** | [`whatif.py`](../cisco_toolkit/whatif.py) | 4 | 300 reached flows → **24 single-points-of-dependency**, 276 resilient |
>
> **Hardened by a two-wave ultracode adversarial review (36 agents, 3 lenses/module).** It found **38 verified defects** (10 high) my own tests missed — an IPv6 ACL crash, a first-partial-number false-health parse, pack-aborting exceptions, a UTF-8-BOM-discards-inventory bug, NX-OS false-truncation, manifest tamper-evidence gaps, a regression-overclaim — **all fixed test-first** (+37 regression tests, full suite green). Doctrine now holds under refutation: every module abstains (`NOT_OBSERVED`/`INDETERMINATE`/`UNVERIFIABLE`/`lost_path`/`coverage_lost`) rather than overclaim.
>
> **✅ ALL 10 engines now WIRED into the pipeline (full suite 1191 green, golden additive 134 ins / 0 del):** always-on sheets+keys — G1 `ACL Shadow Analysis`, I2 `Feature Compliance`, K1 `Capture Integrity`, D2 `<out>.run_manifest.json`; opt-in (golden-safe) — B `--import-inventory` → `SoT Reconcile`, G4 `--scenario` → `Failure What-If`, G3 `--path-intents` → `Path Assertions`, A1/H1/H2 `--assert-pack` → `snap['state_assertions']`. Each reaches the workbook and/or snapshot. Next surface: the explorer (interactive JS readers).

**What changed in the thesis.** The assurance lane (Batfish/Forward/IP Fabric) is **also offline/read-only/deterministic** — so the moat is *not* "we're offline and they're not." The moat is the **union of all three capability bands** (doctrine + assess + deliver/govern) that no single competitor spans, **plus** a class of formal/structural analysis the v1 roadmap never reached.

## The quantified capability matrix (us vs the field)
Scored ● full (2) / ◐ partial (1) / ○ none (0), derived from the wave's primary-source teardowns + the engine's own code — **best-effort from public docs, not a certified benchmark.** `US` = today; `US+` = with this roadmap built. Only `US+` is strong across **all three bands**.

| Capability | US | US+ | Batfish | Forward | IP&nbsp;Fabric | Itential | NetBrain | NetClaw | NetCopilot | NetBox | SuzieQ | Selector/Aviz |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| *Doctrine* — Offline / zero-egress | ● | ● | ● | ◐ | ◐ | ○ | ○ | ○ | ◐ | ● | ● | ○ |
| Read-only (no device writes) | ● | ● | ● | ● | ● | ○ | ○ | ○ | ● | ◐ | ● | ● |
| No-LLM deterministic core | ● | ● | ● | ◐ | ● | ◐ | ◐ | ○ | ◐ | ● | ● | ○ |
| Coverage-honest abstention | ● | ● | ◐ | ◐ | ◐ | ○ | ○ | ○ | ◐ | ◐ | ◐ | ○ |
| *Assess* — RIB→FIB computed forwarding | ● | ● | ● | ● | ● | ○ | ◐ | ○ | ○ | ○ | ◐ | ○ |
| Differential reachability what-if | ● | ● | ● | ● | ● | ○ | ◐ | ○ | ○ | ○ | ◐ | ◐ |
| Failure-injection (1 snapshot) | ● | ● | ● | ● | ◐ | ○ | ○ | ○ | ○ | ○ | ○ | ◐ |
| ACL shadow / line-reachability proof | ● | ● | ● | ◐ | ◐ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Compliance matrix (CIS/NIST/PCI/STIG) | ● | ● | ○ | ◐ | ◐ | ◐ | ◐ | ○ | ○ | ○ | ○ | ○ |
| Golden-config drift | ● | ● | ○ | ◐ | ◐ | ● | ● | ○ | ○ | ● | ○ | ○ |
| Checks-as-data assertions | ● | ● | ◐ | ● | ● | ● | ● | ◐ | ◐ | ◐ | ● | ◐ |
| *Deliver* — Migration deliverables (HLD…NRFU) | ● | ● | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| External SoT reconcile | ● | ● | ○ | ◐ | ◐ | ◐ | ◐ | ◐ | ◐ | ● | ○ | ● |
| Evidence / chain-of-custody | ● | ● | ○ | ◐ | ◐ | ● | ◐ | ● | ◐ | ◐ | ◐ | ◐ |

**Reading it:** the assurance leaders tie us on forwarding/what-if but are ○ on the entire *Deliver* band and weak on coverage-honesty + compliance; the automation/SoT tools own golden-config + reconcile + evidence but are ○ on offline / read-only / RIB→FIB. The `Failure-injection` and `ACL shadow proof` rows are the two places a *peer in our own lane* (Batfish/Forward) genuinely leads us today — Waves G fixes exactly those.

## Wave G — Formal / structural analysis (the assurance-lane gap; strongest new cluster)
Batfish/Forward/IP-Fabric capabilities the v1 roadmap never contained. All pure-offline over already-parsed data.

| # | Item | Grounding (verified) | Effort |
|---|------|-----------|--------|
| **G1 ✅ BUILT** | **`aclcheck.py` — ACL dead/shadowed-line PROOF + flow-space witness-or-proof** (Batfish `filterLineReachability` + `searchFilters`, fused as one work-item). Per ACL line: is its match-space non-empty after the lines above it? Typed taxonomy (`BLOCKING_LINES / INDEPENDENTLY_UNMATCHABLE / CYCLICAL_REFERENCE / UNDEFINED_REFERENCE`), `Different_Action` (a PERMIT silently shadowed by a DENY) = high severity; plus a `search_filters` verb returning a concrete witness 5-tuple **or** a proof none exists. **Coverage-honest:** any line touching an `unevaluable` token → INDETERMINATE, never "reachable"/"dead". | grep-verified **0 hits** for `filterLineReachability`/line-reach in `cisco_toolkit`; substrate = `parse._acl_rule` ([parse.py:2842](../cisco_toolkit/parse.py:2842)) normalized 5-tuple + the explorer's proven `_protoMatch/_addrMatch/_portMatch` ([blast_radius_explorer.html:4340](../cisco_toolkit/blast_radius_explorer.html:4340)). New `cisco_toolkit/aclcheck.py` | **L** |
| **G2** | **`zonematrix.py` — pairwise zone×zone reachability grid** (Forward/IP-Fabric security matrix): zones = VRFs + gateway-SVIs + app-domains; each ordered pair sampled via `fib.trace_fib_path` → fully-connected / partial / isolated, each cell citing a witness flow. | new `cisco_toolkit/zonematrix.py` joining `compute_segmentation` ([analyze.py:5209](../cisco_toolkit/analyze.py:5209)) + `fib.trace_fib_path`/`subnet_reps` ([fib.py:172](../cisco_toolkit/fib.py:172)) | **M** |
| **G3** | **`path_assertions.py` — named, persisted segmentation/path assertions** re-validated across `--compare` (Forward "saved path check + status:delivered" + IP-Fabric isolation intent). A committed JSON catalog `{id, src_selector, dst_selector, proto, port, expect: REACHES\|ISOLATED}` evaluated over `fib.trace_fib_path`. | new `cisco_toolkit/path_assertions.py` over `fib.py:172`; re-checked in `reachability_delta` ([fib.py:424](../cisco_toolkit/fib.py:424)) | **M** |
| **G4** | **`whatif.py` — single-snapshot failure-injection what-if** (Selector "what-if", recast offline): a committed scenario catalog `{failures:[{type:node\|site, id}], flows[], expect}` → deep-copy + mutate the snapshot in memory → re-run `fib`. Distinct from C1 (which needs two *real* snapshots). | verified `reachability_diff`/`_delta` both require old+new real snaps; nothing mutates ONE. New `cisco_toolkit/whatif.py` calling [fib.py:332](../cisco_toolkit/fib.py:332) | **L** |

**Binding doctrine guards (G):** **G2/G3 inherit `fib.py`'s single-VRF blindness (the deferred fib #19)** — a cross-VRF cell/path MUST render `UNVERIFIABLE`, never "isolated" (a VRF-blind NxN grid would fabricate isolation). **G1 is the one genuine `ADOPT`** (the others `ADAPT`); ASR-4 `specs.py` (a unified selector DSL) is **CUT for now** — the built `assertions.py` already ships a `subject`+`device` scoper, so a Batfish-grammar DSL is low-value and (per F2) the surfaces are deliberately non-aligned.

> **G1 ✅ BUILT this session (test-first, full suite green).** [`cisco_toolkit/aclcheck.py`](../cisco_toolkit/aclcheck.py) + [`tests/test_aclcheck.py`](../tests/test_aclcheck.py) (10 tests): a 5-dimensional header-space box algebra (proto co-finite set × src/dst IPv4 prefix-sets × sport/dport interval-sets) with exact guillotine box-subtraction for union coverage; emits `BLOCKING_LINES` (+`different_action`), `INDEPENDENTLY_UNMATCHABLE`, `UNDEFINED_/CYCLICAL_REFERENCE`, and coverage-honest `INDETERMINATE` (it refused a non-contiguous wildcard in its own test fixture). **Runtime-proven on the real [HISTORY-REDACTED] snapshot** (301 ACLs / 3 507 rules → **35 dead lines** a migration can drop, 4 honest INDETERMINATE), and **independently refuted to 0 counterexamples** by a separate concrete first-match simulator over 3 840 real packets. `search_filters` returns a witness 5-tuple or a proof none exists. Lands `snap['acl_line_reachability']`; next: wire the Excel sheet + explorer Security mode.

## Wave H — Assertion engine v2 (extend the now-BUILT `assertions.py`)
| # | Item | Grounding | Effort |
|---|------|-----------|--------|
| **H1 ✅ BUILT** | **Two-operand extract-and-compare + the `%` utilization operator** (Itential `#comparison`) + `contains1`. | **DONE** (proof spike #2): `ratio`/`contains1` rule types in [assertions.py](../cisco_toolkit/assertions.py) (`_rule_holds` + `_first_num`); zero-denominator → abstain, never a false pass; `tests/test_assertions.py` 11 green | **S** |
| **H2** | **Per-OBJECT `for_each` grammar** (NetBox CustomValidator + Infrahub uniqueness): map a model name → a snapshot collection, then `min/max/length/required/prohibited/eq/neq/uniqueness` per row — "for every interface, mtu in band". Coverage-honest: a rule over a never-collected field → NOT_OBSERVED per row. Dedup duplicate-IP to the shipped `compute_addressing_conflicts`. | extend [assertions.py](../cisco_toolkit/assertions.py) (`for_each` resolver beside `evaluate_assertion`; predicates beside `_rule_holds`) | **M** |

## Wave I — Conformance & golden-config depth (extends Wave E)
| # | Item | Grounding | Effort |
|---|------|-----------|--------|
| **I1** | **`compute_json_conformance` with the verbatim Ansible `validate` 8-field error record** (`data_path / json_path / expected / found / message / validator / schema_path / relative_schema`) + the 3×2 array-match matrix — the concrete contract for v1's **E2**. Offline JSONPath subset over controller-REST blobs vs a Git-committed baseline (never a live fetch). | grep-verified **0 hits** for `compute_json_conformance`/`json_path`; new fn beside `compute_golden_drift` ([analyze.py:4228](../cisco_toolkit/analyze.py:4228)) | **L** |
| **I2** | **Per-feature ConfigCompliance decomposition** (Nautobot Golden Config): a committed `feature→match_config` map re-projecting `compute_golden_drift`'s flat delta into per-(device×feature) rows `{feature, config_type:cli\|json, ordered, compliant, missing[], extra[]}`, device = AND-over-features. | extend `compute_golden_drift` ([analyze.py:4228](../cisco_toolkit/analyze.py:4228)) with a `_FEATURE_MAP`; new Excel sheet | **M** |
| **I3** | **Day-1-never-conformed vs Day-2-drifted history axis** (NetBrain) — across the already-collected `--compare`/`--trend` pair (no live poll): a device failing golden is `day1` if it also failed earliest, else `day2_drifted`. | optional prior-snapshot param on `compute_golden_drift` ([analyze.py:4228](../cisco_toolkit/analyze.py:4228)) | **M** |

## Wave J — Provenance & integrity depth (extends Wave D)
| # | Item | Grounding | Effort |
|---|------|-----------|--------|
| **J1** | **Per-detector `healthy_value`/`threshold` descriptor** (NetCopilot rule-catalog) — promote the flat `_PUNCH_SOURCE_COMMAND` map into `{cited_fields[], healthy_value, threshold, source_commands[]}`, making "not-observed ≠ healthy" a **schema property**. **REJECT** the YANG half (engine has zero NETCONF). | [analyze.py:3136](../cisco_toolkit/analyze.py:3136) (`_PUNCH_SOURCE_COMMAND` → descriptor) | **M** |
| **J2** | **Attribute-level fact lineage** (Infrahub) — `ssot.fact_lineage(snap)` projecting `{value, source_command, collected_at, schema_version}` per canonical fact; the per-fact backbone for D1/D3. | new projector in [ssot.py](../cisco_toolkit/ssot.py) beside `canonical_facts:99` | **M** |
| **J3** | **Snapshot schema-contract census** (SuzieQ `describe`) — `describe_schema(snap)` reporting per section `published\|collected_but_empty\|not_collected` + the `abstention_reason` — coverage-honesty as a queryable artifact (field/section level vs today's device-level `compute_collection_completeness`). | new projector in [ssot.py:127](../cisco_toolkit/ssot.py:127) (reuse `abstention_reason`) | **M** |
| **J4 → fold** | **Navigable append-only hash-chain ledger** (NetClaw GAIT) → **amend D2**: make the run-manifest a per-step hash-chained JSONL (each row `prev_sha256`), not just a single seal. **Stable `finding_id` + frozen-citation invariant** (NetCopilot) → the `finding_id` half is **already planned (W3-3)**; keep only the constructor-enforced citation invariant. | folds into D2 ([COLLECT_PARSE_V3_23_0.py:1135](../COLLECT_PARSE_V3_23_0.py:1135)) + `add()` ([analyze.py:3187](../cisco_toolkit/analyze.py:3187)) | **S** |

## Wave K — Collection & parser integrity (new robustness cluster)
| # | Item | Grounding | Effort |
|---|------|-----------|--------|
| **K1** | **Per-config-body capture-integrity / `[INCOMPLETE]` truncation guard** (Oxidized's #1 real-world failure: debug shows full config, store keeps part). `compute_collection_completeness` checks **file presence, not body integrity** (its own comment, [analyze.py:1188](../cisco_toolkit/analyze.py:1188)) — a truncated `show run` today scores "complete" and every downstream finding off it can false-pass. Stamp `[INCOMPLETE]` → flows into `abstention_reason`. | extend `compute_collection_completeness` ([analyze.py:1065](../cisco_toolkit/analyze.py:1065)) | **M** |
| **K2** | **Parser registry with committed golden-line examples** (Ansible `cli_parse` discipline) — lift the real-output fixtures already in `test_audit5_parse_fidelity.py` into a `PARSER_EXAMPLES` registry + a test that re-runs each parser against its committed example (guards the recurring format-fidelity defect with REAL lines, not self-authored). | [parse.py](../cisco_toolkit/parse.py) + new `tests/test_parser_examples.py` | **S** |
| **K3** | **Declarative per-OS collection-profile table** (Oxidized Model DSL + RANCID `.cloginrc`) — externalize the hardcoded `COMMANDS_*` lists + noise-reject regexes into one table both the live collector and `--no-collect` union consume; **secrets via env/vault handle, never inline**. Noise-reject also feeds the golden comparator (suppress volatile-line false deltas). | new `cisco_toolkit/collection_profiles.py` from the registries at [COLLECT_PARSE_V3_23_0.py:489](../COLLECT_PARSE_V3_23_0.py:489) | **M** |
| **K4** | **Adversarial redaction-leak corpus** (the competitors' own anonymizer bugs: substring over-replace, no word boundaries, MAC/IPv6 misses) → concrete negative-test fixtures for `--redact`/secret-scrub, folded into F1's Secret-exfil class. | extend `tests/test_redact_e2e.py`; folds into F1 | **S** |

## Wave L — Graph & enrichment (cheap halves; defer the heavy)
| # | Item | Grounding | Effort |
|---|------|-----------|--------|
| **L1** | **Typed-link taxonomy on the model graph** — stamp each `build_network_model` edge with `link_type` + `derivation` (`observed` CDP/LLDP vs `inferred`), reusing the existing `_ECONF` vocabulary so there's one source of truth; the cross-run/site tenancy key is **deferred**. | [analyze.py:434](../cisco_toolkit/analyze.py:434)/`:480` | **M** |
| **L2 → fold** | **External-inventory enrichment sub-record** (Selector Data-Hypervisor / Aviz connectors) → **fold into B1** as its persist+precedence half (`snap['enrichment']`, additive, first-party evidence wins on conflict). **Askbot intents-as-inspectable-queries** (Selector NL→SQL) → **fold into A2** as an `answerable_questions` projection (descriptive only). **Fault-propagation RCA** (Selector) → **defer**: `compute_failure_impact` + the Blast-radius explorer already deliver it; only the typed `network_graph` serialization is the thin gap. | B1 / A2 / `network_graph` thin-slice | **S** |

## Frontier — verified gaps the critic surfaced (smaller, high-signal)
- **MTU / jumbo blackhole verdict along the computed fib path** — `fib.py` factors MTU into *zero* path verdicts today (the L1–L4 feature parses MTU but the tracer ignores it).
- **Return-path / forwarding-asymmetry verdict** — `trace_fib_path` is one-directional; the "works one way, RPF-drops the other" cutover-regression class needs the reverse trace + an asymmetry flag.
- **Offline NRFU verification-command EXPORT** — the read-only actuator hand-off: emit the generated `show`/`ping`/`traceroute` the human runs to confirm a cutover (we render config in AUTO-3 but no *verification* commands).
- **Prefix / VLAN / VRF utilization + overlap census** (NetBox's highest-volume compute) — beyond reconcile.

## Updated Top-5 (across v1 + v2, by impact-per-effort)
1. **G1 — `aclcheck.py` ACL shadow proof (L).** The one place a peer in our own lane (Batfish) genuinely leads us; pure-offline over already-parsed ACLs; the critic's #1 pick.
2. **K1 — capture-integrity `[INCOMPLETE]` guard (M).** Closes a silent false-health hole (truncated capture reads "complete") — the highest-risk correctness gap found.
3. **I2 — per-feature ConfigCompliance (M).** Turns one golden-drift number per device into an auditable per-feature grid; extends shipped code.
4. **G4 — single-snapshot failure-injection what-if (L).** The other assurance-lane lead (Selector/Forward); makes the FIB engine answer "what if this core dies" with no second collection.
5. **D2+J4 — sealed, navigable chain-of-custody (M).** Still the cheapest high-trust win; now upgraded to a per-step hash-chain.

> **Three capabilities already BUILT this session** (test-first, full suite green): **A1** `assertions.py` (checks-as-data engine, runtime-proven on the real 253-device [HISTORY-REDACTED] snapshot) + **H1** the two-operand `%` operator, and the **marquee G1** `aclcheck.py` (ACL shadow proof — runtime-proven on 301 real ACLs, independently refuted to 0 counterexamples). They demonstrate the roadmap is executable, not paper.

## Cut / already-shipped / mischaracterized (the critic was right)
- `reachability_diff` ([fib.py:332](../cisco_toolkit/fib.py:332)) **already IS** the Batfish/Forward differential-reachability peer — don't re-propose it.
- Forwarding **loop detection** is **HAVE** (`fib.py:291`, memoized DFS back-edge); config-hygiene **undefined-references** is HAVE (archreview + punchlist). A "Batfish detectLoops/undefined-refs" idea would be redundant.
- `SOT-4` historical **state-lake + query grammar** — value **overstated** for a per-engagement (not polling) tool; **deferred**.
- `AUTO-3` offline **config-render → CLI delta** — the **least doctrine-pure** idea (an assessment engine rendering device CLI risks the coverage-honesty line); **deferred**, and if ever built, strictly a LABELED, CITED *advisory* block inside the human-owned MOP, never executable.
- `ASR-4 specs.py` DSL, `AIO-5` fault-graph, the tenancy key — **deferred/folded** (see G/L notes).
