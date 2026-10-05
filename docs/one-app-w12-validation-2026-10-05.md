# W12 Decision rollups validation

PR-A implements G06 move-group readiness and G01 health-band membership from
main `a9ed0532`. PR-B follows its successful merge and owns G09 device findings
plus the G13 VLAN-wave residual. Deferred gaps and the supervisor's dependency
PRs remain outside W12.

The health partition is a pure owner fold in `ssot.py`, not a stored engine
section. Its complete source membership and Critical/Poor canonical overlap are
guarded before publication. Canonical absence and all-unscored posture remain
withheld. The Insufficient Data bucket remains independently observable.
No persisted reconcile census, sample snapshot or golden changes.

Readiness consumes the producer's written labels, switch membership, endpoints,
checklist and disposition. Identity, membership and check/count/verdict
contradictions withhold the list; absent core inputs and failed analyses retain
their states. READY is a bounded checklist disposition, not cutover approval.
Endpoints are the producer's per-switch learned-MAC sum, not distinct fleet
endpoints. The frontend renders those facts, references and qualifications.

## Closed schema and native review

The delta adds seven definitions for check status, readiness lists/rows and
health-band rows. Existing FleetHealth and Overview gain the required fields;
LimitationId and Trust's limitation count follow the registered qualifications.
No old definition is removed and no new schema keyword family or input-domain
feature is admitted. Independent source review confirmed the new definitions
reuse closed objects, local references, published/withheld alternatives,
nonnegative integers, existing array constraints, dependencies and enums.

Literal audit pins use compact ensure-ASCII JSON plus LF in owner key order:

- view: `2c54b69ca7cdf706aefa4e181cc3181156eff55989114882a5c80300153b269b`
- list: `339a56549ba1fde1f346a5451710a395e4859f054895197d0456f37aba1ca329`

Pins remain source literals. Provider/version, private resolver guard, admitted
instance domain, mutation checks, offline fallback and public-error behavior
remain unchanged. Fresh native/Python equivalence and hosted 300 ms acceptance
are required before merge; source review does not replace execution evidence.

## Current verification boundary

The first focused Python run passed 62 cases covering the new partition guard
and projection behaviors, including real-producer readiness, withheld/absent
inputs, malformed identities, canonical drift and boolean/float count mutations.
It used the current checkout's owners and the stock Python validator. Canonical
OpenAPI export and TypeScript generation completed. A frontend worker's service
capacity failure occurred after its source edits; those edits are preserved and
have not yet received a test verdict. No test failure is asserted from that
service failure.

Independent frontend review caught an HTTP-shape mismatch: readiness groups are
paged in transport, while the first UI/fixtures used the raw engine list. The UI
now uses the existing source-bound pagination renderer, and renderer/native
fixtures use that actual page envelope. Empty host buckets retain collected-but-
empty state and a published count zero. Syntax checks pass; fresh execution is
still required to verify this correction.

Native equivalence, frontend verification, final publication privacy/history,
all protected exact-head CI and unchanged hosted latency acceptance remain open.
Local work stays light while RAM is low; full construction, suites, smoke and
performance measurement remain hosted. No Atlas Scope, release publication,
tag, signing, device or vault action is part of W12.

## First published head: preserved failure

PR-A #597 first head `6ac674da` passed fresh repository, complete commit/patch
and PR-body privacy gates. Its webapp workflow `37269457449` passed the frontend,
E2E and visual jobs, but the backend job's Scope-hub build rejected the shared
synthetic fixture under its stricter no-unchecked-index typing (TS2532 at
projectionFixtures.ts lines 95/96). The fixture now maps explicit band/host
records, avoiding a possibly undefined array index; no Scope file or safeguard
changes. That failure and every pending/terminal result remain bound to `6ac`.
The corrected source requires fresh exact-head CI and hosted latency receipts.

Full Python suites also rejected the unregistered readiness dependency consumer,
the newly reached eight-subject note preview, and missing one-hop caveat scopes.
The mechanical dependency proof now names only the existing four punch-list
forwarding sites and the exact five readiness failure/reference sites. Hostile
alias, indexing, rebinding and authorizing-read mutants remain rejected. The cap
registry adds only the actual producer's `subjects[:8]` preview; source-backed
tests preserve eight named subjects, exact omitted count and the complete
Validation/NRFU sink. The precise new Overview prefixes retain their caveats.
Four focused correction proofs passed, including the controlled owner-state
tests and cap helper. Those narrow passes do not erase the broader failed runs.

The distribution and portable jobs correctly rejected stale tracked SPA bytes;
the old output must be regenerated, not allow-listed. Pinned Node 24.19.0/npm
11.16.0 material hashes match their retained tool receipt. Necessary dependency
installation began with 1,747,476,480 bytes free RAM and passed with zero audit
findings, but a second RAM check refused the build below the 1.5 GB floor. No SPA
build occurred locally. A bounded source/input/member handoff in the existing
hosted frontend job is being verified to obtain generated review inputs without
using the laptop for heavy construction. It grants no release authority and does
not replace the unchanged final-source reproducibility guard. All old `6ac`
receipts, including its passing measurement job, remain solely old-source facts.

The hosted handoff/classifier process passed 70 cases with three Windows
link/FIFO capability skips and zero failures. It verifies current committed
inputs, fresh source/member censuses, ordinary paths, bounded stable reads,
captured bytes' canonical marker scan and copied-member rechecks. Its exact
script/guard paths engage frontend CI. An earlier command-format exit 4 occurred
before test execution and remains preserved separately. This handoff is a
generated review input, not a release or a substitute for rebuilding the final
committed SPA bytes under the unchanged exact-head guards.

Final handoff refutation additionally covered deleted inputs omitted from a
mutable index and generated JavaScript's existing path-qualified marker policy.
The owner now selects the committed HEAD tree and requires exact index-set/blob
equality. It reuses the canonical compiled-JS alias rule without adding a waiver;
brand, user and compound markers stay active. Its final helper-only pass is 35
cases with three Windows capability skips and no failures. Independent source
review is clear. API/archive digest, closed members and independently selected
input hashes must still be verified before importing generated bytes, and the
final committed source must rebuild them under fresh CI and latency gates.

## Hosted generated inputs received

Bootstrap `909c19fc` integrates supervisor-merged main `21c115f2`. Expected
producer `acd7868c72feaf501e3bf2286834ddbe500d480e`, tree
`b2e3d592db93faa178965194dfa090b0197ad2ae` and all 144 committed source/material
hashes were independently selected before download. Artifact `11331348793` from
frontend job `111663583534`, run `37279348321`, is 551,909 bytes; its API/archive
SHA-256 is `9c8444d24af902f79de981dff089da2cc2a521a7466101786a1f1f74d79918bc`.
Closed seven ordinary files (two metadata plus five SPA members), input/member
hashes, canonical privacy markers and index asset links independently pass.
The job's setup log proves Node 24.19.0/npm 11.17.0, matching its manifest; the
receiver's initial old-local-npm assumption and refusal are preserved separately.

The frontend job succeeded, but the overall bootstrap workflow later cancelled.
No overall pass or release authority is inferred. The five ordinary generated
files were imported into the owned tracked dist and three obsolete generated
files removed. These are review inputs; the changed final source must reproduce
them under fresh protected CI and the unchanged hosted latency gate. No old
receipt transfers and no local SPA, release, frozen smoke, deployment or device
execution occurred.

## Published generated-SPA checkpoint: preserved frozen-smoke failure

Head `64266e67` passed the complete hosted webapp workflow and distribution
contract. The independently reviewed hosted measurement passed the unchanged
strict 300 ms sample gate at limits 50 and 200: maxima 239.7438 and 233.5012 ms.
The synthetic 300-device profile remains diagnostic (704.9067 ms later-first,
427.6949 ms repeated maximum); it retains 26 topology nodes and does not prove a
300-node topology gate. These receipts remain bound to `64266e67` only.

Portable run `37284403553`, binary job `111689640380`, built Atlas and passed all
13 self-tests, then failed its frozen projection HTTP smoke. The smoke's expected
Overview paged only axes and top-gating lists; the new readiness groups are also
paged by the real transport. Its mocked test mirrored the old incomplete
expectation. Correct the independent expectation to include the nested group
page and drive test responses through the actual transport, with hostile group
page mutations. Keep exact body, stored-source and native-provider checks intact.
The failure remains preserved; a focused correction does not replace a fresh
hosted frozen binary, complete exact-head checks or a new latency receipt.

The real-transport fixture reproduced the obsolete expectation's exact owner
comparison failure before the fix. After the explicit nested-page correction,
all 31 focused smoke-contract cases passed, including 13 new readiness page
mutations; lint and whitespace checks passed. This was a bounded mocked-response
test, with no local Atlas build, binary execution or HTTP server. Hosted frozen
execution remains required on the corrected source.
