# Operator guide: the AssessHub core screens

This guide is for the engineer who runs an assessment and reads its results. It covers the one
application, the core screens of a snapshot, how the screens show what the evidence does not
cover, and the records AssessHub keeps. The field discipline for the USB stick (selftest,
eject, corruption, redaction, update) lives in `portable/README-FIELD.txt`, and the developer
setup lives in `webapp/README.md`.

Written against `main` on 2026-10-09. Where this guide and the running application disagree, the
application is right; correct this guide.

## 1. The one door

There is one application. **AssessHub** is its door: campaigns, the core screens, comparison,
the cutover plan, execution runs and document downloads all live there.

- **On the USB stick, `Atlas.exe` is AssessHub.** Double-clicked, it serves AssessHub on the
  loopback address and opens your browser. Keep its console window open; closing it stops the
  application.
- **`Atlas.exe` is also the engine command line.** `Atlas.exe --run-engine <engine arguments>`
  runs the assessment engine (`cisco-assess`) inside the same program, so the stick carries no
  separate engine program.
- **From an installed toolkit,** `assesshub` is the same entry, and `cisco-assess` is the engine.
- **Field commands** (`Atlas.exe --selftest`, `--redact-folder`, `--verify-manifest`) are listed
  in `portable/README-FIELD.txt`.

The engine owns every analysis fact. The screens show what the engine published; they do not
recompute, rank or fill in a value the engine withheld.

## 2. Getting a snapshot in

Open **Campaigns**, create or open a campaign, and add a wave in one of three ways:

- **Upload a snapshot file** (`*.snapshot.json`) that an engine run produced.
- **Ingest a raw collection** as a ZIP of `show`-command outputs (one folder per device).
- **Ingest a local folder** on the machine running AssessHub. The folder must sit under an
  allowed ingest root: by default the Atlas folder on the stick, or the repository checkout.

For both ingest routes AssessHub runs the real engine offline over the files (`--no-collect`).
Nothing connects to a device. The raw files are staged in a temporary folder that is removed
after the run, and AssessHub stores the resulting snapshot, not the raw captures.

**Open a sample fleet** on the home page loads the bundled demo snapshot, so you can learn the
screens without client data.

## 3. How to read any value

Every value on the core screens carries a state. A value that is not published shows a dash and
a state label with the engine's reason. **A dash is never zero and never healthy.**

| Label | What it means |
|---|---|
| Published | The engine measured it. |
| Collected, empty | The evidence was collected and holds nothing of this kind. It is not a blind spot. |
| Not collected | A blind spot: the evidence was never collected, or that device was not collected. |
| Not assessed | The engine could not judge it, for example a fleet health with no scored device. |
| Analysis unavailable | That analysis step failed in this run, so an empty result is not evidence of absence. |
| Unverified | A value exists but failed a check (type, reconciliation, a contradiction, a duplicate), so it is not shown as a measurement. |

Three things help you read a value:

- **Evidence ↗** beside a value opens a drawer with its basis, its subject address, its source
  references (each with a role), the engine state where one is published, the qualifications
  and the stored snapshot identity. Raw evidence text is not shown there.
- **Qualifications (N)** appears when a limitation applies to the value. Read it before you
  quote the value.
- **List paging.** Long lists read "Rows X–Y of N projected rows" with Previous and Next. N counts
  every row in the list, not only the rows on this page.

At the bottom of every view, **Snapshot and engine identity** shows the stored snapshot's SHA-256,
its size, and the engine and schema versions that produced it.

## 4. The core screens

A snapshot opens on its core screens. Five views run across the top: **Overview, Trust,
Inventory, Findings, Topology & Paths**. A **Device** page opens from any device name. The page
header also has **Open in Atlas Scope ↗** (when the installed build supports it) and **Tools and
downloads**.

### Overview

- The engine's fleet posture statement.
- Five headline facts: devices with health records, complete collections, evidenced endpoints,
  VLANs in use, and the mean fleet health score.
- The health assessment, with each health band's devices linked to their Device pages.
- The lifecycle bands (Past-LDoS, Near-LDoS, Past-EoS, Active, Unknown) and their as-of date.
- The gating items and the assessment axes, then any axes without a published result.
- Move-group readiness, with each group's checks and devices.
- The design-decision count. Design-decision details are on the Tools page.

### Trust

Read Trust before you quote any number. It is the screen that says what the analysis could not
see:

- **Evidence coverage:** the engine's published coverage totals.
- **What the analysis could not see:** one row per axis of the engine's per-device risk register.
  Each row says how many inventory devices that input could not assess, lists them with their
  custody state, and links each one to its Device page. A withheld count keeps its state and
  reason; it is never shown as zero.
- **Unknown evidence:** parser exceptions, suspicious zero yield and unsupported shapes, with
  their sources.
- **Single source of truth checks**, the **section census**, **recorded analysis failures** and
  the **limits and qualifications** that apply to this snapshot.

### Inventory

Four tabs: **Devices** (model, health band, move group, finding and coverage roll-ups),
**VLANs** (readiness, STP root and gateway detail), **Endpoints** (with shared-IP and dual-homed
evidence) and **Peers**: cable-map neighbours that the collection did not collect.

### Findings

The prioritised findings, in the engine's own order, with the engine's finding total. Each
finding shows its severity, priority and devices (linked), and opens to the issue, the
remediation and the evidence references. On `main` this view publishes no severity or category
facet totals; the screen says so.

### Topology & Paths

- A **2-D map** of the engine's nodes and cable map, with a record inspector for any node or
  link.
- **3-D investigation** embeds Atlas Scope (section 6). It is enabled only after every topology
  page has loaded.
- **Investigate an IP path** asks the engine about a source and destination IP. The answer comes
  from the stored route model; no traffic is sent.
- The topology evidence lists: nodes, cable map, structural links, failure impact and observed
  address records.

### Device

One device, in this order:

1. Identity and move group; health; collection; physical; lifecycle; finding severity; coverage
   summary; risk band.
2. **If this device fails:** the engine's stored failure-impact rows for this device: severity,
   VLANs impacted, stranded endpoints, hard-partition, backup-covered, FHRP-covered and
   off-scan-gateway VLANs, and the per-VLAN detail.
3. **Structural links:** the engine's stored structural-link rows for this device: link ends,
   whether the link is a bridge, the switch pairs it would sever, and its betweenness and rank.
4. Exposure axes, compound findings, health deductions and their evidence references, and
   per-axis device coverage.
5. Under **Interfaces, links and routing** and **Security and remediation**: interfaces, links,
   routes, routing neighbours, security checks, native-VLAN mismatches, remediation items and
   NRFU cases.
6. Links to this device's findings and endpoints.

The failure-impact and structural-link rows are stored engine rows in engine order. The page does
not simulate, rank or fill them in.

## 5. Coverage honesty: NOT ASSESSED, not collected, lower bounds, unavailable

The engine never turns missing evidence into a clean result. The screens show four cases:

- **Not collected.** The evidence is missing. On the core screens it is the **Not collected**
  label with a reason. A device the collection never reached has no failure-impact row at all,
  and an absent row is not "no impact".
- **NOT ASSESSED.** The engine had nothing it could judge. On the core screens it is the
  **Not assessed** label. On the Tools page and in the cutover plan it is the token
  `NOT ASSESSED`, for example the last keystone entry when a row could not be ranked, or a
  wave's worst case when no switch in it could be ranked.
- **Lower bound.** A count the engine could only partly simulate is published as a lower
  bound: the true impact can be larger. This happens, for example, when the switch has
  inter-switch links without trunk or STP evidence, an off-scan gateway, or a cabled neighbour
  that was not collected. A severity below High and a zero count are withheld in that case.
  - On the core screens the value shows as published. Its **Evidence** lists a reference with
    the role `witness`, and its qualification explains the rule. Read it as "at least".
  - The Tools page **Failure impact** tab prints it as `≥ N` with the reason.
  - The keystone list and the cutover plan describe it as "LOWER BOUND, at least N endpoint(s)
    stranded", with the reason.
- **Unavailable.** **Analysis unavailable** means that analysis step failed in this run.
  **Unverified** means a value failed a check. Neither is evidence that nothing is there.

## 6. Atlas Scope: a preview

Atlas Scope is a 3-D investigation view of one snapshot. AssessHub serves it at
`/scope/snapshots/<id>/`, opened from **Open in Atlas Scope ↗**, and embeds it as **3-D
investigation** under Topology & Paths. It reads the stored snapshot from AssessHub, and it is
read-only.

It is an integrated **preview**, not an accepted product. Its acceptance report
(`atlas-scope/docs/acceptance-report.md`, graded 2026-10-02/03) records 24 of 39 acceptance
criteria failing and 3 unproven. Use it to look around, and confirm any finding on the core
screens before you act on it. A quiet or empty 3-D view is not a clean bill of health.

## 7. The Tools and downloads page

**Tools and downloads** keeps the earlier full snapshot page while the core screens grow:

- the headline cards and distributions;
- the Device Risk Register and the keystone devices;
- **Ask the engineer** (the architecture review), the target-state design blueprint and the
  causal flow;
- the **cutover plan** (run-of-show) and **Start execution run**;
- the document downloads, the fleet topology, the cable map, the embedded explorer and the
  detail-section tabs (including **Failure impact**).

## 8. Comparison, cutover and execution receipts

- **Compare two waves** (Campaign page) runs the engine's comparison over two stored snapshots
  and shows its overall cutover gate. This comparison is not stored.
- **Campaign trajectory** shows the server's cutover decision for each adjacent pair of
  snapshots, under **Adjacent canonical cutover receipts**, and can export it as JSON.
- **The cutover plan** gives each wave a GO, CONDITIONAL GO or NO-GO gate. With no wave to gate,
  the fleet verdict is `NOT ASSESSED`, and a wave whose blast radius cannot be ranked shows a
  `NOT ASSESSED` worst case. The Cutover Plan and NRFU / Acceptance Test Plan documents come only
  from AssessHub.
- **An execution run** (the war room) is started from the cutover plan. **Bind post-change
  evidence** selects a newer snapshot. The server re-checks order, campaign, engagement, source
  hashes and owner versions, then appends an **immutable comparison receipt**.
  - A new run can be successful only when its latest receipt is PASS.
  - A run that predates receipts is shown as legacy and cannot be backfilled.
  - The Post-Implementation Review comes only from an execution run.

## 9. Records you cannot delete, and what is not built yet

- A comparison receipt is an append-only decision record. AssessHub refuses, with HTTP 409 and
  the reason, to delete:
  - a snapshot that a receipt names (before, after, or a failure-trial source);
  - an execution run that holds a receipt;
  - a campaign that contains one.
- A campaign without receipts can be deleted from its page.
- **A per-campaign purge is not implemented yet.** The decision to retain scrubbed raw evidence,
  with a retention indicator and a per-campaign purge, is recorded in
  `docs/decisions/0007-one-application-direction.md` (D10). Neither the purge nor the retention
  indicator exists today.

## 10. Where the data lives, and backups

| How AssessHub runs | Database |
|---|---|
| `Atlas.exe` on the stick | `Atlas\data\assesshub.db`, beside `Atlas.exe` |
| A repository checkout | `webapp/data/assesshub.db` |
| An installed toolkit (`assesshub`) | the user's application-data folder: `Atlas\assesshub.db` under `%LOCALAPPDATA%` on Windows |

`--db <file>` or the `ASSESSHUB_DB` environment variable selects another file.

At every start AssessHub checks the database's integrity. When the database has changed, it keeps
a timestamped copy in a `backups` folder beside it, and it keeps the **newest 3** of its own
copies. Backups are taken at start, not continuously. The restore procedure is in
`portable/README-FIELD.txt`, under CORRUPTION.

## 11. Redaction is a command-line step

AssessHub's downloads are **not redacted**: they carry the client's addresses, serials and
hostnames. To make a share-safe set, use the command line:

- on the stick, `Atlas.exe --redact-folder <collection> --out <empty folder>`, adding
  `--redact-collection` to scrub secrets from the raw captures in place, and `--reuse-out` only
  to re-render the same job into its own folder;
- or the engine's `--redact` on a full run.

Redaction keeps hostnames and descriptions on purpose. Read `portable/README-FIELD.txt`,
REDACTION, before anything leaves the site.

## 12. Collection safety

- AssessHub's upload and ingest routes never connect to a device.
- A live SSH collection is an explicit engine run. Apart from the session's own paging settings
  (`terminal length 0`, `terminal width 511`), the collector types only `show` commands that
  pass a whole-string read-only check: no command chaining, no redirection, and only output
  filters after a pipe. Authentication failures are never retried, to avoid locking the
  account.
- Controller REST collection is opt-in. Apart from the login, it sends only GET requests. On a
  controller the read-only guarantee comes from the account's read-only role, not from the
  protocol, so use a dedicated read-only account.
- On the stick, a live collection also needs `--allow-live-network` before `--run-engine`.
  `portable/README-FIELD.txt` has the exact command.

## Arriving with the next release (not on `main` yet)

Open pull request #630 (an integration train, not merged on 2026-10-09) carries several changes
to these screens. If it merges as proposed, two of them change what you see:

- The Findings view shows severity, category and per-device facets.
- The core screens mark a lower bound, NOT ASSESSED and unavailable values distinctly.

Until #630 merges, this guide describes `main`. Update this section when it does.

<!--
Owners behind each statement (verified on origin/main 6390b66c, 2026-10-09). This block is for
maintainers; correct the prose above when an owner changes.
- One door, --run-engine, loopback-only frozen bind: webapp/backend/serve.py (ENGINE_SENTINEL,
  _run_engine, main: numeric-loopback refusal when frozen); ingest._engine_argv; pyproject.toml
  [project.scripts] assesshub, cisco-assess.
- Routes and views: webapp/frontend/src/App.tsx (/snapshots/:id -> CoreSnapshot,
  /snapshots/:id/tools -> Snapshot); webapp/frontend/src/pages/CoreSnapshot.tsx (titles, Overview,
  Trust, InputGap, Inventory, Findings, Device, FailureImpactRow, StructuralLinkRow, ScopeLink,
  identity panel); webapp/frontend/src/pages/core/TopologyPaths.tsx, TopologyScope.tsx,
  ProjectionList.tsx, ProjectionEvidence.tsx (STATE_LABEL, FactView, drawer).
- State meanings: cisco_toolkit/ssot.py abstention_reason and _CENSUS_NOTE;
  cisco_toolkit/ui_projection.py STATES, DOMAIN_STATE_OWNERS, REF_ROLES.
- Lower bounds: cisco_toolkit/impact_assessability.py; ui_projection._topology_impact and the
  impact_scanned_scope limitation; webapp/backend/summary.py IMPACT_BOUND_MARK,
  impact_bound_cell, impact_entry, _keystones, IMPACT_NOT_ASSESSED; webapp/backend/cutover.py
  GATE_* and _worst_blast_radius.
- Trust inputs: ui_projection.TRUST_INPUTS from analyze.DOSSIER_AXIS_INPUTS.
- Lifecycle band names: ui_projection.LIFECYCLE_BAND_ORDER.
- Atlas Scope: webapp/backend/app.py _SCOPE_MOUNT, get_snapshot_scope_view;
  atlas-scope/docs/acceptance-report.md (Verdict section).
- Ingest: webapp/backend/ingest.py run_collection_zip, run_collection_folder (temp workdir removed
  in finally), _allowed_ingest_roots (ASSESSHUB_INGEST_ROOTS).
- Comparison and receipts: webapp/backend/app.py compare, compare_execution;
  webapp/frontend/src/pages/Campaign.tsx (Compare two waves, TrendCanonicalReceipts);
  webapp/frontend/src/pages/Execution.tsx (Bind post-change evidence, PASS rule, legacy runs);
  webapp/frontend/src/components/CutoverPlanner.tsx (Start execution run);
  cisco_toolkit/docmeta.py WEB_ONLY_KINDS, artifact_spec("pir").
- Deletion refusals: webapp/backend/app.py delete_campaign, delete_snapshot, delete_execution (409);
  webapp/backend/storage.py delete_*_if_unreceipted. Purge not implemented: no purge or retention
  route in webapp/backend; decision in docs/decisions/0007-one-application-direction.md D10.
- Data locations and backups: webapp/backend/app.py _platform_default_db, _default_db_path;
  webapp/backend/serve.py _resolve_db; webapp/backend/storage.py _BACKUP_DIR, _BACKUP_KEEP.
- Redaction: webapp/backend/serve.py --redact-folder/--out/--redact-collection/--reuse-out; no
  redaction route in webapp/backend/app.py (_send_file serves unredacted deliverables).
- Collection safety: COLLECT_PARSE_V3_23_0.py TERMINAL_SETUP_CMDS, is_ssh_wire_command,
  ssh_wire_commands; webapp/backend/ingest.py (both engine invocations pass --no-collect);
  cisco_toolkit/attestation.py is_read_only_command; cisco_toolkit/rest_collect.py module
  docstring; portable/README-FIELD.txt OFFLINE / LIVE NETWORK BOUNDARY.
- Next release: PR #630 (W41 G21 punch-list facets; W47 F8 distinct lower-bound, NOT ASSESSED and
  unavailable rendering), open and unmerged on 2026-10-09.
-->
