# Holdout activation contract — DEC-007 (P1-2)

> **The policy owner** for *when* a sealed optimisation/holdout split over the REAL PIR-outcome
> rows activates and *how* the holdout may be read — registered in [`docs/ssot.md`](../ssot.md)
> (Law 1). Ratified 2026-07-10 as DEC-007 of
> [`docs/architect-master-plan-2026-07-10.md`](../architect-master-plan-2026-07-10.md) ("hybrid:
> floors now, sealed 70/30 activates at N≥50 REAL"). Mechanics + figures owner:
> [`cisco_toolkit/holdout.py`](../../cisco_toolkit/holdout.py) — every number below is a **cited
> cache** of a code constant, never a second source. Discipline (refusal, tamper-detection,
> access-logging) pinned by `tests/test_holdout.py`.
>
> **This contract exists before the data.** The store holds zero REAL rows on the day this file is
> committed — that is deliberate pre-registration: the split rule, the activation floor and the
> read discipline are fixed and in git *before* anyone has seen the data they will govern, so they
> cannot be chosen to flatter it.

## 1. Today — below activation, nothing changes

Until activation, the repo's **existing floors are the only gates**, exactly as already built:

- **Tuning floor (D11):** `calibration.propose_adjustment` refuses to move any `ScoringConfig`
  parameter below `cisco_toolkit.calibration.DEFAULT_N_FLOOR` (= 5) **REAL** labelled outcomes,
  and is propose-only above it. Owner: `cisco_toolkit/calibration.py`.
- **Descriptive target:** N ≥ 20 REAL rows is the point at which the descriptive calibration gap
  (false-confidence / false-alarm rates) is treated as *worth reading directionally*. This is a
  **policy target owned by this contract** (ratified in DEC-007), not a code gate — nothing
  refuses below it and nothing unlocks at it.
- **No holdout exists.** No manifest file is committed below the floor (the plan's §6 frozen set:
  the sealed manifest is *created at activation*), and `python -m cisco_toolkit.holdout seal`
  **refuses** to create one — see §2.

Never fabricate rows to reach any threshold in this contract (doctrine 5 / R8): a REAL row is
minted only by a genuine post-cutover PIR, `source_class` set only by the PIR writer.

## 2. Activation — the trigger and the split

When the store's **REAL** labelled rows reach **N ≥ `holdout.ACTIVATION_FLOOR`** (= 50), the
sealed split activates as a **one-time human-run event**: `python -m cisco_toolkit.holdout seal`.

- **REAL-only, source_class-aware.** Rows count via the same discriminator as the D11 gate
  (`calibration.normalize_outcome`): only `source_class == REAL` counts; fault-injected /
  retro-public / compare-pair / shadow-PIR / synthetic / untagged / unrecognized rows **never**
  count, in any quantity. A surrogate flood can no more activate the holdout than it can unlock a
  tuning proposal.
- **Below the floor the tool refuses** (`HoldoutActivationError`, CLI exit 2) and says why —
  activation is enforced in code, not by this paragraph.
- **The split is 70/30 optimisation/holdout** over the REAL rows only (`holdout.HOLDOUT_PCT` = 30;
  holdout gets `floor(N × 30 / 100)` rows — at N = 50 that is 15/35). Surrogate rows are not
  split: they are permanently descriptive-only, so set-membership is meaningless for them.
- **The assignment is deterministic and content-addressed** — rows ordered by the digest of their
  calibration-normalized payload, lowest 30 % to the holdout. No randomness, no order dependence:
  anyone can recompute the membership. The split is *not secret*; it is *tamper-evident* (§5).

From activation onward: **optimisation rows** are the working set — threshold tuning, judge
prompt iteration, calibration-driven proposals all read them freely. **Holdout rows** are read
only per §4, only for evaluation of an already-frozen change, never to fit one.

## 3. The seal — what the committed manifest freezes

The seal is a **committed** `docs/quality/holdout_manifest.json` built on the
`cisco_toolkit/manifest.py` hash chain (the run-ledger's mechanism, reused).

> **Which sense of "tamper-evident".** The chain is **unkeyed** and `manifest.build_manifest` is
> public, so recomputing a clean `chain_root` over edited rows is trivial: on its own the chain
> catches a *careless* edit, deletion or truncation — not a forger. What upgrades the claim here is
> that this manifest is **committed**: a re-seal cannot be quiet, it has to land as a changed
> tracked file in a reviewed diff, against a `chain_root` already in git history. The run manifest
> (`<out>.run_manifest.json`) ships to a client with no such history, which is why its verify verb
> offers `--expect-root` — an out-of-band root is that file's substitute for git.

- **Step 0 seals the policy terms** — floor, split percentage, row counts — so the terms of the
  seal are themselves tamper-evident; steps 1..k each seal one holdout row's content digest.
  Editing, reordering or truncating any step breaks `chain_root` verification.
- **Digests, not data.** The manifest stores each holdout row's SHA-256, never a copy of the row —
  `docs/quality/pir_outcomes.jsonl` stays the one owner of the data (Law 1). Deleting or
  content-editing a sealed store row is caught by `verify` (the sealed digest no longer resolves,
  multiplicity-aware).
- **Coverage of the seal, said plainly:** the digest covers exactly the semantic payload
  calibration reads (`predicted`/`actual`/`source_class`/`date`/`engagement`/`unit`/`commit`/
  `notes`). A field outside that payload is outside the seal. Optimisation rows are not sealed —
  the append-only store convention and git history cover them. `sealed_at` is informational
  provenance outside the chain.
- **Committing the manifest is part of the seal.** An uncommitted manifest proves nothing; the
  git commit is what makes the seal public, timestamped and third-party-visible.

## 4. Reading the holdout — one path, every access logged

**The only sanctioned read of holdout rows is the logging accessor:**

```
python -m cisco_toolkit.holdout read --who <name> [--purpose "<why>"]
```

- Every access attempt against the data — success or integrity failure — **appends who/when** (+
  best-effort OS user, purpose, manifest `chain_root`, outcome, row count) to the append-only
  `docs/quality/holdout_access.jsonl`, which is **committed** so the trail sits in git history.
  An unattributed call is refused before anything is read.
- The accessor verifies the seal against the store before returning rows; an integrity failure
  raises *after* logging the attempt (CLI exit 4).
- Reading `pir_outcomes.jsonl` directly for optimisation work remains normal and expected — but
  work that *selects on holdout membership* outside the accessor violates this contract. That is
  a **convention the accessor makes auditable, not impossible** (see §5).
- Access-log review is part of the standing weekly review (the same cadence as the gate-override
  log, plan R3): each logged read should map to a declared evaluation event; an unexplained read
  is a finding.

## 5. What this contract is NOT — audit trail, never proof

**Mathematical proof of non-use does not exist, and this contract does not claim it** (the
coverage-honesty doctrine, applied to the contract itself). The holdout rows sit in plaintext in a
repo readable by every human and agent with a checkout; no mechanism here can make them unreadable,
and a reader who bypasses the accessor leaves no log line. What the mechanism actually provides:

1. **Tamper-evidence** — holdout membership and content are frozen under a committed hash chain;
   a quiet swap, edit, deletion or re-cut of the split breaks verification loudly.
2. **Attributable access** — the sanctioned path writes an append-only, git-tracked who/when
   trail; honest processes leave a record, and the *absence* of a record for a claimed evaluation
   is itself checkable.
3. **Pre-registration** — floor, split rule and read discipline were committed before any REAL
   data existed, so they cannot have been fitted to it.

Integrity therefore rests on **audit-trail review plus the repo's trust model** (CLAUDE.md:
"read-only is a trust model, not a sandbox"), exactly like proposer≠verifier identity fields: a
declared residual, not a hidden one. Any claim that holdout results are "provably untouched"
overstates this contract and is wrong.

## 6. After the seal

- **Rows arriving after activation** join the **optimisation** set by default; the sealed holdout
  does not grow silently.
- **Re-sealing** (e.g. to grow the holdout at a much larger N) is a **human-gated event**: the CLI
  refuses to overwrite an existing manifest; the human supersedes it explicitly — commit the new
  manifest, keep the old one's history in git, and record the decision (log + PR). Every re-seal
  resets what the holdout can honestly certify, so it should be rare.
- **Holdout evaluations** are rare, human-decided events on frozen candidates (each one leaks a
  little information — that is why every read is logged and reviewed).

## 7. Enforcement map — figure/rule → owner

| Figure / rule | Owner (read it there — cells here are cited caches) |
|---|---|
| Activation floor N ≥ 50 REAL | `cisco_toolkit/holdout.py :: ACTIVATION_FLOOR` |
| 70/30 split, holdout share | `cisco_toolkit/holdout.py :: HOLDOUT_PCT` + `split_real_rows` |
| Tuning floor 5 REAL (D11) | `cisco_toolkit/calibration.py :: DEFAULT_N_FLOOR` |
| N ≥ 20 descriptive target | this contract §1 (policy target, ratified by DEC-007; no code gate) |
| REAL vs surrogate discriminator | `cisco_toolkit/calibration.py :: normalize_outcome` / `_SOURCE_ALIASES` |
| Hash-chain seal mechanics | `cisco_toolkit/manifest.py :: hash_chain` / `verify_chain` |
| Refusal · tamper-detection · access-logging discipline | `tests/test_holdout.py` |
| Store schema (`pir_outcomes.jsonl`) | [`docs/quality/README.md`](README.md) |
| DEC-007 ratification record | `docs/architect-master-plan-2026-07-10.md` §4 |

---
*Coverage-honest by construction: this contract states its own limits (§5) and owns nothing it can
mechanically defer — every enforceable figure lives in code, every enforced behavior in tests.*
