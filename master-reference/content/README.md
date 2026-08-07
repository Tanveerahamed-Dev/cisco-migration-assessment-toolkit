# Atlas curated content layer

This directory is the repository-owned, client-free content contract for the
master reference. It is deliberately data-first so the site can render search,
tables, maps, labs, gap drilldowns, and horizon views without creating another
source of truth.

## Files

- `atlas-core.json` — truth contract, owners, current bounded facts, outcomes,
  maturity, non-goals, six system planes, eight traffic planes, and domain
  registry.
- `capability-catalog.json` — the finite, versioned closed Capability Catalog.
- `delivery-governance.json` — actionable gaps, transparent opportunity axes,
  decision queue, invariants, quality scenarios, and fourteen advisory labs.
- `open-horizon-register.json` — the separate open-world watch mechanism and
  primary-source families. Nothing in this file is a product-support claim.
- `index.ts` — static build-time exports and relationship helpers.

## Maintenance contract

1. Read `docs/ssot.md` and the named live owner before changing a current fact.
2. A `current` or `partial` record needs a live `owner_refs` entry. `partial`
   also needs a `gap_refs` entry for the unsupported remainder.
3. Every `missing`, `gated`, `excluded`, or `unknown` record needs a gap with an
   explicit disposition, next action, acceptance evidence, and owner role.
4. Bump `catalog_version` when the closed denominator changes. Describe an
   added capability as scope growth, not as a regression in implementation.
5. Keep labs and all external content `advisory`; they never mutate assessment
   truth or prove implementation.
6. Promote a horizon item only in a reviewed change that adds the capability,
   evidence contract, owner, tests, gap disposition, and denominator version
   together.
7. Run the focused validator after edits:

   ```powershell
   node --test tests/content/catalog-validation.test.mjs
   ```

Do not add raw collections, client identifiers, credentials, private paths, or
personal-vault content here.
