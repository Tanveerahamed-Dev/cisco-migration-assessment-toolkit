# Atlas Release 3 QDP-001 staged operator-study contract

Date: 2026-08-31

State: `DISCOVERY_PLANNING_ONLY`

Machine authority: none

Human participant evidence: none until a real uncontaminated participant returns Phase A

## Outcome

This slice turns the tracked synthetic QDP-001 campaign into one reproducible formative
operator-comprehension study. It owns four distinct artifact classes:

1. a researcher-only exact-source master kit;
2. a standalone Phase A participant delivery;
3. a standalone Phase B participant delivery released only after an exact Phase A response
   lock verifies; and
4. a debrief released only after an exact Phase B response lock verifies.

The source owner is
`tools/build_atlas_r3_break_this_plan_operator_study.py`. The deterministic technical
scorer is `tools/atlas_r3_operator_study_scoring.py`. The campaign and discovery owners
remain the owners registered for QDP-001 in `docs/ssot.md`.

The workflow never acts as a participant, invents a participant response, starts network,
runtime, or workload collection, fills an authority placeholder, selects a candidate, or
changes a release state.

## Exact-source build

A deliverable build requires a clean, non-shallow exact source checkout. The master manifest
binds the source commit and tree plus the Git mode, blob identity, byte count, and SHA-256 of
every study, scorer, campaign, discovery, schema, fixture, contract, and transitive simulator
source named by the builder's closed source path set.

The builder recomputes the canonical tracked synthetic campaign at that exact source state.
It does not inherit the checks, reviews, approval, merge, or release status of the historical
base campaign merge. A dirty build is available only as an explicitly labelled test preview
and is not a participant or release artifact.

The source, package, stage, and response digests are unkeyed exact-byte consistency
bindings. They are not authentication, signature, trusted time, or external custody. The
master verifier regenerates every expected payload and manifest claim from the exact source,
so master-only resealing fails; an actor able to replace and reseal a per-run stage, response,
and lock chain still requires separate organizational custody to detect.

## Participant information gate

Before Phase A can be emitted, the researcher must provide one closed run configuration:

- pseudonymous participant and run identifiers;
- participant, withdrawal, and accessibility contacts;
- study purpose and session cap;
- data use, storage, access, retention, and deletion statements; and
- confirmation that recording is not planned for this minimum slice.

Required values have no source defaults. Phase A release refuses placeholders, missing
fields, unexpected fields, unsafe identifiers, or an invalid duration. The participant
information states that participation is voluntary, the participant may pause or stop
without penalty, and recording is forbidden until a separately designed consent receipt is
implemented.

## Two-phase blinding and response locks

The researcher-only master kit is never a participant delivery.

Phase A release emits only Phase A content, its response schema, the run-specific participant
information, a closed stage manifest, and a checksum list. It contains no Phase B, debrief,
answer key, source alias map, campaign machine result, or researcher material.

The Phase A lock consumes the preserved original response bytes. It:

- accepts either the browser JSON response or the deterministic no-JavaScript worksheet;
- validates exact response schema and field closure;
- binds the raw byte count and SHA-256, canonical response SHA-256, study, source, campaign,
  run, participant, and Phase A stage manifest; and
- records only local-system untrusted observation time.

Phase B release refuses a missing, malformed, cross-run, cross-participant, cross-stage,
cross-source, or byte-mismatched Phase A lock. Its stage manifest binds the exact lock
receipt digest. Phase B lock and debrief release apply the same rule in sequence.

These gates establish a local auditable workflow. A researcher with source access can bypass
it, so organizational procedure and separate custody remain required.

## Response-surface equivalence

The browser and no-JavaScript surfaces share the same closed Phase A and Phase B response
schemas and exact field sets. The worksheet contains one fenced JSON response object and is
parsed without moderator field remapping. Every required participant-entered value begins as
an explicit invalid placeholder; no answer is prefilled.

The forbidden-claim domain is eight independent required YES/NO choices on both surfaces.
N−1, N, N+1, and schema-valid hostile cases must traverse the worksheet parser and scorer
with the same canonical response and scorer disposition as the browser serialization model.
Duplicate-key, deeply nested, oversized, and placeholder worksheets must refuse before
scoring with stable bounded-input errors.

## Accessibility contract

Participant HTML is offline and source-checked for language and viewport metadata, one main
landmark, heading structure, native labelled controls, fieldsets and legends, table headers,
visible focus, responsive reflow, dark-mode contrast tokens, live status, and a no-JavaScript
path. A browser preflight may verify DOM, keyboard order, download behavior, zoom/reflow, and
JavaScript-disabled use.

Source and browser checks are not NVDA, Narrator, or other assistive-technology evidence.
The run record must name any accommodation and target AT preflight. An unmet participant
need stops or reschedules the run; it is never silently treated as success.

## Scoring and reviewers

The source scorer pins the exact source-derived answer-key digest and verifies the closed
master package before scoring. This prevents a standalone answer-key plus manifest rewrite
from passing under unchanged trusted source. It does not defeat a source-rewriting active
resealer.

Automated scoring checks closed structured values only. It always leaves
`participant_pass=null`. Two distinct reviewers must independently grade every narrative
and cross-response contradiction, record evidence locations, and freeze their judgments
before either sees the other's result. Disagreement and adjudication remain explicit.

One participant is one `HUMAN_FORMATIVE_RUN`, never operator acceptance or population
validity.

## Fixed non-promotion boundary

- Release 2: `CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT`
- QCP-001: `EXPERIMENTAL / CONTRACT_ONLY`
- runtime: `PARTIAL_NONPORTABLE_PROTOTYPE`
- Release 3: `DISCOVERY_PLANNING_ONLY`
- `R2-AUTH-001`, `R2-AUTH-002`, and `R2-AUTH-004`: null/unresolved

The study cannot select, qualify, promote, publish, ship, claim GA, or authorize any device,
runtime, workload, or field evidence collection.

## True next boundary

After exact-source integration, pristine verification, run-specific participant information,
and target accessibility preflight, release only the standalone Phase A delivery. Stop until
an uncontaminated human returns the original response bytes. No agent or synthetic fixture
can cross that boundary.
