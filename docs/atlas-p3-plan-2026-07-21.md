# Atlas P3 — Field discipline: implementation plan (2026-07-21)

**Status:** proposed — awaiting owner approval before implementation.
**Upstream:** ADR-0004 (P0 decisions, D5 amendment), Project Atlas artifact §15 (the trusted
roadmap), P1 complete (PRs #404/#405), P2 complete session-side (PRs #406/#409; stick built and
selftest-proven on-stick 2026-07-20).

## Scope — the artifact §15 P3 row, verbatim

> **P3 · Field discipline** — SQLite unplug-safety: integrity check + timestamped backup at boot,
> write-probe with a friendly error on read-only sticks, eject discipline in the README;
> BitLocker-To-Go guidance (client evidence lives on that stick); `--redact` as the documented
> "before it leaves the site" step; credentials prompted, never stored; update = replace `app\`,
> keep `data\`.
> **Done when:** README-FIELD covers loss-of-stick, read-only, corruption, redaction and update
> scenarios. **Size:** 1 session.

## Clause-by-clause gap analysis (verified against code this session)

| P3 clause | Reality on main (2026-07-21) | Disposition |
|---|---|---|
| Integrity check + timestamped backup at boot | `webapp/backend/storage.py::Store.__init__` opens the DB with only `PRAGMA foreign_keys = ON`; no check, no backup anywhere in `webapp/backend/` | **BUILD — slice 1** |
| Write-probe, friendly error on read-only sticks | `--selftest` has the db-writable probe (`serve.py::run_selftest`); a plain serve on a write-locked stick dies in `Store.__init__`'s `mkdir` with a raw traceback | **BUILD — slice 1** |
| Eject discipline in the README | No field-facing README exists (`portable/README.md` is the developer/build doc) | **BUILD — slice 2** |
| BitLocker-To-Go guidance | One sentence in `portable/README.md` | **DOCUMENT (slice 2) + OWNER action** on the physical stick |
| `--redact` documented as the leave-site step | Engine flags exist (`COLLECT_PARSE_V3_23_0.py:1627` `--redact`, `:1632` `--redact-collection`) and are reachable frozen via `Atlas.exe --run-engine` (P2 smoke proved the sentinel reaches the real argparse) | **DOCUMENT — slice 2** |
| Credentials prompted, never stored | The engine chain (ADR-0004 D4, `COLLECT_PARSE:1148-1181`) already does this on the console build. **The D4 sentence "AssessKit P1 surfaces this as a one-prompt fleet flow with a per-device override editor" was never built** — `webapp/backend/app.py` has no collection route at all; live collection from the stick is terminal-only (`Atlas.exe --run-engine …`, getpass per username) | **DOCUMENT + explicit deferral decision** (below) |
| Update = replace `app\`, keep `data\` | **Done in P2**: `portable/make_stick.ps1` re-run is the update flow (robocopy `/MIR` with absolute `/XD` on top-level `data\`; `tests/test_make_stick.py`) | README documents it — no code |

## Slice 1 — evidence durability at boot (code PR, `feat/atlas-p3-unplug-safety`)

The stick gets yanked, the laptop dies mid-write, the DB is client evidence. Boot must prove the
store is sound and keep a restorable copy — fail-loud, never destructive.

1. **`storage.py`** — boot hardening in `Store` (opt-in flag, threaded from the production entry
   so dev servers and tests don't grow backup dirs):
   - Open → `PRAGMA quick_check` → on failure **refuse to serve** with a message naming the DB
     path and `data\backups\`. Never delete, rename, or overwrite the corrupt file (it is client
     evidence; restore is a human action documented in README-FIELD).
   - On pass → `sqlite3.Connection.backup()` to `data\backups\assesshub-<UTC-stamp>.db`;
     **skip** when the newest backup is not older than the DB file's mtime (a boot loop must not
     churn a 100 MB store); **rotate keep-3**, oldest deleted last-first.
   - Pin `journal_mode=DELETE` + `synchronous=FULL` explicitly with the unplug rationale
     (these are SQLite's defaults — make the choice visible; WAL is deliberately NOT used:
     an orphaned `-wal` on exFAT after a yank is worse than rollback journaling).
2. **`serve.py`** — pre-serve write probe (the selftest's probe, reused): on a read-only
   `data\`, print a friendly two-line explanation (write-locked stick / NTFS perms / how to
   check) and exit 1 instead of the mkdir traceback. `--selftest` gains/extends a check for
   `data\backups\` writability (count moves past 8/8 — memory + docs note updated at merge).
3. **Tests** (`webapp/tests/test_atlas_entry.py` + storage tests): corrupt-DB fixture → boot
   refuses with the message; backup created / skipped-when-fresh / rotated at 3; read-only
   parent → friendly error path (probe seam, not real ACLs, for CI portability). Full gate green.

## Slice 2 — README-FIELD + bundle wiring (docs PR, `feat/atlas-p3-field-readme`)

1. **`portable/README-FIELD.txt`** — the field engineer's one page, shipped in the bundle root
   (lands on the stick at `Atlas\README-FIELD.txt`). **ASCII-only** (the make_stick.ps1 cp1252
   lesson applies to anything opened on arbitrary Windows boxes). Covers, as named sections, the
   five exit-gate scenarios plus daily discipline:
   - **First run / every engagement start:** `Atlas.exe --selftest` — expect all checks PASS.
   - **Loss of stick:** BitLocker-To-Go is the mitigation — enable once (owner, admin, physical
     stick); without it a lost stick is a client-data incident.
   - **Read-only stick:** what the friendly boot error means and how to clear it.
   - **Corruption:** what boot already did (quick_check + `data\backups\`); restore = close
     Atlas, copy the newest backup over `data\assesshub.db`, reboot, selftest.
   - **Redaction — before anything leaves the site:** `Atlas.exe --run-engine … --redact` for
     the deliverable set; `--redact-collection` to scrub raw captures in place.
   - **Update:** re-run `make_stick.ps1` (or copy a new bundle over `Atlas\`) — everything is
     replaced except `data\`; then `--selftest`.
   - **Credentials:** prompted per run (once per username, per-device `password_env` overrides),
     never written to the stick.
   - **Eject discipline:** close Atlas (Ctrl+C / close the console) → Windows "Safely remove" →
     then pull.
2. **`portable/atlas_bundle.py`** — add README-FIELD.txt to the manifest; gate test in
   `tests/test_atlas_bundle.py`.
3. **Ratchet test** (repo style, kills doc-rot): parse README-FIELD.txt — every `--flag` it
   names must exist in the engine or serve argparse; the five scenario section headings must be
   present (the artifact's "done when", mechanized).
4. **`portable/README.md`** — link README-FIELD, drop the "(P3)" future-tense from the
   field-discipline bullet.
5. **ADR-0004 amendment (P3 note):** record (a) the D4 UI fleet-flow deferral below, and (b) the
   artifact-vs-reality delta already shipped in P1/P2: there is no separate `cisco-assess.exe` on
   the stick — the `--run-engine` sentinel is the CLI door.

## Decision for the owner — D4 credential UI: recommend DEFER (not P3)

ADR-0004 D4 sketched an AssessHub "one-prompt fleet flow + per-device override editor". It was
never built, and I recommend **keeping it out of P3**:

- The artifact's P3 scope does not include it; the console path already satisfies the field
  requirement ("prompted, never stored" — D3's explicit-opt-in collection, getpass on a real
  terminal, which is exactly why the build is `console=True`).
- Building it means SSH credentials transiting browser → backend → child-process env: a new
  secret-handling surface (logging, XSS/CSRF blast radius) in a webapp we just spent three
  hardening PRs locking down — real cost for a flow the terminal covers.
- If the owner wants browser-driven live collection later, it becomes a P4 candidate with its own
  security review. The ADR amendment records the deferral + revisit trigger.

## Owner checklist (calendar items)

One bullet per item, open ones first — a status that changes does not belong in the heading.

- **NEW:** enable BitLocker-To-Go on the physical stick (admin, one-time; README-FIELD will
  carry the steps).
- Still owed from P2: `Atlas.exe --selftest` once on a **Python-less** PC.
- Still owed from P2: **confirm the 2026-07-05 credential rotation** — independent of the attic,
  and made *more* urgent rather than less by the unaccounted-for credentialed backup ADR-0004
  now records.
- ~~delete `..\Enhancements_attic_2026-07-05\`~~ — DONE 2026-07-25 at the owner's instruction;
  ADR-0004 carries the verified inventory.

## Exit gate & bookkeeping

- Both PRs green on the full gate; README-FIELD scenario coverage enforced by the ratchet test.
- **Bundle rebuild + stick update** (required by slice 2 anyway — README-FIELD ships inside the
  bundle): `npm run build` + `python portable/build_atlas.py` + `make_stick.ps1`. NB the stick
  made 2026-07-20 predates the entire 25-unit motion/design wave (#407 first merged 12:56 that
  day; wave ran through 07-21) and no built bundle currently exists in the checkout — this
  rebuild is what brings the field app fully current with the new UI/UX, `data\` preserved.
- After merge: update the Project Atlas artifact §15 (same URL — "P3 done" callout in the
  decided-box style), refresh the portable-app memory (selftest count, P3 status), and log the
  retro lesson if any.
- Size check against the artifact estimate: 1 session, 2 PRs — consistent.
