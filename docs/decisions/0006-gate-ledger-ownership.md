# 0006 — Gate-ledger ownership: declared, not inferred

- **Status:** accepted (2026-07-22)
- **Deciders:** Tanveer Ahamed (delegated to the engagement-lead session with "take the best
  possible decision" on all four questions, after being presented the refutations below)
- **Context:** `cisco_toolkit/gate_state.py` stores PPDIOO document-gate approvals in
  `docs/engagement-state.json`, resolved relative to a `root` argument (default: the process
  working directory). Gate state is documented as **per-engagement**, but nothing in the ledger
  recorded *which* engagement it governed — ownership was inferred entirely from where the process
  happened to be running. This blocked two things: enforcing the MOP gate on the Atlas field path,
  and any automatic gate disclosure in the field tool.

## The refutations this decision rests on

Two ownership heuristics were implemented and refuted with runnable end-to-end demonstrations
(2026-07-22), then reverted:

1. **Anchor on the invoking process cwd.** Resolves to the shell's directory, which varies by launch
   method. For `Atlas.exe` on a USB stick that is the `Atlas\` folder, which `portable/make_stick.ps1`'s
   `robocopy /MIR` wipes on every update — a ledger could never durably live there.
2. **Anchor on the collection folder and walk up (bounded) to the nearest `docs/engagement-state.json`.**
   Demonstrated to adopt a *shared* parent's or the repo checkout's ledger: a run for engagement
   GLOBEX printed "all recorded approvals present" out of engagement ACME's ledger. The documented
   field layout (`<STICK>/collections/acme`, ledger at `<STICK>/docs/`) sits inside any sensible
   bound, and wrapping a folder in an archive makes the same constant simultaneously overshoot and
   undershoot.

The conclusion drawn is **not** that a third, smarter heuristic would work. It is that proximity is
not ownership, and ownership must be declared.

## D1 · A ledger declares what it governs; a run declares what it is for

The store gains an append-only top-level `engagement` identifier (`ENGAGEMENT_KEY`), and
`enforce()` / `record_decision()` / `pending_approvals()` accept the engagement the run declares.
Verification replaces inference:

| ledger declares | run declares   | outcome                                                     |
| --------------- | -------------- | ----------------------------------------------------------- |
| nothing         | nothing        | legacy — proximity decides, gates apply UNVERIFIED (unchanged) |
| an id           | nothing        | gates apply, logged UNVERIFIED (operator is at the root)     |
| an id           | the same id    | gates apply, VERIFIED                                        |
| an id           | a different id | **REFUSE**, not overridable                                  |
| nothing         | an id          | **REFUSE** — bind the ledger first                           |

Silence stays permissive, so every ledger that exists today behaves exactly as it did — the field
is additive, not a migration of live engagements (pinned by
`test_unbound_ledger_and_undeclared_run_behave_exactly_as_before`).

Both refusals are **non-overridable**. `--override-gate` is consent to bypass a *known* gate; when
ownership does not check out, no gate for this engagement has been located, so there is nothing to
consent to. This is the same reasoning that already makes a mis-set `root` non-overridable. The
refusal also writes nothing — an override audit line landing in another client's ledger is itself
the harm.

The check applies to the **write** path too (`record_decision`). A mis-attributed approval is worse
than a mis-attributed read: it both fails to gate the engagement the lead meant *and* silently
unblocks a different one.

Binding is one-time (`gate_state bind <id>`). Re-binding to a different identifier is refused, not
warned about: every approval already in the ledger was signed for the engagement it was bound to,
and moving the label would retroactively re-attribute all of them.

## D2 · The identifier is human-minted and opaque, not derived from the evidence

The tempting candidate — derive identity from the snapshot (`ssot.canonical_facts`, the assessment's
own fields) — is refuted on three independent grounds, each sufficient:

1. **There is nothing to derive it from.** The snapshot has 59 top-level sections and not one names
   a client or engagement; the engine has no `--client`/`--engagement` input. `canonical_facts`
   yields *counts* (303/253/50), not identity.
2. **Redaction splits any derived key.** `--redact` pseudonymizes IPs, MACs and serials, so a
   fingerprint over those differs between the redacted and unredacted run of the *same* engagement —
   and the redaction path is precisely where ownership was needed. (Hostnames survive redaction, so
   a hostname-set hash would too — but see 3.)
3. **The fleet is the thing being replaced.** The gates span Assess→PIR, an interval across which a
   migration deliberately changes hostnames and hardware. Any fleet-derived key drifts across
   exactly the window the ledger must stay valid, and matching it fuzzily is a heuristic again.

`collected_at` identifies a **collection** (a baseline, a pre and a post are several per engagement),
not an engagement.

Comparison is case- and whitespace-insensitive; values are stored verbatim. A refusal over
`acme-2026` vs `ACME-2026` would only teach operators to stop passing `--engagement`.

## D3 · The two gate records stay distinct and share the identity vocabulary

`webapp/backend/gates.py` maintains a separate per-campaign gate board in SQLite (the per-wave
T-minus axis, `engagement.GATE_SEQUENCE`, `UNIQUE(campaign_id, wave, gate)`).

They do **not** converge. A document approved once and a wave signed at each T-minus are different
facts, so under `docs/ssot.md` Law 1 each already keeps exactly one owner — merging them would force
the stdlib-only JSON ledger to carry wave rows it has no use for, or force the stick to carry
campaign state it cannot have. Note also that the SQLite board has no ownership defect to fix:
`campaign_id` is a verified foreign key, unambiguous within its database.

What converges is the **vocabulary**: `engagement` is the token both records name, and what any
future join would key on. No SQLite schema change is made now, because none is needed to hold that
position.

## D4 · MOP posture: block only on a *verified revoked* gate; disclose everywhere else

The MOP is the one deliverable where blocking genuinely contains something — its cutover procedure,
quantified rollback triggers, RACI and sign-off blocks exist in no other artifact. (The design's
`target_state`/`wave_plan` also ship in the snapshot, the explorer and the executive deck, all
written *before* the gates run, so refusing the design DOCX withholds two renderers while the
unapproved design ships anyway and tells the operator it was withheld — a false containment claim,
worse than an honest ungated one.)

So the narrow, defensible rule when a caller can name its engagement: refuse the MOP on an
explicitly **revoked** `lld_approved`, verified against a ledger proven to govern this engagement.
`is_revoked` / `revoked_requirements` make that distinction first-class — a gate nobody ever signed
is unapproved *by silence* (perhaps an engagement that never opted in), while a revoked gate is a
human's positive withdrawal of approval. Only the second is strong enough to withhold. Blocking on
mere absence would re-introduce the brownfield trap at the worst possible moment.

Everywhere else, **disclose rather than withhold**: `pending_approvals()` reads the posture without
deciding and without writing, never raises, and never claims approval it did not verify.

`webapp/backend/ingest.py::run_redaction_folder` therefore stays **ungated**, now for a sharper
reason: the stick carries no engagement identifier and no field UI collects one, so the run cannot
declare what it is for — the legacy row of the table. Wiring the MOP rule there is gated on giving
the field tool an engagement identifier, which is a change to its inputs, not to this decision.

## Consequences

- New: `--engagement` on the engine CLI; `bind` verb and `--engagement` on `approve`/`revoke`;
  `show` prints the engagement governed or a loud `UNBOUND`. *(Re-verified item by item against
  main on 2026-07-25 — all present.)*
- ~~Existing ledgers and existing invocations are unaffected until someone binds one.~~
  **Corrected 2026-07-25 — see the Correction below.** What holds is the narrower claim: the
  **ownership model** is inert until a ledger is bound — an unbound ledger read by an undeclared
  run decides exactly as it did before, and ownership itself never refuses. The ledger FILE is a
  separate matter: a missing-approval refusal now appends an audit row to *any* readable ledger,
  bound or not.
- Auto-discovery is now explicitly a **non-goal**. A future "smarter resolver" would be
  re-introducing the defect this closes.
- Pinned by `tests/test_gate_state.py` (the ownership table row by row, non-overridability,
  write-path refusal, re-bind refusal, the disclosure contract, and the engine source guard).
  *(Re-verified 2026-07-25: all five table rows, `..._not_overridable_and_write_nothing`,
  `..._signing_into_another_engagements_ledger_is_refused`, `..._refuses_a_rebind`,
  `..._pending_approvals_reads_without_deciding_or_writing` and the engine source guard are
  present.)*

## Correction (2026-07-25) — "existing ledgers are unaffected" was false

This ADR had exactly one commit (`1c5304f`) and was never revisited when the refusal-audit
reconciliation landed, so a Consequences bullet went stale in a way that mattered: it told a reader
that adopting ADR-0006 could not touch an existing ledger file. It can.

The falsifier is **not** the ownership model. It is the refusal-audit feature (`GateVerdict` /
`_record_refusal`, commit `f64c655`) which rode into the same PR #439 from a different session and
was later reconciled with #445: `enforce()` now appends a durable `refuse` row for every refusal
that has a readable ledger to write to, so that the *safe* path is as auditable as the override.
`cisco_toolkit/gate_state.py` says so directly — "The ledger therefore grows by one row per refused
deliverable per run."

Reproduced against main (legacy ledger, never bound; run declares nothing):

```
bound?  None      audit rows BEFORE: 1
enforce("mop")  ->  status=pending, proceed=False
                  audit rows AFTER : 2
new row: {"event":"refuse","generator":"mop","status":"pending",
          "engagement":null,"declared":null,
          "missing":["lld_approved","baseline_captured"], ...}
still unbound?  None
```

The boundary is exact, and the ownership half of it is intact — only a `pending` verdict (a
readable ledger that located a gate and it said no) is recorded:

| ledger / run | status | ledger written? |
| --- | --- | --- |
| unbound, undeclared | `pending` | **yes** |
| bound ACME, declares ACME | `pending` | **yes** |
| bound ACME, declares GLOBEX | `ownership_mismatch` | no |
| unbound, declares ACME | `ownership_unbound` | no |

The two ownership refusals write nothing by design — appending would enrol an unenrolled
engagement, or let one engagement's run touch another's ledger. They are two of the five members of
`gate_state.UNEVALUATED` (`bad_root`, `ungated`, `unreadable`, `ownership_mismatch`,
`ownership_unbound`), which report `GateVerdict.recorded=False` rather than implying a write, and
are pinned by `test_ownership_refusals_are_not_overridable_and_write_nothing` and
`test_ownership_refusal_stays_unrecorded_and_says_so`.

Decision content (D1–D4) is unchanged; this is a factual correction to Consequences only.

**related:** `cisco_toolkit/gate_state.py :: ENGAGEMENT_KEY`, `ownership_error`, `engagement_of`,
`bind_engagement`, `enforce`, `record_decision`, `pending_approvals`, `is_revoked`,
`revoked_requirements`; `webapp/backend/ingest.py :: run_redaction_folder`;
`webapp/backend/gates.py`; `cisco_toolkit/engagement.py :: GATE_SEQUENCE`;
`tests/test_gate_state.py :: test_no_engine_caller_declares_a_gate_posture`; `docs/ssot.md`.
