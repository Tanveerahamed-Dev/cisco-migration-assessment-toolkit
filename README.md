# Cisco Migration-Assessment Toolkit

[![CI](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/workflows/ci.yml)

A Python toolkit that connects to Cisco switches (IOS / IOS-XE / NX-OS), parses
their `show`-command output, and correlates the full **L1 → L4 + cross-layer +
routing-protocol + security/config** picture into decision-ready outputs for a
network migration. It answers the three questions an assessment must: **what's
the current state, where is the migration risk, and what do I fix first.**

## The one application

This repository is **one application**, and **AssessHub** is its door:

- **AssessHub** ([`webapp/`](webapp/README.md)) is the web application where an
  assessment is read and run. It holds the campaigns, the core assessment screens,
  comparison, the cutover plan, execution runs and document downloads. Section
  [AssessHub — the one door](#assesshub--the-one-door) below covers it.
- **Atlas.exe** ([`portable/`](portable/README-FIELD.txt)) is the same application
  packaged as one Windows folder for a USB stick. Double-clicked, it serves AssessHub
  on the loopback address. Run as `Atlas.exe --run-engine <engine arguments>`, it *is*
  the engine command line, so the stick carries no separate engine program. See
  [Atlas — the portable field app](#atlas--the-portable-field-app).
- **The engine** (`COLLECT_PARSE_V3_23_0.py` + `cisco_toolkit/`, command `cisco-assess`)
  owns every analysis fact. The screens render what it published.
- **Atlas Scope** ([`atlas-scope/`](atlas-scope/README.md)) is a 3-D investigation view
  that AssessHub serves at `/scope`. It ships as a **labelled preview**, not an accepted
  product: its acceptance is not complete, and its
  [acceptance report](atlas-scope/docs/acceptance-report.md) (graded 2026-10-02/03) records
  24 of 39 acceptance criteria failing. Atlas Scope has changed since that grade, and no later
  grade is recorded. Scope's status bar and AssessHub's entries to it are marked **Preview**.

How to read the core screens, including how they show missing evidence, is in the
[operator guide](docs/operator-guide-core-screens.md).

## What an assessment run produces

An assessment run writes a self-contained, **offline / air-gapped** deliverable set
(listed under [Inputs & outputs](#inputs--outputs); flags such as `--no-html` turn single
documents off) — no live network is needed to read it. The two to open first:

- a **multi-sheet Excel workbook** (30+ tabs) that opens on a one-page
  **Executive Summary**: fleet posture, the punch-list breakdown, the
  **keystone devices** the fleet most depends on (by migration blast radius),
  and per-move-group readiness;
- an interactive single-file **Network Migration Explorer** (the
  `blast_radius_explorer.html` viewer) with 14 analysis modes and a graphical
  **Risk cockpit** that distils thousands of findings into "fix these first."

The engine is **multi-vendor**: Cisco IOS / IOS-XE / NX-OS over SSH show-text plus
JSON controller-REST ingestion (Cisco ACI/APIC, Catalyst SD-WAN/vManage, ISE, FMC),
Arista EOS, Juniper SRX, Fortinet FortiGate, and AWS security-group exports — and it
carries a set of offline **proof engines** (ACL shadow-proofs, RIB→FIB path traces,
capture integrity, parse-yield telemetry, state assertions, chain-of-custody manifest)
whose verdicts are coverage-honest: absence of evidence is never reported as health.

Underneath sit a per-switch **health score (0–100)**, a per-move-group
**migration-readiness verdict** (`READY` / `CAUTION` / `NOT READY`), a
consolidated severity-ranked **migration punch-list**, and a blast-radius
**failure-impact** simulation — all derived offline from one collection.

> ℹ️ The topology embedded in the bundled `blast_radius_explorer.html` is
> **demo/sample data** (private `10.0.x.x` addresses, generic `CORE` / `DIST`
> labels) — not a real network capture.

## Repository contents

| File | What it is |
|------|------------|
| [`COLLECT_PARSE_V3_23_0.py`](COLLECT_PARSE_V3_23_0.py) | The toolkit — collects over SSH (netmiko), parses, scores health, computes migration readiness, and writes the workbook + explorer. |
| [`COLLECT_PARSE_V3_23_0.md`](COLLECT_PARSE_V3_23_0.md) | Documentation for the current version (health scoring, the 10-check readiness checklist, the HTML Health mode) plus the change log. |
| [`cisco_toolkit/blast_radius_explorer.html`](cisco_toolkit/blast_radius_explorer.html) | The interactive single-file explorer that renders a collected snapshot — topology graph plus 14 analysis modes (Blast radius, Path trace, Compare, Flow, **Health** w/ the Risk cockpit, Protocols, Cross-Layer, Causal Flow, Waves, Apps, Review, Design, Cable Map, 3D). The live snapshot is baked into a copy of this template on every run. (Lives inside the package so it ships in a wheel.) |
| [`cisco_toolkit/`](cisco_toolkit/) | The engine package: parsers, analysis, the coverage-honest projection the screens read (`ui_projection.py`), and the engine's deliverable writers. AssessHub's own Cutover Plan, NRFU / Acceptance Test Plan and Post-Implementation Review writers live in `webapp/backend/`. |
| [`webapp/`](webapp/README.md) | AssessHub, the one door: the FastAPI backend and the React app, with a prebuilt copy of the app and a synthetic demo snapshot. |
| [`portable/`](portable/README-FIELD.txt) | Atlas, the portable Windows build, and `README-FIELD.txt`, the field guide that ships on the stick. |
| [`atlas-scope/`](atlas-scope/README.md) | Atlas Scope, the 3-D investigation view AssessHub serves at `/scope` (preview). |
| [`docs/operator-guide-core-screens.md`](docs/operator-guide-core-screens.md) | How to read the AssessHub core screens, receipts, data locations and backups. |

## Requirements

- **Python 3.10+** (CI tests 3.10 → 3.14 on Linux and Windows)
- [`netmiko`](https://pypi.org/project/netmiko/) — SSH collection
- [`openpyxl`](https://pypi.org/project/openpyxl/) — Excel read/write
- [`python-docx`](https://pypi.org/project/python-docx/) and
  [`python-pptx`](https://pypi.org/project/python-pptx/) — the default document family
- FastAPI/Uvicorn/python-multipart — the installed AssessHub surface

## Install

Install the project itself to get the complete, stable **`cisco-assess`**,
**`assesshub`**, and **`cisco-mcp-server`** command surface. A plain install
(or built wheel) is relocatable: the explorer template, verified offline
registries, AssessHub SPA and synthetic demo data ship inside the distribution:

```bash
pip install .                         # complete runtime
pip install -e ".[dev]"              # editable + test/lint/type tooling
```

After installing, `cisco-assess …` is equivalent to `python COLLECT_PARSE_V3_23_0.py …`
(same entry point). The **editable** form (`-e`) is a development convenience —
code edits take effect without reinstalling — not a runtime requirement.

## Inputs & outputs

**Inputs**
- A **devices file** (`--devices-file`, JSON) describing what to connect to (see below).
- A **template workbook** (`--template`, default `Migration_Assessment_Template_Updated.xlsx`)
  used as the starting point for the filled report. *Provide your own; it is not
  included in this repo.*

**Outputs** (written to the working directory)
- `Migration_Assessment_AUTOFILLED_<timestamp>.xlsx` — the filled workbook. It
  opens on the **Executive Summary** tab and then carries 30+ detail sheets
  (Switch Inventory, SVI/Gateway, VLAN & Endpoint census, Move Groups, Topology
  Links, Capacity, Interface/Physical Health, Security Posture, Config
  Compliance & Hygiene, STP & STP-Root, Routing Adjacencies, Cross-Layer
  Analysis, Causality Chains, Failure Impact, Health Scores, Migration
  Readiness, the Migration Punch-List, and more).
- `..._explorer.html` — the Network Migration Explorer beside the workbook
  (unless `--no-html`), with the snapshot embedded.
- `..._snapshot.json` — the data contract shared by the workbook and explorer
  (also re-loadable in the explorer and usable with `--compare`).
- `..._runbook.docx` — the Assessment & Migration **Runbook**, the narrative twin
  of the workbook (unless `--no-docx`; needs `python-docx`).
- `..._executive_deck.pptx` — the **Executive presentation deck**: a short,
  stakeholder-ready slide summary (posture, top risks, keystone devices,
  end-of-support exposure, the wave plan, where to start) generated from the same
  snapshot (unless `--no-pptx`; needs `python-pptx`).
- `..._design.docx` — the **As-Built Network Design Document** (HLD + LLD): the
  current design reconstructed from the snapshot (topology tiers, L2/L3 design,
  resilience, multicast/timing, segmentation, per-device build detail, BoM) plus
  target-state recommendations (unless `--no-design`; needs `python-docx`).
- `..._mop.docx` — the per-wave **Method of Procedure**: a maintenance-window
  cutover template per migration wave (scope, blockers, pre-cutover baseline,
  port mapping + staged config, the procedure with per-step success criteria,
  post-cutover validation and rollback) (unless `--no-mop`; needs `python-docx`).
- `..._crd.docx` — the **Customer Requirements Document**: the Plan-phase
  requirements-capture instrument, primed with the assessment evidence
  (current-environment summary, evidence-gated technical-requirement sections,
  REQ-ID capture tables and the traceability skeleton into design and acceptance)
  (unless `--no-crd`; needs `python-docx`).
- `..._engagement.docx` — the **Engagement Workflow & Plan of Record**: the
  engagement-management layer over the whole document set — an evidence-led
  verdict (proceed / proceed-with-conditions / hold), a phase tracker with
  entry/exit gates, the ordered next-action queue, a per-wave T-minus gate
  calendar (commit → checkpoint → go/no-go → window → hypercare exit), and a
  RAID log seeded from the assessment's own findings (unless
  `--no-engagement`; needs `python-docx`).
- `..._archreview.docx` — the **Architecture Review & Conformance Report**: the
  automated senior-engineer design review — ~24 leading-practice checks across
  8 design domains (hierarchy, resiliency, L2, L3/gateway, capacity &
  oversubscription, operational readiness, security & segmentation, lifecycle
  & software), each with a verdict / evidence / why-it-matters / remediation /
  cited rule, rolled up into a conformance grade, a domain scorecard and a
  priority remediation queue; checks whose evidence was not captured are
  declared not-assessable rather than silently skipped (unless
  `--no-archreview`; needs `python-docx`).
- `..._ops_handbook.docx` — the **Operations Handbook**: the PPDIOO
  Operate-phase deliverable — the Day-2 handbook whose baselines are this
  fleet's own assessed evidence: the alert list is what the syslog analysis
  actually saw fire, the capacity baseline is each device's own measured
  normal, plus drift control, software/PSIRT governance cadence, a routine
  operations calendar and a TAC-readiness evidence pack; sections whose
  evidence was not collected are declared, never invented (unless
  `--no-opshandbook`; needs `python-docx`).
- `<output-base>.run_manifest.json` — the per-run, hash-chained custody record. The
  finalizer seals the exact current-run artifact set, provenance, evidence,
  redaction state, phase failures, and finalized timings, then immediately
  re-verifies the chain, metadata, and artifact bytes before reporting success.
  The seal is unkeyed: it detects corruption or careless edits, but it does not
  authenticate the producer unless its full `chain_root` is compared with a
  value retained out of band.

## Usage

```bash
# Collect from devices, then build the workbook and explorer
python COLLECT_PARSE_V3_23_0.py \
    --devices-file devices.json \
    --template Migration_Assessment_Template_Updated.xlsx

# Diff two previously saved snapshots into a change workbook (no SSH, no template)
python COLLECT_PARSE_V3_23_0.py --compare old_snapshot.json new_snapshot.json

# CI/change-pipeline mode: write the same artifacts, then exit 2 unless the combined cutover gate passes
python COLLECT_PARSE_V3_23_0.py --compare old_snapshot.json new_snapshot.json --fail-on-compare-gate

# Trend a SERIES of snapshots across the migration into a campaign workbook (oldest first)
python COLLECT_PARSE_V3_23_0.py --trend wave0.snapshot.json wave1.snapshot.json wave2.snapshot.json

# Evaluate a finite synthetic traffic catalog during the same evidence-producing run
python COLLECT_PARSE_V3_23_0.py \
    --devices-file devices.json \
    --template Migration_Assessment_Template_Updated.xlsx \
    --traffic-intents cisco_toolkit/data/traffic-intents.example.json

# See every option
python COLLECT_PARSE_V3_23_0.py --help

# Re-check a delivered set after transfer (artifact bytes are checked by default)
python -m cisco_toolkit.manifest verify path/to/run.run_manifest.json

# Inspect only a deliberately separated manifest; this explicitly skips artifact bytes
python -m cisco_toolkit.manifest verify path/to/run.run_manifest.json --metadata-only
```

`--compare` reports one combined cutover gate across the observed snapshot delta and the bounded
FIB/path-intent Pre-Change Certificate. The certificate verdict never overrides a protocol or other
observed regression; use `--fail-on-compare-gate` when automation must stop on any non-`PASS` result.

Useful flags: `--workers N` (parallel SSH workers, default 5; `1` = sequential),
`--no-html` / `--no-docx` / `--no-pptx` / `--no-design` / `--no-mop` / `--no-crd` /
`--no-engagement`
(skip the explorer / runbook / deck / design doc / MOP / CRD / engagement plan),
`--output FILE` (override the workbook name), `--golden-config FILE` (a config
baseline for the **Golden-Config Drift** sheet — omit to auto-derive it from the
fleet majority), `--flow-src IP` / `--flow-dst IP` (add an optional flow-trace
sheet between two endpoints), `--traffic-intents FILE` (evaluate the bounded catalog in
[`cisco_toolkit/data/traffic-intents.example.json`](cisco_toolkit/data/traffic-intents.example.json)
and add the canonical
**Traffic Assurance** snapshot/workbook result), and `--redact` (pseudonymize IPs / MACs / serials across the
**whole output bundle** — the snapshot JSON, the HTML explorer, **and** the always-produced
`.xlsx` workbook — consistent and subnet-preserving, hostnames kept — so every deliverable can
be shared without leaking real addressing). See
[`COLLECT_PARSE_V3_23_0.md`](COLLECT_PARSE_V3_23_0.md) for the full feature set.

Traffic Assurance accepts a finite list of exact IPv4 TCP/UDP five-tuples, requested
forward/return directions, an optional observed MTU requirement, and at most one synthetic
node/site/link failure per row. It is available only on a full assessment run; combining
`--traffic-intents` with `--compare` or `--trend` is refused because those modes do not publish
the result. A hard verdict requires same-run capture/parser custody, exact scoped-route and
configuration bindings, all applicable modeled forwarding gates accounted for, and no
categorical-unmodeled gate or modeled-projection gap.
Incomplete, stale, or malformed custody, configured NAT, and an applicable stateful or
categorically unmodeled forwarding gate produce an explicit indeterminate/not-observed result
rather than a guessed permit or deny. Even when that bounded control-plane projection is proven,
it does not claim tunnel state or underlay delivery, endpoint attachment or L2 delivery, live
sessions, application success, or field behavior; those remain not assessed. The always-present
`unknown_evidence` snapshot block separately aggregates parser exceptions, suspicious zero-yield,
and unsupported diagnostic shapes without copying raw evidence or identifiers; it is a triage
queue, not proof that every vendor syntax is modeled.

The example is package data in both the wheel and source distribution. From an installed toolkit,
print its absolute path with `python -c "from importlib.resources import files;
print(files('cisco_toolkit').joinpath('data/traffic-intents.example.json'))"`, then pass that path to
`cisco-assess --traffic-intents`.

### Devices file

A JSON file — accepted as an array, a single object, or one object per line.
Each entry needs `ip`, `hostname`, and `username` (common aliases like `host`,
`name`, and `user` are accepted). `platform` is optional and autodetected when
omitted (`ios` / `nxos` / `auto`). Start from
[`devices.example.json`](devices.example.json) — it shows the recommended,
password-free shape.

```json
[
  { "hostname": "core-1", "ip": "10.0.0.1", "username": "netadmin", "platform": "ios" },
  { "hostname": "dist-1", "ip": "10.0.0.2", "username": "netadmin", "password_env": "DIST1_PASS", "platform": "nxos" }
]
```

**Keep passwords OUT of the file — the environment chain is the default.**
Passwords resolve in this order:

1. `"password_env": "VAR"` on the entry — read from that environment variable,
2. the global `$CISCO_PASS` environment variable (one read-only account fleet-wide),
3. a secure `getpass` prompt (interactive terminals only),
4. an explicit `"password"` on the entry — supported for back-compat, **discouraged**:
   `devices.json` then holds live credentials in cleartext on disk.

Authentication failures are **never** retried (this avoids account lockout);
transient connection/timeout failures are retried with backoff.

**Collection is read-only by design.** Only a live collection that you start connects to network
equipment: an engine run without `--no-collect`, or the opt-in controller REST collector. Offline
analysis (`--no-collect`) and every AssessHub upload or ingest read files only.

- **What the engine sends over SSH.** The collector in `COLLECT_PARSE_V3_23_0.py` sends two session
  settings of its own, `terminal length 0` and `terminal width 511` (`TERMINAL_SETUP_CMDS`). Every
  other string it sends is an entry from its command registries that passes `is_ssh_wire_command`:
  a `show` command with no command chaining or redirection, and only output filters after a pipe.
  An entry that fails the check is withheld from the session and logged. The engine calls no
  enable-mode or configuration-mode function.
- **What the SSH library sends for itself.** netmiko also writes to the session: on connect, its
  own paging and width settings and Enter keystrokes to find the prompt; on disconnect, `exit`.
- **Platform autodetection.** When a device's `platform` is `auto` (the default when
  `devices.json` names none), netmiko's autodetection first opens a separate session and sends
  its own identification commands. The engine's check does not cover them, and they can include
  other vendors' commands, such as `display version` or `get system status`. Set `platform` to
  `ios` or `nxos` to skip this step.
- **Controller REST.** The opt-in collectors (`cisco_toolkit/rest_collect.py`) send only GET
  requests apart from the login. On a controller the read-only guarantee comes from the account's
  read-only role, so use a dedicated read-only account.

### Secrets at rest — the raw collection directory

The collection directory holds the devices' **verbatim output**, running-configs
included — passwords, SNMP communities, and keys in **cleartext**. `--redact` makes the
*deliverables* share-safe but deliberately never touches this evidence dir (it is the
`--compare` / `--trend` source), and every run now prints a `[SENSITIVE]` warning naming
it. Once analysis is final, scrub the raw captures in place with **`--redact-collection`**:
it replaces secret *values* with the same conservative deny-list `--redact` uses, keeps
IPs/hostnames/interfaces so the dir stays analyzable, is idempotent, and never deletes
anything. (Scrubbed captures will no longer match any archive hashes recorded at
collection time — that modification is the point, and it is opt-in.)

## Reading the results

**Excel — start on the Executive Summary.** The first tab is a one-page synthesis:
fleet posture (health-band distribution), the migration punch-list breakdown, the
**keystone devices** ranked by blast radius (the few switches the fleet most
depends on — the prioritisation that still works when every per-switch score
saturates to Critical), per-group readiness, and a plain-English *"where to
start."* Each section points to a detail tab for the underlying evidence.

**Then the Device Risk Register.** The per-**asset** synthesis: the eleven
per-device axes (health, hardware EoL, software risk, control-plane capacity,
operational logs, CIS posture, config hygiene, golden drift, QoS, physical,
protocol) stacked per box and ranked by **risk index = topology impact ×
exposure**, with named **compound patterns** (CR-01..CR-06) where independent
risks coincide on one asset — an end-of-support keystone, a root bridge on
degraded hardware, an open advisory surface on a box whose removal partitions
the network — and a one-sentence engineer's verdict each. An axis without
evidence reads *not assessed*, never healthy-by-silence. The top row is the
scariest box in the fleet; the compound patterns also fold into the punch-list.

**Explorer — 14 modes over one topology.** Pan/zoom the graph; search by
switch / IP / MAC; filter by VLAN. The modes:

- **Blast radius** — click a switch to simulate its removal and see what it strands.
- **Path trace** — the L2/L3 path between two switches, with the bridges / articulation points on it.
- **Compare** — diff two snapshots (pre/post-cutover): what regressed, what improved.
- **Flow** — an L1→L3 flow trace between two endpoints, with ACL / NAT / MTU / VRF awareness.
- **Health** — the **Risk cockpit**: a risk-by-tier matrix, the keystone devices, the
  **Asset risk register** (the fleet ranked by per-asset compound risk, with CR-pattern
  chips and inline engineer's verdicts) and a punch-list triage up top, then per-switch
  health, the root-cause SPOF list, and a what-if remediation simulator. Selecting any
  switch in any mode opens its dossier, led by the engine's **Engineer's verdict** card.
- **Protocols** — routing-protocol topology, redistribution boundaries, adjacency health.
- **Cross-Layer** — findings that compound across layers into one real migration risk.
- **Causal Flow** — each structural SPOF as a trigger → mechanism → impact → mitigation chain.
- **Waves** — the migration move-groups in recommended cutover order, each with its readiness
  verdict, scenario (make-before-break vs hard cutover) and post-cutover validation checks.
- **Apps** — application domains (workloads) with footprint, criticality tier and inter-domain
  coupling — the unit the business actually migrates.
- **Review** — the senior-engineer architecture review: leading-practice checks across eight
  design domains with an A–F conformance grade and not-assessable honesty.
- **Design** — the evidence-gated target-state blueprint: recommended decisions, trade-offs,
  affected devices, and the requirement questions that remain open.
- **Cable Map** — a role-tiered physical view of CDP/LLDP cabling, with operational state,
  port-channel membership, and uncollected links kept visibly not observed.
- **3D** — an orbitable tiered fabric view with device health, selection, and link highlighting.

The explorer is a single self-contained file (no server, no external assets) and
runs fully offline — safe to email or open from a USB stick.

## AssessHub — the one door

[`webapp/`](webapp/README.md) is the web application over the engine. Where one engine run
produces one assessment, AssessHub keeps the whole migration *campaign* in a local SQLite
database and is where an assessment is read, compared, planned and executed.

**Start it.** The built web app ships inside the distribution, so no Node toolchain is needed
to run it:

```bash
pip install .
assesshub            # serves http://127.0.0.1:8000 and opens the browser
assesshub --selftest # checks the assets that would otherwise degrade silently
```

From a checkout, `python -m webapp.backend.serve` is the same entry. With no token configured,
AssessHub's API answers loopback clients only; any other access needs `ASSESSHUB_TOKEN` and TLS
(see *Access model* in [`webapp/README.md`](webapp/README.md)). Click **Open a sample fleet** for
the bundled synthetic demo — no network needed.

**Getting evidence in.** On a campaign page, add a wave by uploading a finished
`*.snapshot.json`, a **ZIP of raw `show`-command outputs**, or a collection folder on the
AssessHub machine. For a ZIP or folder, AssessHub runs the real engine offline over the files
(`--no-collect`); it never connects to a device. The raw files are staged in a folder under the
system temporary directory, which AssessHub deletes when the run ends (a failed deletion is not
reported). AssessHub stores the resulting snapshot, not the raw captures.

**The core screens.** A snapshot opens on five views — **Overview, Trust, Inventory, Findings,
Topology & Paths** — plus a **Device** page for any device, which includes **If this device
fails** (its stored failure-impact rows) and **Structural links**. Every value on these screens
carries its evidence state. A value the engine did not publish shows a dash, its state
(*Collected, empty*, *Not collected*, *Not assessed*, *Analysis unavailable* or *Unverified*) and
the engine's reason, never zero or healthy. **Trust** says what the analysis could not see. The
[operator guide](docs/operator-guide-core-screens.md) walks through each screen, including how a
lower bound reads.

**Tools and downloads** keeps the earlier snapshot page: the Device Risk Register, the keystone
devices, **Ask the engineer** (the architecture review), the design blueprint, the causal flow,
the **cutover plan** (per-wave GO / CONDITIONAL GO / NO-GO gates and a run-of-show), the document
downloads, the fleet topology, the cable map, the embedded explorer and the detail-section tabs.
The engine's documents come from the engine's own writers. The Cutover Plan and the NRFU /
Acceptance Test Plan are generated only by AssessHub, and the Post-Implementation Review only
from an execution run.

**Compare, cutover and execution receipts.**

- **Compare two waves** on a campaign page shows the engine's cutover gate for that pair; it is
  not stored. The campaign trajectory shows the server's decision for each adjacent pair.
- An **execution run** (the war room) starts from the cutover plan. **Bind post-change
  evidence** checks a newer snapshot against the run and, when the checks pass, appends an
  **immutable comparison receipt**; a new run can be successful only when its latest receipt is
  PASS.
- The **gate board** records per-wave sign-offs (commit → checkpoint → readiness review →
  go / no-go → window → hypercare exit).

**Records that cannot be deleted.** AssessHub refuses (HTTP 409) to delete a snapshot a receipt
names, an execution run that holds a receipt, or a campaign that contains one. Records without a
receipt can be deleted, but **an in-app delete is not disposal**: a deleted row can stay readable
in the database file and its start-time backups. **There is no purge in AssessHub, by
decision**: on 2026-10-09 the owner decided to keep everything, with receipts immutable and no
in-app purge, so the per-campaign purge planned in
[ADR 0007](docs/decisions/0007-one-application-direction.md) (D10) is superseded by its
Amendment 1 and is not built (the decision is recorded in [`docs/NOW.md`](docs/NOW.md), *Owner
decisions*, 2026-10-09). Disposing of a client's data is a documented manual step outside the
application: see the [operator guide](docs/operator-guide-core-screens.md) (section 10) and
[`portable/README-FIELD.txt`](portable/README-FIELD.txt) (DISPOSING OF CLIENT DATA).

**Where the data lives.** `Atlas.exe` keeps its database in `Atlas\data\assesshub.db`; a
checkout uses `webapp/data/assesshub.db`; an installed `assesshub` uses the user's
application-data folder. `--db` or `ASSESSHUB_DB` selects another file. At every start through
`assesshub` or `Atlas.exe`, the store is integrity-checked (a damaged store is not served) and,
when it has changed since the last copy and holds at least one campaign, copied to a `backups`
folder beside it; the newest 3 of AssessHub's own copies are kept.

**Redaction is command-line only.** AssessHub applies no redaction to the documents it serves
for download. For a share-safe set use the engine's `--redact`, or on the stick
`Atlas.exe --redact-folder` (next section).

**Atlas Scope (preview).** On a snapshot's page, **Open in Atlas Scope** opens the same stored
snapshot at `/scope/snapshots/<id>/`, and **Topology & Paths** can embed it as a 3-D view. It is
read-only and an integrated preview; its acceptance report records 24 of 39 criteria failing
(graded 2026-10-02/03, with no later grade recorded), so confirm what it shows on the core
screens. In a checkout the link appears only when Atlas Scope's hub build exists
([`atlas-scope/README.md`](atlas-scope/README.md)).

## Atlas — the portable field app

[`portable/`](portable/README-FIELD.txt) builds Atlas, the whole application as one Windows
folder that runs from a USB stick without an installed Python. `Atlas.exe` is the one door:

- Double-clicked, it serves AssessHub on `127.0.0.1` and opens the browser. The portable build
  binds loopback only.
- `Atlas.exe --run-engine <engine arguments>` runs the engine command line in the same program.
- `Atlas.exe --selftest` checks the stick before an engagement (expect `SELFTEST: PASS`).
- `Atlas.exe --redact-folder <collection> --out <empty folder>` renders a redacted deliverable
  set; `--redact-collection` also scrubs cleartext secrets from the raw captures in place, and
  `--reuse-out` re-renders into a folder that already holds a set.
- `Atlas.exe --verify-manifest <run_manifest.json>` re-checks a delivered set.

Everything Atlas stores lives in `Atlas\data\`, the only writable folder; an update replaces
the rest. A live SSH collection from the stick also needs `--allow-live-network` before
`--run-engine`. The field discipline (first run, loss of stick, corruption and restore, eject,
redaction limits, update and rollback) is in
[`portable/README-FIELD.txt`](portable/README-FIELD.txt), which ships on the stick.

<!--
Owners behind "The one application", "AssessHub — the one door", "Atlas — the portable field app"
and "Collection is read-only by design" (verified on origin/main 6390b66c, 2026-10-09; the
collection paragraph and the corrections of the W56 review re-verified the same day). Each
statement is a cache of these owners; correct the prose when one changes. Per-statement detail is
in the owner block at the end of docs/operator-guide-core-screens.md.
- One door and --run-engine: webapp/backend/serve.py (module docstring, ENGINE_SENTINEL, _run_engine,
  _resolve_db, loopback-only frozen bind in main, argparse flags); pyproject.toml [project.scripts].
- Core screens and Tools page: webapp/frontend/src/App.tsx, pages/CoreSnapshot.tsx,
  pages/core/*.tsx, pages/Snapshot.tsx; state labels in pages/core/ProjectionEvidence.tsx.
- Ingest: webapp/backend/ingest.py run_collection_zip / run_collection_folder (--no-collect; the
  temp workdir under _engine_temp_parent is removed by shutil.rmtree(ignore_errors=True) in
  finally).
- Receipts and deletion refusals: webapp/backend/app.py compare, compare_execution, delete_* (409);
  webapp/backend/storage.py delete_*_if_unreceipted; pages/Execution.tsx (PASS rule).
- No purge, by decision: no purge/retention route in webapp/backend; the owner's 2026-10-09
  keep-everything decision (docs/NOW.md, Owner decisions, 2026-10-09 entry; ADR 0007 Amendment 1)
  supersedes D10's purge. In-app delete is not disposal: storage.py issues neither PRAGMA
  secure_delete nor VACUUM.
- Preview labels: atlas-scope/src/app/PreviewLabel.tsx (rendered by StatusBar.tsx);
  webapp/frontend/src/components/ScopePreview.tsx (CoreSnapshot.tsx ScopeLink, Snapshot.tsx
  AtlasScopeLink, core/TopologyScope.tsx).
- Data and backups: webapp/backend/app.py _platform_default_db; serve.py main
  (boot_hardening=True); storage.py Store._boot_hardening (quick_check, no copy of a
  campaign-free store, mtime test), _BACKUP_DIR, _BACKUP_KEEP.
- cisco_toolkit row: cisco_toolkit/docmeta.py ARTIFACT_SPECS writer_module (cutover, nrfu and pir
  writers are webapp.backend.*).
- Redaction: no redaction route in webapp/backend/app.py; serve.py --redact-folder family.
- Atlas Scope preview count: atlas-scope/docs/acceptance-report.md, Verdict (graded at 2dd95d74;
  the report is unchanged since c95de5cc while atlas-scope/ changed in later merges, e.g. #599,
  #601, #606, #618).
- Gate board steps: cisco_toolkit/engagement.py GATE_SEQUENCE. Cutover gates: webapp/backend/cutover.py.
- Collection safety: COLLECT_PARSE_V3_23_0.py TERMINAL_SETUP_CMDS, is_ssh_wire_command,
  ssh_wire_commands, collect (withheld entries logged), connect_device, autodetect_platform
  (netmiko SSHDetect when platform is auto/blank), load_devices plat_map (default
  "auto"), NETMIKO_TYPE (cisco_ios / cisco_nxos only); no enable()/config-mode call in the engine.
  netmiko's own writes (read in the installed 4.7.0; pin netmiko>=4.1,<5): CiscoIosBase and
  CiscoNxosBase session_preparation (terminal width 511, terminal length 0, prompt RETURNs),
  CiscoBaseConnection.cleanup ("exit"), ssh_autodetect.SSH_MAPPER_DICT (probe commands such as
  "display version", "get system status", "uname -a"). cisco_toolkit/rest_collect.py docstring
  and _post (the three logins); webapp/backend/ingest.py (--no-collect only).
-->

## Health score & migration readiness

The score starts at 100 with weighted, **per-category-capped** deductions across
L1, L3, cross-layer, and protocol findings, banded **Excellent / Good / Fair /
Poor / Critical**. Migration readiness runs a 10-check pre-migration checklist
per move group: any hard-fail check → `NOT READY`, otherwise any warn →
`CAUTION`, otherwise `READY`. Both the weights and band thresholds are a
defensible default, not calibrated against a labelled dataset — tune to taste.
Full details are in [`COLLECT_PARSE_V3_23_0.md`](COLLECT_PARSE_V3_23_0.md).
