# Atlas Release 2 authority-candidate protocol

Date: 2026-08-29

Disposition: `NONAUTHORITATIVE_CANDIDATE_FREEZE_PROTOCOL`

Release 2 disposition: `CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT`

## Claim boundary

This protocol creates and verifies a detached, exact-source candidate package for accountable
Release 2 decisions. It does not select the source, establish runtime closure, approve a workload,
authenticate a trust root, approve a budget, qualify QCP-001, promote Release 2, or authorize
Release 3 product work.

The machine-owned product states remain unchanged:

- QCP-001 is `EXPERIMENTAL` / `CONTRACT_ONLY`.
- Runtime is `PARTIAL_NONPORTABLE_PROTOTYPE` until genuine complete evidence is accepted.
- Release 3 is `DISCOVERY_PLANNING_ONLY`.
- Release 2 remains `CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT`.

The package builder is `tools/build_atlas_r2_authority_candidate.py`. Its verifier, not this
document, owns package integrity. A generated package is detached from the source commit so that
the commit cannot recursively contain a receipt that names itself.

## Why the current path cannot close

The following are source-contract facts, not reviewer judgments:

1. `transition_runtime_inventory.py` v1 rejects every representation of complete runtime closure.
   It is an intentionally incomplete reference inventory.
2. `transition_runtime_closure.py` `/2` defines a strict external-review protocol, but no current
   evidence producer supplies all 22 required artifact roles and semantic closure conditions.
3. Windows discovery `/5` is an incomplete observation source. It must not be relabelled as the
   closure inventory or as complete evidence.
4. `transition_workload_review.py` `/1` authenticates a supplied decision but does not bind the raw
   bytes of a closed representative-workload denominator, corpus, criteria, execution receipts,
   or coverage reconciliation.
5. `transition_tcb_review.py` freeze `/1` consumes neither the runtime-closure review nor the
   workload-adequacy review. It requires workload-absence markers and later requires the
   deliberately incomplete runtime inventory v1 to be complete. Its positive path is therefore
   unreachable by construction.
6. The runtime, workload, and budget verifiers authenticate relative to caller-selected policy
   bytes. They do not establish the external policy authority, policy succession, key custody,
   trusted time, complete revocation history, or genuine organizational separation.

Passing unit tests prove the implemented structural validators and fail-closed interlocks behave as
implemented. They do not prove runtime closure, representative-workload adequacy, or authority.

## Candidate package contract

The builder operates only on a clean tracked Git checkout and requires the caller to supply the
expected commit and tree. It produces a closed directory with:

- a deterministic tar containing every tracked Git blob for the exact commit, regardless of
  `export-ignore` attributes;
- a source-freeze manifest listing every tracked blob by path, Git mode, Git object ID, raw byte
  count, and SHA-256;
- unresolved decision packets for `R2-AUTH-001`, `R2-AUTH-002`, and `R2-AUTH-004`;
- a claim-boundary README;
- a package manifest binding every other member by exact byte count and SHA-256.

Verification must fail for a dirty tracked checkout; the wrong commit or tree; any missing, extra,
renamed, or altered package member; any path, mode, blob, byte-count, or digest mismatch; archive
drift; non-canonical JSON; or drift from the generated null authority, unresolved choice, and fixed
release-boundary templates. Untracked files outside the generated package do not change the
committed source subject, but are never included in it.

The source-freeze package is evidence for choosing an exact candidate. It is not independently
custodied provenance and is not an authority receipt.

### Immutable package and detached decisions

The package is immutable. The applicable independently authorized actors must never fill null fields
inside a generated packet, because doing so correctly invalidates the package manifest. Each actual
choice is a separate canonical `atlas.r2-authority-decision-receipt/1` object that binds:

- the authority and decision IDs;
- the SHA-256 of the exact `package-manifest.json` and `source-freeze.json` bytes;
- the candidate commit and tree;
- one allowed choice, a reason, and an issuance time;
- the accountable principal and organization plus an authority-basis digest; and
- the signer key ID, public-key digest, signature algorithm, payload digest, and detached signature.

The generated packet owns the allowed choices and this structural receipt contract, but supplies
none of those external values. Receipt authentication, current policy selection, custody, trusted
time, revocation, and separation remain governed by `R2-AUTH-004`; a merely well-shaped receipt is
not authority.

The current package is decision-template-ready, not decision-consumption-ready. It includes no
parser or authority verifier for a later `atlas.r2-authority-decision-receipt/1`. A versioned
consumer must define canonical field types, signing domain, non-null and choice-specific rules,
expiry, current-policy and revocation revalidation, separation checks, and Stage A-to-Stage B
bindings before any detached receipt can affect a gate.

## R2-AUTH-001 precondition packet

The generated packet pre-fills only machine-verifiable candidate facts. Its
`R2-AUTH-001-PRECONDITION-D1` source-subject choice is one of:

- `SELECT_CANDIDATE_FOR_EVIDENCE_COLLECTION`
- `REJECT_CANDIDATE`
- `HOLD`

Selection means only that the named commit and tree become the exact subject for independent
runtime evidence collection and review. It does not mean the source is complete, qualified,
approved for release, or accepted as `COMPLETE_EXACT_RUNTIME_CLOSURE`.

This selection is a precondition to `R2-AUTH-001`, not the runtime-closure decision itself. It also
does not close `R2-AUTH-006`: selected-source ceremony and independently custodied provenance remain
open until their own accountable evidence is accepted.

A closure-capable successor must, without mutating inventory v1 or discovery `/5`:

1. bind raw bytes for every runtime-closure artifact role to the selected commit and tree;
2. reconcile the complete role denominator, coverage booleans, positive counters, zero counters,
   gaps, process lifetime, loader events, static resolution, mapped bytes, enforcement, platform
   state, and collector/verifier TCB;
3. accept only a freshly reverified external runtime-closure decision under current authenticated
   policy, trusted time, revocation, custody, and separation evidence; and
4. feed that current authorization into a versioned final-freeze successor.

Actual Windows closure evidence, policy, keys, signatures, reviewers, custody, trusted time, and
source selection remain external and unresolved.

## R2-AUTH-002 decision packet

The generated packet must leave the accountable owner, population, corpus, thresholds, criteria,
reviewer, and final decision unresolved. Stage A is the pre-collection
`R2-AUTH-002-D1` plan choice: `AUTHORIZE_WORKLOAD_EVIDENCE_PLAN`, `REVISE`, or `HOLD`.

An authorized Stage A plan must precommit and bind:

- the workload owner and independent adequacy reviewer;
- target population, sampling frame, inclusion and exclusion rules, selection method, strata, and
  weights;
- the required artifact-role denominator and the target, eligible, selected, executed, valid, and
  assessed count-reconciliation contract; and
- precommitted adequacy criteria, correctness and resource thresholds, permitted failures,
  blocking-gap rules, decision rule, and evidence-completeness rules.

Stage B must bind the immutable Stage A receipt digest plus exact raw bytes for the denominator,
corpus manifest, workload input set, execution receipt set, coverage and per-stratum count
reconciliation, provenance/custody record, criteria evaluation, results, and known gaps. Its actual
target, eligible, selected, executed, valid, and assessed counts must be nonzero where required and
reconcile exactly for every required stratum. Before Stage B use, the Stage A signer and receipt
must be reverified under current policy, revocation, trusted time, custody, and separation evidence.

The later Stage B successor `/2` decision is `ADEQUATE`, `INADEQUATE`, or `ABSTAIN`. `ADEQUATE`
requires every required raw artifact and stratum, all count predicates reconciled, every criterion
evaluated, zero blocking gaps, and fresh current authority. Workload review `/1` accepts only
`ADEQUATE` or `INADEQUATE`; it cannot represent abstention. Missing custody, criteria, denominator,
trusted time, current policy, or genuine separation must yield `/2` `ABSTAIN` and a final-freeze
`BLOCK`, never `ADEQUATE`.

The tracked synthetic gateway denominator and boundary measurements are useful prototype evidence,
not a representative field-workload denominator.

## R2-AUTH-004 decision packet

The generated packet presents `PROPOSED_UNAPPROVED` Profile P1 for
`APPROVE_PROFILE_P1_FOR_IMPLEMENTATION` or
`HOLD_R2_AUTH_004`. Approval authorizes only implementation of the proposed validation mechanics;
it does not close `R2-AUTH-004` or designate an operational authority. A later operational
designation and evidence packet must name, without invention:

- an accountable policy authority;
- an independent reviewer organization and principal;
- the policy-authority, reviewer, producer, collector, budget-proposer, release-builder, and key-
  custodian principal namespaces;
- a key-custody quorum and recovery process;
- a trusted-time authority; and
- an append-only policy-ledger witness and custody location.

Profile P1 requires separate policy-authority and reviewer keys, two-person control with offline or
hardware-backed custody and quorum-preserving recovery, signed predecessor-linked policy
succession, monotonic sequence, cumulative non-removable revocations, a trusted timestamp over the
review receipt and policy head, trusted evaluation time, explicit policy and receipt validity
intervals, a revocation observation sequence, and a signed separation decision binding externally
grounded identities, organizations, the role-conflict matrix, reviewer, and evidence digest.

The authenticated policy-selection/succession receipt must bind the authority namespace, policy ID,
monotonic sequence, predecessor and current policy digests, genesis-root authority basis, candidate
bindings digest, review-receipt digest, cumulative key-and-receipt revocation-ledger digest and
high-water mark, trusted-time evidence digest, and expiry. Local code can validate structure,
signatures, digests, and linkages relative to supplied roots; it cannot establish the external truth,
custody, authority, time, or separation those inputs assert.

`R2-AUTH-004` remains open until an externally accepted policy, key and custody evidence, current
trusted time and revocation evidence, and genuine reviewer separation are all bound to the selected
candidate and freshly verified.

## Versioned successor boundary

Freeze `/1` and runtime inventory v1 remain preserved and fail closed; discovery `/5` remains
incomplete-only. Workload review `/1` remains a structural detached-review verifier but is not a
closed representative-workload evidence protocol: it can accept an `ADEQUATE` receipt over one
generic manifest artifact without binding the raw artifact bytes, closed roles, or reconciled
counts. A versioned final-freeze successor may be implemented only after its consumed authority
profiles are fixed. It must join fresh runtime-closure, workload-adequacy, and TCB-budget
authorizations over one exact candidate and compare their bindings, policy heads, trusted times,
and evidence digests at every use. It must reject historical booleans, policy forks or rollback,
shrinking revocation history, stale time, subject teleportation, identity conflicts, missing raw
artifact bytes, and marker deletion without a positive current authorization.

Encoding unknown principals, workload thresholds, custody rules, or trust roots into source would
be fabrication rather than technical progress. Those values remain null in the generated packets
until an accountable external decision supplies them.
