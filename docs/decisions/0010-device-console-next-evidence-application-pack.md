# 0010: Device console, next-evidence suggestions and the application pack

**Date:** 2026-10-16 · **Status:** accepted. Implementation follows ADR 0008, ADR 0009 Wave 0 and
RC8-P1-F. · **Decided by:** Claude Code under the owner's explicit delegation · **Related:**
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
   - **Evaluation order:**
     1. canonicalize aliases;
     2. apply the existing whole-string grammar as a floor;
     3. apply the per-platform block list (write-inside-read forms, shell escapes such as guestshell,
        app-hosting, run bash, tclsh);
     4. apply argument rules to each pipe stage.
   - **Classes:** `read`; `active_probe` (ping and traceroute, disabled until a separate decision);
     `never`.
   - **Producers.** The collector catalogue, pack confirm-on-device commands, `next_evidence`, the
     console and NRFU exports all draw from this one registry. `attestation.is_read_only_command`
     remains the independent second verifier.
   - **Class test.** A test enumerates every producer from its registry and fails if either gate
     refuses any command that producer can emit.
   - **Rules and edits.** Rules are written from Cisco documentation and verified against real device
     output, never copied from another vendor's policy files. There is no operator-editable policy in
     v1: a policy change is code plus review, and the block list is a floor nothing can relax.
2. **In-app collection is RC8-P1-F (PR #668), not a second design.** Its custody model is kept as is:
   - memory-only credentials;
   - a target guard;
   - strict host keys;
   - independent secret-scrub verification before offline ingest;
   - one live job at a time;
   - no unattended retries.

   Additions:
   - the command catalogue comes from the policy registry and the packs;
   - a gated `show version` detection replaces the autodetect probes, so a failed login is never
     retried on a second connection;
   - each device's failure reason (auth-failed, timeout, host-key-refused, unreachable,
     refused-by-guard) becomes an engine fact in `collection_completeness`;
   - CDP/LLDP peers that were not collected are offered as seeds to tick for the next job, never
     followed automatically;
   - a targeted job collects chosen devices × chosen commands;
   - controller REST collection comes in a later increment through the same job boundary.

   Operator-confirmed first-use host-key acceptance (fingerprints shown before any credential is sent,
   recorded in the job audit, a changed key is a hard failure) is proposed to the RC8-P1-F reviewer.
3. **A read-only "Run on device" console in the Investigate workspace.** It is a gated request/response
   runner on the RC8-P1-F job boundary, not a terminal emulator.
   - Every command, typed or suggested, is evaluated by the engine policy; a refused command never
     leaves the laptop. An allowed batch shows the exact commands and target and runs only after an
     explicit click.
   - Output passes the credential barrier and redaction and is parsed by the owning pack. It becomes a
     timestamped evidence addendum that the engine re-analyzes into a new snapshot revision.
   - Not allowed: enable, configuration mode, `terminal monitor`, and interactive sub-modes. MCP never
     gains a tool that runs commands or triggers collection.
4. **Deterministic next-evidence suggestions.** This adds item 8 to the ADR 0009 pack contract.
   - **Pack checks.** A check that returns `problem` or `unknown` may declare `next_evidence` entries.
     Each entry names a registered command, the bound object, what it would resolve, and which check
     re-runs.
   - **Other sources.** The dependency graph's unknown links, collection blind spots and `protocol_kb`
     states feed the same list.
   - **Delivery.** `analysis_result/1` serves `next_evidence` beside `confirm_on_device`.
   - **Local model.** A model on 127.0.0.1 may only rephrase the engine's explanation. It never
     selects, ranks or adds commands, and its text is never a run button.
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
  - Decision 1 and an empty `next_evidence` field land with ADR 0009 Wave 0, golden output unchanged.
  - The ACL counter fix (decision 6) lands before the application pack.
  - Decision 2 follows ADR 0008 and RC8-P1-H; decision 3 follows decision 2.
  - Decision 4 is populated in Wave 1.
  - Application pack v1 takes the engine slot after Wave 1. Its `unsupported(vrf)` and
    `unsupported(nat)` states lift as Waves 2 and 3 land.
- **Workspaces:**
  - Investigate: the console, the Why view and application paths.
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
