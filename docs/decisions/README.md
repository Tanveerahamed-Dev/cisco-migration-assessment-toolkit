# Decision records (ADRs)

One file per engineering decision that isn't derivable from the code: `NNNN-<kebab-slug>.md`.
Registered fact-domain: **"why we decided X" lives here** (per `docs/ssot.md` Law 1 — the code owns *what*,
graphify owns *structure*, this directory owns *why*). Keep each record short: Context → Decision →
Consequences → `related:` symbols/docs. Name code symbols exactly (so `python -m graphify explain <symbol>`
finds the record once the graph re-extracts docs/).

Existing decisions of record predating this directory live in the planning docs
(`IMPROVEMENT_AND_GREENFIELD_PLANS.md` PLAN-B verdict, `docs/next-best-improvements-2026-07-04.md` refuted
list, the TRAP-AVOID lists) — do not duplicate them here; new decisions start at 0001.
