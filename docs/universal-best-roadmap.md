# Universal & Best — a grounded roadmap from the Transit AI · SmartyMe · NotebookLM teardowns

Distilled from three adversarially-verified deep-research teardowns ([product-teardowns.md](research/product-teardowns.md)),
then **grounded in our real code (file:line) by two multi-agent waves** (31-agent Transit-AI/SmartyMe wave +
18-agent NotebookLM wave), each ending in an adversarial critic (both verdicts: **SHIP-WITH-FIXES**). Every item
obeys the three non-negotiables — **fully offline / no egress, read-only, coverage-honest (no overclaim)** — and
anything needing a cloud LLM or risking an unsupported claim was **cut**, not adopted.

> **Status — what is BUILT vs PROPOSED (read this first).** The Wave tables below are a **PROPOSED design**: each
> item's `file:line` is the **landing site** where it would go, NOT an existing feature (e.g. `--collect-raw-outputs`
> / `snap['cmd_outputs']` in W3-3 do **not** exist yet — they're the proposed shape). **SHIPPED so far** (2026-06-25,
> test-first, committed): **W1-1/W1-2** the read-only + no-egress falsifiable guards (`610d3e2`, `tests/test_readonly_and_no_egress.py`);
> **W3-1 backend** `ssot.abstention_reason()` + **W3-5** the reconcile pre-emission gate (`510129a`); **the marquee
> W2-1 + W2-2** — `cisco_toolkit/fib.py`: native longest-prefix-match RIB→FIB resolver + computed path tracer
> (`d47fce4`) and the differential reachability what-if `reachability_diff()` (`0eb3bbd`), both test-first
> (`tests/test_fib.py`, 29 tests) and runtime-verified on the real AJ snapshot, then HARDENED by a 12-defect
> adversarial wave (`99e6072`). **W2 is now LIVE in `--compare` (`70c03c8`):** `compute_snapshot_delta` computes
> `fib.reachability_delta(old,new)` over auto-derived representative inter-subnet flows and drives the cutover
> VERDICT to REGRESSED on a definitively `newly_blocked` flow (AJ self-diff: 400 flows in 0.16s, 0 fabricated
> regressions). The remaining surface is the **explorer flow-sim** L3 upgrade. Everything else here is design,
> sequenced and grounded, awaiting implementation.

## The thesis — what "universal & best" actually means here
The waves **verified** that the engine already wins on three things no cloud competitor can match:
- **Air-gapped by construction** — only two network paths exist (netmiko SSH + opt-in GET-only `rest_collect`);
  zero cloud/LLM imports in the analysis→deliverable pipeline.
- **Read-only by construction** — *not one* `send_config_set`/`config_mode`/`commit`/`load_*` sink anywhere; the
  only non-`show` strings on the wire are `terminal length 0` / `terminal width 511` (`COLLECT_PARSE_V3_23_0.py:810`).
- **Coverage-honest by doctrine** — 82 `_d_*` detectors each cite a published principle (`_decision(pid)` →
  `design_kb.by_id`, `design_advisor.py:1354-1356`); "not observed" never becomes "healthy".

The two teardowns sharpen this; the third reinforces it:
- **Transit AI** → *make the moat falsifiable.* Today read-only/no-egress are **trust statements with no test** —
  a silent regression would pass. Turn them into offline regression nets (Transit-AI's structural-safety lesson
  **without** its cloud dependency — which we'd never adopt).
- **SmartyMe** → *honesty as product.* Our anti-SmartyMe edge (cite the field/line) is real but **under-surfaced**;
  make per-claim provenance visible — but **never a self-asserted "trust" badge** (that's SmartyMe's overclaim).
- **NotebookLM** → *make grounding clickable.* A single corpus rendered many ways with click-through citations
  and honest abstention. This *is* our doctrine (`ssot.py` + `snapshot.json` + 12 renderings); the gap is that the
  grounding is **invisible in the UI**.

**The marquee move both waves converge on:** the one capability that beats IP Fabric / Forward / Batfish — a
**native, pure-Python, evidence-cited computed-forwarding (RIB→FIB) simulation + differential what-if** that can
**PROVE a cutover preserves reachability/segmentation before the maintenance window** — delivered with the
air-gapped, read-only, every-claim-cited posture the competition structurally cannot offer.

> **Positioning:** the only fully air-gapped, read-only-*by-architecture*, coverage-honest multi-vendor L1–L4
> brownfield assessment + migration platform that **computes forwarding from collected evidence and proves a
> cutover preserves reachability** — every finding traced to the show-line and principle that justify it, every
> blind spot declared, zero data ever leaving the operator's air gap. *The offline, evidence-grounded peer to
> Batfish, with the deliverable-and-doctrine layer Batfish lacks.*

---

## Wave 1 — Lock the moat (cheap, doctrine-tightening, days)
Convert the three differentiators from *trust statements* into *falsifiable offline regression nets* caught by the
existing pytest Stop-hook. **Highest impact-per-effort.** *(Critic-mandated fixes folded in — these are binding.)*

| # | Item | Grounding | Effort |
|---|------|-----------|--------|
| W1-1 | **Read-only by architecture** — one anchored allow-list test on the SEND PATH | `COLLECT_PARSE_V3_23_0.py:810` (the 2 terminal-setup commands), `:833` (`send_cmd`→`send_command`, no config path), `COMMANDS_*` six SSH registries `:487/579/664/670/675/679`; lands in `tests/test_data_quality.py` | **S** |
| W1-2 | **No-egress import guard** — assert the analysis→deliverable modules import no network libs | only `netmiko` (`:458`, *lazy, inside `connect_device`*) + `rest_collect` urllib are runtime egress; `data/gen_port_registry.py:149` is the dev-only exception | **S** |
| W1-3 | **Per-claim source provenance** (`source_command`) on health deductions/findings — the honest core of evidence-trust | `analyze.py:5017` deduction tuples; `reconcile()` reads only NAMED dotted paths so added fields are SSOT-invisible (low risk) | **M** |

**Binding critic fixes (must hold or the items false-fail / overclaim):**
- **W1-1 regex must match the *actual* registries.** The proposed `^(show|display|get|moquery|api/…)` would go
  red day-one: `COMMANDS_CLOUD` has `aws ec2 describe-security-groups` (starts `aws`). Scope the **SSH** test to
  `^(show|display|get|dir |ping )` **plus `aws `**, re-derived from the six registries; assert the **REST**
  allow-list separately against `rest_collect`. Scope the source-grep to `cisco_toolkit/` + the live
  `COLLECT_PARSE_V3_23_0.py` — **exclude `_ref/`** (a checked-in stale duplicate).
- **W1-2 import-scan must catch LAZY imports** (netmiko is imported *inside* `connect_device`, not top-level) —
  walk all `Import`/`ImportFrom` at any depth; explicitly allow-list `rest_collect` + `data/gen_port_registry`.
- **W1-3 stops at per-finding "from: `<show cmd>`" tooltips** — **no global "every claim is traced" badge** (that's
  the SmartyMe overclaim until provenance is universal across all claim types).

## Wave 2 — The universal capability: computed forwarding + differential what-if
The single gap vs every assurance leader. Native, pure-Python, air-gapped, coverage-honest.

| # | Item | Grounding | Effort |
|---|------|-----------|--------|
| W2-1 ✅ **BUILT** (`d47fce4`) | **Native longest-prefix-match RIB→FIB resolver** — upgrade reachability from L2 topology-BFS to computed L3 forwarding | **DONE** in `cisco_toolkit/fib.py` (`compute_fib`/`fib_lookup`/`trace_fib_path`); pure stdlib `ipaddress`, coverage-honest (`computed:reached` / `computed:unreachable` / `lower_bound:*`). The `analyze.py:2186` L2 lower-bound stays; fib is the computed upgrade, AJ-verified | **L** |
| W2-2 ✅ **BUILT + LIVE** (`0eb3bbd`, `70c03c8`) | **Differential what-if** — diff current-vs-proposed reachability → a pre-cutover **proof** | **DONE + WIRED**: `reachability_diff` / `reachability_delta` (preserved / newly_blocked / newly_reachable / inconclusive); `compute_snapshot_delta` runs it in the `--compare` flow and a `newly_blocked` flow drives the cutover verdict to REGRESSED (+ a Reachability sheet in the diff workbook) | **L** |
| W2-3 | **Framework-mapping table** (CIS / NIST 800-53 / DISA-STIG / PCI) over the EXISTING detector corpus — a "proof of compliance" matrix | the 82 `_d_*` detectors already carry `citation`; CIS axis already fires. A mapping dict + renderer, **not** a new check engine | **M** |

**Doctrine guard (W2-1/2):** a resolved path is "computed from collected routes"; any unresolved/partial leg
**stays "lower bound — routes not observed"** (mirror `analyze.py:2186`) — never an overclaiming "reachable".
Build incrementally (connected+static → OSPF/BGP-best); keep an opt-in pybatfish power-mode a *separate future
id*, never a runtime dependency. W2-3: an unmapped/unfired control renders **"not auto-assessed", never "pass"**.

## Wave 3 — Make grounding *clickable* (NotebookLM) + self-apply the doctrine
The NotebookLM "citation UX" program (the explorer/askbot honesty layer) + the doctrine-graph invariants.

| # | Item | Grounding | Effort |
|---|------|-----------|--------|
| W3-1 | **First-class `[NOT OBSERVED]` 3-state abstention** (not-collected / collected-but-empty / not-applicable) — closes the silent "not-observed → healthy" gap *by construction* | new `ssot.abstention_reason()` beside `ssot.py:99`; split `blast_radius_explorer.html:8707` (`abH_fallback`); in-tree precedent `abH_license` | **M** |
| W3-2 | **Precision-tiered evidence chips** (LINE/BLOCK/DEVICE/FLEET) on the live evidence dict — never fake-precise; ship with a **byte-match verifier** (demote-to-BLOCK on mismatch, tested vs real AJ text) | `causal.py:95-106` (`_flow(evidence=)`) → `CausalFlow.tsx:179` + explorer `:333`; tested `tests/test_causal_flows.py` | **L** |
| W3-3 | **Universal `evidence_index` + clickable `[host:cmd:L#]` chips** — one-hop verification on every surface | opt-in `--collect-raw-outputs` → `snap['cmd_outputs']`; thread `{finding_id,sources[]}` through punchlist `add()` at **`analyze.py:2945`** (one axis first) | **XL** |
| W3-4 | **Mind-Map: click a topology/causal node → scoped offline askbot question + citation chip** | explorer renderer + askbot `abSubmit:9131`/`abAnswer:9081`; deterministic, no LLM | **M** |
| W3-5 | **`ssot.reconcile()==[]` fail-soft pre-emission gate** before any deliverable is written | wire into `webapp/backend/deliverables.py:71` (does NOT call it today) + reuse `assessment_integrity` (`ssot.py:213`) | **L** |
| W3-6 | **Doctrine-graph invariants** — AST-project `_decision(pid)`↔`design_kb` into a doctrine_graph; gate two pytest invariants (no orphan detector; engine_actionable ⊆ cited pids) — coverage-honesty as a build gate | `design_advisor.py:1354-1356`; `design_kb.py` engine_actionable fields; new `tools/build_doctrine_graph.py` | **M** |
| W3-7 | **Auto-generated traceability appendix** (finding→principle→citation→evidence) in HLD/CRD/archreview — the one safe *product* win | each decision already carries `{principle:{id,title,citation}}`; `--no-*` gated | **M** |

**W3-3 binding fix:** `--collect-raw-outputs` must **force secret-scrub (`_scrub_secrets`) + excerpt-only,
unconditionally** (independent of `--redact`, which is default-OFF) — else `show running-config` ships cleartext
secrets. `redact_snapshot`'s recursive `_walk` (`html.py:701`) covers it *only under `--redact`*.

---

## Top 3 to do first (best impact-per-effort, across both waves)
1. **W1-1 read-only send-path test (S)** — proves the #1 differentiator structurally; caught by the existing
   Stop-hook; with the C1 regex fix it cannot false-fail or overclaim.
2. **W1-2 no-egress import guard (S)** — proves the air-gap moat; with the lazy-import + `_ref/` fixes.
3. **W3-1 `[NOT OBSERVED]` abstention (M)** — the one item that *changes answers*; closes the engine's signature
   false-health gap by construction; working in-tree precedent (`abH_license`).

*Then the marquee:* **W2-1 native RIB→FIB → W2-2 differential what-if** — the universal capability vs Batfish/Forward/IP Fabric.

## Cut (doctrine / redundancy — the waves were right, several correct my own draft)
- **Guided microlearning onboarding** — *already exists*: the explorer ships an offline coachmark tour
  (`blast_radius_explorer.html:1082` "Take the guided tour") + punchlist orders Critical→Low by blast-radius. A new
  `tour_sequence` = a second ordering of one fact = the SSOT-drift class we police. *Salvage: deep-link the
  existing tour into specific findings.*
- **Offline audio / "listen" mode** — a TTS `.wav` is the one output that is **not citable, grep-able, diff-able,
  or version-controllable** — hostile to the cite-the-line doctrine and the CAB/peer-review workflow; adds a
  fragile dep (Piper is GPL-3.0; XTTS non-commercial) for an artifact no L1–L4 cutover audit consumes. **Cut.**
- **Interview deliverable right-sizing** — asserting "artifact X not needed for THIS estate" is a prescriptive
  *negative* a snapshot can't evidence — the exact SmartyMe overclaim. *Salvage: wire the already-computed
  open/needs-requirement decisions into the plan-of-record (honest "D/E OPEN pending X").*
- **Streak/habit gamification** — wrong pressure on a go/no-go safety gate; the planned-date metric isn't derivable
  (`GATE_SEQUENCE` stores free-text offsets) so it would fabricate. *Salvage: gate-velocity + remediation burn-down,
  computed live, "window not anchored" instead of a fabricated verdict.*
- **Ordinal-equivalence redaction** — an **anti-goal**: "this community is reused on A,B,C" is exactly the
  attacker-useful fact redaction must *destroy*; `_scrub_secrets` deliberately one-way-scrubs. **Cut.** (IP/MAC/
  serial pseudonyms already preserve safe consistency.)
- **OS-keychain credential bundle** — gold-plating an already-closed threat (`$CISCO_PASS` keeps secrets out of the
  file; they live only in an in-process dict; `html.py` scrubs every secret form before any write). *Salvage:
  SSH-key-by-path only, as a small future add.*
- **A self-asserted "no-egress / evidence-trust" badge or axis** — pure positioning; pollutes the
  `executive_brief` SSOT. The only load-bearing piece is the **W1-2 test**; the property is already disclosed
  in-product (`blast_radius_explorer.html:8947` "fully offline… no cloud, no model, no telemetry").

## Risks (carry into implementation)
- **Format-fidelity (recurring):** a regex-derived `line_no` citing the wrong line on a real format variant is a
  *confidently-wrong* claim — worse than none. → W3-2 byte-match verifier + tests on **real AJ collected text**.
- **W2 RIB/FIB overclaim:** partial route parse → false "reachable". → keep the "lower bound — not observed" label.
- **Provenance creep → trust-badge:** ship tooltips + a fired-only appendix; never a global honesty badge.
- **Doctrine-graph rot:** rebuild from source every run (AST-only) + the pytest invariant; never commit a stale
  snapshot as truth.

---

## Graphify maximization (goal half B — DONE this session, with the remainder scoped)
You were right it was underused — and the audit found it was **30% polluted**. Actions taken + verified:

**✅ Done:**
1. **De-polluted the graph: 5591 → 3940 nodes** (−1651, ~30%). Excluded the stale `_ref/` engine duplicate (537
   nodes — the *actual* root cause of the duplicate god-nodes) + the graph's own `graphify-out/` output dumps (1159)
   via `.graphifyignore`, then `update . --force`. Verified: all legit code preserved (cisco_toolkit 1115, webapp
   557, tests 1459, docs 480), `_ref/` gone, dup god-nodes resolved. *(I had wrongly called the dups "legitimately
   distinct"; the wave + node-count refuted me.)*
2. **Generated the offline nav artifact** the dead wiki rule wanted — `graphify tree` → `graphify-out/GRAPH_TREE.html`
   (D3 collapsible tree, 340 KB). `export callflow-html` available for Mermaid call-flow.
3. **Rewrote the CLAUDE.md graphify section**: killed the dead `wiki/` rule; made the **advanced surface a default**
   — `affected "<sym>()"` (reverse blast-radius, the highest-value unused verb) + `god_nodes`/`query_graph`/
   `tree`; and **flagged the egress verbs** (`add`, `label`, MCP `get_pr_impact`/`list_prs` hit live GitHub — I'd
   wrongly recommended `get_pr_impact`; the wave caught it).
4. **Fused the research corpus** into the graph — the three teardowns under `docs/research/` are indexed (docs 465→480).

**◻ Remaining (in the roadmap, low effort):**
5. **Wire `graphify affected "<symbol>"` into the ASNE commands/agents** (`qa.md`/`audit.md`/`assess.md` +
   `topology-reachability-analyst`/`mop-change-author`/`deliverable-qa-reviewer`) — only 1/8 agents + 3/9 commands
   mention graphify today; this is W3-6-adjacent and directly attacks the parser↔detector drift bug class.
6. **Doctrine-graph projection** (W3-6) — the latent 240-principle↔82-detector graph that graphify's AST layer
   can't see; an offline build + pytest gate.
7. Correct `MEMORY/graphify-setup.md` (the doc-derived nodes are not `graphify add` output).
