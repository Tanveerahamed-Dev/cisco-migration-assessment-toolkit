# Promo / Demo Video Briefs — Cisco Migration Assessment Toolkit

> Session archive of every video brief produced, the production notes, and the resume state.
> Render path: paste a brief into **Claude.ai web/desktop** (the hosted HyperFrames connector is
> blocked inside Claude Code/CLI; it works from a chat client and costs no Claude Code quota).
> For TRUE animated/character footage, use this as a storyboard for Sora / Runway / Kling / Luma.

---

## ★ PRIMARY — 5-minute AD FOR NETWORK ENGINEERS ("Stop Migrating Blind")

**Audience:** brownfield network engineers / architects / NOC leads doing migrations & assessments.
**Tone:** dark NOC aesthetic, real CLI, monospace, cyan/amber, tense → confident. Lead with pain,
sell the technical moat, end on proof. The emotional core is **FALSE HEALTH** ("the network lies");
the competitive kill is **grounded & air-gapped vs cloud AI that hallucinates** (the anti-SmartyMe /
anti-NotebookLM angle).

### Full script (VO · ON-screen · VIS)

**ACT 1 — THE 2 AM HOOK (0:00–0:30)**
VIS: dark NOC; a terminal; clock reads 02:14; a maintenance-window timer counts down 01:28:00; `show`
output scrolls; a chat ping — "VLAN 30 is down??".
VO (tense, real): "It's 2 AM. Your maintenance window closes in ninety minutes. You just cut over the
distribution layer — and a VLAN just became a black hole. Nobody documented that it had a single
uplink. Sound familiar?"
ON: "02:14 · window closing · VLAN 30: unreachable."

**ACT 1b — THE PAIN STACK (0:30–1:05)**
VIS: a wall of `show running-config` / `show cdp neighbors` / `show ip route` / `show vpc` across
hundreds of devices; a half-filled Excel inventory; a 3-year-stale Visio.
VO: "You inherited three hundred switches. No diagram. No source of truth. The last engineer is gone.
And you have to migrate it — without breaking a thing. So you scrape `show` output by hand, build
inventory in a spreadsheet, guess the topology, and pray the redundancy is real."
ON: "300 devices · no diagram · no SSOT · cutover in 3 weeks."
★ KILLER LINE — VO: "And here's the part nobody admits: the network LIES to you. `show logging` comes
back clean on a box that's quietly failing. The 'redundant' vPC pair? One leg's been down for months.
You find out at 2 AM."
VIS: a `show vpc` table — a row flips red `down*`; `show logging` returns clean while an error counter
silently climbs. ON: "false health — the lie that ends the window."

**ACT 2 — THE TURN (1:05–1:30)**
VO: "What if a senior network architect read every device, rebuilt the truth, modeled the blast
radius, and rehearsed the cutover — and refused to guess, or lie? Offline. Read-only. On YOUR network."
VIS: a calm cyan system boots; the chaos resolves into a clean, lit topology.
ON: "what if it just… told you the truth?"

**ACT 2b — INTRO (1:30–1:45)**
VO: "This is the Cisco Migration Assessment Toolkit. An automated senior network engineer. No cloud.
No egress. No hallucination. It runs air-gapped, it never touches a device, and it shows its work."
ON: "OFFLINE · READ-ONLY · EVIDENCE-GROUNDED."

**ACT 3 — HOW IT SOLVES YOUR PROBLEMS (1:45–3:50)** — problem → feature, in NE language
1) "You can't see the current state." VO: "Feed it the `show` output you already collect — IOS,
   IOS-XE, NX-OS, IOS-XR, plus Arista, Juniper, Fortinet, ACI, SD-WAN. It rebuilds the live topology,
   the device inventory, the VLAN and endpoint census — every MAC fingerprinted to a vendor and a role."
   VIS: show-output → topology + inventory + endpoint census assemble. ON: "topology + inventory +
   5,000+ endpoints, reconstructed."
2) "Will this cutover break reachability?" VO: "Ask it: can A still reach B after I pull this box? It
   runs a native RIB-to-FIB what-if — an offline Batfish — and answers before you touch a thing.
   VRF-aware. ACL-aware. NAT and MTU aware." VIS: a path traces; a matrix cell flips BLOCKED on an ACL
   deny. ON: "RIB→FIB reachability what-if — offline Batfish-peer."
3) "What's the blast radius?" VO: "Pull any switch in simulation — see exactly which endpoints strand,
   which VLANs partition, which neighborhoods go dark." VIS: blast-radius ripple + stranded count.
   ON: "blast radius · stranded endpoints · per device."
4) "Is the redundancy REAL?" VO: "It checks the redundancy that only exists on the diagram — vPC
   health, FHRP consistency, single-gateway SPOFs, accidental STP roots. On one real fleet it caught
   six hundred and sixty-eight down vPC legs." VIS: vPC down-legs glow; an FHRP gap; a lone gateway.
   ON: "668 down vPC legs caught · the redundancy that wasn't."
5) "Am I exposed?" VO: "Every device screened for end-of-life, last-day-of-support, and software-
   advisory exposure — and audited against CIS hardening." VIS: an EoL timeline + a CIS pass/fail.
   ON: "EoL / LDoS · PSIRT surface · CIS hardening."
6) ★ THE MOAT — VO: "But here's the one thing nothing else does: it refuses to fake health. If it
   didn't collect your core, it doesn't paint it green — it marks it UNKNOWN and tells you redundancy
   is unverified. Not observed is never 'healthy.' It's the only tool honest about what it can't see."
   VIS: a core region stays grey, tagged "UNASSESSED — not 'low risk'." ON: "coverage-honest — it never
   fakes green."
7) "Prove it to the CAB." VO: "It sequences the migration into move-groups, writes the MOP with
   rollback, builds the NRFU test, and proves the cutover landed clean with a pre/post diff." VIS:
   move-groups + a MOP doc + a pre/post diff snapping to PASS. ON: "move-groups · MOP+rollback · NRFU ·
   pre/post cutover diff."

**ACT 4 — THE OUTPUT (3:50–4:20)**
VO: "One run, and out comes the whole package: a workbook; an interactive 3D blast-radius explorer you
fly through — with a hop-by-hop flow simulator and an offline 'ask the engineer' chat; a runbook; HLD
and LLD; MOP; CRD; engagement plan; architecture review; ops handbook; and a board-ready deck. Plus
AssessHub — a live war-room for the whole campaign." VIS: deliverable cards fan; the explorer 3D
topology rotates; the AssessHub dashboard. ON: "10+ deliverables · 3D explorer · offline Ask-the-
Engineer · AssessHub war-room."

**ACT 5 — THE COMPETITIVE KILL (4:20–4:40)** — the anti-cloud-AI / anti-SmartyMe / anti-NotebookLM beat
VO: "The AI tools want your configs in their cloud — and they make things up. This one runs on YOUR
air-gapped network, and cites the exact `show`-command line behind every single claim. Grounded.
Auditable. It would rather say 'I don't know' than lie to you." VIS: a finding card expands to its
evidence line; a cloud icon with a red strike; a hallucinated answer crossed out. ON: "grounded, not
generated · cites every claim · it won't hallucinate."

**ACT 6 — PROOF + CLOSE (4:40–5:00)**
VO: "Proven on a live broadcast network — over three hundred devices, five thousand endpoints. Built
test-first. Hardened by four adversarial audit waves and sixty-two fixed defects. Stop migrating
blind." VIS: real numbers tick; the full lit topology, calm, grey-unknown still marked.
ON: "300+ devices · 5,127 endpoints · 385+ tests · 4 audit waves."
VO: "The senior architect that never sleeps, never guesses, and never lies. The Cisco Migration
Assessment Toolkit." ON: logo / tagline "See the whole network. Trust the plan." → CTA.

### Paste-ready HyperFrames prompt (5-min NE ad)
```
Create a hard-hitting ~5-minute ad aimed at NETWORK ENGINEERS for "Cisco Migration Assessment Toolkit —
the automated senior network engineer." Dark network-operations-center aesthetic: real CLI / `show`
output, monospace data, topology graphs, dashboards. Palette near-black/navy, electric-cyan accent,
amber for risk/down, muted grey for "unknown." Tense → confident. Captions = short phrases + big
numbers only. Lead with PAIN, sell the TECHNICAL moat, end on PROOF. Scenes:
1) 2AM HOOK — clock 02:14, maintenance window timer counting down, `show` output scrolling, "VLAN 30 is
   down??". VO: "It's 2 AM, your window closes in 90 minutes, you just cut over distribution and a VLAN
   is a black hole — nobody documented its single uplink."
2) PAIN STACK — walls of show-output across 300 devices, a half-built Excel inventory, a stale Visio.
   VO: "300 switches, no diagram, no source of truth, the last engineer gone — you scrape show output by
   hand and pray the redundancy is real." KILLER LINE: "the network LIES — `show logging` is clean on a
   failing box, the 'redundant' vPC pair has a leg down for months." Show a vPC table flipping red down*.
3) THE TURN — a calm cyan system resolves the chaos into a clean lit topology. VO: "What if a senior
   architect read every device, rebuilt the truth, modeled blast radius, rehearsed the cutover — offline,
   read-only, and refused to guess or lie."
4) INTRO — "OFFLINE · READ-ONLY · EVIDENCE-GROUNDED. No cloud, no egress, no hallucination."
5) SOLUTIONS (problem→feature, fast): rebuilds topology+inventory+5,000 endpoints from IOS/IOS-XE/NX-OS/
   IOS-XR + Arista/Juniper/Fortinet/ACI/SD-WAN; a native RIB→FIB reachability what-if (offline Batfish:
   "can A still reach B after I pull this box" — VRF/ACL/NAT/MTU aware, show a matrix cell flip BLOCKED on
   an ACL deny); blast-radius sim (stranded endpoints when a switch drops); real-redundancy checks (vPC
   health — "668 down vPC legs caught", FHRP, single-gateway SPOFs, accidental STP roots); EoL/LDoS +
   PSIRT + CIS hardening.
6) THE MOAT — coverage-honest: an uncollected core stays GREY, tagged "UNASSESSED — not low-risk." VO:
   "It refuses to fake health. Not observed is never healthy. The only tool honest about what it can't see."
7) PROVE IT — move-groups, MOP+rollback, NRFU, a pre/post cutover diff snapping to PASS.
8) OUTPUT — 10+ deliverables fan out (workbook, 3D blast-radius explorer w/ flow simulator + offline
   Ask-the-Engineer chat, runbook, HLD/LLD, MOP, CRD, engagement plan, arch review, ops handbook, exec
   deck) + AssessHub war-room (FastAPI+React).
9) COMPETITIVE KILL — "Cloud AI tools want your configs in their cloud and they hallucinate. This runs on
   YOUR air-gapped network and cites the exact show-command line for every claim. Grounded, not generated."
   Show a finding expanding to its evidence line; a cloud icon struck out.
10) PROOF + CLOSE — "300+ devices · 5,127 endpoints · 385+ tests · 4 audit waves · 62 defects fixed."
    Tagline "See the whole network. Trust the plan."
Key numbers on screen: "300 devices", "5,127 endpoints", "668 down vPC legs", "offline Batfish",
"0 device writes", "no egress", "cites every claim".
```

---

## ★ 60-SECOND LINKEDIN TEASER ("Stop Migrating Blind")

**Built for muted autoplay** — on-screen captions carry the story without sound; hook in <3s; one CTA.
Cut from the 5-min ad: 2AM hook → false health → offline moat → "cites every claim" → proof → CTA.

| t | ON-SCREEN (carries it muted) | VO | VIS |
|---|---|---|---|
| 0:00 | "It's 2 AM. The window closes in 90 minutes." | "It's 2 AM. Your maintenance window closes in ninety minutes—" | clock 02:14; window timer bleeding down; `show` output scroll; ping "VLAN 30 down??" |
| 0:03 | "You just stranded a VLAN. Nobody documented its single uplink." | "—and you just stranded a VLAN nobody told you had a single uplink." | a topology; one VLAN goes dark |
| 0:08 | "300 switches. No diagram. No source of truth." | "Three hundred switches. No diagram. No source of truth." | walls of show-output; stale Visio; half-built Excel |
| 0:14 | "And the network LIES. 'Redundant' pair — one leg down for months." | "And the network lies to you. The 'redundant' pair? One leg's been down for months." | `show logging` clean while error counter climbs; vPC row flips red `down*` |
| 0:20 | "Meet your automated senior network engineer." | "So we built the senior architect that reads every device and refuses to guess." | calm cyan system resolves chaos into a clean lit topology |
| 0:26 | "Offline. Read-only. No cloud. No egress." | "Offline. Read-only. It never touches a device." | padlock + air-gap badge |
| 0:32 | "Reachability what-if BEFORE you cut over." → "668 down vPC legs caught." → "Unknown stays UNKNOWN." | "It runs an offline reachability what-if before you touch anything, finds the redundancy that only exists on the diagram — and refuses to fake health." | RIB→FIB path trace + matrix cell BLOCKED; blast-radius ripple; vPC down-legs; a grey uncollected core |
| 0:42 | "Cloud AI hallucinates. This cites the `show`-line for every claim." | "Cloud tools hallucinate. This one cites the exact show-command line behind every claim." | a finding expands to its evidence line; a cloud icon struck out |
| 0:50 | "300+ devices · 5,127 endpoints · proven." | "Proven on a live broadcast network — three hundred devices, five thousand endpoints." | numbers tick up |
| 0:56 | "Stop migrating blind. → See the whole network. Trust the plan." | "Stop migrating blind." | full lit topology, grey-unknown still marked → logo |

### Paste-ready HyperFrames prompt (60s teaser)
```
Create a punchy 60-second teaser for LinkedIn (built for MUTED autoplay — large on-screen captions
carry the story, hook in the first 3 seconds) for "Cisco Migration Assessment Toolkit — the automated
senior network engineer." Dark NOC aesthetic, real CLI / `show` output, monospace, electric-cyan accent,
amber for risk/down, grey for unknown. Fast cuts. Beats:
1) (0–3s) HOOK: clock 02:14, a maintenance-window timer bleeding down, show output scrolling, "VLAN 30
   down??". Caption: "It's 2 AM. The window closes in 90 minutes."
2) (3–8s) caption "You just stranded a VLAN — nobody documented its single uplink"; one VLAN goes dark.
3) (8–14s) walls of show-output, a stale Visio, a half-built Excel. Caption "300 switches. No diagram.
   No source of truth."
4) (14–20s) FALSE HEALTH: `show logging` clean while an error counter climbs; a vPC row flips red down*.
   Caption "And the network LIES — the 'redundant' pair has a leg down for months."
5) (20–26s) a calm cyan system resolves the chaos into a clean lit topology. Caption "Meet your
   automated senior network engineer."
6) (26–32s) caption "Offline. Read-only. No cloud. No egress."
7) (32–42s) fast montage: a RIB→FIB reachability path trace + a matrix cell flips BLOCKED; a blast-radius
   ripple; vPC down-legs light up; an uncollected core stays GREY tagged UNKNOWN. Rapid captions:
   "Reachability what-if before you cut over" → "668 down vPC legs caught" → "Unknown stays UNKNOWN."
8) (42–50s) a finding expands to its `show`-command evidence line; a cloud icon struck out. Caption
   "Cloud AI hallucinates. This cites the show-line for every claim."
9) (50–56s) numbers tick: caption "300+ devices · 5,127 endpoints · proven."
10) (56–60s) full lit topology, grey-unknown still marked, resolve to logo. Caption "Stop migrating
    blind → See the whole network. Trust the plan."
Keep captions BIG and short; this must read with the sound off.
```

---

## ALT A — Cinematic single film for a GENERAL audience ("The Invisible City")
Metaphor: a network migration = moving a living city of light overnight without a light going out; the
product is "The Guide." Premium motion-graphics. *(Use for execs / non-technical buyers; NOT for NEs.)*
Full brief: see chat history this session — concept (city of light), "The Guide" character, 3-movement
arc (Dark City → The Guide maps & diagnoses & plans → The Move, verified, zero blackout), brand reveal
+ proof close. Signature beat: a district stays honestly GREY ("unseen ≠ safe").

## ALT B — 3-part TECHNICAL-COMPLETE series (wall-to-wall coverage)
- **Part 1 "The Engine":** problem → doctrine (offline/read-only/coverage-honest) → Ingest→Reconstruct
  →Analyze→Deliver → every vendor → every architecture (SD-Access/LISP, ACI, TrustSec, vPC/MLAG,
  BGP-EVPN, DMVPN/IPsec, BFD, MPLS, IPv6; 40+ detectors / 23+ classes; media: multicast/PTP/ST-2110).
- **Part 2 "The Intelligence":** reachability L1–L4 + RIB→FIB; blast radius/SPOF; the analysis axes
  (EoL, CIS, STP, FHRP, vPC, drift, hygiene, multicast/PTP, QoS, syslog, addressing, redistribution,
  segmentation); endpoint/OUI fingerprinting; the CCDE design brain (261 principles, 82 evidence-gated
  detectors, trade-off scorecard); move-groups + wave sequencing + readiness; Device Risk Register.
- **Part 3 "The Delivery & Proof":** the deliverable set + `--redact`; explorer (3D, flow simulator,
  causal-flow bowties, offline Ask-the-Engineer, 240-Q interview + GO/NO-GO board); PPDIOO gate track +
  8 specialist agents + orchestrator; AssessHub; rigor (385+ tests, graphify offline graph, 4 audits /
  62 defects); real-world proof (303/253/5,127/202).
Full per-chapter scripts + a coverage checklist mapping every pillar to a chapter: see chat history.

---

## Production notes
- **HyperFrames = premium motion graphics**, NOT Pixar/character animation. For true animated footage,
  feed these scripts to **Sora / Runway / Kling / Luma** (AI video) or an animation studio.
- **Client anonymized** as "a live broadcast-media network" throughout. Name the real client ONLY with
  sign-off (append "name the client as <X> in the closing card").
- Render the NE ad first; for an exec audience render ALT A; for full technical coverage render ALT B.

## Session resume state (as of this save)
- Branch `feat/asne-rig-and-ssot`, pushed to origin (backup current through commit `03bfbb6`).
- Four multi-domain adversarial audits folded test-first: **62 confirmed defects fixed**; engine +
  webapp suites green; golden clean.
- **Audit-5 wave was stopped** to preserve budget; **~80% complete (397 agent outputs journaled)** under
  run id **`wf_d5a058ed-429`**. To finish cheaply next week: re-launch with
  `Workflow({scriptPath: "<…/multidomain-engine-audit-5-wf_d5a058ed-429.js>", resumeFromRunId: "wf_d5a058ed-429"})`
  — completed agents return cached, only the remainder runs — then fold the confirmed defects.
