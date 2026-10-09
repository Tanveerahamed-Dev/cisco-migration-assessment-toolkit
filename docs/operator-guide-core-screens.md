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
  allowed ingest root: by default the Atlas folder on the stick, or the repository root when
  AssessHub runs from a checkout. The `ASSESSHUB_INGEST_ROOTS` environment variable names other
  roots.

For both ingest routes AssessHub runs the real engine offline over the files (`--no-collect`).
Nothing connects to a device. The raw files are staged in a folder under the system temporary
directory, which AssessHub deletes when the run ends (a failed deletion is not reported). Your
own collection folder is only read. AssessHub stores the resulting snapshot, not the raw
captures.

**Open a sample fleet** on the home page loads the bundled demo snapshot, so you can learn the
screens without client data.

## 3. How to read any value

Every value on the core screens carries a state. A value that is not published shows a dash and
a state label with the engine's reason. **A dash is never zero and never healthy.**

| Label | What it means |
|---|---|
| Published | The engine published a value. Read its qualifications: some published values are lower bounds (section 5). |
| Collected, empty | The evidence was collected and holds nothing of this kind. It is not a blind spot. |
| Not collected | A blind spot: the evidence was never collected, or that device was not collected. |
| Not assessed | The engine could not judge it, for example a fleet health with no scored device. |
| Analysis unavailable | That analysis step failed in this run, so an empty result is not evidence of absence. |
| Unverified | The value cannot be trusted: it failed a check (for example its type, a reconciliation, a contradiction with its producer's rule, a duplicate) or its owner failed, so it is not shown as a measurement. |

Three things help you read a value:

- **Evidence ↗** beside a value opens a drawer with its basis, its subject address, its source
  references (each with a role), the engine state where one is published, the qualifications
  and the stored snapshot identity. Raw evidence text is not shown there.
- **Qualifications (N)** appears when a limitation applies to the value. Read it before you
  quote the value.
- **List paging.** Long lists read "Rows X–Y of N projected rows" with Previous and Next. N is
  the number of projected rows in the whole list, not only the rows on this page.

At the bottom of every view, the collapsible **Snapshot and engine identity** panel shows the
stored snapshot's SHA-256 and size, the engine script version and snapshot schema recorded in
it, when it was generated and collected, and the schema version of the running code.

## 4. The core screens

A snapshot opens on its core screens. Five views run across the top: **Overview, Trust,
Inventory, Findings, Topology & Paths**. A **Device** page opens from a linked device name. The
page header also has **Open in Atlas Scope ↗** (when the installed build supports it) and **Tools
and downloads**.

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
- **Unknown evidence:** the engine's count of evidence it could not classify (for example a
  parser exception, or collected content that parsed to nothing), how many of those events are
  unresolved, and the state of each evidence source it read.
- **Single source of truth checks**, the **section census**, **recorded analysis failures** and
  the **limits and qualifications** that apply to this snapshot.

### Inventory

Four tabs: **Devices** (model, health band, move group, finding and coverage roll-ups),
**VLANs** (readiness, STP root and gateway detail), **Endpoints** (with shared-IP and dual-homed
evidence) and **Peers**: cable-map neighbours that the collection did not collect.

### Findings

The prioritised findings, in the engine's own order, with the engine's finding total. Each
finding shows its severity, priority and devices (linked), and opens to the issue, the
remediation and the evidence references. Below the list, **Findings by severity**, **Findings by
category** and **Findings by inventory device** give the engine's own facet totals. A withheld
total keeps its state and reason and is never a zero, and a total the engine publishes only as a
minimum reads `≥ N` (section 5).

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
  - On the core screens (the Device page's **If this device fails** rows and the failure-impact
    list under Topology & Paths) it reads `≥ N`, with its reason on a line below it. Its
    **Evidence** lists a reference with the role `witness`, and its qualification explains the
    rule.
  - A **Findings** facet total that the engine publishes only as a minimum also reads `≥ N`.
  - The Tools page **Failure impact** tab prints it as `≥ N` with the reason.
  - In the cutover plan, a wave's worst-case blast radius reads `≥ N` for a lower bound,
    `NOT ASSESSED` when nothing in the wave could be ranked or its largest count is only a zero
    lower bound, and unavailable for a withheld count. None of them reads as 0.
  - The keystone list and the cutover plan describe it as "LOWER BOUND, at least N endpoint(s)
    stranded", with the reason.
- **Unavailable.** **Analysis unavailable** means that analysis step failed in this run.
  **Unverified** means a value failed a check. Neither is evidence that nothing is there.

## 6. Atlas Scope: a preview

Atlas Scope is a 3-D investigation view of one snapshot. AssessHub serves it at
`/scope/snapshots/<id>/`, opened from **Open in Atlas Scope ↗**, and embeds it as **3-D
investigation** under Topology & Paths. It reads the stored snapshot from AssessHub, and it is
read-only.

It ships in the next release candidate as a **labelled preview** (owner decision, 2026-10-09),
not an accepted product. Its acceptance is not complete: its acceptance report
(`atlas-scope/docs/acceptance-report.md`, graded 2026-10-02/03) records 24 of 39 acceptance
criteria failing and 3 unproven. Atlas Scope has changed since that grade, and no later grade is
recorded. The label is on screen wherever you meet it:

- Atlas Scope's status bar carries a **Preview** label on every view and at every window width.
- AssessHub shows **Preview** beside **Open in Atlas Scope ↗** (on the snapshot header and on
  Tools and downloads) and beside the embedded **3-D investigation** heading, whose view has no
  status bar of its own.

Use it to look around, and confirm any finding on the core screens before you act on it. A quiet
or empty 3-D view is not a clean bill of health.

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
- **Failure impact on a receipt.** When a comparison receipt binds failure-impact rows (its
  rehearsal evidence), the execution run and **Adjacent canonical cutover receipts** show them
  only as the engine reads them live from the bound after snapshot. A lower bound, a value that
  was not assessed and an unreadable row each stay distinct from a measurement and from 0. That
  reading is for display: it is not part of the receipt, and the JSON export holds only the bound
  evidence. **Compare two waves** does not supply this reading.

## 9. Records you cannot delete, and why there is no purge

- A comparison receipt is an append-only decision record. AssessHub refuses, with HTTP 409 and
  the reason, to delete:
  - a snapshot that a receipt names (before, after, or a failure-trial source);
  - an execution run that holds a receipt;
  - a campaign that contains one.
- A campaign without receipts can be deleted from its page.
- **There is no purge in AssessHub, by decision.** The owner decided on 2026-10-09 to keep
  everything: receipts stay immutable, and AssessHub has no in-app purge. The per-campaign purge
  and retention indicator that `docs/decisions/0007-one-application-direction.md` (D10) had
  planned are not built under this decision. Removing a client's data at the end of an engagement
  is a documented manual step outside the application (section 10, *Disposing of client data*).

## 10. Where the data lives, and backups

| How AssessHub runs | Database |
|---|---|
| `Atlas.exe` on the stick | `Atlas\data\assesshub.db`, beside `Atlas.exe` |
| A repository checkout | `webapp/data/assesshub.db` |
| An installed toolkit (`assesshub`) | the user's application-data folder: `Atlas\assesshub.db` under `%LOCALAPPDATA%` on Windows |

`--db <file>` or the `ASSESSHUB_DB` environment variable selects another file.

At every start through `assesshub` or `Atlas.exe`, AssessHub checks the database's integrity and
refuses to serve a damaged one. If the check cannot run (usually because another copy of Atlas
already has the database open), it warns and starts without this protection. When the database
has changed since the last copy and holds at least one campaign, it keeps a timestamped copy in
a `backups` folder beside it, and it keeps the **newest 3** of its own copies. Backups are taken
at start, not continuously. The restore procedure is in `portable/README-FIELD.txt`, under
CORRUPTION.

### Disposing of client data (manual, outside AssessHub)

AssessHub keeps everything and has no purge (section 9). Disposal is a deliberate step you take
with the operating system, at the end of an engagement and only when the client agreement allows
it. It is not a repair: for a damaged database, follow CORRUPTION in `portable/README-FIELD.txt`.
Never edit the database or try to remove single records: receipts are immutable by design. On the
stick the same procedure is in `portable/README-FIELD.txt`, DISPOSING OF CLIENT DATA.

1. Hand over or archive everything the agreement says to keep first: the deliverables, and the
   comparison receipts and execution records they rest on.
2. Stop AssessHub (close the `Atlas.exe` console window, or stop `assesshub`) and close its
   browser tab.
3. Find every copy. Client data can be in all of these places:
   - **Beside the database** (the table above): the database file; a `-journal` file of the same
     name, if one exists; any `.corrupt` copies made during a restore; the `backups` folder
     (start-time copies, and any copy you parked there yourself); and, on the stick,
     `Atlas\data\release-backups` (database copies and hash receipts kept by updates and
     rollbacks).
   - **Engine logs** (`cisco_migration_autofill_v<version>.log`, which name devices and hosts):
     in `Atlas\data` for an engine run started inside the Atlas folder on the stick, otherwise
     in the folder the run was started from.
   - **Beside `Atlas\` on the stick:** `Atlas.data-handoff`, if an update was interrupted. It
     holds the whole data folder.
   - **Folders you chose:** raw collection folders, every `--out` folder and engine output
     folders.
   - **The computer that ran AssessHub:** documents downloaded from it (usually the browser's
     Downloads folder), and anything named `assesshub_*` or `atlas_redact_*` in the system
     temporary folder. AssessHub removes those after each run or download, but a failed removal
     is not reported.
4. Delete them with the operating system, not through AssessHub. Remove the database together
   with `backups` and `release-backups`, so that no older copy survives. The empty folder that
   held them can stay.
5. Deleting a file does not make it unrecoverable on a stick or a disk. Where the agreement
   requires that, follow your organisation's media-sanitisation procedure.

The next start creates a new, empty database.

## 11. Redaction is a command-line step

AssessHub applies **no redaction** to the documents it serves for download: they carry whatever
the stored snapshot holds, which for an ingested collection is the client's addresses, serials
and hostnames. To make a share-safe set, use the command line:

- on the stick, `Atlas.exe --redact-folder <collection> --out <empty folder>`, adding
  `--redact-collection` to scrub cleartext secrets from the raw captures in place, and
  `--reuse-out` only to re-render the same job into its own folder;
- or the engine's `--redact` on a full run.

Redaction keeps hostnames and descriptions on purpose. Read `portable/README-FIELD.txt`,
REDACTION, before anything leaves the site.

## 12. Collection safety

- AssessHub's upload and ingest routes never connect to a device.
- A live SSH collection is an explicit engine run (one without `--no-collect`). Authentication
  failures are never retried, to avoid locking the account.
- **What the engine sends.** The collector sends two session settings of its own,
  `terminal length 0` and `terminal width 511`. Every other string it sends is a command-registry
  entry that passes its whole-string read-only check: a `show` command with no command chaining
  or redirection, and only output filters after a pipe. An entry that fails the check is
  withheld from the session and logged. The engine calls no enable-mode or configuration-mode
  function.
- **What the SSH library sends.** netmiko also writes to the session for itself: on connect, its
  own paging and width settings and Enter keystrokes to find the prompt; on disconnect, `exit`.
- **Platform autodetection.** When a device's `platform` is `auto` (the default when the devices
  file names none), netmiko's autodetection first opens a separate session and sends its own
  identification commands. The engine's check does not cover them, and they can include other
  vendors' commands, such as `display version` or `get system status`. Set `platform` to `ios`
  or `nxos` in the devices file to skip this step.
- Controller REST collection is opt-in. Apart from the login, it sends only GET requests. On a
  controller the read-only guarantee comes from the account's read-only role, not from the
  protocol, so use a dedicated read-only account.
- On the stick, a live collection also needs `--allow-live-network` before `--run-engine`.
  `portable/README-FIELD.txt` has the exact command.

<!--
Owners behind each statement (verified on origin/main 6390b66c, 2026-10-09; section 12 and the
corrections from the W56 review re-verified the same day; the preview labels, section 9's no-purge
decision and section 10's disposal procedure added by W62 on main ec289ab0, 2026-10-09; the
Findings facets, the lower-bound readings and the receipt failure-impact reading that #630 merged
added by the W62 integration on main ddac90e3, 2026-10-09). This block is for maintainers;
correct the prose above when an owner changes.
- One door, --run-engine, loopback-only frozen bind: webapp/backend/serve.py (ENGINE_SENTINEL,
  _run_engine, main: numeric-loopback refusal when frozen); ingest._engine_argv; pyproject.toml
  [project.scripts] assesshub, cisco-assess.
- Routes and views: webapp/frontend/src/App.tsx (/snapshots/:id -> CoreSnapshot,
  /snapshots/:id/tools -> Snapshot); webapp/frontend/src/pages/CoreSnapshot.tsx (titles, Overview,
  Trust, InputGap, Inventory, Findings, Device, FailureImpactRow, StructuralLinkRow, ScopeLink,
  identity panel); webapp/frontend/src/pages/core/TopologyPaths.tsx, TopologyScope.tsx,
  ProjectionList.tsx ("Rows X-Y of N projected rows", page.total), ProjectionEvidence.tsx
  (STATE_LABEL, FactView, Qualifications, drawer); CoreSnapshot.tsx identity <details> (sha256,
  bytes, script_version, snapshot_schema, generated_at, collected_at, code_schema_version).
- State meanings: cisco_toolkit/ssot.py abstention_reason and _CENSUS_NOTE;
  cisco_toolkit/ui_projection.py STATES, DOMAIN_STATE_OWNERS, REF_ROLES. Unknown evidence:
  ui_projection._unknown_evidence; cisco_toolkit/unknown_evidence.py _KIND_META, _SOURCE_ORDER.
- Lower bounds: cisco_toolkit/impact_assessability.py; ui_projection._topology_impact and the
  impact_scanned_scope limitation; webapp/backend/summary.py IMPACT_BOUND_MARK,
  impact_bound_cell, impact_entry, _keystones, IMPACT_NOT_ASSESSED; webapp/backend/cutover.py
  GATE_* and _worst_blast_radius.
- Trust inputs: ui_projection.TRUST_INPUTS from analyze.DOSSIER_AXIS_INPUTS.
- Lifecycle band names: ui_projection.LIFECYCLE_BAND_ORDER.
- Atlas Scope: webapp/backend/app.py _SCOPE_MOUNT, get_snapshot_scope_view;
  atlas-scope/docs/acceptance-report.md (Verdict section; graded at 2dd95d74, unchanged since
  c95de5cc while atlas-scope/ changed in later merges such as #599, #601, #606 and #618).
- Ingest: webapp/backend/ingest.py run_collection_zip, run_collection_folder (temp workdir under
  _engine_temp_parent, removed by shutil.rmtree(ignore_errors=True) in finally; the folder route
  stages a private copy), _allowed_ingest_roots (frozen: the exe folder; else the repository root;
  ASSESSHUB_INGEST_ROOTS overrides); app.py ingest_collection_folder (contain=True).
- Comparison and receipts: webapp/backend/app.py compare, compare_execution;
  webapp/frontend/src/pages/Campaign.tsx (Compare two waves, TrendCanonicalReceipts);
  webapp/frontend/src/pages/Execution.tsx (Bind post-change evidence, PASS rule, legacy runs);
  webapp/frontend/src/components/CutoverPlanner.tsx (Start execution run);
  cisco_toolkit/docmeta.py WEB_ONLY_KINDS, artifact_spec("pir").
- Deletion refusals: webapp/backend/app.py delete_campaign, delete_snapshot, delete_execution (409);
  webapp/backend/storage.py delete_*_if_unreceipted. No purge, by decision: no purge or retention
  route in webapp/backend; the owner's 2026-10-09 keep-everything decision (receipts immutable, no
  in-app purge, manual disposal outside the app) is recorded in docs/NOW.md (W62 handoff); ADR 0007
  D10's planned purge is not built.
- Preview labels (owner decision 2026-10-09, Scope ships as a labelled preview):
  atlas-scope/src/app/PreviewLabel.tsx (ACCEPTANCE_GRADE cache, reconciled to the report by
  PreviewLabel.test.tsx) rendered by StatusBar.tsx; webapp/frontend/src/components/ScopePreview.tsx
  beside CoreSnapshot.tsx ScopeLink, Snapshot.tsx AtlasScopeLink and core/TopologyScope.tsx's
  heading (contract mode, atlas-scope/src/contract-mode/, renders no status bar).
- Disposal locations: storage.py _BACKUP_DIR; portable/make_stick.ps1 release-backups,
  Atlas.data-handoff; cisco_toolkit/__init__.py engine_log_path; ingest.py mkdtemp prefixes
  assesshub_ingest_ and atlas_redact_ under _engine_temp_parent; app.py/deliverables.py/engine.py
  mkstemp prefixes assesshub_*, removed by _send_file or their own finally blocks with errors
  suppressed; storage.py
  _boot_hardening (an absent database is a first boot).
- Data locations and backups: webapp/backend/app.py _platform_default_db, _default_db_path;
  webapp/backend/serve.py _resolve_db, main (boot_hardening=True); webapp/backend/storage.py
  Store._boot_hardening (quick_check refusal, OperationalError warn-and-continue, no copy of a
  campaign-free store, mtime test), _BACKUP_DIR, _BACKUP_KEEP.
- Redaction: webapp/backend/serve.py --redact-folder/--out/--redact-collection/--reuse-out; no
  redaction route in webapp/backend/app.py (_send_file serves unredacted deliverables).
- Collection safety: COLLECT_PARSE_V3_23_0.py TERMINAL_SETUP_CMDS, is_ssh_wire_command,
  ssh_wire_commands, collect (withheld entries logged), connect_device, autodetect_platform
  (netmiko SSHDetect for platform auto/blank), load_devices plat_map (default "auto"),
  NETMIKO_TYPE; no enable()/config-mode call in the engine. netmiko's own writes (read in the
  installed 4.7.0; pin netmiko>=4.1,<5): CiscoIosBase / CiscoNxosBase session_preparation,
  CiscoBaseConnection.cleanup ("exit"), ssh_autodetect.SSH_MAPPER_DICT probe commands;
  webapp/backend/ingest.py (both engine invocations pass --no-collect);
  cisco_toolkit/attestation.py is_read_only_command; cisco_toolkit/rest_collect.py module
  docstring; portable/README-FIELD.txt OFFLINE / LIVE NETWORK BOUNDARY.
- Merged with #630 (ddac90e3): Findings facets: CoreSnapshot.tsx FindingFacets and
  FACET_LOWER_BOUND_CAVEATS (ui_projection._finding_facets). Lower-bound readings:
  core/ProjectionEvidence.tsx FactView lowerBound and ImpactFactView
  (components/ImpactValue.tsx projectionImpactBound), CoreSnapshot.tsx FailureImpactRow,
  core/TopologyPaths.tsx RowFacts; cutover worst case: components/CutoverPlanner.tsx WorstCase,
  webapp/backend/cutover.py _worst_blast_radius (engine.wave_blast). Receipt failure impact:
  webapp/backend/app.py _receipts_with_impacts_views, engine.receipt_impacts_view,
  components/ComparisonDecision.tsx RehearsalImpacts (unavailable without a supplied view),
  pages/Execution.tsx and pages/Campaign.tsx impactsView.
-->
