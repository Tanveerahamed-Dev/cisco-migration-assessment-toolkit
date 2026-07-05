# MASTER PLAN — the best possible version (2026-07-05)

*Produced by an 18-agent deep analysis (11 repo-mapping agents over the full tree at `ed8bc78`, 5 web-landscape
research agents, 2 docs-digest agents; ~1.6M analysis tokens) cross-validated against every planning doc in the
repo (`IMPROVEMENT_AND_GREENFIELD_PLANS.md`, `docs/next-best-improvements-2026-07-04.md`,
`docs/orchestration-best-roadmap.md`, `docs/absolute-universal-roadmap.md`, `docs/universality-gap-register.md`,
`docs/deliverable-excellence-plan.md`, `docs/universal-best-roadmap.md`), the git history v3.23.169 → v3.26.0 →
main, `CHAT_SUMMARY.md`, and the field data. Every load-bearing claim is grounded in a file/line or a cited web
source. This document does not restate the standing backlog — it validates it, sequences it, and adds what no
existing doc has.*

---

## 0. Verdict

**The engineering is exceptional and the standing thesis is confirmed: the analysis surface is saturated; the
frontier is trust, provability, and execution-grade output.** Since `next-best-improvements-2026-07-04.md` was
written, main has received only two chore commits (`4580a4e`, `ed8bc78`) — **every one of its recommendations is
still open** (verified: no `precert.py`/`attestation.py`/`PARSER_EXAMPLES`/`zonematrix.py`/playwright anywhere on
main). So that doc remains the valid product backlog. What this plan adds:

1. A **secure-and-tidy Day-0 pass** — findings from today's audit that no existing doc records (§2).
2. **Research-enriched upgrades** to the standing backlog items (§3) — each verified against July-2026 state of
   the art (Batfish/Genie/ntc/SuzieQ health, IP Fabric / Forward / NetBrain / Catalyst Center capabilities,
   Cisco AS deliverable standards, NDFC 4.1-era practice).
3. **Genuinely new workstreams** no repo doc proposes (§4): the L2 failover twin, the cutover dry-run simulator,
   the per-VLAN cutover workbook, the doctrine-safe LLM layer, the PIR→ScoringConfig calibration loop, and an
   explorer Playwright smoke gate.
4. The **platform foundation for this new laptop** (§5): dev-environment bootstrap + the Obsidian/Claude/graphify
   "LLM wiki" (Karpathy pattern) with a clean division of labor against the existing graph.
5. A **30/60/90 sequencing** that respects the repo's own load-bearing-order discipline (§6).

---

## 1. State of the project (updated honest scorecard)

**Scale (verified today):** ~65k LOC engine (entry module 2,896 ln + `cisco_toolkit` 44 files / 37,133 ln) ·
canonical explorer template 999,757 B / 10,500 ln / 14 modes · webapp ~3.1k LOC backend + React SPA ·
**1,388 test functions in 125 files** (1,315 engine + 73 webapp) · golden contract = 86 snapshot keys + 62 sheets
· 5,409-node knowledge graph · 13 tags, v3.26.0 current · 303 commits since v3.23.169, single author + agent rig.

**Strengths to preserve (do not regress):** the doctrine moat (read-only / no-egress / coverage-honest abstention
/ proposer ≠ verifier / SSOT federation) is now *mechanically enforced* — doctrine-as-tests
(`test_readonly_and_no_egress.py`), golden shrink-guard (`test_golden_guard.py`), registry conformance gates
(axes / MODES / sections / docs-parity / ssot-registry), executed JS↔Python FIB parity under node, adversarial
redaction corpus, CI × 5 gating jobs + path-filtered webapp CI + tag-release + OIDC publish. The review-release
rhythm (every feature arc followed by an adversarial self-review release) is a genuine competitive advantage —
keep it.

**The 12 ranked problems of `IMPROVEMENT_AND_GREENFIELD_PLANS.md` §1b are now ~90% retired** (verified via
CHANGELOG v3.24.0–v3.26.0 and code). What remains open from that list: god-functions (#5 — `main()` strangler
Stage-3 done, collect-stage extraction Plan-A #15 remainder open), explorer executed-JS coverage beyond FIB (#7),
O(N³) perf terms (#6 — data-gated), KB staleness cadence (#11 — partially: eoldb vintage guard shipped).

---

## 2. Part I — SECURE & TIDY (Day 0–2; do before any feature work)

Findings from today's audit. None of these are in any existing planning doc.

### 2.1 Confidentiality (client data) — highest priority
| # | Finding | Action |
|---|---|---|
| S1 | **`devices.json` holds one shared cleartext SSH credential for all 303 devices** (verified: 1 distinct username, 1 distinct password, `password_env` used by 0 entries) — sitting unencrypted in `Desktop\Enhancements` on both C: and the D: copy | Convert to `password_env`/`$CISCO_PASS` (the engine's documented default since v3.24.0); **rotate the fleet credential** (it has lived in plaintext on ≥2 machines); delete or scrub the D:\ duplicate |
| S2 | Working tree holds identifiable client evidence: 2 collection dirs (304 device dirs; 106 configs with `snmp-server community`, tacacs/radius `key 7` lines), 64 MB snapshot, 19.5 MB explorer, `topology.dot/.mmd` with real `*.broadcast.ajmn` hostnames, Syntys BOQ w/ a real Cisco sales order | Verified all are gitignored and **never committed** (`git log --all` sweep clean). Keep it that way; run `--redact-collection` once the AJ analysis is final; consider BitLocker on this laptop (client data at rest) |
| S3 | `requirements.aj.json` (names the AJMN engagement + SDD architecture) and `CHAT_SUMMARY.md` ARE tracked and pushed to GitHub | **Verify the GitHub repo is Private** (Settings → visibility). If it was ever public, treat S1's credential as burned regardless of rotation |
| S4 | `~$Syntys_BOQ.xlsx` (Excel owner-lock, leaks last-editor identity) is untracked and NOT matched by the `Syntys_*` gitignore rule (leading `~$`) | Add `~$*` to `.gitignore` |
| S5 | One documented egress incident: `raw/example_com.md` (graphify web-capture test) + `.gstack/browse-audit.jsonl` (headless-browser side-project use) | Benign, but delete `raw/` and note the lesson: the no-egress doctrine held for the *product*; keep tool egress out of the repo workspace |

### 2.2 Repo hygiene
| # | Finding | Action |
|---|---|---|
| H1 | **`feat/design-sync-assesshub` is the only real unmerged work in the repo** (5 commits: the entire 16-component `.design-sync/` library, conventions.md, NOTES.md) — exactly what next-best Tier-4 "Phase 0" asks to commit | Merge it. Trivial (touches only `.design-sync/`) |
| H2 | 15 dead local branches (worktree-*, claude/*, feat/plan-a-tier2 — all verified content-on-main) + `.claude/worktrees/` (~146 MB of full repo copies) | Delete branches; prune worktrees |
| H3 | Repo-root `blast_radius_explorer.html` is **2 releases stale** (12 modes, no 3D) vs the canonical `cisco_toolkit/` copy — a wrong-file-edit trap (`html.py:778-781` prefers the package copy) | Delete the root copy from disk (it is gitignored; the engine falls back correctly) |
| H4 | `CLAUDE.md` stale facts: "385 tests" (reality ~1,388 defs), "~5147 nodes" (now 5,409), "29 architecture classes" (registry says 40 detectors / 23 classes — the docs themselves disagree) | Update counts once; where a count has a mechanical SSOT (registry, pytest), state the *pointer*, not the number — per your own SSOT law |
| H5 | `graphify-out/.graphify_python` pins the OLD laptop's interpreter (`C:\Users\SOOQ ELASER\...`); python isn't installed here yet | Re-pin after §5.1 bootstrap; then `python -m graphify update .` (respect the shrink guard — no `--force`) |
| H6 | Stale `cisco_migration_assessment_toolkit.egg-info` (3.23.142) | Regenerated on next `pip install -e .` — no action beyond §5.1 |
| H7 | `webapp/frontend/dist` is committed and can silently go stale vs `src/` (nothing pins build freshness) | Add a CI check (dist build hash vs source) or stop committing dist and build in CI |

---

## 3. Part II — THE PRODUCT FRONTIER (the standing backlog, validated & enriched)

The three do-first items from 2026-07-04 stand. Research upgrades each:

### 3.1 The Verification-Deliverable trio *(effort M each; the clearest next build — convergent in 3 docs)*
- **`precert.py` — Pre-Change Validation Certificate** (roadmap C1): binds `fib.reachability_delta`
  (`cisco_toolkit/fib.py:424`) to a candidate change. *Enrichment:* Forward Networks announced exactly this
  ("Forward Predict", GA fall 2026) and NDI ships "Pre-Change Analysis" — your offline one-pager beats both on
  air-gapped engagements. Model the certificate wording on Forward's "network equivalency" framing: *flows
  preserved / segmentation invariant holds / N flows change (each cited old→new) / M inconclusive (named blind
  spot)*.
- **`attestation.py` — zero-egress attestation panel** (roadmap D3): re-derive read-only/no-egress/no-LLM at
  build time using the same AST/regex as `tests/test_readonly_and_no_egress.py` → falsifiable Trust panel on
  explorer + workbook cover + HLD front matter. No competitor can make this claim as a *proof*.
- **Offline NRFU verification-command export** (frontier `:233`): *enrichment from Cisco AS practice research:*
  structure it as the canonical **four-phase NRFU** (Phase I device-level → II logical/connectivity → III
  service/traffic → IV application), test-case IDs, per-site vs end-to-end split, **expected values pre-filled
  from the assessment snapshot** so the post-check diff is assertive, not informational. Optional companion
  export: a pyATS testbed + snapshot-job skeleton (generate-only — pyATS remains a rejected runtime dep;
  Windows-unsupported, verified again July 2026).

### 3.2 The Playwright design gate *(effort M; the only quality surface with no ratchet)*
`.ds-sync/` already vendors playwright 1.58 + chromium and a render-check harness; `ds-bundle/_ds_sync.json`
already carries per-component render hashes. The documented trap (NOTES.md:147-155): **render hashes are blind to
CSS-only changes** — the exact class that shipped broken glass CSS for a day. Screenshot-diff CI over the 16
synced components closes precisely that hole. Do after H1 (the library must live on main first).
*Addition (new, §4.6):* the same Playwright investment should also smoke the **offline explorer** — open the
built HTML, click all 14 modes, assert 0 console errors — automating the manual "live-verified, 0 console
errors" ritual your changelog performs every release.

### 3.3 Real-line fixtures — kill the false-health bug-class at its root *(effort S+M)*
- **K2 `PARSER_EXAMPLES` registry**: lift the real AJ lines already in `tests/test_audit5_parse_fidelity.py`
  into a per-parser registry + one test that replays every parser against its committed real line.
- **Redacted real-world golden**: promote one redacted real capture to a golden so member-down /
  uncollected-in-group / ACL-verdict paths are exercised by *real* structure.
- *Enrichments from research:* (a) **genieparser's repo is Apache-2.0 and contains thousands of real
  show-command fixtures** — harvest per-command real lines for platforms the AJ fleet lacks; (b) **containerlab
  v0.76 (healthy, Nokia-backed) as a fixture factory** — cat9kv/n9kv images generate fresh real output for new
  parser work (dev/CI only, Linux/WSL2); (c) keep ntc-templates strictly as the CI referee (its silent-partial-
  success failure mode is the opposite of the honesty doctrine — verified unchanged in 9.1.0).

### 3.4 Assurance-lane depth (Tier 2 of the standing doc — all verified open)
MTU/jumbo-blackhole verdict along the FIB path · return-path/RPF asymmetry verdict · ECMP multipath-consistency
· H2 `for_each` assertion grammar · `zonematrix.py` (stays **blocked** on fib #19 multi-VRF — data-gated).
*Sequencing note:* do MTU first — the EVPN research is unambiguous that a 1500-byte underlay "drops VXLAN
silently and mimics random loss," which makes the MTU verdict the single most engagement-relevant missing check
for the AJMN target fabric.

### 3.5 Coverage-honesty as a queryable schema (Tier 3 — the moat, deepened)
J1 per-detector `{healthy_value, threshold, cited_fields}` descriptors · J3 `describe_schema(snap)` census ·
J2 `ssot.fact_lineage()` attribute-level provenance · I1 `compute_json_conformance` · I3 Day-1-vs-Day-2 drift
history over `--compare`/`--trend`.

### 3.6 Deliverable Excellence P2/P3 + the Cisco-AS gap list (research-verified additions)
The open DE items stand (ops Backup-&-Recovery/Known-Issues; mop BLUF + per-§ rollback booleans + comms plan;
crd Constraints/Out-of-scope). Research against Cisco AS standards adds these **concrete generator upgrades**:
1. **Split HLD from LLD and make the LLD CLI-level** (per-device hostnames/ASNs/loopbacks/VTEP addressing,
   VRF/VNI/VLAN tables, exact NX-OS stanzas) + a **scale-validation table** (VNIs/SVIs/MAC/ARP/TCAM vs verified
   platform limits) — "assessments that skip scale checks are the classic audit finding."
2. **CRD → Requirements Traceability Matrix**: numbered requirements traced requirement → HLD § → LLD object →
   MOP step → NRFU test case. The engagement doc already has gates; this closes the chain.
3. **Quantified rollback triggers in the MOP** ("if >0.1% validation failures / no convergence in N min"), named
   roles, per-step expected output — overlaps roadmap C2/C3; land them together.
4. **NDFC 4.1-era alignment** in ops/LLD: brownfield-import rules (Preserve-Config, fabric-template values that
   must match existing: ASN/underlay/replication/vPC domains/resource ranges), config-compliance discipline
   (no out-of-band CLI once managed), change-control tickets, NDI pre-change/delta hooks. **Directly serves the
   AJMN engagement** (NDFC-managed NX-OS EVPN Multi-Site per `requirements.aj.json`).
5. **Closure artifacts**: as-built regeneration (post-cutover re-collection diffed against LLD intent), exception
   report, lessons-learned, bake-period monitoring plan — how AS formally closes engagements.

### 3.7 Tier 5–7 (unchanged, ordered)
K4 corpus finish · ntc referee to ~15–20 cmds · CLI-side `_reconcile_gate` parity (webapp-only today,
`webapp/backend/deliverables.py:24-37` — and note it is *advisory* even there; consider surfacing violations to
the downloading user, not just the server log) · K1 body-integrity `[INCOMPLETE]` stamps · bundled CSAF/PSIRT
pack (precedent: IP Fabric ships CVE-Excel from offline NVD matching; keep the refresh manual/out-of-band) ·
capacity headroom columns · then breadth only when a client needs it (OpenConfig/gNMI first, K3
collection-profiles, PAN-OS/F5/Aruba).

### 3.8 DATA-GATED (unchanged; flag for the next field access)
Collect the **50 uncollected DS/CS cores** — still the single biggest evidence unlock (redundancy on the AJ
fleet is UNKNOWN; every uplink points at an uncollected tier) · fib #19 multi-VRF · O(N³) perf validation at
600/1000 via `tests/perf_scale.py` · port-security NX-OS un-blinding · BGP received-prefix depth.

---

## 4. Part III — NEW WORKSTREAMS (in no existing doc)

### 4.1 The L2 failover twin *(new; value high, effort M; a real market gap)*
Batfish and Forward are famously L3-centric; **STP/FHRP failover is deterministically recomputable from data you
already collect** (bridge priorities, port costs, link state, FHRP priorities/preempt). Extend `whatif.py`:
given a failed root bridge or uplink, re-run the 802.1w election and tree computation and the FHRP failover
mechanics → *"if the STP root dies, the new root is X (won by default election — the smell you already flag),
these ports flip to forwarding, and this FHRP pair goes split-brain because preempt is off."* Fits the doctrine
(pure static compute), reuses `stp_roots`/`fhrp`/`link_phy`, and no competitor ships it.

### 4.2 The cutover dry-run simulator *(new; the highest-billable composition)*
A MOP wave is an ordered list of graph mutations (shut link → move FHRP priority → re-home uplink → …). Apply
the sequence step-by-step on a snapshot copy; at each step run the §4.1 recomputation + `fib.reachability_delta`
+ the four-way flow classification (unaffected / ECMP-survives / protocol-backup-exists / stranded) → a
**per-step impact report**: *"after step 3, VLAN 40 loses its only path until step 5."* This is CrystalNet's
migration-rehearsal use case at graph fidelity — and it turns the MOP from a document into a *simulated*
document. Compose from `whatif.py` + `fib.py` + move-group data; surface per-wave in MOP §s and the explorer
Waves mode.

### 4.3 The per-VLAN cutover workbook *(new sheet; effort S; "the single most valuable artifact")*
One row per VLAN/subnet, generated from data already in the snapshot: VLAN→VNI mapping, current STP root,
HSRP group/VIP/priorities/virtual-MAC, SVI location, attached endpoints + criticality tier, dependencies
(firewall/LB/WAN adjacency, multicast, DHCP relay), assigned wave, window, rollback owner (blank for the human).
Every column exists in `stp_roots`/`fhrp`/`endpoint_identity`/`application_intelligence`/`move_groups` — this is
one `excel.py` sheet + a MOP appendix away, and it is what cutover teams actually run the window from.

### 4.4 The doctrine-safe LLM layer *(new; "offline first, API later" — this is the 'later' design)*
The July-2026 field has converged on your architecture: deterministic facts, LLM only for language (Selector's
NLM translates NL→queries; Cisco/Juniper assistants are skins over deterministic backends; NetConfEval shows
LLMs fail as analyzers). Three additions, strictly opt-in, engine 100% functional without them:
1. **Extend the shipped MCP server** (`cisco_toolkit/mcp_server.py`, 7 tools) — add `run_intent` (bridge the
   36 Ask-the-Engineer intents), `get_finding(id)`, `whatif(node|link)`, `precert(change)` once 3.1 lands.
   Read-only stdio stays; this makes Claude Desktop/Code a first-class front-end with zero egress *from the
   tool*. This is the highest-leverage AI move and it's ~80% shipped already.
2. **LLM-written executive narrative** behind `--ai-narrative` (or an AssessHub toggle): the LLM sees *finding
   objects only* (never raw configs), under a "no new facts, cite finding IDs" contract; output is
   deterministically validated per-claim (every number cross-checked, every claim mapped to a finding ID;
   regenerate-or-fallback to the templated brief). Label it "AI-generated summary of deterministic findings."
3. **NL→intent translation** in front of the chat (LLM chooses the intent + params against the existing schema,
   echoes its interpretation, never authors the answer; keyword matcher remains the offline fallback).

### 4.5 The calibration loop *(new; closes your oldest known limitation)*
"Weights are a defensible default, not calibrated" has been the standing caveat since V3.23.0. You now own the
missing half: **AssessHub war-room executions + PIR records are labeled outcomes** (what actually broke/slipped
per wave). Add a `calibration` report that joins pre-cutover verdicts (readiness/health/risk-index) against
as-executed outcomes (deviation scribe log, step failures, closeout verdicts) per campaign → over engagements,
this becomes the labelled dataset that tunes `ScoringConfig` empirically. Nobody in the market closes this loop
offline.

### 4.6 Verification gaps worth closing *(from today's test-suite audit)*
- **Explorer Playwright smoke** (see 3.2): 14 modes × 0-console-errors on the real built HTML — automates the
  manual release ritual. The other ~12 modes' JS currently has zero executed tests (only FIB has parity).
- **Windows CI is a single cell** (py3.12) while goldens are Windows-generated — add py3.10 + py3.14 Windows
  cells (drift there is invisible today).
- **Perf budget gate**: `.phase_timings.json` is asserted for shape only — add a soft budget vs a committed
  baseline so a 10× phase regression fails loudly before an engagement.
- **Optional-dep blindness**: the whole DOCX/PPTX family silently `importorskip`s on minimal envs; add one CI
  assertion that the docx/pptx suites *ran* in the full-matrix job.
- **`html.py` has no dedicated test file** (only pipeline/CSP/redaction coverage) — the slimming logic
  (`_slim_for_embed`) and the last-occurrence snapshot-slot replacement deserve direct tests.
- Later/slack: touch-pointer events for the 2D explorer canvas (tablet walkthroughs); keyboard nav for 3D.

### 4.7 Positioning & distribution *(decide deliberately, not by default)*
- **PyPI**: publish.yml is ready (OIDC), but LICENSE is all-rights-reserved — publishing grants no rights and
  invites confusion. Either keep GitHub-releases-only (recommended while it's a consulting edge) or pick a real
  license strategy first.
- **Public demo**: the sample fleet is synthetic by construction — a GitHub Pages static host of the demo
  explorer + the promo brief you already wrote (`docs/promo-video-briefs.md`) is a zero-risk portfolio asset.
- **Economics context** (research): commercial per-device pricing runs ~$54–$193/device/year (NetBrain leak,
  Catalyst list) — a free offline engagement tool is a structural differentiator for consulting work; the trust
  trio (3.1) is what makes that credible to a client's change board.

---

## 5. Part IV — PLATFORM: this laptop + the LLM wiki

### 5.1 New-laptop bootstrap (blocking almost everything above)
Current state: git 2.55 ✔ · **no real Python** (Store stub) · no Node · no gh · no git identity · Desktop is
NOT OneDrive-redirected (verified) · winget 1.29 ✔.
```
winget install Python.Python.3.12          # 3.12: matches CI matrix middle; 3.14 also tested
winget install OpenJS.NodeJS.LTS           # node 20+: webapp build + JS-parity gate + .ds-sync
winget install GitHub.cli                  # gh: PR workflow the repo's process depends on
winget install Obsidian.Obsidian           # §5.2
git config --global user.name  "Tanveerahamed-Dev"
git config --global user.email "150244631+Tanveerahamed-Dev@users.noreply.github.com"
gh auth login
cd C:\Users\jajch\Desktop\Enhancements
python -m pip install -e ".[dev,docx,pptx,mcp]" && pip install -r webapp/requirements.txt
python -m pytest -q                        # expect ~1,390+ green — the proof this machine is engagement-ready
# graphify: reinstall the tool, fix graphify-out/.graphify_python, then: python -m graphify update .
cd webapp/frontend && npm ci && npm run build
```
Then re-verify the two Stop hooks fire (verify-green, graph-refresh) — they are the safety net everything else
assumes.

### 5.2 The LLM wiki (Karpathy pattern: raw/ → wiki/ → schema; ingest/query/lint)
**Two stores, one graph, one contract each — never merged** (this is your own SSOT law applied to knowledge):

| | Repo (`Enhancements`) — *engagement/code knowledge* | Vault (`C:\Vaults\brain`) — *career/domain knowledge* |
|---|---|---|
| Owner | graphify (AST, regenerable) + `docs/` | Obsidian + Claude Code (curated, compounding) |
| Answers | "what calls X / what breaks if I edit this parser / why did we decide Y here" | "what do I know about EVPN migrations / vendor X / client-pattern Z" |
| Already exists | ✔ (5,409 nodes, hooks, MCP) | ✗ — create |

- **Repo side (small adds):** `docs/decisions/` — one ADR-style page per engineering decision (`related:` links
  name code symbols so `graphify explain` finds them; register new fact-owners in `docs/ssot.md` per Law 1) and
  `docs/log.md` (append-only session log — CHAT_SUMMARY.md's successor, one line per session).
- **Vault side (new):** `C:\Vaults\brain\` with `CLAUDE.md` (the contract: frontmatter schema
  `type/status/updated/related/cluster/confidence`, tree-over-cluster linking, **never write raw/, never delete
  (deprecate), NO client identifiers ever — anonymize to "client-A" pattern pages**, "for engine code facts:
  don't restate — cite the symbol and query graphify in that repo"); `raw/` (clipped articles, Cisco docs, RFCs
  — immutable); `wiki/` (`index.md`, `log.md`, `hot.md` + `concepts/ entities/ sources/ syntheses/`); `daily/`
  (inbox only, compiled weekly); `.claude/skills/` → `/ingest`, `/lint` (weekly: contradictions, orphans, stale),
  `/close` (update hot.md + log.md).
- **Tooling:** Claude Code with the vault as working dir (no MCP needed); Obsidian as the reader/graph view;
  plugins: Dataview, Templater, obsidian-git (auto-commit + commit-per-ingest; private remote); `.gitattributes`
  `*.md text eol=lf`; exclude `.claude/` from Obsidian's graph.
- **The bridge (one-way, sanitized):** engagement *lessons* (e.g. "bare `show logging` on NX-OS is a
  false-health trap") get promoted into `wiki/concepts/` with client identity stripped; raw evidence never
  crosses. Grant Claude Cowork/Desktop the vault folder only — **never the Enhancements repo** (client data).
- **Primary sources for the pattern:** Karpathy's llm-wiki gist
  (gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) + the Apr-2026 "LLM Knowledge Bases" post — the
  three operations (Ingest/Query/Lint) and the bookkeeping insight ("the tedious part is the bookkeeping") are
  the design.

---

## 6. Sequencing — 30/60/90 (each step golden-safe; order is load-bearing)

**Week 1 — foundation:** §2 secure-and-tidy (S1–S5, H1–H5) → §5.1 bootstrap → suite green on this machine →
merge design-sync (H1) → start `precert.py`.
**Weeks 2–4 — trust & gates:** finish the trio (3.1) → Playwright design gate + explorer smoke (3.2, 4.6) →
K2 real-line registry + redacted golden (3.3) → per-VLAN cutover workbook (4.3) → MCP server extension (4.4.1).
Cut **v3.27.0** ("the trust release").
**Days 30–60 — assurance depth:** MTU verdict → RPF asymmetry → ECMP (3.4) → L2 failover twin (4.1) → cutover
dry-run simulator (4.2) → DE-01 P2/P3 + AS-gap items 1–3 (3.6) → LLM narrative + NL-intent opt-ins (4.4.2/3).
Cut **v3.28.0** ("the rehearsal release").
**Days 60–90 — schema & robustness:** J1/J2/J3 + I1 + I3 (3.5) → Tier-5 items (3.7) → CSAF pack + capacity
headroom → calibration loop v1 (4.5) → CI gaps (4.6). Cut **v3.29.0**.
**Standing, opportunity-driven:** the DS/CS 50-device re-collection (unblocks fib #19 → zonematrix, O(N³)
validation, W3-3, K1-on-real — the biggest single unlock in the whole plan); vendor breadth per client demand;
vault lint cadence weekly.

## 7. Traps (their list, still binding + three new)
No rewrite · ntc-templates never the default lane · no mass excel rewrite · no mutation-testing priority ·
**no DuckDB** (egress autoloader) — all reaffirmed. New: **don't let the vault duplicate graphify** (second
rotting source of truth); **don't publish to PyPI under all-rights-reserved by reflex**; **don't adopt
scrapli 2.0 (year-long RC churn) or Nornir (stewardship 3 days old)** — netmiko 4.7 remains correct; Genie/pyATS
stays Windows-fatal as a runtime dep (re-verified July 2026).

---

*Cross-references: standing backlog = `docs/next-best-improvements-2026-07-04.md` (all items open as of
`ed8bc78`); doctrine = `CLAUDE.md` + `docs/architecture-no-egress.md`; release flow = `RELEASING.md`. Research
sources are cited inline in the session that produced this plan.*
