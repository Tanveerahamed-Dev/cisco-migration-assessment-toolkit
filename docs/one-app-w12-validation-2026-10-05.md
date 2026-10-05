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
