# 0010: Device console, next-evidence suggestions and the application pack

**Date:** 2026-10-16 · **Status:** accepted. The implementation order is in Consequences. ·
**Decided by:** Claude Code under the owner's explicit delegation · **Related:**
`docs/decisions/0008-engine-computes-interface-displays.md`,
`docs/decisions/0009-protocol-packs-and-dependency-graph.md`, the RC8-P1-F in-app collection design
(PR #668), `cisco_toolkit/traffic_assurance.py`, `cisco_toolkit/attestation.py`,
`COLLECT_PARSE_V3_23_0.py`

## Context

On 2026-10-16 the owner asked whether Atlas should do three things:
- map applications onto the network, as IP Fabric 8.1 now does;
- collect from devices inside the app, with no separate script;
- suggest the next show command, as the Transit AI SSH terminal does.

These findings were fact-checked against primary sources:

- **IP Fabric Application Infrastructure Mapping (AIM).** It first shipped in v8.1.3 (GA 2026-09-23)
  and is a licensed premium add-on (`docs.ipfabric.io` release notes 8.1 and the AIM overview).
  - It correlates a *supplied* inventory (applications, workloads, workload interfaces and flows) with
    the discovered network. The inventory is entered by hand, imported, or pulled from Illumio, today
    the only external provider.
  - It computes the devices an application's flows traverse with the same path-lookup engine IP Fabric
    uses elsewhere, so traversal is modeled, not observed. Its value is the named inventory, the
    per-application roll-up, and the reverse question "which applications depend on this device".
- **Transit.** Transit 6.5.9 (dated 2026-10-01) gates the commands its AI proposes with per-platform,
  default-deny policies:
  - aliases are canonicalized before matching;
  - when a command matches both lists, the block wins;
  - every pipe stage is checked separately;
  - shell escapes are blocked, as are file writes hidden inside read commands (for example
    `show tech-support` to a file or URL).

  Its suggestions come from an LLM, by default a cloud model that receives device output. Its
  local-model mode still depends on a cloud-signed pass that works offline for at most seven days.
- **Atlas today:**
  - **Present.** Endpoint identity, an ACL service map with hit counts, Traffic Assurance over declared
    five-tuples, a whole-string show-only wire gate (`is_ssh_wire_command`), and an independent
    attestation verifier (`attestation.is_read_only_command`).
  - **Missing.** There is no in-app collection: AssessHub ingests finished snapshots or captures
    offline, and live SSH runs only from the command line; PR #668 holds the design. There is also no
    console, no flow evidence, and no named application inventory.
  - **Latent gaps.**
    - The pipe filter accepts `| sort` with any arguments.
    - `show tech-support … file <dest>` passes the grammar. Transit's policies treat it as a write;
      this is not yet confirmed against Cisco documentation for every platform.
    - Platform autodetect sends non-show probes outside the gate.
    - NX-OS `[match=N]` ACL counters are not parsed, so NX-OS hit counts never reach the service map.

## Decision

1. **One engine-owned command policy registry**, `cisco_toolkit/command_policy.py`, keyed by platform.
   **Default-deny:** a command is allowed only when it resolves to a registered form for that platform.
   Anything else is refused, whatever the block list says.
   - **Registered forms.** Each is a policy ID with a command template and typed parameters (an
     interface, a VLAN, a peer address), not an arbitrary string. A printed form may also use a
     *placeholder* parameter, for example `<vlan-N-gateway-ip>` or `<chosen-native-vlan>`. The output
     marks it as a value the engineer supplies. A sent form never has one.
   - **Classes:**
     - `read`;
     - `session_control`: exact strings the SSH transport sends to manage the session. These are
       `TERMINAL_SETUP_CMDS` at session start and the transport's `exit` at teardown, and nothing
       else;
     - `active_probe`: ping and traceroute;
     - `change`: configuration lines;
     - `never`.
   - **Channels.** The catalogue today mixes SSH CLI commands, controller REST paths and offline-only
     names. The registry keys every form by channel:
     - SSH CLI forms follow the rules below;
     - REST forms follow the existing controller boundary: GET requests only, after one authentication
       login per controller;
     - offline-only names are never sent.
   - **Sent versus printed.** The registry distinguishes commands Atlas *sends* to a device from commands
     it only *prints* for an engineer to run.
     - **Sent** (the collector catalogue, the console and `next_evidence`): `read` forms, plus
       `session_control` matched as exact strings. Only these classes may be sent. `active_probe` is
       never sent until a separate decision, and `change` and `never` are never sent at all.
       - Today the command-line collector's `platform: auto` path also sends SSHDetect probes. Decision
         2's gated detection therefore replaces autodetect in the shared collector, so the command line
         and the app both use it. Until it lands, those probes are a disclosed exception and the only
         one.
     - **Printed** (NRFU exports, the validation plan, `compute_remediation_plan`, MOP steps and
       confirm-on-device text): every printed command is a registered form and never `never`.
       `active_probe` and `change` are allowed only here, because the engineer runs them under the
       change process.
       - Comment lines (starting with `!`) are explanatory text, not commands, and are exempt.
       - This keeps today's printed ping, traceroute, remediation and comment lines unchanged.
     - **Provenance references** are not producers. These are engine strings that only name the
       command a fact came from, such as the capture labels in baseline rows, capture integrity and
       parse yield. Each must resolve to a catalogue form, and the structural scan accepts it on that
       basis.
   - **Evaluation order.** Steps 1 and 2 apply to every command; steps 3 to 5 apply to sent SSH CLI
     commands only:
     1. canonicalize aliases;
     2. resolve the command to a registered form and class for its channel, and refuse it if none
        matches;
     3. apply the existing whole-string grammar as a floor (`session_control` uses its exact-string
        allowlist instead);
     4. apply the per-platform block list (write-inside-read forms such as `show tech-support` to a file
        or URL, and shell escapes such as guestshell, app-hosting, run bash and tclsh);
     5. apply argument rules to each pipe stage.
   - **Verifier.** `attestation.is_read_only_command` remains the independent second verifier for sent
     commands. The Wave 0 PR gives it the same exact `session_control` allowlist, as a reviewed change.
     Any change to attestation method text is part of Wave 0's reviewed attestation regeneration
     (ADR 0009 Decision 6).
   - **Class tests.** Producers declare themselves to the registry, and the tests enumerate those
     declarations; they never use a hand-named list.
     - Every command a *sending* producer can emit passes both gates for its class and channel.
     - Every command a *printing* producer can emit is a registered, non-`never` form. Printing
       producers include `compute_validation_plan`, `compute_remediation_plan`, the NRFU export and the
       MOP.
     - A structural scan fails if any module builds a device command string outside a declared producer,
       except provenance references that resolve to a catalogue form.
   - **Rules and edits.** Rules are written from Cisco documentation and verified against real device
     output, never copied from another vendor's policy files. There is no operator-editable policy in
     v1: a policy change is code plus review, and the block list is a floor nothing can relax.
2. **In-app collection is RC8-P1-F (PR #668), not a second design.** Its custody model is kept as
   that design defines it:
   - memory-only credentials;
   - a target guard;
   - host keys verified before any credential is sent, under the policy RC8-P1-F's review settles (its
     revision recommends operator-confirmed first use);
   - **analysis of the original captures first, then secret scrubbing with independent verification**.
     Scrubbed copies are never re-analyzed, because scrubbing can change a verdict, for example the
     SNMP default-community severity;
   - no unattended retries;
   - added by this record: one live job at a time.

   Additions:
   - the command catalogue comes from the policy registry and the packs;
   - a gated `show version` detection replaces the autodetect probes in the shared collector, used by
     both the app and the command line, so a failed login is never retried on a second connection;
   - each device's failure reason (auth-failed, timeout, host-key-refused, unreachable,
     refused-by-guard) becomes an engine fact in `collection_completeness`;
   - CDP/LLDP peers that were not collected are offered as seeds to tick for the next job, never
     followed automatically;
   - a targeted job collects chosen devices × chosen commands;
   - controller REST collection comes in a later increment through the same job boundary.

   Under operator-confirmed first-use host-key acceptance, fingerprints and their algorithm are shown
   before any credential is sent, the acceptance is recorded in the job audit, and a changed key is a
   hard failure. RC8-P1-F's own revision now recommends it, subject to that design's independent review.
3. **A read-only "Run on device" console in the Investigate workspace.** It is a gated request/response
   runner on the RC8-P1-F job boundary, not a terminal emulator.
   - Every command, typed or suggested, must resolve to a registered `read` form for that device's
     platform (decision 1, default-deny). Free text that resolves to no form is refused and never leaves
     the laptop. An allowed batch shows the exact commands and target, and runs only after an explicit
     click.
   - Output passes the in-memory credential barrier and is parsed and analyzed by the owning pack from
     the original capture. The capture is then scrubbed and independently verified before storage, as in
     RC8-P1-F, and the scrubbed copy is never re-analyzed. The result is a timestamped evidence addendum
     in a new snapshot revision.
   - Not allowed: enable, configuration mode, `terminal monitor`, and interactive sub-modes. MCP never
     gains a tool that runs commands or triggers collection.
4. **Deterministic next-evidence suggestions.** This adds item 8 to the ADR 0009 pack contract.
   - **Pack checks.** A check that returns `problem` or `unknown` may declare `next_evidence` entries.
     Each entry names a registered command, the bound object, what it would resolve, and which check
     re-runs.
   - **Other sources.** The dependency graph's unknown links, collection blind spots and `protocol_kb`
     states feed the same list.
   - **Delivery.** `analysis_result/1` serves `next_evidence` beside `confirm_on_device`.
   - **Local model.** It is optional and off by default. A model on 127.0.0.1 may only rephrase the
     engine's explanation. It never selects, ranks or adds commands, and its text is never a run button.
     Its text is labeled "model-phrased, not authoritative" (ADR 0008: the engine's result is the
     answer). The model client lives outside `cisco_toolkit` and the collector, so the static
     `no_llm_runtime` and no-egress import scans stay true for the engine. The engine snapshot is
     produced before any rephrasing can happen, so the snapshot's attestation is unchanged. Model use is
     recorded in the app session or investigation record and shown in the Trust drawer.
5. **An application pack**, registered in `docs/ssot.md` as the owner of the declared application map.
   - **Input.** An operator-declared inventory (CSV or JSON keyed by external id, shaped compatibly with
     AIM), hashed and bound to the snapshot.
   - **Outputs:**
     - workload location: IP → ARP → MAC → switch, port and VLAN;
     - a per-flow Traffic Assurance verdict, forward and return;
     - a per-application footprint;
     - a reverse index from device, link, VLAN, move group or wave to the dependent applications.
   - **States:** `modelled_permit`, `modelled_deny`, `unsupported(<reason>)`, `not_calculated` and
     `not_located`.
   - **Provenance.** Every field is labelled `declared`, `observed` (with a capture pointer) or
     `modelled`.
6. **Observed corroboration, narrowly.**
   - **First**, NX-OS ACL counters are parsed and each hit is bound to its device and ACE.
   - **Then**, an opt-in flow-evidence pack may read on-box state that already exists, by show command
     only: flow monitor caches, ASA connection and translation tables, IOS NAT translations. It uses
     them to suggest candidate flows and to mark a declared flow "seen in cache on device X at time T".
   - This narrowly amends ADR 0009's flow-telemetry exclusion. Flow exporters are never configured on a
     device and Atlas never opens a flow listener. Command forms not yet confirmed against Cisco
     documentation stay disabled until they are.

## Consequences

- **Order of work:**
  - Decision 1 and an empty `next_evidence` field land with ADR 0009 Wave 0. No analysis output
    changes; the only golden change is the reviewed attestation regeneration (module counts and the
    `session_control` method text).
  - The ACL counter fix (decision 6) lands before the application pack.
  - Decision 2 follows ADR 0008 and RC8-P1-H; decision 3 follows decision 2.
  - Decision 4 is populated in Wave 1.
  - Application pack v1 follows Wave 1 in stream order (`docs/NOW.md` rule 9). Its `unsupported(vrf)` and
    `unsupported(nat)` states lift as Waves 2 and 3 land.
- **Workspaces:**
  - Investigate: the console, the root-cause answer and application paths.
  - Fix: confirm on device.
  - Migrate: applications per wave.
  - Cut over: NRFU application checks generated from declared flows.
  - Deliver: the application appendix.

  No per-feature screen is added.
- **Honesty.** Nothing modeled is called observed traffic. An application absent from a sampled cache
  is not proven unused. `not_calculated` never renders as zero dependencies.
- **Rejected:**
  - an autonomous discovery crawl;
  - cloud-LLM or model-chosen commands;
  - an unrestricted interactive shell;
  - bundling or driving Transit;
  - live API integrations with application platforms (offline file import instead);
  - flow collectors or device-side flow configuration;
  - saved credentials in v1;
  - an MCP tool that runs commands;
  - a dedicated application screen.
