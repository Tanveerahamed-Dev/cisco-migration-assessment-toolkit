# RC8-P1-F: in-app read-only collection — revised design and threat model

**PROPOSED, docs only; independent re-review required.** Holder: Codex, 2026-10-16.
The [independent review of `961f65cd`](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/668#issuecomment-6214268613)
was **BLOCKED: five P2 and six P3 design findings**, despite 15/15 CI. This revision replaces
that design; its resolution ledger below is a specification, not implementation verification
or approval. No code, test, dependency, workflow, golden or sample change is included.

Source observations began at main `3401627f`; main `9112a16e` and then `d73d33e2` are integrated
by merge commits. Current source remains the owner of existing behavior. New engine interfaces,
memory-backed evidence and command-policy facilities below are proposed, not present on main.

**Implementation hold:** no implementation PR until the supervisor verifies that F0/ADR 0008
and RC8-P1-H foundation work have merged, this design is independently approved, and explicitly
resumes F. Use immutable PR merge receipts and Git ancestry/owner acceptance records for those
predicates. An Active-table row disappearing under NOW rule 8 is neither failure nor proof of
the gate; row presence is not a prerequisite. Design CI, a merged design PR, and a partial H
delivery do not self-authorize implementation. No merge, release or device contact here.

## 1. One app, one engine owner

The committed [ADR 0008 at PR #672 head `8fd9e520`](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/blob/8fd9e52076024380e2f49d69d508a56848a85efb/docs/decisions/0008-engine-computes-interface-displays.md)
owns the five-workspace Atlas direction: **Investigate** (default), **Fix**, **Migrate**,
**Cut over**, **Deliver**. New assessment lives at the engagement home. The topology/cable map,
Browse drawer and answer panel belong to Investigate; the shared Find bar, Trust drawer and
snapshot selector expose engine answers and evidence. No separate Explorer or `/scope` entry,
new console workspace, Network tab, Inventory tab or second frontend is proposed. The native
window is a target shell; today's launcher/browser behavior is not claimed already replaced.

The supervisor's six collection/command additions in the current instruction are binding here
and intended for ADR 0010. At inspection PR #675 contains ADR 0009 protocol packs, not a published
ADR 0010 file. This design does not claim that future ADR or `cisco_toolkit/command_policy.py`
has landed. Reconcile its eventual authoritative record before resumed implementation; do
not edit or copy another workstream's draft to make a dependency appear complete.

| Concern | Sole fact/policy owner | App responsibility |
|---|---|---|
| Seeds, selected scope and caps | Engine device normalization, policy expansion and preflight plan | Decode input cells, forward values, display engine rows/errors/counts and available actions |
| Network, trust and commands | Engine destination/consent policy, command registry and session owner | HTTP security and private IPC/process mechanics; forward explicit operator decisions |
| Job and per-device outcomes | One engine job-state reducer, including parent-side OS observations when the child is dead | Spawn/drain/reap; relay observations; persist and display the typed projection |
| Progress, failure reasons and coverage | Engine `collection_completeness`, capture-integrity and assessment owners | No recount, inferred percentages, absence verdict or log-derived success in browser/backend |
| Analysis and persistence admission | Engine analysis of original bytes, then engine redaction and independent verification | Atomically store the admitted snapshot/evidence; navigate using committed identities |

Backend Python is interface code too. New user-visible facts must first have an engine owner
and owner/reconcile tests, an SSOT registration, then a typed projection. Job facts use a
versioned engine job projection before a snapshot exists; persisted assessment facts use
the engine snapshot/`ui_projection`. Formatting/sorting/filtering/layout are allowed; deriving
a new verdict/count is not. Missing engine output displays unavailable, never healthy or zero.
RC8-P1-H owns the shrinking interface-debt register and executed two-sided parity gates.
This feature adds no interface-computation exception. Independent verifier implementation
remains independent of its producer even if its current webapp location is later reconciled.

## 2. Consultant flow and the two job types

1. At engagement home choose **New assessment → Collect from devices**, or the existing
   **Import existing collection** offline route. Offline import never acquires live authority.
2. Paste IPs/hostnames or import a CSV. The engine returns a preview with canonical device
   labels, addresses, `auto`/IOS/IOS-XE/NX-OS hints, row errors and counts. Hints are editable
   per device. No DNS, socket or probe occurs during preview/preflight.
3. Choose **Assessment collection** (the engine's approved platform bundle), or **Targeted
   collection** (chosen devices × chosen registered read commands). The engine shows the exact
   expansion, prerequisite commands, files/bytes/time reservations and scope not requested.
4. Select an engine-admissible batch, enter per-job credentials and choose trust/transport policy.
   The app displays the engine's preflight and requires an unchecked consent plus **Authorize
   and collect once**. Changed targets, command arguments, profile, credentials assignment,
   trust or caps invalidate the prepared grant. There is no scheduled or automatic continuation.
5. The engine job projection supplies per-device progress and qualified failures. A first-use
   key prompt, if selected, occurs before authentication as described below. Cancel is explicit;
   closing a tab is not cancellation. Reopening reconnects to that job's projected status.
6. The engine analyses **original captures in memory**, then scrubs, verifies and admits safe
   persistence. The app displays those stages, the engine's full job denominator and reasons.
   A partial assessment needs **Open partial assessment**; no usable evidence means no snapshot.
7. Open the committed snapshot in **Investigate**, with its engine coverage chip/Trust drawer
   and scoped collection outcomes. If that workspace is unavailable, use the same app's snapshot
   view with a clear unavailable message; never open a separate Explorer/Scope frontend.

Targeted jobs are a first-class engine job kind, not a full-assessment shortcut. The operator
selects engine policy IDs with typed arguments, not arbitrary command strings. Mandatory trust,
version, privilege and session-presentation prerequisites are visible in the expansion. Only
chosen approved reads and those prerequisites execute. Unselected commands are `not-requested`,
with their dependent axes not assessed, never collected-empty or feature absent. A job may
produce an investigation result without meeting full snapshot admission. Any new partial
snapshot requires the engine's explicit coverage/eligibility result and operator acceptance;
it never mutates or silently merges into an older snapshot. Bind results to device, command,
job, time and source snapshot context without claiming cross-vintage equivalence.

Investigate's engine question/confirm-on-device action may preselect this same job dialog.
The later read-only console must consume the same policy/job channel; this PR adds no console,
free-form terminal, arbitrary shell, config mode or write capability. Active probes stay off.

After a job, the engine may project **uncollected CDP/LLDP peers as candidate seeds for the next
job**, with evidence pointers and ambiguity/unresolved-address qualifiers. The operator ticks
them, supplies/confirms valid targets and hints, runs preflight, and authorizes a new job.
Peers are never followed, resolved, contacted, added to the current grant or marked collected
automatically. Unselected candidates remain outside that job's authorized denominator; the
engine separately exposes pending engagement scope so a small batch is not a full-fleet claim.

## 3. One engine command policy; same-session detection and privilege

The future **`cisco_toolkit/command_policy.py`** is the one per-platform registry. A row binds
stable ID, platform, canonical wire form, allowed aliases and typed argument/filter grammar,
class, privilege/evidence prerequisites, output/file/byte bounds and coverage dependencies.
Classes are **`read`**, **`active_probe`** (off/unavailable in these jobs) and **`never`**.
Unknown platforms, commands, aliases, arguments, stages or missing policy bounds fail closed.
The app renders the registry; it has no copied algorithm/command allowlist.

Canonicalize approved aliases/case/whitespace under the engine grammar before classification;
reject control characters, hidden/ambiguous spellings and chaining rather than repair them
into executable input. The collector's existing whole-string grammar is a **floor**, not proof
that every `show` command is safe. Apply the per-platform explicit block rules to the complete
canonical command and **every pipe stage/argument**. Block file/URL destinations in `show
tech-support`, redirection/append/tee/transfer forms, unsafe or unrecognized `sort` arguments,
and any stage with write/egress semantics. A safe first word or first pipe does not admit a
later stage. A registry ID cannot override a block. Examples are test shapes, not a hand-kept
denominator: tests derive the complete registered domain and its grammar mutations.

`cisco_toolkit.attestation.is_read_only_command` stays the independent second verifier; it
does not import the registry's decision/grammar. A wire send needs **both** producer-policy
admission and independent-verifier admission. No `extra_verbs` waiver, new class default or
test weakening to force agreement. If required session setup cannot pass both, refuse until
an independently reviewed owner change supplies positive/negative controls. Terminal paging/
width setup may be explicitly registered operational session reads; `enable`, config, write,
copy, reload and transfer never execute. Driver preparation and every low-level channel send
are checked too, so Netmiko implicit preparation cannot bypass the policy.

Today's attestation function has the independent verb/chaining/pipe-prefix floor; it does not
by itself prove safe platform-specific tech-support destinations or full sort arguments.
Before enabling these app jobs, its owner must provide independently reviewed per-platform,
full-argument coverage of the admitted registry domain, without importing the producer's
grammar/verdict or sharing its admission result. Missing coverage refuses the capability.
Calling today's function twice or treating its existing True as that stronger certification
does not satisfy this requirement. All existing verifier assertions and independence stay intact.

**Replace SSHDetect in the new app job path.** Establish one approved SSH transport/channel,
verify its host key, authenticate at most once, then issue gated `show version` in that same
session. The engine chooses/binds the supported platform driver to that authenticated session
without opening/re-authenticating another connection. Preflight reserves a policy-approved
bootstrap and the worst-case outputs of each allowed platform alternative. An unknown version,
hint conflict outside the confirmed alternatives, unapproved driver preparation, or a driver
that cannot reuse the session refuses the device; there is no IOS fallback or second auth.
The app job performs no automatic reconnect. Existing CLI changes, if needed later to share
the owner, require their own reviewed parity tests; this docs PR changes no CLI behavior.

**IOS privilege is an engine fact.** After version detection, execute policy-approved `show
privilege` before any configuration-derived capture. Full assessment requires a positively
parsed **privilege 15** result. Below 15, missing/ambiguous result, denied command or timeout:
refuse full collection before `show running-config`, with `refused-by-guard` and a specific
privilege qualification. Never invoke enable/escalation. A well-formed partial configuration
ending in `end` does not prove complete visibility. If a targeted operational job is explicitly
admitted at a lower verified level, only rows whose engine policy permits that level run;
its configuration-dependent axes remain not observed/insufficient privilege and cannot assert
absence, pass or readiness. Missing proof refuses rather than guessing. NX-OS uses its owned
role/command-authorization evidence, not a fabricated IOS numeric level; denied or uncertain
visibility qualifies the affected axes. Preserve paging, prompt fallback and transport metadata.

## 4. Preflight caps before DNS or SSH

The engine uses the existing `load_devices` schema/aliases/platform normalization through a
shared pure memory-input seam; the browser does not add semantic validation or a devices-file
format. CSV is an input adapter for canonical `ip`, `hostname`, `platform` fields and approved
aliases. Credentials are supplied separately. Reject credential/env columns, duplicate/unknown
headers, malformed rows, ambiguous identities and normalized filename collisions with constant
errors/row numbers, never reflected input. Preserve legacy devices-file parity in owner tests.
Input targets are literal unicast IPs or bounded DNS names, not URLs, CIDRs/ranges, userinfo,
ports, paths, UNC, expressions or control-bearing strings. The engine offers safe unique labels
and displays unknown hints as `auto` for confirmation, never as a recognized platform fact.

**300 is a seed-catalog limit, not an advertised 300-device job.** Seed input is at most 512 KiB;
the operator explicitly chooses a smaller admissible job. No silent truncation or automatic
batching/contact. The selected job's original roster, including failures and refusals, is the
denominator of its outcomes; pending catalog scope remains separately visible as engine facts.

Before Start may authenticate or resolve a name, the engine freezes a complete plan binding:
policy/registry version and digests, device/platform alternatives, command/prerequisite expansion,
worst-case member census, original-memory and sanitized-output reservations, limits, credential
groups, trust, target policy and consent. Parent preflight is pure/no network; the child repeats
it before enabling live intent and acknowledges reservation. Missing bounds or insufficient
capacity refuses **the whole proposed job before any SSH session**, including trust-only probes.

Proposed conservative app-job limits (review choices, not measured field capacity):

| Resource | Bound and preflight consequence |
|---|---|
| Original capture store | 256 MiB RAM-only pool; 16 MiB total reservation per device, at most 2 MiB per command; no disk spill |
| Child memory | 1 GiB enforced process/job memory cap, including the capture pool and analysis/serialization headroom; refusal if the profile cannot reserve/enforce it before SSH |
| Disk/member set | At most 500 MiB sanitized job output and 20,000 physical entries, or any stricter existing ingest/verifier limit; include logs, markers, sidecars, templates, audit and all artifacts |
| Parallelism | At most four sessions/workers, with serialized authentication per credential/account group; no extra auto-detect/retry sessions |
| Time | Device wall cap 1,200 s; job wall cap 3,600 s; post-collection analysis/scrub/verify/admission/partial-choice cap 600 s; bootstrap/reservation cap 30 s; cancellation 5 s cooperative plus 5 s forced reap |

Derive `Fmax = job-wide members + sum(maximum members per allowed device/platform branch)`
from the command policy, actual writer/artifact registry and bootstrap/metadata/log owners,
not a copied command count. Optional/heavy commands, failure files and targeted products count.
Admit only if `Fmax <= min(20,000, all downstream entry limits)` and the byte/memory reservations
fit. Current `collect` writes roughly 103 wire files per device before other members: 300 such
devices alone exceed 20,000. That observation is a refutation of the old promise, not a new
hardcoded platform count. A registry change invalidates the plan and reruns preflight.

For the proposed defaults, eight devices are the absolute maximum: two four-worker waves
reserve `2 × 1,200 + 600 + 30 = 3,030 s`, below the 3,600 s job cap, and eight 16 MiB original
reservations occupy 128 MiB. The actual cap is the minimum of this time limit, memory, exact
file/byte limits and any stricter platform/credential scheduling constraints. A serial profile
may admit fewer. Targeted jobs still use these conservative ceilings until separately qualified.
Device wall time starts on assignment to a wave slot, including credential-auth permit wait,
trust choice and setup; the scheduler cannot start its timer only after successful auth.
If any computed cap is exceeded, the engine returns admissible scope and asks the operator to
choose a new job; it does not collect first and discard the evidence later.

These are **hard resource/deadline reservations, not a throughput SLA or a promise that 103
commands finish in 20 minutes**. Existing 120/300-second command read limits can exceed the
device wall cap when added. Each read uses the lesser remaining device/job/command deadline;
expiry produces explicit uncollected/partial coverage, not a complete result. The UI displays
that completion feasibility is not field-qualified. CI fake-clock/boundary tests prove the
envelope/refusals, not real-fleet duration. Do not increase any existing 600-second offline
ingest, verifier, projection or test budget to admit this feature. Require hosted measured
memory/time evidence for these proposed caps before implementation is accepted; if absent or
infeasible, keep Collect unavailable rather than claim scale. Actual over-limit output refuses
the device/capture in RAM, without persisting a truncated clean-looking file or exceeding caps.

## 5. Positive destination admission and job-scoped network authority

Destination eligibility is an engine-owned **positive prefix table**, not “anything except
these bad addresses” or the host Python version's `is_global`. Admit only:

- RFC 1918 private IPv4 prefixes (`10/8`, `172.16/12`, `192.168/16`);
- RFC 4193 unique-local IPv6 (`fc00::/7`);
- prefixes positively classified as globally reachable unicast by the reviewed, pinned IANA
  allocation and special-purpose registry data, with valid destination/forwarding semantics.

Build a finite disjoint positive table from complete versioned source data, resolving more-
specific reservations before broader allocations. Public allocated/legacy unicast uses the
IANA allocation basis; special-purpose exceptions require explicit applicable destination,
forwardable and globally-reachable admission. Blank/unknown/N/A, expired, malformed or
unclassified entries do not authorize an address. Do not treat `2000::/3`, any allocated `/8`,
or `not is_private` as sufficient. Source absence/drift or unsupported embedded-address forms
fail closed; no runtime IANA fetch. Test every class/overlap and boundary from the pinned data,
including a newly added synthetic non-admissible reservation, rather than a named bad subset.
IANA's globally-reachable field does not guarantee actual routability to a particular device.
Sources: [IPv4 special purpose](https://www.iana.org/assignments/iana-ipv4-special-registry),
[IPv6 special purpose](https://www.iana.org/assignments/iana-ipv6-special-registry),
[IPv4 allocations](https://www.iana.org/assignments/ipv4-address-space), and
[IPv6 global-unicast allocations](https://www.iana.org/assignments/ipv6-unicast-address-assignments).

Membership is only eligibility. This job's exact operator-authorized target/address/port
allowlist (TCP/22), reservations and effective transport policy permit only a bounded key-
exchange socket. An imported match or explicit bound-key acceptance is an additional gate
before any username/password, authentication request or command. This split permits the
first-use prompt without silently granting authentication to an unknown key. Normalize
IPv4-mapped forms to their underlying IPv4 subject before class admission;
never use a second spelling to evade the same positive table. Do not follow routing, HTTP,
proxy/jump-host, CDP/LLDP or device-output destinations. Unsupported forms refuse.

DNS happens only in the authorized child after resource preflight and explicit consent that
shows resolver traffic. Use the configured resolver for the finite names; apply the positive
table to **every** answer and pin the admitted map for the entire job. A mixed invalid answer,
unresolvable name or unapproved address change refuses that target; never re-resolve on retry.
Allow only that bounded resolver phase and then the exact pinned SSH tuples. Bind the map into
the engine audit. The process wrapper is defense in depth, not an OS sandbox; enforce the same
engine plan at collector construction and every connect path, including driver internals.

The app/server remains numeric-loopback-only and outbound-denied. **Collect admission refuses
a server launched with bare `--allow-live-network`, an active ambient live grant, or an absent/
unprovable required boundary**, before Start body/network work. Do not flip a shared server
environment flag to recover. Existing CLI use remains separate. Only the validated job child
receives live intent, applied after its memory envelope, reservations and target guard are
validated; argv alone never authorizes the new job path. Preserve Host/CSRF/auth/read guards.

All offline import/analysis children must be constructed with an explicit offline dispatch:
no live flag and no `ATLAS_PORTABLE_ALLOW_LIVE_NETWORK` in their environment, regardless of
the parent. Current `ingest._engine_argv` forwards that flag from the parent; it cannot be
reused unchanged and called offline-safe. Child bootstrap attests its denied boundary before
analysis; failure refuses. This design does not send a scrubbed collection to such a child
for a second authoritative analysis. Existing import routes still never collect from devices.

## 6. Strictly memory-only Start, credentials and private control

Proposed job routes remain guarded campaign-scoped prepare/start/status/cancel/partial-choice
operations; prepare has no credentials or network. New Start uses an opaque one-use prepared
plan ID/digest plus credentials, not repeated raw devices or filesystem paths. Atomic start
consumption returns an existing job or 409 on replay, never a duplicate child. Revalidation,
cross-campaign/expired-plan refusal and admission precede secret intake where possible.

**Start has a fixed 64 KiB raw-body ceiling and a dedicated non-spooling receive path.** The
existing `_RequestBodyLimitMiddleware` uses `SpooledTemporaryFile(max_size=1 MiB)` for unsafe
API bodies; ordinary JSON is not a no-disk guarantee. Classify the normalized Start route
before that generic spool and receive it in a bounded RAM buffer, never a temporary file,
file-backed mmap, multipart parser or disk replay queue. The global JSON env override cannot
raise its cap or select the generic spool. Keep access/Host/CSRF and early declared-length
guards before body reads, then enforce actual bytes for chunked/absent/lying lengths. Refuse
over-limit before buffering the offending chunk; reject non-JSON/compressed/multipart,
duplicate keys, non-finite or malformed values with constant errors. Never log/echo raw bodies,
decoder exceptions, unknown field values or request object reprs. Give new job-control routes
the same fixed memory path where they could carry sensitive data. No middleware order bypass.

The job-namespace selector must cover raw/decoded-path, trailing-slash and routing error
variants before any generic spool; ambiguous path/method/encoding refuses before body intake.
Never redirect/replay a credential-bearing Start or fall back to generic body buffering just
because its route model or path normalization failed. Exercise these variants in T05.

Credentials (including username) live only in transient browser form state, that RAM request
buffer, private child IPC and bounded engine memory. Clear form/request references after
submission/cancel; no URL/argv, env credential, cache/history/local/session storage, analytics,
saved credentials, snapshot, support bundle, credential hash or log. Use no-store responses.
Disable body/debug capture for this path without disabling security guards. No fallback to
`CISCO_PASS`, `password_env`, getpass, SSH-agent/key search or inherited user configuration.

Pass one versioned length-bounded **anonymous inherited stdin envelope**, at most 64 KiB,
containing the admitted plan binding and credential map. No shell, pickle, named/public pipe
or credential file. Parent/child validate exact schema, length, identity, expiry and digest;
acknowledge reservation, then close bootstrap stdin and drop unnecessary references. EOF,
extra frames, unknown version/field, timeout or failed acknowledgement refuses before network.
Typed progress is a separate bounded stdout stream; unstructured stderr stays in RAM until
safe constant/allowlisted diagnostics can be emitted. Never persist raw stderr and scrub later.

The envelope carries compact command IDs/typed arguments, selected devices and exact expansion/
policy digests, not hundreds of repeated wire strings or the full seed catalog. The child
re-expands with the same installed engine owner and verifies the identical canonical plan.
If even that representation exceeds 64 KiB, refuse and replan a smaller job before any socket;
never raise the cap or spill the envelope. Sensitive prepare/seed input also uses an explicit
512 KiB route ceiling before a generic spool, independent of the global JSON env override.

A separate inherited private framed control pipe/event carries only cancel, per-device
first-use key decisions and partial-choice intent, each bound to job/device/plan and one-use
nonce. It carries no credential values and is not an HTTP capability. Closing credential stdin
cannot disable control. Unknown/stale/extra control messages refuse; loss means interruption.
Drain output concurrently to prevent backpressure deadlocks. At most 16 KiB per event and
2 MiB projected status; relay newer complete engine projections rather than recomputing state.

Python/JavaScript cannot guarantee physical zeroization or defeat privileged memory readers,
browser password managers, OS paging/hibernation or externally configured dumps. The guarantee
is no application persistence/emission; managed-host policy must address those residual risks.
No claim of secure erasure, encrypted RAM or crash-proof secrecy follows from a pipe.

## 7. Host keys and consecutive authentication failures

**Recommendation:** prefer imported/independently verified pins; also support **opt-in,
operator-confirmed first-use acceptance per device** for authorized brownfield work. Unknown
keys never auto-accept, and there is no Accept all. Import-only is stronger when trusted
material exists but prevents legitimate first contact without a prepared inventory. First-use
confirmation alone remains vulnerable to a first-contact MITM; the UI states that risk and
offers out-of-band comparison, without claiming the device identity was independently proven.

Both paths show and bind target/name, pinned address, port, exact public-key blob/key type,
**fingerprint digest algorithm plus value**, negotiated host-key/signature algorithm and
effective transport policy. A bare digest with no algorithm is invalid. For RSA, distinguish
the public-key type from the negotiated RSA-SHA2/signature algorithm; same fingerprint is not
a waiver of the profile. Approved negotiation must satisfy the bound algorithm policy.

For first use, perform only approved SSH key exchange on the already authorized/reserved
target; do not send username, password or an authentication request until the engine receives
that exact displayed-key acceptance. Pause the same connection, with a two-minute choice
deadline inside device/job deadlines. Refusal/expiry closes it. Record key bytes/fingerprint,
algorithms, target, local operator-decision reference, time and acceptance method in the job
audit. Keep accepted public trust bindings in an engagement-scoped ledger for later jobs;
they are not credentials and do not mutate global known_hosts. **A changed key is a hard
host-key-refused failure**, with no in-job override or “accept replacement” shortcut. Rotation
needs separate out-of-band re-onboarding under an owner-approved trust procedure, not a retry.
No credential precedes trust on explicit or auto-platform paths. If a packaged provider cannot
expose/gate key acceptance before authentication on one session, Collect stays unavailable.

W59's approved default/legacy profile, two-level per-device/run consent, explicit-platform
restrictions and negotiated-session facts remain the transport authority. No algorithm list
copied into UI, implicit SHA-1 fallback or unreviewed provider. Baseline Paramiko 4.0.0 is not
assumed to enforce W59's standard boundary: inability to enforce the approved default policy
refuses Collect even with legacy hidden. An auto target incompatible with W59's effective
profile refuses before connection; a standard failure never switches profile.

**Engine-owned authentication circuit breaker:** at most one authentication in progress per
credential/account group; existing successfully authenticated sessions may collect concurrently.
Default threshold is **two consecutive authentication failures**, operator may lower it to one
but never raise it in this design. Increment only an actual auth failure; a successful auth
resets that group's consecutive count. Timeout/unreachable/host-key/guard outcomes neither
increment nor reset it. At threshold, atomically stop scheduling/authenticating that group,
close its pending unauthenticated connections, and mark its unattempted devices refused-by-guard
with `credential-auth-stop`. Other groups may continue under the same job caps. No queued third
attempt, SSHDetect fallback, password-method fallback or reconnect after authentication failure.

Canonicalize equivalent credential slots in RAM. Conservatively group the same username
across the whole job, including case/Unicode-equivalent comparison forms, regardless of slot,
password, claimed realm or transport profile; a renamed/duplicate override cannot reset the
stop counter. This comparison never changes the literal username/password sent for auth.
It may stop unrelated same-named accounts too; that safe limitation is displayed. A claimed
realm is not evidence allowing more attempts. Audit
opaque group IDs, counts and stop outcomes, never username/password or their hashes. The UI
shows the engine stop and remaining unattempted devices, not “unreachable”. No automatic
retry/new job; re-entry requires fresh credentials and consent. This bounds attempts, not
proof against an AAA lockout policy stricter than the chosen threshold; show that limitation
and require the consultant to use the site's read-only account policy.

## 8. Original analysis first; scrubbed persistence second

**Authoritative analysis input is the original transport bytes.** Existing
`tests/test_redact_collection.py::test_cli_flag_scrubs_after_analysis_and_warns` owns this
ordering for `--redact-collection`. The previous design's `scrub → --no-collect analysis` was
wrong: default SNMP `public/private` severity and secret-valued golden drift can change.

To preserve that ordering AND the no-credential-on-disk rule, new app jobs need one **bounded
RAM evidence backend** for the existing engine reader/custody/parser owners, not a second
analysis engine. Collect original bytes there, including credential-like lines and echoed job
identities. Original command captures, unsanitized metadata/snapshots/artifacts and exceptions
must never touch disk, logs, spill files, crash reports or backups. Bind all engine reads to
that immutable in-memory set through the existing custody interface's reviewed memory seam.
If any parser, library or writer requires an original on disk, refuse this job mode; a private
temporary file followed by deletion is not compliant. No partial implementation of this seam
may enable Collect. The original RAM store is a required implementation gate, not current code.
Original bytes are exactly the collector capture representation the existing CLI would parse,
including its line endings; the RAM adapter performs no additional normalization or filtering.

Ordering is explicit:

1. Complete/qualify collection, version/privilege/command evidence and the full selected roster.
2. Freeze the original in-memory evidence set; run **all** assessment/normalization checks on
   it, including SNMP severity, weak-user checks and golden drift. Keep secret-bearing computed
   structures in RAM. Resource overrun or missing originals produces an unavailable/partial
   engine result, never a silent switch to scrubbed inputs.
3. Freeze the authoritative analysis facts. Then run the engine's `--redact-collection`
   semantics on a copy/view and a reviewed engine-owned **secret/credential-only operational
   persistence transform** on the snapshot/metadata before any file writer. This is not the
   wholesale `--redact`/`html.redact_snapshot` share-safe transform, which pseudonymizes
   topology identities. Reuse applicable owner primitives without duplicating the vocabulary;
   retain original noncredential IP/MAC/serial/device facts needed by Investigate and confirm-
   on-device. The app adds the explicit credential-identity withholding policy below. Do not rerun
   value-dependent analysis over the scrubbed tree to manufacture a replacement snapshot.
4. Independently verify the exact sanitized captures and secret-only operational snapshot,
   metadata, log/audit and any artifact set under a reviewed operational persistence contract.
   The existing share-safe artifact certification is a different claim; it cannot be relabelled
   or weakened to certify an operational snapshot. Missing independent secret-only coverage
   refuses persistence. Require nonempty proof, complete member/census reconciliation and stable
   digests. Every excluded/binary/uncovered member needs its own appropriate verifier or the
   whole retention refuses. A flag, producer count, exit 0 or zero checked files is not proof.
5. Persist only the admitted safe set. Store the **original-analysis snapshot**, after its
   persistence redaction, through the existing snapshot validation/atomic storage boundary.
   Reuse storage/summary consumers after foundation reconciliation; **do not call `_assess_tree`,
   `run_collection_folder` or `--no-collect` on scrubbed captures for authoritative ingest**.
   Preserve finite JSON, usable-evidence eligibility, engine coverage, custody and digest forms.
6. Atomically bind job/campaign/snapshot, sanitized evidence and verification scope. Navigation
   happens only after commit. Retry returns the same committed snapshot. A promoted filesystem
   orphan without a database commit is unpublished recovery state, not a workspace success.

**Username-versus-evidence decision: mask only AFTER analysis, with a qualifier; refuse if that
cannot be proved safe.** The live username is a credential, including when it occurs in
`username <name>` configuration, logging/accounting or a weak-user finding. Original text stays
in RAM for analysis. Before persistence the engine replaces that identity with an opaque
job-scoped token in retained captures, labels, structured findings, logs and all metadata,
using a distinct consistent token per original credential identity so counts/joins do not
collapse. Preserve line structure and supply safe retained-evidence pointers. It masks password
values too; it never hashes credentials into the snapshot. If a safe identity/field/pointer
transform cannot be completed or independently certified, refuse persistence of that result.
No pre-analysis mask, dropped offending line or “identity was public anyway” exception.

The engine publishes `credential_identity_withheld` and affected record/axis qualifiers:
the original-analysis severity/result remains, identity detail is unavailable, and a later
re-analysis of sanitized evidence cannot claim original-value equivalence. In particular,
weak-user failure/severity/count cannot become pass or disappear just because names are
withheld. CLI raw scrubbing currently keeps identities (`html.py::redact_collection_dir`);
the app is intentionally stricter about its job identity at persistence. Tests allow only
those explicitly mapped identity/secret payload differences, never weakened findings or
blanket exclusions from the fact comparison. Other topology identities remain as observed
unless they collide with a job credential; that collision must be qualified or refused.

Value-dependent checks are engine-owned and explicitly catalogued/tested. The original run
publishes their original result plus the retention/replay limitation. If ONLY scrubbed source
is available in a later offline import, engine policy withholds the affected check or marks
it not assessable from original values; it must not assert feature absent, no drift, or a
weaker clean verdict. Do not use string placeholders as if they were measured device values.
Custody distinguishes original RAM observations from retained scrubbed bytes and explicitly
states `original_evidence_not_retained`; a retained-tree digest cannot certify the disposed
originals' byte identity. Do not persist a raw secret-bearing input digest as an oracle or
silently waive the existing disk-custody receipt checks. The memory mode needs its own reviewed
engine custody contract and tests; without it, refuse the app job. Existing CLI custody gates
stay unchanged. A qualified original-analysis result is not portable original-raw custody.
Known W60c P2-6/P3-7 and the certified marker-alias escape remain negative evidence, not fixed
by this design. In particular, current producer AND verifier certify a known private residue:
their green result alone cannot admit this app path. The deployed job capability must remain
unavailable until independently reviewed engine/privacy-owner enforcement can reject those
preserved counterexamples and their grammar variants without weakening any legacy test/golden.
Inject each known certified escape through fake-device output and require **no retained
evidence, snapshot or downloadable artifact**, despite simulating today's false certification.
Do not create a fixture-name exception, app-side vocabulary copy or operator override. Any
unproved transformation/residue refuses persistence. Passing this finite corpus still cannot
prove universal secrecy, share-safe delivery or field qualification.

## 9. States, failure facts, cancellation and partial results

One engine reducer owns `prepared → preflighted → authorized → starting → collecting →
analysing_originals → scrubbing → verifying → awaiting_partial_acceptance (if needed) →
committing → completed | completed_partial`. Per-device key choice is an engine substate,
not an app-invented success. Refused/failed/cancelled/interrupted and timeout reason are
terminal dispositions. The same engine owner in the supervisor process consumes typed OS
exit, bootstrap, control-loss, watchdog, cleanup and restart observations when no child event
exists. App/backend never derives the job verdict from an exit code or event silence.

Publish **each selected device's failure reason as an engine fact in `collection_completeness`**:
`auth-failed`, `timeout`, `host-key-refused`, `unreachable`, `refused-by-guard`, with stable detail
codes, stage, attempt count, requested/observed command coverage and evidence pointer. Unattempted
devices after a guard/auth stop are refused-by-guard with why, not fabricated auth failures.
Success does not erase privilege/paging/prompt/partial qualifiers. Extend the engine's closed
owner/schema/projection with reconciliation tests, not an app status dictionary. The source
roster and outcomes reconcile exactly; missing reason/row is unavailable, never zero failures.

Supervisor mechanics own a hidden child and process tree (Windows Job Object kill-on-close;
equivalent owned process group on POSIX), bounded pipe drains and the generation slot. Cancel
goes through the private control channel to the engine; stop scheduling and close sessions,
then force/reap within 5+5 seconds if needed. A stuck collector thread cannot be safely killed
by `Future.cancel`; terminate the child and let the engine mark all unfinished devices
interrupted/partial. Never extend a deadline on progress, retry, key choice or cleanup.

The 600-second post-collection bound and global deadline include partial acceptance, with
the earlier expiry displayed. Sessions/credential references close before waiting. Expiry
refuses snapshot admission, records the engine reason and releases resources after cleanup.
Atomic commit arbitration prevents late child events turning cancellation into completed;
commit winning returns the existing snapshot and refuses a late cancel as already complete.
After a crash/restart, engine state is interrupted, not automatically resumed; no credentials
are recovered from disk. Missing usable device/interface evidence means no assessment snapshot.

## 10. Per-job paths, log census, retention and disposal

Process cwd and sanitized staging are a private external job root, for example the resolved
per-user local application-data `Atlas/collection-jobs/<opaque-id>` directory, **outside the
executable/install/update trees**, not `<exe_dir>/data`, repo code or a static/download root.
Canonicalize and reject overlapping roots, links/reparse points, hard-linked/nonregular files,
caller paths and unsuitable ACLs before auth. Check writability and bounded disk space. No
working directory that falls back into the executable tree is admissible.

`cisco_toolkit.engine_log_path` sends any frozen child whose cwd is inside the executable tree
to a shared `<exe_dir>/data` log. Therefore an apparently isolated `data/jobs/<id>` cwd is unsafe.
The job bootstrap must resolve/assert the exact final engine log path before SSH, pin it to
the external job root, install the safe log sink before engine logging, and include every
writer/child logger in the frozen member/byte census. No parent/shared FileHandler or raw
stdout/stderr spill. If the current resolver would select the shared log or the root cannot
be proven, refuse before collection; do not clean/delete a shared file belonging to other jobs.
Frozen-profile tests must prove no write under the shared log/bundle, including exception paths.

Logs that reach disk contain only allowlisted safe engine events/IDs, never original captures,
raw exceptions or credentials. Finalized safe evidence may then be copied and reverified into
the active data store, which may be `<exe_dir>/data` as the documented **writable data exception**
to immutable application bytes. That retained-data exception never authorizes a child cwd or
shared job log there. Copy across volumes into a private destination, reverify exact members,
then commit; no assumption that cross-volume rename is atomic. Originals never follow that copy.

Under [ADR 0007 D10/Amendment 1](decisions/0007-one-application-direction.md), retain verified
scrubbed evidence and safe audit records; no in-app purge/retention indicator or expiry of
committed evidence. Dispose manually under the client agreement outside Atlas. List the new
external roots and retained-data copies in the operator/field guides before implementation
acceptance, alongside database/journals/backups, update/release copies, exports, browser data
and all other media. App deletion on flash is not secure erasure. No active staging in backups.

Original RAM references are released on every terminal path; only safe staged output can
need filesystem cleanup. A failed scrub/persistence/cleanup leaves no retained-clean label,
no served snapshot and an engine `cleanup_required` reason for any safe-but-incomplete disk
set; block new collection until that exact owned root is handled. If an implementation ever
finds a plaintext original/credential file, treat it as a violated gate/security incident,
quarantine it from app serving/backups and stop; ordinary deletion is not proof it never existed.

The versioned append-only job audit stores plan/policy/source identities, reservations,
positive target map, public-key/algorithm decision, explicit consent, opaque credential-group
failure counts, command IDs, original-analysis versus retained-evidence forms, qualifications,
per-device outcomes, verifier/member digests, snapshot ID/digest form and cleanup result. No
credential values/hashes, original secret-bearing payload/digest oracle, bodies or raw log
tails. Audit availability is a preflight prerequisite; audit-write failure aborts new SSH.
Local operator/time records are observations, not authenticated signatures, trusted time or
tamper-proof custody. Engine facts remain authoritative; the app stores them without recounting.

## 11. Threat model

Assets are credentials, device configuration/availability, original evidence/analysis truth,
retained privacy, job authorization and host storage. Boundaries are browser → guarded API RAM
→ private IPC → engine/session/SSH peer → original RAM analysis → scrub/verifier → durable store.
Adversaries/failures include drive-by pages, malformed seeds, MITM/changed keys, hostile device
output, accidental credential mistakes, concurrent requests, process death and media exhaustion.
A compromised host or modified executable is outside the app's enforcement boundary.

| Threat | Required control | Decisive refusal/negative control |
|---|---|---|
| Body/credential persistence or echo | Fixed non-spooling Start, original RAM-only readers/writers, post-analysis identity masking and independent sink scans | Chunked oversized body, env-raised cap, username in real config/syslog and one deliberate file leak must fail |
| Analysis softening after redaction | Originals authoritative; direct original-result ingestion; value-dependent replay qualifiers | `public/private` SNMP and distinct-secret golden drift change under scrubbed-only analysis but original-result verdict never changes |
| Device writes or active probes hidden behind `show` | One platform registry, whole-string floor, every pipe/argument block, independent attestation and driver-send gate | Aliases, tech-support destinations, sort arguments, later unsafe pipe, config/enable/transfer and driver bypass refuse |
| SSRF/discovery/ambient live grant | Positive IANA/RFC classes plus exact job tuples, pinned DNS, offline child grant stripping, server-live admission refusal | Full class/boundary corpus, mixed/rebinding answer, peer auto-follow and bare-live server produce no unauthorized session |
| MITM, low privilege, AAA lockout | Algorithm-bound trust before auth, changed-key hard failure, one-session detection/privilege gate, per-group consecutive stop | Unknown/unaccepted key sends zero credentials; privilege 1 valid-looking config never yields absence; no third auth after threshold 2 |
| Expensive impossible job, hung/orphan child or partial false success | Exact caps/reservations before SSH, owned process tree/deadlines, complete engine failure roster, atomic commit | 300-device over-cap request, disk/memory refusal, stalled reads, parent death and cancel/commit race cannot complete falsely |
| Cross-site/campaign job theft or forged coverage | Existing Host/CSRF/auth guards; campaign-bound one-use plan; engine states/SSOT projection | Foreign/missing headers/IDs, forged app totals, missing/late engine events and replayed Start refuse or display unavailable |

## 12. Hosted acceptance tests (specified, not implemented or run here)

All execution is on GitHub-hosted ephemeral runners with synthetic data/fake SSH only; **no
real gear ever**. Current golden/sample bytes and every test, gate and budget remain unchanged.

- **T01 Whole job:** deterministic IOS/NX-OS fake SSH with test key and a wire/auth transcript;
  real API → supervised child → original engine analysis → scrub/verifier → snapshot store →
  Investigate handoff. Do not stub the engine/store/redaction to manufacture end-to-end success.
  Production rejects fixture loopback addresses; a test-only source-harness dependency injection
  supplies the endpoint policy, absent from packaged entry points and unreachable via HTTP,
  argv or env. Frozen tests separately prove real bootstrap, path, socket and IPC enforcement;
  absent packaged coverage stays not verified, never a production bypass.
- **T02 Original-versus-scrubbed parity:** two lanes over identical original fixtures: existing
  CLI contract analysing originals then `--redact-collection`, and the proposed RAM evidence
  backend analysing the same original bytes. Compare the complete engine analysis/check
  status/severity/count/drift outputs, after narrowly specified identity/payload redaction
  and run-identity bindings. No missing-check or value-dependent exemption. Include literal
  SNMP `public`/`private` versus nondefault RO and distinct secret-bearing golden directives;
  prove high severity and distinct drift survive. A third, deliberately scrubbed-only analysis
  is the negative oracle: demonstrate the changed results and require replay qualification,
  not equality to a weakened baseline. The test must fail if app ingest reanalyses scrubbed
  captures or any pre-analysis filter changes original engine input.
- **T03 Username/evidence and all-sink leaks:** synthetic username actually in `username ...`,
  logging/accounting, weak-user findings, metadata and an identity collision; original RAM
  readers see it, persisted fields use the owner token and qualification, findings retain
  original fail/severity/count. Password echo/encoded carriers too. Instrument every file
  creation/write, spool/rollover, argv/env, browser cache/storage, request/progress/log/error,
  snapshot/database/journal/backup, archive/OOXML and artifact path, not only end-state grep.
  Scan declared Unicode/JSON/URL/HTML/base64/escape variants. A deliberate transient write
  deleted before completion must still fail. Refuse unsafe masking/pointer transformations;
  check credential hashes and original secret-bearing capture digests against every persisted
  custody/output field too; a retained-tree hash must not be passed off as original custody.
  no credential appears even transiently on disk. Reports use IDs/counts, never leak values.
- **T04 Cap preflight:** derive every platform/targeted/prerequisite/failure member from owners;
  exact-boundary pass and one-over rejection for entries, bytes, pool/RSS, workers, slots and
  deadline reservations. A 300-device default request and policy-census growth refuse with
  **zero resolver calls, TCP connections and SSH sessions**. Memory/disk/log-root reservation
  failure also refuses before SSH. Test the eight-device time arithmetic and stricter serial
  constraints; fake clocks prove all limits and no timer reset, not real gear throughput.
- **T05 Start memory:** actual ASGI middleware chain with 64 KiB and one-over, chunked/omitted/
  false Content-Length, rejected content encodings, high `ASSESSHUB_MAX_JSON_BODY_BYTES`, malformed
  JSON and cross-site/Host/auth refusals. Spy on tempfile/spool/file-backed APIs and raw logging;
  all Start/control body paths must have zero disk operations and zero body reflection. Trace
  bootstrap/stdin copies and failure paths; no ambient credential lookup or fallback.
- **T06 Privilege:** same-session fake IOS privilege 15 positive; levels 1/7, denied/malformed/
  missing probe, timeout, and a valid-looking limited `show running-config` ending `end`.
  Full collection refuses or the explicitly admitted targeted job has engine visibility
  qualifiers; no config-derived feature-absent/pass/readiness. No enable command. NX-OS role
  and command-denial controls do not synthesize IOS privilege proof.
- **T07 Commands and detection:** registry-derived complete per-platform classes/aliases and
  every pipe grammar; tech-support file/URL forms, sort arguments, later unsafe stages and
  implicit driver writes all refuse. `active_probe` never runs. Mutate producer admission and
  independent attestation separately; either check must block a bad send without importing the
  other's verdict. One TCP/auth session for `show version`, privilege and collection; wrong
  hint/unknown platform/provider refusal/auth failure causes no second connection/auth attempt.
- **T08 Auth circuit:** one bad credential across many devices, threshold 2 stops before a
  third attempt; threshold 1 stops earlier. Serialized auth under concurrency, success reset,
  neutral failures not resetting, alias/override bypass, and independent group continuation.
  Remaining rows have refused-by-guard/auth-stop, actual failures auth-failed. Audit no secrets.
- **T09 Trust:** algorithm-less fingerprint refusal; imported match, optional first-use prompt
  and exact-key acceptance/refusal/expiry; **zero username/password/auth transmission before
  acceptance**, including version/auto/reconnect code paths. Changed key always fails; RSA key
  type versus signature policy, stale/foreign control nonce and downgrade/provider cases.
  Assert audit/key-ledger bindings and no global known_hosts mutation.
- **T10 Destinations and inherited grants:** generate cases from every pinned IANA/RFC class,
  each prefix edge/overlap and new unknown reservation, plus normalized mapped addresses,
  mixed DNS answers and pinned-answer changes. Require positive membership plus exact job
  scope. Bare-live server refuses Collect; offline argv/env always strip grant, and an offline
  child socket attempt stays denied even if the parent was explicitly live. No HTTP/env escape.
- **T11 Failure facts and peers:** real fake-device auth, timeout, trust, unreachable and guard
  refusals produce all five engine `collection_completeness` reason codes and exact selected
  roster reconciliation. CDP/LLDP candidates retain evidence/ambiguity, never trigger DNS/SSH;
  only an explicitly ticked, preflighted, separately authorized next job may contact one.
  Targeted unrequested commands stay not-requested/not-assessed, not empty/full coverage.
- **T12 Paths, liveness and admission:** frozen child external cwd, exact log path and complete
  output census; inject a bundle/data cwd and shared handler/fallback to prove pre-auth refusal
  and no shared-log write. Bootstrap death, broken/full pipes, malformed events, cancel during
  auth/read/key choice, hung thread, parent exit, partial expiry, memory/disk exhaustion,
  verifier residue/uncovered member, mutation after verification, copy/DB crash and restart.
  Feed every preserved W60c certified escape through the fake peer and simulate current
  producer/verifier false-green results: capability admission/persistence must refuse, with
  zero retained evidence/snapshot/artifact until owner enforcement is independently established.
  Hard reap/cleanup and one atomic snapshot hold; no late completed state or duplicate ingest.
- **T13 Foundation/consumer parity:** engine facts/SSOT registrations, closed schemas/OpenAPI,
  complete capture/write-site census and golden/sample equality; forge app totals and missing
  engine status to prove there is no backend/browser recount. Original CLI input/analysis
  behavior and offline routes stay covered. Existing full Python/frontend/distribution/
  portable/reference gates and budgets stay intact; internal source review is not acceptance.

## 13. Review resolution ledger and stop conditions

All entries mean **specified in this revision, pending independent re-review and later hosted
implementation evidence**. They do not convert BLOCKED `961f65cd` into approved/implemented.

| Finding/addition | Decision and where to review | Closing test contract |
|---|---|---|
| P2-1 originals and semantic parity | Section 8: original RAM analysis authoritative; scrub after analysis; ingest its snapshot, not scrubbed-only reanalysis; value-dependent replay qualifiers | T02 |
| P2-2 username collides with evidence | Section 8: original identity in RAM; post-analysis mask with explicit qualifier/pointer mapping, otherwise persistence refusal; intentionally stricter persistence than CLI | T03 |
| P2-3 caps versus scale | Section 4: 300 catalog only; exact file/byte/memory/scheduling preflight before any session; conservative max eight or fewer, hard time bounds not SLA | T04 |
| P2-4 Start spooling | Section 6: fixed 64 KiB non-spooling receive before generic body spool, env override irrelevant; all error/chunk paths memory-only | T05 |
| P2-5 IOS privilege | Section 3: engine `show privilege`; full assessment requires proven 15; targeted lower-level visibility explicit; never infer absence | T06 |
| P3-6 inherited live grant | Section 5: bare-live app server refuses; offline argv/env explicitly strip and child denies sockets | T10 |
| P3-7 destination subset | Section 5: positive RFC/IANA membership with complete pinned class tests plus exact job allowlist | T10 |
| P3-8 frontend/ADR/hold | Sections 1–2 and NOW: committed #672 `8fd9e520`, five workspaces/Investigate; durable merge evidence and supervisor resume, never Active-row existence | T13; owner review |
| P3-9 consecutive auth stop | Section 7: engine threshold 2 (lowerable to 1), serialized per-group auth, no alias bypass/retry/third attempt | T08 |
| P3-10 fingerprint algorithm | Section 7: key blob/type plus digest/signature algorithms, profile-bound acceptance before any credential | T09 |
| P3-11 staging/shared log | Section 10: external cwd, resolver/log/handler preflight and census; retained writable-data exception only after safe promotion | T12 |
| Supervisor (a) one command registry | Section 3: command_policy owner, aliases, grammar floor, platform blocks/every pipe, read/active_probe/never, independent attestation | T07 |
| Supervisor (b) no SSHDetect | Section 3: gated show version, driver on same authenticated channel; no second auth | T07–T08 |
| Supervisor (c) per-device reason | Section 9: five failure reasons in engine collection_completeness, complete roster and qualifiers | T11 |
| Supervisor (d) peer seeds | Section 2: engine candidates, operator ticks next job; no automatic following | T11 |
| Supervisor (e) targeted jobs | Section 2: devices × registered commands, prerequisites/coverage explicit, future console uses same policy/channel | T01/T07/T11 |
| Supervisor (f) first-use trust | Section 7: recommended optional human-confirmed first use, imported pins preferred; algorithms/audit before auth, changed key hard failure | T09 |

Coordination remains through NOW. F0/#672 owns the frontend/ownership ADR; H owns foundation
enforcement; G owns the app's Investigate canvas/renderer; desktop holders own installed shell,
pipe/process/path capability proof; engine/SSH/redaction owners own the policies and original
analysis contracts. Do not implement any of them in this docs PR or claim their delivery.

Run fresh Rule-7 repository privacy and every-new-commit/message/per-parent/publication marker
scans before each push. Require all 15 protected contexts on the exact final PR head and all
applicable hosted workflow results; earlier-head success, cancellation or partial results do
not transfer. Post one consolidated finding-by-finding summary and **STOP for independent
re-review**. CI here checks documentation integration, not the future fake-SSH feature or
design approval. The implementation hold at the top remains in force; no merge or release.
