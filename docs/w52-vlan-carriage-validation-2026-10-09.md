# W52 / G14: stored cable and VLAN carriage

Status: **bootstrap source reviewed; no hosted validation or readiness claim.** Base main is
`f797444eb53fb6fd5d3b2a40e0d9281c54e7a332`, the supervisor's W34/#627 merge.
The merged/head/tested715/clean tree is `4570571f10d86539cd612b61568d91822b4975fc`.
W34 is retired in this PR's board edit with its complete history retained. Codex did
not approve or merge it, and no historical G15 result qualifies this changed source.

## Product contract

G14 adds the stored `vlan_carriage/1` section. Its owner is
`cisco_toolkit/vlan_carriage.py`; it consumes the existing cable map, interfaces,
namespace-aware STP observations and the exact ordered VLAN-cutover rows. It never
changes the old `_link_carries` simulation predicate, elects a root or enumerates
all VLANs from an allowance expression.

Each cable/VLAN pair retains original row/member indices, endpoints and evidence
pointers. Its relation can be forwarding, STP-blocked or not-carried only with
admitted evidence at both ends. One end without evidence stays not-collected,
including when the other is blocked. A separate evidence-shape field distinguishes
one-end-only, no-evidence and uncertainty. Typed PVST and configured trunk allowance
are distinct bases. MST without a VLAN mapping, malformed ranges, host/port
collisions, uncertain orientation and incomplete or mixed bundles remain held.
Readable member evidence and malformed-input witnesses remain available beside the
qualified section; an input census is never collection completeness.

The projection reads this closed stored section into
`inventory.vlans.rows[].selections.carriage`. It supplies relation, basis, end
coverage, cable identity and nested member/end facts. It validates stored shape
and joins source identities; it never computes a replacement relation. Missing
legacy sections stay missing. Existing VLAN/STP facts, election ambiguities and
unknown nested-selector refusal remain. The VLAN page renders these facts and
qualifications, including readable rows inside an uncertain list. L2 styling and
the separately queued Scope raw-impact consumer are not delivered by this slice.

## Refutation history

All findings below are source-derived and unexecuted until hosted controls say
otherwise. Original rejected snapshots and reports remain in the external W52
evidence directory.

- First producer draft: malformed orphan interfaces vanished from its census;
  physical port tokens could certify a bundle; whitespace range tokenization
  could raise; validator identity/duplicate admission was incomplete. The second
  draft corrected those exact paths, but independent review then found malformed
  duplicate-member census disagreement and a real reverse-direction bundle member
  that could select unrelated interfaces. All six paths are now independently
  source-corrected with real-producer controls; hosted execution remains required.
- Initial projection draft used a different VLAN selector from the stored owner
  and could drop a missing basis pointer while retaining a published assertion.
  Owner-selector parity and source-witness admission now cover those paths. A
  held aggregate still checks identities on published end observations. A second
  review found stale literal interface/neighbor identity and configured-fallback
  STP admission gaps; shared owner admission and typed identity checks correct
  them. Six published-relation native controls supplement the sixteen hostile
  cases. Independent source clearance is not an executed native result.
- Initial regeneration-route draft did not bind run/attempt across phases and
  missed executable-mode drift on changed output files. Source corrections and
  hostile controls are independently clear for bootstrap only. The initial
  blanket untracked ban was corrected before execution to a fixed installer-data
  profile. Its actual hosted census remains unverified.

## Hosted generation and final gates

Use the bounded route in `docs/engine-output-handoff.md`: mandatory source/policy
controls before generation, complete exact-source producer success, independent
selection and semantic review of the three inert output files, then exact copying.
No workstation receiver, dry-run, engine, schema/hash controller or compiler runs.
The legacy W31 local-route and ZIP-stream findings remain unresolved and uninvoked;
producer repairs do not promote its archive custody.

The final committed candidate needs unchanged golden comparisons and a real
`build_sample.py --check` under UTC. A new sample requires reviewed hosted Scope
outputs and its exact digest binding, followed by complete current Scope gates.
Generated OpenAPI types and literal native view/list pins must come from the
existing hosted contract observer with independent delta review. Hostile native
controls must record actual True/False/False returns without exceptions, alongside
stock parity; wrapper fallback alone is insufficient.

No generated golden, sample, Scope, type or receipt value is invented locally.
New LF path-set receipts, if needed, must be observed on the hosted candidate.
Every applicable whole workflow, all current protected context instances,
CodeQL, current body/head/base/tested-tree/protection and independent final review
remain required before a single supervisor handoff. Supervisor alone approves
and merges. All W34/W45 failures, cancellations and earlier unexecuted findings
remain historical; A3/A6/B7, other O79, native licensing, unsigned/external-release,
custody and performance boundaries are not regraded.
