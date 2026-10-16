# RC8-P1-F: collect a brownfield assessment inside Atlas

**Status: PROPOSED — docs-only review; implementation held for the foundation.**
Owner decision: 2026-10-16, relayed by the supervisor. Holder: Codex.
Source baseline: `3401627f6fd69bb838a2c921d7f95c77b2373623` on GitHub `main`.
Integrated main `9112a16e4e4d91674ba5cb2881f0d75071c7d78c` with a merge commit;
its knowledge-export changes do not alter the collection owners described here.
This PR contains documentation only. It authorizes no live collection, implementation,
merge, release, device change, or field-qualification claim.
The supervisor's 2026-10-16 foundation decision applies immediately: no implementation PR
until **F0 / ADR 0008 and RC8-P1-H have merged**, this design has independent approval, and
the supervisor explicitly resumes RC8-P1-F. A green design PR alone does not lift that hold.

## Outcome and scope

A Cisco Advanced Services consultant opens **New assessment → Collect from devices**, pastes
addresses or imports a CSV, supplies credentials, reviews the exact targets and read-only SSH
policy, and explicitly starts one collection. Atlas supervises the existing engine in a child
process, shows each device's result, verifies secret scrubbing, ingests a snapshot, and opens
the topology workspace. No terminal or hand-written `devices.json` is required.

The other New assessment choice remains **Import existing collection**. Its ZIP and folder
routes remain offline and cannot acquire network authority. This phase covers Cisco IOS/IOS-XE
and NX-OS SSH collection through the existing engine; controller REST collection, discovery
sweeps, arbitrary commands, configuration mode, device writes, saved credentials, scheduled
collection and unattended retries are outside this design.

## ADR 0008: the engine computes, the interface displays

This design follows `docs/decisions/0008-engine-computes-interface-displays.md` from F0's
`claude/foundation-adr-0008` branch. At inspection it is an uncommitted owner draft, not a
merged main artifact (observed Git blob `34b958fef535dc1c3429b366787128141d425ca1`).
The supervisor's current instruction binds this design; re-read the approved merged ADR and
RC8-P1-H contracts before any resumed implementation. Do not copy F0's draft into this PR.

**Collection, job states and coverage have one engine owner.** That includes seed validation
and canonical plans, target counts, consent/policy decisions, per-device outcomes, aggregate
progress, timeouts/cancellation disposition, partial-result eligibility, evidence verification
and coverage/retention facts. Neither browser code nor `webapp/backend` may compute a parallel
version. A Python function in the webapp backend is still interface code, not the engine.

| Concern | Engine-owned contract | Application responsibility |
|---|---|---|
| Inputs and authorization | Shared devices normalization, validated plan/digest, full roster and counts, effective trust/transport policy and per-job consent | Collect form values, enforce unchanged HTTP security/body admission, forward bounded inputs, display engine validation/results verbatim |
| Collection and lifecycle | Existing collector plus one engine job-state owner; ordered events, transitions, reason codes, deadlines, all-device outcomes and aggregate totals | Spawn/own/reap the child and drain pipes; pass typed OS/control observations to the engine owner; persist/relay its state projection |
| Coverage and partial results | Engine collection-integrity/completeness and verification owners; failed/not-collected denominator, usable-evidence/partial-admission decision | Display the engine's counts, qualifiers and available actions; forward the consultant's choice without recounting or deciding readiness |
| Snapshot, retention and audit | Engine evidence/custody/verification results, digest forms, event/audit facts and admission decision | Perform the approved atomic filesystem/database operations, store the engine result, and navigate using committed IDs |

The engine job-state owner must also run in the supervisor context so it can consume typed
process-exit, bootstrap-failure, deadline, cancellation, cleanup and restart observations when
the child is dead or has emitted nothing. OS process management stays in the application;
the interpretation as failed/interrupted/cancelled/completed and its coverage consequences
stays in engine code. The app must not infer an assessment result from exit code, log text,
event silence or array length. Missing engine status is shown as unavailable, without a
fabricated outcome, zero count or healthy default.

Every new user-visible fact must first gain an engine owner and test, be registered in
`docs/ssot.md` with a reconcile/owner guard, then be exposed through a typed engine projection
and displayed. Persisted assessment facts use the engine snapshot/`ui_projection`; ephemeral
job facts use the same engine-first contract discipline through a versioned job projection.
The application may format, sort, filter and lay out those facts. It must not calculate
percentages, recount devices, merge outcomes into a new verdict or simulate coverage. Job
policy limits likewise come from the engine contract; interface controls display those limits.

RC8-P1-H owns the foundation enforcement and existing summary/topology duplicates. Existing
`summary.py` or interface graph logic is not a model for new collection facts. This feature
must add no interface-computation debt; any temporary existing duplicate stays under F0/H's
closed shrinking debt register and executed two-sided parity gate, without an F exception.
Current verifier helpers below are baseline location pointers, not permission to create new
webapp-owned verification facts. The resumed engine/verification owners must expose the
canonical admission result through the engine contract while preserving producer/verifier
independence; any owner relocation requires explicit registry/tests, not a second implementation.

## Current owners and gaps

These observations are source-bound, not claims that the proposed feature exists:

| Contract | Current source owner | Consequence for this design |
|---|---|---|
| Device file parsing, aliases and platform mapping | `COLLECT_PARSE_V3_23_0.py::load_devices`; `devices.example.json` | Reuse one parser/normalizer; add a memory-input seam, not a second devices schema. The file loader currently also reads password environments and may prompt. |
| Collection and read-only wire vocabulary | `COLLECT_PARSE_V3_23_0.py::connect_device`, `autodetect_platform`, `collect`, `send_cmd`, `ssh_wire_commands`, `is_ssh_wire_command`, `TERMINAL_SETUP_CMDS` | Keep the command owner and capture-integrity semantics. Both auto-detect and driver session preparation require wire-level tests. |
| Frozen live-network permission | `webapp/backend/serve.py::main`, `_main_scoped`; `portable/network_boundary.py` | `--allow-live-network` currently enables a process-wide socket gate; it is not a target-scoped grant. A job adapter must add target confinement. |
| Engine child and offline ingest | `webapp/backend/ingest.py::_engine_argv`, `_assess_tree`; `webapp/backend/app.py` ingest routes | Today these routes run `--no-collect`, with a 600-second timeout, and write a temporary devices file. They cannot carry live credentials or be repurposed into a network route. |
| Request security and resource admission | `webapp/backend/app.py` Host, cross-site read/write, body-size, token and generation-slot middleware | New job routes join existing classifications and guards. No exemptions or changed Host/CSRF semantics. |
| Redaction and evidence custody | engine `--redact-collection`, `_stage_finalize`; `webapp/backend/redaction_verify.py::verify_collection_secret_scrub`; ingest redaction/promotion helpers | A flag, process exit 0 or producer log count is insufficient to retain evidence. Independently verify the exact complete tree. |
| Raw-evidence policy | [ADR 0007 D10 and Amendment 1](decisions/0007-one-application-direction.md) | Keep verified scrubbed evidence. No retention indicator or in-app purge; disposal is manual outside Atlas. |
| Known redaction limits | [W60c residuals](w60c-redaction-residuals-2026-10-12.md) | P2-6/P3-7 and the inherited certified marker-alias escape remain open. Recognized-grammar verification is bounded evidence, not universal secrecy. |
| Legacy SSH | [W59 #636](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/636) | Still open at design inspection. Do not claim its profiles, transport or disclosure are on baseline main. Reconcile its approved merged owner before implementation. |

Graphify supplied navigation leads only; source inspection established these boundaries. No
graph refresh, engine run, local test/build or device contact was performed for this design.

## Consultant flow

1. **Create assessment.** Choose/create a campaign and assessment label, then Collect from
   devices. Explain: read-only SSH still consumes sessions and device CPU, may collect sensitive
   running configuration, and requires the consultant's authority for the listed devices.
2. **Seed devices.** Paste one IP/hostname per line, or select a CSV locally. Show an editable
   preview table with target, engine hostname/label and platform hint (`auto`, `ios`, `nxos`).
   Supply one hint to all rows or override each row. No DNS lookup, probe or connection occurs.
3. **Credentials and trust.** Enter a username/password for this job, optionally override by
   device/group. Import trusted public host-key entries or enter independently verified SHA-256
   fingerprints per target. The supported first increment is password authentication only;
   arbitrary key paths, SSH-agent forwarding and enable secrets are unavailable.
4. **Review and authorize.** Show the engine's final device count and expanded table, platform hints,
   SSH port 22, trusted key bindings, standard/legacy profiles, concurrency and time limits,
   capture handling, and incomplete-evidence implications. An unchecked acknowledgement and
   **Authorize and collect once** are required. Cancel/back makes no connection. Changing any
   target, credential assignment, trust, profile or limit invalidates the prepared authorization.
5. **Collect.** Show queued/connecting/collecting/collected/failed/timed-out/cancelled for every
   seeded device and the current global stage. Show bounded reason codes and command counts;
   never stream terminal output, banners, raw errors or credentials. Provide Cancel and explain
   that closing the tab does not cancel an accepted job. Reopening the campaign reconnects to it.
6. **Verify and ingest.** Show Scrubbing → Verifying → Saving. If some devices failed, require
   **Open partial assessment** after showing the exact failed/not-collected denominator; do not
   label the run complete or those devices healthy. If all failed or no usable interfaces were
   parsed, provide the failure summary without a snapshot/workspace success link.
7. **Open topology.** After committed snapshot creation, open RC8-P1-G's canonical workspace
   for that campaign/snapshot identity. Keep collection failures and evidence coverage visible.
   If that workspace is unavailable, open the existing snapshot page with a clear workspace
   unavailable message. A navigation failure never reruns collection or duplicates a snapshot.

### Seed conversion and validation

The browser may split pasted lines/decode CSV cells in memory as input handling; the engine
alone maps aliases, validates devices, supplies preview labels/counts and returns row errors.
The app sends a bounded JSON body, not a multipart upload that can spool to disk.
Proposed engine-owned limits: 1 MiB seed import, 300 rows, one active live job
per Atlas process, at most four collector workers. These are new job caps, not changes to any
existing budget. Larger imports refuse with a split-job instruction; they never truncate.

CSV headers map to the engine's existing canonical fields `ip`, `hostname`, `platform`, with
the engine's existing address/name/platform aliases resolved by that same owner. A pasted
target supplies `ip`; the engine offers a unique safe hostname label when one is absent, displayed
for confirmation. Credentials are supplied in step 3, resolving engine-required `username`
in memory. Do not infer inventory facts from a label or hint. Unknown platform input follows
the owner's current `auto` normalization and is explicitly shown for confirmation; the UI
must not silently describe it as a recognized platform.

Extract the loader's normalization into a shared pure seam in an approved implementation PR,
with parity tests against existing JSON/list/object/legacy-stream inputs. The GUI creates the
same normalized device records without requiring a physical file. Do not add CSV parsing to
the engine's devices-file format merely for this UI. Reject credential-bearing CSV columns
(`username`, password/secret aliases, `password_env`), unknown columns, duplicate headers,
malformed rows, missing targets, and ambiguous duplicate device identities. Report row numbers
and field names, never echo rejected values (a value itself may contain a secret).

The network-facing adapter adds safety checks absent from the permissive legacy loader:
strings with strict lengths; numeric unicast addresses or validated DNS names; no URL, userinfo,
port, CIDR, range, shell expression, control character, UNC/path or path-like device label.
Reject unspecified, multicast, broadcast, loopback, link-local and metadata destinations,
including mapped-address equivalents. Private unicast networks are allowed. No implicit
neighbor expansion, external web fetch, reverse lookup or target derived from capture text.
Refuse duplicate safe-filename/case/Unicode-normalized labels instead of overwriting captures.
The server calls the same engine validation owner and the child revalidates the bound plan;
the interface must not implement another semantic validator or infer a successful validation.

## Job and credential boundary

The following route names and protocol are proposed, not implemented API claims:

| Operation | Proposed contract |
|---|---|
| Prepare | `POST /api/campaigns/{id}/collection-jobs/prepare`: bounded seeds, public trust, assignments and limits; no credentials or network. Returns opaque preparation ID, canonical plan digest and expiry. |
| Start | `POST /api/campaigns/{id}/collection-jobs`: preparation ID/digest, explicit consent and credential map in one strictly bounded JSON body. Validate campaign, admission and complete plan before consuming the one-use preparation. Returns 202 with opaque job ID. |
| Status | `GET /api/campaigns/{id}/collection-jobs/{job_id}`: bounded typed stage/device events and last sequence. Existing access/cross-site guards; no secrets, raw log tails, targets in URLs or filesystem paths. Polling suffices for phase 1. |
| Cancel | `POST /api/campaigns/{id}/collection-jobs/{job_id}/cancel`: same access/CSRF checks, idempotent cancellation acknowledgement; completion is reported only after child exit and cleanup. |
| Partial admission | `POST /api/campaigns/{id}/collection-jobs/{job_id}/accept-partial`: accepts an already verified result, never reauthorizes SSH. |

The engine preparation contract expires after five minutes; application-generated opaque
job identities and typed clock observations are inputs to its monotonic-deadline owner.
The engine binds the grant to campaign, exact canonical device set, credential
assignments (opaque references only), trust policy, effective profiles, limits, plan digest and
one child instance. Consume atomically; duplicate Start returns the existing job identity or
409 without another child. Concurrent conflicting starts refuse under the existing admission
mechanism; do not queue credential bodies on disk. Cross-campaign job IDs refuse. A job retry
always needs new credentials and new explicit authorization.

Credentials exist only in browser transient form state, bounded server memory, the private
bootstrap pipe, and collector child memory. Clear browser form state after submission/cancel;
no local/session storage, URL, history state, analytics, autofill persistence controlled by the
app, service-worker caching, file input export, crash payload, snapshot or audit serialization.
Use no-store responses and do not echo the Start body. Disable request-body/access-debug
capture on this route without removing any security middleware. Avoid credential-bearing
object repr/tracebacks; use allowlisted constant errors. Username is sensitive too.

Use an anonymous inherited **stdin pipe** for one versioned, length-bounded JSON envelope;
stdout is a separate framed progress channel, stderr is bounded and sanitized in memory.
No pickle, shell command, environment credential, named/public pipe, credential file, argv
secret or reusable secret reference. The child reads exactly one envelope, validates schema,
length, version, job identity/deadline and plan digest, acknowledges receipt, and closes stdin.
Short reads, EOF, oversized/extra frames, unknown fields, missing credentials, bootstrap timeout
or failed acknowledgement refuse before SSH. Limit Start/envelope to 2 MiB; bootstrap to
10 seconds. Parent drops its credential references after acknowledgement; child releases them
when sessions close and terminates. No credential reuse across jobs or fallback to `CISCO_PASS`,
`password_env`, getpass, agent/key search or inherited developer configuration.

Cancellation uses a separate private inherited control event/handle, owned by the supervisor
and polled by the child between waits/commands; POSIX may use an owned control pipe instead.
It carries only cancel intent, no credentials, and is not exposed as an HTTP capability or
named public endpoint. Closing bootstrap stdin cannot disable cancellation. Handle setup
failure refuses startup; child control loss is interruption, subject to the same hard reap.

Application code cannot guarantee physical RAM erasure in Python/JavaScript, prevent a
privileged local process reading memory, or control OS pagefiles, browser password managers,
hibernation and externally enabled full-memory dumps. The promise is no application persistence
or emission; field operating policy must address those residual host risks. Do not claim secure
zeroization, encryption-at-rest or crash-proof secrecy from a pipe.

### Confine the existing live gate to one supervised child

Do not start the GUI/server with `--allow-live-network` or set its environment globally.
The controller and offline ingest children remain network-denied. Add an approved job-bootstrap
dispatch beside the existing frozen `--run-engine` dispatch; it invokes the same
`COLLECT_PARSE_V3_23_0` collector/analysis owners, not a new SSH implementation. Existing CLI
semantics remain separately tested. The job path must validate the envelope and install its
target guard **before** applying the existing live-flag permission or importing code that can
open sockets. A live intent in child argv contains no credentials and is insufficient by itself:
absence of a valid parent pipe/envelope refuses. Never temporarily unlock the server process.

Only the child receives the existing `--allow-live-network` intent. Its additional guard
restricts connects to approved numeric destination/port tuples; the existing boolean gate
alone would permit arbitrary outbound traffic. Hostname resolution occurs only after consent,
through the host's configured resolver, for the finite authorized names. Show beforehand that
DNS queries may be sent. Admit and pin all answers after applying the same destination rules;
mixed disallowed answers, resolver failure or ambiguity refuse that target. No re-resolution
on reconnect, address fallback outside that set, search-based discovery or proxy/jump host.
Bind the resolution map into the job's audit result. DNS changes cannot redirect later retries.
Allow only the bounded resolution phase's resolver traffic and then target TCP/22. Do not
modify global DNS settings. Unsupported resolution/confinement platforms fail closed.

The process socket wrapper is defense in depth, not an OS sandbox. Enforce the same target
binding at collector construction/connect, disable ambient proxy/config behavior, and test
every frozen/socket/async path the adapter uses. No device-originated path, script, dynamic
command or deserialized executable is run. The server stays numeric-loopback-only; CSRF,
Host, auth, read protections and existing offline socket guard remain unchanged.

### SSH trust and transport policy

Baseline `connect_device`/`autodetect_platform` do not explicitly configure strict host-key
verification. This design therefore requires a new tested host-key input seam; it does not
claim today's default establishes trust. Before sending credentials, verify the server's
public host key against the job's independently supplied trusted fingerprint/known-host entry,
bound to the normalized name, pinned address set and port. Cover auto-detection, reconnects
and normal driver sessions equally. Unknown, missing, changed or mismatched keys fail that
device before authentication. No AutoAddPolicy, silent TOFU, global known-host mutation or
"ignore mismatch" control. Phase 1 has no untrusted key-discovery shortcut; consultants obtain
trust material out of band and enter/import it in the app.

Standard SSH is the default. Legacy transport is a separate, initially unchecked, per-device
consent in addition to live-network consent. It must consume W59's approved profile vocabulary,
two-level row/run authorization, explicit-platform rule and negotiated-session disclosure;
never copy algorithm lists into the UI or silently downgrade after a standard failure. Show
the weaker profile and exact affected devices before Start. If W59 is unmerged/unapproved or
the packaged legacy provider is missing/refused, legacy selection is unavailable/refused.
Baseline `portable/windows-x64-requirements.lock` pins Paramiko 4.0.0; hiding a legacy checkbox
does not establish W59's standard-profile boundary. Collection admission must also verify an
approved provider/policy enforces W59's default-profile restrictions before any authentication,
including auto-detection. If that default boundary cannot be enforced, disable/refuse Collect
entirely; do not call the existing transport modern merely because no legacy option was chosen.
Do not bundle an unreviewed provider, change a dependency pin or weaken authentication/trust
to enable the feature. Bind effective profile and negotiation evidence to each device/job.

## Supervision, progress and failure semantics

The approved implementation needs engine-owned typed progress events and a job projection
at the existing engine collection boundaries. Never parse human logs to establish success.
The engine computes event/state transitions, aggregate progress and coverage. Events carry protocol version,
job/device opaque IDs, strictly increasing sequence, stage, attempt/command counts, time and
closed reason codes; no passwords, usernames, raw outputs or arbitrary exceptions. Browser
labels are mapped from the validated plan. Event size is capped at 16 KiB, retained status at
2 MiB; coalesce progress updates while preserving each device's final outcome and cancellation.
Pipe drains must run while the child runs so a full progress/stderr pipe cannot deadlock it.
Coalescing may relay a newer complete engine projection; transport code must not fold events
into its own job state, progress counter or coverage verdict.

Keep existing per-connect/auth/command deadlines and authentication-no-retry behavior. Add
an explicit typed terminal-failure path for auto-detection: baseline `autodetect_platform`
catches all exceptions and returns `ios`, so an auth/trust refusal can otherwise be followed
by a second driver connection. Propagate auth, host-key, consent and deadline refusals without
fallback or another authentication attempt; preserve ordinary platform-detection semantics
only for nonterminal outcomes. This is a required adapter correction, not current behavior.
Add these stricter job bounds: device wall deadline 20 minutes, job wall deadline 60 minutes,
post-collection scrub/verify/ingest stage 600 seconds, cancellation grace 5 seconds then forced
termination/reap within another 5 seconds. The current offline ingest 600-second cap remains
unchanged. Device timeout includes auto-detection, connection retries and command time; neither
device nor job timers reset on an event/reconnect. A device timeout closes its connection;
if an uncooperative collector thread cannot be stopped safely, terminate the whole child and
mark every unfinished device interrupted. Do not claim thread cancellation from Future.cancel.
The exact proposed caps are design-review choices; implementation cannot silently increase
them or relax existing test/measurement budgets.

The 600-second post-collection bound and overall job deadline include partial acceptance;
the UI displays the earlier expiry. All SSH sessions and credential references are closed
before waiting. Expiry refuses snapshot admission, releases the generation slot after safe
cleanup and records `partial_acceptance_expired`; a disconnected tab cannot hold it indefinitely.

The supervisor owns a hidden child and descendant process group (Windows Job Object with
kill-on-close; equivalent process-group ownership on POSIX), working directory and generation
slot until exit and cleanup. It forwards Cancel to the engine owner, which stops scheduling
and requests cooperative connection close; process management enforces the hard reap deadline.
Parent exit, child crash, broken pipe, malformed events,
missing terminal event and lost child identity cannot become success. Watchdog and restart
recovery must handle a process dying during bootstrap/import; no unbounded wait/receive.
After restart the engine owner marks nonterminal durable job records interrupted; never resume collection or
recover credentials from disk. A disconnected browser does not transfer supervision.

Proposed engine-owned job states: `prepared → authorized → starting → collecting → scrubbing → verifying →
awaiting_partial_acceptance (if needed) → ingesting → completed | completed_partial`.
Refusal/failure/cancellation/interruption are terminal; timeout is a distinct failure reason.
No terminal cancellation transitions to completed when a late child exits. A final atomic
commit point arbitrates cancel versus ingest: cancellation winning the lock prevents commit;
commit winning returns the committed snapshot and rejects further cancellation as already
complete. Engine-published counts always include all original seeds, including
failed/skipped/cancelled ones. The interface consumes projected state/totals without recomputation.

Only existing engine read-only command vocabulary and session preparation may reach the wire.
Use least-privilege AAA with show/operational access, no enable escalation, config mode,
save/write, reload, file transfer or arbitrary CLI. Preserve terminal paging/width setup and
its failure metadata; these alter session presentation, never configuration. Audit Netmiko
driver preparation and SSHDetect commands against the permitted operational vocabulary too;
an unknown driver write refuses instead of bypassing the collector allowlist. Capture timeouts,
prompt-fallback, command authorization errors, terminal-setup failures and parse gaps retain
their existing integrity qualifiers. Successful SSH is not a complete/healthy assessment.

## Completion, raw evidence and audit

Each job gets a private, randomly named staging directory under the resolved Atlas data root,
outside code/bundle/repository trees and outside static/download routes. Use current-user-only
ACLs, physical-directory/link/reparse/hardlink checks and no caller-selected output paths.
Fail preflight on insufficient bounded storage or unsuitable permissions. Maintain a frozen
file/member census, limits and stable hashes; resource exhaustion is a refusal, not truncation.
The adapter needs a 500 MiB total staging-byte cap and 20,000-file cap, no weaker than existing
ingest tree limits; individual verifier/container limits continue to apply. All outputs count,
including diagnostic and incomplete files. Abort writers when bounds are reached.

Job credentials must not land on disk even if a device echoes them. Install a job-aware,
in-memory credential sink barrier before engine/file logging, capture writes, exceptions,
sidecars and artifacts; include username and password plus declared encoding variants. Structured
events are allowlisted, not sanitized arbitrary strings. Unclassifiable/undecodable credential
carriers refuse the sink, with a constant error. Do not persist raw stderr then scrub later.
Existing engine exception logging and file-input custody are not safe substitutes. Parity-tested
memory inputs must never be serialized wholesale into the run manifest, input binding, snapshot,
temporary devices file or log. Non-secret roster/provenance may be persisted separately.

Other device-originated secrets can exist in private working captures during analysis. Those
are sensitive staging, never retained evidence, downloads, support ZIPs, backup inputs or static
files. Apply the engine's `--redact-collection` after analysis, then independently call
`verify_collection_secret_scrub` on the final physical tree. Require a nonempty verified capture
set and reconcile every file against the writer census: every `uncovered` member must be
individually handled by an appropriate existing verifier or refuse the whole retention. Never
interpret an excluded JSON sidecar as automatically clean. Require current completion/custody
records, stable hashes and no incomplete/unsafe marker; recheck immediately before promotion.

Only that verified scrubbed tree can enter retained storage, digest-bound to the resulting
snapshot. The backend passes a server-owned verified tree handle to the offline ingest core;
do not post arbitrary paths to `/ingest-folder` or broaden its allowed roots. Its child remains
`--no-collect` with no credentials or live grant. Preserve snapshot validation (finite JSON,
usable device/interface evidence), summaries, engine-owned coverage and persisted-byte digest
forms. Store the full failed seed roster as collection provenance, without synthesizing healthy
snapshot devices. Atomically join job/result/campaign/snapshot identity; repeated completion
must return the same snapshot. Crash between file promotion and database commit leaves an
unpublished orphan for recovery, never a workspace pointing at missing/unverified evidence.

Successful output stays a client-confidential in-app assessment, with original topology
identifiers as needed; secret-scrubbed does not mean anonymized or share-safe. Export continues
through the separately verified `--redact-folder` path and its artifact-family checks. Preserve
all W60c residuals explicitly; do not claim this design fixes them or treat verifier success as
universal privacy/field qualification. Independent design approval must assess those known
limits before implementation is authorized; any new failing secrecy case blocks the feature.

Retain verified scrubbed captures and non-secret audit records under D10/Amendment 1 until the
operator's manual engagement disposal. No TTL, in-app purge or retention indicator is added.
Ephemeral unredacted staging is removed after successful promotion and on every refusal,
cancel, timeout or failure, with startup recovery for abandoned workspaces. A failed cleanup
is a separate `cleanup_required` condition that blocks further collection until the operator
removes that exact owned staging tree outside Atlas; never silently retain it as clean or
backup it. Permission/disk/crash failures can leave sensitive staging: show a bounded local
recovery instruction, keep it inaccessible to routes, and include its location in the manual
disposal documentation. Deletion on flash/SSD is not secure erasure.

The existing [operator disposal procedure](operator-guide-core-screens.md#disposing-of-client-data-manual-outside-assesshub)
and `portable/README-FIELD.txt` must enumerate new staging/retained-job locations alongside
database/journal/backups, release-backups, updater copies, exports, logs, OS temp, browser data
and other copied media before implementation ships. Do not back up an active staging tree.

Persist an append-only, versioned local job audit with job/campaign IDs, application/source
identity, plan digest, non-secret target and resolution/trust bindings, consent time and local
session identity (not a falsely authenticated human signature), limits/effective profiles,
per-device outcomes, cancellation/timeout/interruption, scrub/verifier scope and digests,
snapshot ID plus digest form, and cleanup outcome. No credential values, credential hashes,
private keys, request bodies, arbitrary device error text or raw log tails. Audit must be
available before network starts; write failure refuses startup or aborts an active job.
Wall-clock timestamps are local observations, with monotonic durations for deadlines.
Audit is customer data and can be edited by a privileged local user: no tamper-proof,
trusted-time, operator-identity or non-repudiation claim. Backup includes committed safe records
only; unknown/incomplete jobs remain visibly interrupted after recovery.

## Threat model and mandatory counterexamples

Assets: credentials, device availability/configuration, client evidence, snapshot integrity,
authorization scope and host storage. Trust boundaries: browser → loopback API → child IPC →
SSH/DNS peer → staging → independent verifier → durable store/workspace. Threat actors include
a drive-by website, malformed import, compromised/misidentified SSH peer, concurrent local
client, accidental repeat/cancel and process/media failure. A compromised OS or modified Atlas
binary is outside the app's enforcement boundary and remains a deployment risk.

| Threat | Required mitigation | Closing test evidence |
|---|---|---|
| Drive-by CSRF, hostile Host/DNS rebinding, cross-campaign job theft | Existing guards before body/child work; campaign/job ownership; no credential CORS exception | Reject cross-site/missing/forged headers and foreign IDs, with zero SSH/resolver contacts and no secret persistence |
| CSV/target SSRF, DNS redirection, path collision/injection | Shared loader plus strict job adapter; finite authorized names, pinned valid addresses/port; physical server-owned paths | URL/userinfo/CIDR/UNC/traversal/mapped/link-local/metadata, mixed DNS answers, changed DNS and normalized filename collision all refuse |
| Credential exfiltration via request logs, errors, argv/env, captures or telemetry | Memory pipe; sink barriers; no-store; no ambient auth; closed progress/errors | Sentinel scanners over every physical/logical sink and transport; inject echo/banner/auth-error/encoded carriers |
| MITM/legacy downgrade | Verify trusted key before auth on every SSH path; W59 double consent; no fallback | Unknown/changed key sends no credential; default failure never loads legacy provider; stale/ambiguous consent refuses |
| Device configuration/write or unauthorized extra probe | Engine-owned operational allowlist plus driver/detect wire checks; pinned target set | Fixture records every command/auth/connect; config/enable/write/transfer and off-roster destinations cause failure |
| Hanging child, pipe flood, device stall or orphaned descendant | Monotonic deadlines; concurrent pipe drains; bounded events/storage; owned process tree | Kill during import, blocked read, malformed/flooded IPC, slow device, parent death, cancel race and restart converge to bounded failure/reap |
| False success from partial collection or producer-only scrub | Full seed denominator, typed outcomes, independent physical verification and atomic ingest | One failed device remains failed; zero usable evidence refuses; missing/changed/uncovered/unsafe member blocks retention and navigation |
| Raw evidence leak or stale/cross-job promotion | Private staging, exact member/digest binding, no static access, cleanup/recovery | Links, swapped files, disk full, denied cleanup, orphan promotion and foreign receipts cannot produce completed state |
| Forged audit/identity or overclaimed redaction | Local observed audit with explicit scope/limits and residuals | Audit failures stop new SSH; restart preserves negative states; no golden/sample or authority-state rebaseline |

## Hosted test plan and approval gates

No new test code is included in this design PR. All following execution belongs on ephemeral
GitHub-hosted runners, with synthetic inputs only and **no real device contact ever**.

1. **Whole-job fake SSH fixture.** Bind a deterministic loopback SSH server with a generated
   test host key and IOS/NX-OS-like prompt, exact engine command responses and wire transcript.
   Drive the real UI/API Start → actual supervised engine child → redaction → independent verifier
   → offline ingest → stored snapshot → workspace handoff. Do not stub collection/subprocess/
   redaction/store to manufacture end-to-end success. The production adapter refuses loopback
   targets: use an explicit test-only dependency-injected endpoint policy in the source harness,
   absent from frozen production entry points and unavailable through HTTP/argv/env. Prove that
   isolation independently; do not add a product loopback-exception switch for CI. Resolver
   tests use an injected finite fake, never a real external resolver. Frozen tests independently
   exercise bootstrap/socket denial, process supervision and synthetic offline handoff; any
   missing packaged whole-job coverage stays NOT VERIFIED rather than weakening destination policy.
2. **Wire/trust/consent refusals.** Auth denied (one attempt), wrong/unknown/missing/rotated key
   before password, refused terminal setup, unsupported platform/profile, legacy with one
   consent missing, ambiguous/stale target consent, no provider, no gate/no pipe/no grant,
   a legacy-only peer under standard consent and a provider unable to enforce the default policy,
   ambient live/password environment and unexpected driver commands. Record commands for
   auto-detect and reconnect as well as explicit-platform collection. Assert no real sockets
   outside the fixture and no configuration/device-write commands.
3. **Leak scanner.** Use unique synthetic username/password sentinels per device and run on
   success, all-failed, partial, cancellation, refusal, timeout and injected crash. Inspect argv,
   environment, HTTP responses/headers/history, browser storage/cache, progress, parent/child
   stdout/stderr and structured/file logs, every staging/retained filename and byte, database
   and journal/backup copies, snapshots, run manifests/custody, error/incomplete markers,
   generated documents/archives, CI logs and uploaded artifacts. Scan UTF-8/UTF-16, JSON,
   URL/entity/base64/escape variants and format-aware OOXML/archive payloads; raw byte grep
   alone is insufficient. File-write interception must also assert no transient disk write,
   because an end-of-job scan would miss a deleted credential file. Include an intentional
   leaking negative control to prove scanner failure. Never upload failing secret-bearing output;
   CI credentials are synthetic, and reports use IDs/counts rather than echoing sentinels.
4. **Safety and resource refusals.** Exercise every threat-table counterexample, import caps,
   bootstrap deadline/EOF/oversize/unknown-version, worker/session caps, disk/file/event budgets,
   exact deadline handling (including partial-acceptance expiry), private control-handle loss,
   cancellation during bootstrap/authentication/command reads, cancel/commit race and killed-child/parent recovery on Windows and
   Linux. Confirm request rejection precedes any child, DNS or SSH effect. Prove server/offline
   child gates remain denied during and after live-job authorization.
5. **Custody/partial/retention.** Test at least two devices with one timeout, complete failure,
   prompt fallback, empty parser output, uncovered/binary members, sidecar secrets, post-verify
   mutation, redaction residue (including preserved W60c known cases), interrupted promotion,
   cleanup denial and repeated completion. Partial acceptance cannot discard a failure or
   increase collected counts. Test a verified complete path as a positive control, plus no
   snapshot on redaction/custody failure and no duplicate snapshot after a retrying client.
6. **Regression and packaging.** Existing shared-device-loader inputs must retain parity;
   current offline ingest never connects. Require unchanged golden/sample bytes, complete
   current Python/frontend/distribution/portable gates, closed route/write-site inventories,
   OpenAPI types when routes exist, and independent applied-source refutation. Add executed
   owner/consumer tests that forge interface totals, reorder/drop events, supply missing engine
   status and kill the child before its first event: only the engine owner may produce state,
   progress and coverage, and every display must equal its bound projection. Pin each new fact
   to the SSOT registry/reconcile or owner guard and F0/H's shrinking interface-debt/parity gates.
   A backend Python recount is a failing duplicate just as a browser recount is. Keep every
   existing guard/test/budget. Packaging proof never substitutes for live field acceptance.

For this docs-only PR: Rule-7 privacy and commit/message/per-parent/publication marker scans
before each push; all 15 current protected contexts SUCCESS on the exact final PR head (or
its verified tree-equivalent GitHub test merge). CodeQL and every applicable workflow retain
their own terminal results. Post final check evidence on the PR, then **STOP for independent
design review**. Green CI checks documentation integration, not implemented collection or
design approval. Implementation PRs may start only after **F0 / ADR 0008 and RC8-P1-H have
merged**, independent approval of this exact design/open decisions is recorded, and the
supervisor explicitly resumes this row; each must independently stop at 15/15. No merge,
release, real-network trial or golden/sample regeneration is authorized here.

## Coordination and implementation seams after approval

The [live board](NOW.md) owns status and one-writer assignment. The named companion streams
were not listed on baseline main's Active table when inspected. Their local boards subsequently
showed G's Explorer-centred workspace on `codex/rc8-topology-workspace`, P0-C's installer work
on `codex/rc8-desktop-installer` and P1-E's queued native window on `codex/rc8-desktop-window`.
Those are unmerged coordination leads; interfaces below are proposals for their holders,
not evidence of their approval or delivery. Reconcile their current rows/PR
heads before implementing, and preserve every board handoff during main integration.

| Workstream | Handoff and ownership boundary | Required reconciliation |
|---|---|---|
| F0 / ADR 0008 and RC8-P1-H, foundation | F consumes the merged engine-first/SSOT enforcement, projection and shrinking-debt/parity contracts. Collection, job states and coverage remain engine-owned. | Hard implementation hold until both foundation workstreams have merged; supervisor resumes F. Design approval or one foundation PR alone is insufficient. Reconcile H's complete workstream status, not merely its first summary PR. |
| RC8-P1-G, topology workspace | F returns committed campaign/snapshot identity, verification scope and complete collection-outcome provenance. G owns canonical navigation/rendering and engine fact projection. | Confirm route/partial-warning contract in NOW; fallback to existing snapshot page until G is ready. No snapshot schema or topology fact invented by F. |
| RC8-P0-C/P1-E, desktop packaging | Desktop holder owns frozen bootstrap entry, inherited stdin handles, hidden child/process group, private data paths, restart recovery and installed capability admission. F owns collection protocol and gate semantics. | Confirm Windows pipe/Job Object behavior, loopback server profile, early target guard and default-denied offline child in NOW. Missing packaged capability disables Collect with an actionable explanation. |
| W59 #636 | SSH owner supplies approved profile/consent/negotiation semantics. F renders and binds them. | Re-read merged owner, pins and consent restrictions; no silent transport import or separate algorithm policy. |
| Redaction/custody owners | Existing producer, independent verifier, raw-input/finalization and store bindings remain authoritative. | Resolve recognition limits and metadata member coverage without waiving tests or certifying excluded files. |

Implementation decomposition is deferred to the supervisor after the foundation hold is lifted.
This row finishes only this phase-1 design/threat-model PR and stops at 15/15 for review.
No implementation PR or new workstream starts here; shared-file assignments are reconciled
only when the supervisor resumes the row.

Independent review must decide the proposed numeric caps, strict out-of-band host-key workflow,
supported credential mode and W59 dependency, desktop confinement feasibility, and treatment of
the preserved W60c privacy limits. Until that review is approved, implementation and runtime
readiness are **not verified**. Even an approved design stays on hold until F0 and RC8-P1-H
have merged and the supervisor resumes this row. Approval is not authority for live field collection.
