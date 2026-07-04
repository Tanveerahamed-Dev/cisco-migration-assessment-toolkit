# Next-best improvements — cross-surface synthesis (2026-07-04)

**Method.** Mined all four Claude surfaces at once and cross-validated every candidate against the live
code before listing it:
- **Claude Code** — git log (@ `423426e`, v3.26.0), `docs/` roadmaps, the graphify graph (5395 nodes), and the memory store.
- **Claude Cowork** — the CCD session transcripts (`search_session_transcripts`) — same store as Code.
- **Claude Design** — the live `DesignSync` project (`Design System`, owned, `updatedAt 2026-07-04`).
- **Claude Chat** — no direct transcript API; its research is folded into `docs/research/` + memory, which were mined. *(Honest gap: raw claude.ai chat history is not machine-readable from here.)*

**The thesis (all four streams converge on it).** The *analysis* surface is **saturated** — the engine already
scores `●` against Batfish / Forward / IP-Fabric / Itential / NetBrain on RIB→FIB, differential what-if, ACL
shadow proof, compliance matrix, golden drift, checks-as-data, external reconcile, and chain-of-custody
(`docs/orchestration-best-roadmap.md:162-177`). So **the frontier is not more detectors — it is turning strong
analysis into audit-grade, change-safety-certified, provably-trustworthy output**, plus closing the one quality
surface with **no** mechanical gate (design). Everything below is offline / read-only / no-egress by construction.

---

## Do these three first (highest leverage, in-doctrine, reuse shipped engines)

### 1. Playwright visual-regression **design gate** — the only quality surface with no ratchet *(cross-surface; Effort M)*
The engine has a pytest Stop-gate that blocks a red turn, but **design/CSS/token changes have zero mechanical
guard** — a regression ships silently. This is not hypothetical: pre-glass CSS shipped to the live design
project for a full day before it was caught by hand (memory: `design-sync-assesshub.md`). Add screenshot-diff CI
over the 16 synced components (`.design-sync/` render-check harness already emits per-component render hashes).
This is Phase 2 of the documented-but-unbuilt design-optimization plan (only Phase 1, brand-token SSOT / PR #290,
shipped) and it is the single item that most directly answers "across Claude Design."

### 2. The **Verification-Deliverable trio** — package shipped engines as the PPDIOO artifacts a senior engineer hands a client
Each wraps code that already exists; only the *named deliverable* is missing (verified absent in the module list):
- **`precert.py` — Pre-Change Validation Certificate** *(Effort M, roadmap C1)*. One page binding the shipped
  `fib.reachability_delta` (`cisco_toolkit/fib.py:424`) to a candidate change: *"flows X,Y,Z preserved;
  segmentation invariant S holds; N flows change state (each cited old→new); M inconclusive (blind spot)."*
  This is the offline Batfish-pre-change / NetBrain-Triple-Defense peer as a *gate artifact*.
- **`attestation.py` — zero-egress attestation panel** *(Effort M, roadmap D3)*. Re-derive (never hardcode)
  read-only / no-egress / no-LLM at build time using the **same AST/regex as `tests/test_readonly_and_no_egress.py`**
  → a falsifiable "Trust & Sovereignty" panel on the explorer + workbook cover + HLD front matter. The
  differentiator every competitor gestures at but none can make — as a *proof*, not a badge.
- **Offline NRFU verification-command export** *(Effort M, frontier `:233`)*. Emit the read-only
  `show`/`ping`/`traceroute` a human runs to confirm a cutover — the read-only actuator hand-off (we render config
  in the MOP but no *verification* commands).

### 3. Kill the recurring false-health bug-class with **real-line fixtures** *(Effort S+M)*
Every current golden is synthetic, and the recurring, highest-impact defect class is "self-authored fixture hides
the bug" — `parse_ip_routes` once zeroed a real NX-OS RIB; coverage_matrix fake-covered ~100 real rows; both hid
in synthetic data until adversarial review on a *real* snapshot (memory: `pr277-adversarial-review.md`,
`multidomain-engine-audit.md`). Two cheap, compounding fixes:
- **K2 — `PARSER_EXAMPLES` registry** *(Effort S)*: lift the real-output fixtures already in
  `tests/test_audit5_parse_fidelity.py` into a registry + a test that re-runs each parser against its committed
  **real** line. Guards the format-fidelity drift class with real lines, not self-authored ones.
- **Redacted real-world golden fixture** *(Effort M)*: promote one redacted real capture to a golden so the suite
  exercises member-down / uncollected-in-group / ACL-verdict-key paths synthetic goldens structurally miss.

---

## Tier 2 — Assurance-lane depth (extends the digital twin; real silent-cutover-break classes)
| Item | Grounding | Effort | Doctrine note |
|---|---|:--:|---|
| **MTU / jumbo-blackhole verdict** along the computed FIB path | `fib.py` factors MTU into *zero* verdicts today (frontier `:231`) | M | pure static over parsed MTU |
| **Return-path / RPF asymmetry verdict** | `trace_fib_path` is one-directional (frontier `:232`) | M | "works one way, drops the other" |
| **`zonematrix.py`** — pairwise zone×zone reachability grid (Forward/IP-Fabric matrix) | roadmap G2, over `fib.trace_fib_path` | M | **blocked-adjacent**: cross-VRF cells MUST render `UNVERIFIABLE` until fib #19 |
| **H2 `for_each`** assertion grammar — "for every interface, mtu in band" | extend `assertions.py` (roadmap H2) | M | the two-sided consistency surface (SuzieQ-style) |
| **ECMP multipath-consistency** check over the FIB | Batfish `multipathConsistency`; loop-detection already HAVE (`fib.py:291`) | M | incremental over existing FIB |

## Tier 3 — Coverage-honesty as a queryable schema (deepen the actual moat)
| Item | Grounding | Effort |
|---|---|:--:|
| **J1** per-detector `{healthy_value, threshold, cited_fields}` descriptor — makes "not-observed ≠ healthy" a *schema property* | `analyze.py:3136` (`_PUNCH_SOURCE_COMMAND`) | M |
| **J3** `describe_schema(snap)` — per-section `published / collected_but_empty / not_collected` census (SuzieQ `describe`) | `ssot.py:127` (reuse `abstention_reason`) | M |
| **J2** `ssot.fact_lineage(snap)` — attribute-level `{value, source_command, collected_at, schema_version}` | `ssot.py:99` | M |
| **I1** `compute_json_conformance` — offline JSONPath rules over ACI/vManage JSON vs a git-committed baseline | new fn beside `compute_golden_drift` `analyze.py:4228` | L |
| **I3** Day-1-never-conformed vs Day-2-drifted history axis over `--compare`/`--trend` | optional param on `compute_golden_drift` | M |

## Tier 4 — Finish the in-flight Deliverable Excellence P2/P3 (presentation, not analysis)
*Verified against code: archreview SPOF section is **already present** (`archreview.py:260` "Resiliency & availability") — dropped. Remaining, confirmed open:*
- **ops.py** — Backup-&-Recovery + Known-Issues sections (no such section today; only a "single point in time" note).
- **mop.py** — Executive-Summary BLUF + explicit per-§ rollback-trigger boolean + pre-implementation checklist + comms plan (only a passing comment exists). *Overlaps roadmap C2 "Change-Defense Ledger" (label §s PRE/DURING/POST) + C3 build-gate (every wave has ≥1 verify AND rollback).*
- **crd.py** — Constraints + Out-of-scope sections + theory-of-operation prose per requirement.
- **Commit the untracked design-sync assets** (`.design-sync/`, `webapp/frontend/ds.entry.ts`, conventions.md/NOTES.md) so the design library is durable on `main` (Phase 0 of the design plan).

## Tier 5 — Security / robustness (cheap, S)
- **K4** — finish the adversarial redaction-leak corpus (a real SNMP-community survivor was already found; each new vendor is a redaction risk). `tests/test_redact_e2e.py`.
- **Widen the `ntc-templates` parser referee** to ~15–20 commands (Tier-3 #17) — hardens the parser↔detector drift class.
- **CLI-side reconcile pre-emission gate parity** — the W3-5 `_reconcile_gate` exists only on the webapp path (`webapp/backend/deliverables.py:95`, fail-soft); add the symmetric gate to the CLI deliverable path.
- **K1 body-integrity** — extend `compute_collection_completeness` (`analyze.py:1065`) to stamp `[INCOMPLETE]` on truncated bodies (it checks file presence, not body integrity — a truncated `show run` scores "complete").

## Tier 6 — External-inspired, genuinely new, in-doctrine (medium bets)
- **Offline PSIRT/CVE matching from a *bundled* CSAF advisory pack** — match parsed `show version` platform+train against a periodically-refreshed, *bundled* dataset (the live openVuln API is **egress — out of doctrine**; the refresh is a manual human out-of-band step). We have EoL (`eoldb.py`); known-CVE-with-fixed-release is the gap. *(Sources: developer.cisco.com/docs/psirt, CiscoPSIRT/openVulnQuery.)*
- **Capacity headroom** — parse interface utilization + MAC/TCAM/CPU/mem/PoE/licensing from existing `show` output (table-stakes assessment columns; EASY).

## Tier 7 — Breadth (bigger bets; defer unless a client needs it)
- **OpenConfig/gNMI offline reader** — the vendor-neutral channel that makes vendors #6/#7/#8 cheap (highest breadth-leverage remaining; `absolute-universal-roadmap.md` Wave 3).
- Palo Alto (PAN-OS XML) / F5 / Aruba AOS-CX / Nokia SR OS; Azure/GCP cloud breadth.
- **K3 `collection_profiles.py`** — externalize hardcoded `COMMANDS_*` into one declarative table both channels consume.
- **Finish the `main()` strangler (Plan-A #15)** — extract the collect stage (`COLLECT_PARSE…:1772-1810`); the finalize leaf already folded onto `AnalysisContext`. Internal DX.

---

## DATA-GATED — cannot be actioned now (flag for the next real collection)
- **Collect the 50 uncollected DS/CS core switches** — redundancy is currently **UNKNOWN**; the single biggest evidence unlock (memory: `canonical-aj-fleet.md`, `pending-on-new-data.md`).
- **fib #19 multi-VRF** (VRF-keyed `RouteEntry`) — unblocks G2 zonematrix + cross-VRF path asserts.
- Port-security NX-OS un-blinding; BCDOH 9300 `show environment all`; BGP received-prefix depth.
- The three O(N³) perf terms (dependency-map 8.7×, causality-chains 6.5×, failure-impact 5.8×) — need a real 300+ device fleet **or** a synthetic-fleet builder to validate the relief.
- The 91 P2 / 47 P3 Cisco-depth detector items (`universality-gap-register.md`) — data-gated **and** de-prioritized (analysis saturation).

## Deliberately NOT recommended — refuted as already shipped (trust-through-refutation)
`manifest.py` sealed chain-of-custody (roadmap D2, WIRED) · `aclcheck.py` ACL shadow/line-reachability proof
(G1, WIRED) · `assertions.py` checks-as-data + `%` operator (A1/H1, WIRED) · `external_import.py` SoT reconcile
(B, WIRED) · `whatif.py` failure-injection (G4, WIRED) · `path_assertions.py` (G3, WIRED) ·
`feature_compliance.py` (I2, WIRED) · CIS/NIST/PCI/STIG compliance matrix (`US=●`) · config-hygiene
undefined-refs/unused-structures (`build.py:124`) · forwarding loop detection (`fib.py:291`) · golden-drift
base incl. supplied-target + fleet-consensus (`analyze.py:4228`) · citation-grounding demotion (`causal.py`) ·
archreview Availability/SPOF section (`archreview.py:260`). The Claude Design project is **in sync and current**
(verified today) — no re-upload owed.
