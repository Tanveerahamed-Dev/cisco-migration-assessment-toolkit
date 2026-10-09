# W52 / G14: stored cable and VLAN carriage

Status: **reviewed hosted material adopted; final runtime qualification pending.** Base main is
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

## First hosted bootstrap and reviewed material adoption

Initial draft #631 published `c47f8d5894d3a7bd71304d1609c3be6f76014157`, sole
parent `f797444e`, tree `83a13b8d7a2900c3e24bb32c1b1acfc2d689b499`. PR tested
`97dcf82dd2317341d3c6543011a8d04e339336cc` has ordered f797+c47 parents and the
same tree. Pre-publication canonical privacy and all twelve history/text rules
passed on that reviewed tree; all earlier rejected source snapshots remain.

Actual early LF job `113749653439` failed its receipt assertion (one failure,
0.52 seconds), printing LF183/`ad3a288e2262578228c5d7484b584afed7a586968e4a1b5d2bbcb779e220c589`
and broader145/`70d0567fa2dc96b3d1f5ac4a63d4bafe2e2958880de598f7c677f94ee44b1ee0`.
Only those observed receipt pairs are adopted. The new LF-domain path is the
carriage owner. Rules, publisher scope, derived owners and assertions are intact;
the later attribute/byte guards and full suite were skipped and still need fresh
execution. No receipt digest was calculated locally.

Frontend job `113749716400` completed observation and upload, then failed the
unchanged generated-API agreement check. Later unit/type/build/SPA capture work
was skipped. E2E job `113749716231` separately stopped at web-server exit2 and its
upload found no test-result files. Its child compiler/build/preview cause was not
printed and remains unknown; it was not a passing browser run.

The completed backend log later supplied 141 named API failures: 139 concern
the old native-pin/admission/proof path, while two STP-blocked view/list cases
fail before native construction. They must not be attributed to pins. Independent
source tracing found that the positive test fixtures omitted the CLI table
separator: candidate counting requires it, while the role parser still reads
the line, so zero candidates versus one parsed row correctly produces unverified.
The correction changes only fixture framing, adds positive 1/1/no-malformed
preconditions and preserves a missing-separator refusal case. All production
admission, expected published STP-blocked results and native-return assertions
remain unchanged. Fresh hosted execution must verify the correction; the prior
source review missed the framing mismatch. The first material-adoption privacy
pass on tree3481417c is historical after this necessary test-only correction.

Linux 3.12 job `113749653192` subsequently finished with 164 failures, 11,794
passes, 144 skips, one xfail, eight warnings and 26 subtests. Its own failure
census is 139 native cases, two API STP cases, two golden cases, one LF case,
three source-contract misses and 17 root producer/projection STP-fixture cases.
The latter share the same helper; their recovery is still unverified. The final
UTC sample check was skipped after the failed full suite.

The three source-contract corrections retain the existing guards: derive the
carriage state vocabulary from SSOT in its original order, bind hold precedence
to owned state values, expose exact public host/port identity helpers instead of
private projection imports, register only the nine specific read-only carriage
imports, and assert the exact fourth selection source alongside the original
three. The reviewed sample's carriage source is unverified; a separate legacy
case without it stays not-collected/empty. No scanner exception, wildcard import,
recomputation permission or dropped assertion is added. State values/order and
normalization behavior are preserved by source review and authored parity cases;
fresh generated-output comparison and runtime recovery remain mandatory. The
completed f6bbe544 privacy pass precedes these corrections and remains historical.

Manual run `37909228079` / job `113750067226` completed successfully on **c47
itself**, with 210 mandatory controls passing and no skips, two canonical
generation-mode golden writers passing with shrink disabled, then real sample
generation, privacy/capture and upload. These writer passes are not the final
unchanged-golden comparison. One independently selected artifact `11605957977`
was received once as inert data. Its four members and all 1,721 non-output Git
inputs were reviewed; the six installer metadata files remain bounded installer
data, not authenticated program source or archive custody.

The reviewed workbook schema is byte-identical. Golden changes are new carriage,
its census and module counts. The sample has ten changed top-level sections in
total, including carriage/census, and 226 existing leaf changes: raw timestamps, protocol input/baseline hashes,
71 source byte sizes and module counts. In particular, collected_at changes from
`2026-08-07T00:00:00+03:00` to `2026-08-07T00:00:00+00:00`. Host newline effects
on receipt bytes are a source-supported explanation, not a locally recomputed
hash proof. No changed risk/decision value was found. Golden carriage has 18
pairs (4 published, 3 not-collected, 11 unverified); sample carriage has 220
(33 published, 84 not-collected, 103 unverified). Both sections remain unverified
with incomplete input census and no capture-completeness claim. The sample has
14 forwarding and 19 not-carried relations; a sampled STP-blocked case is not
invented from the separate authored controls.

Contract diagnostic `11605328978`, received once, binds tested97dc/tree83a with
all 1,724 before/after Git inputs. Independent review admits the exact generated
TypeScript and observed literal view pin
`1851c39053e44c896b5fced607e4ce2e4d7f4e83f77fab3e19081efc1179545e` and list pin
`d0535478d51055a3926b975c5cf27cfc3cedcf0fafe70f4a46513ebb025f700b`.
The TypeScript delta includes nine G14 definitions/links/vocabulary and 27
canonical tuple-to-array representations; actual JSON/native limitation-array
bounds remain 30 (path-view18). No runtime schema bound was removed or local
generator/schema hash substituted.

This correction copies only reviewed material and literal pins. It still needs
fresh native True/False/False/no-exception and published-relation proof, full
default/golden/sample checks and all protected workflows. The new sample must
receive its own hosted Scope rebind. The new VLAN renderer also needs the existing
hosted frontend receipt route and reviewed committed distribution before the
portable source comparison can pass. No old compiled output qualifies this head.
