# Atlas bounded braces

This local package replaces `braces` on exactly one dependency edge of the
Master Reference build: Vinext 0.0.50 -> vite-plugin-commonjs 0.10.4 ->
vite-plugin-dynamic-import 1.6.0 -> its nested fast-glob 3.3.3 ->
micromatch 4.0.8 -> braces. The override in `master-reference/package.json`
sits inside the `vinext@0.0.50` object, and no other lock record resolves
`braces`.

## Why it exists

GHSA-vfj7-8cjw-p6xm (CVE-2026-93687, CWE-674, CVSS 7.5) covers every published
`braces` release (`<= 3.0.3`). The recursive AST walkers in `lib/compile.js`,
`lib/expand.js` and `lib/stringify.js` have no depth guard, so a deeply nested
brace or parenthesis pattern under the 10,000-character input limit can
exhaust the call stack. No patched npm release exists; 3.0.3 is still the
latest release.

## Provenance

- Base: npm `braces` 3.0.3 as published. Tarball integrity
  `sha512-yQbXgO/OSZVD2IsiLlro+7Hf6Q18EJrKSEsdoMzKePKXct3gvD8oLcOQdIzGupr5Fj+EDe8gO/lxc1BzfMpxvA==`,
  the value the lock recorded for `node_modules/braces` before this
  substitution. `LICENSE`, `index.js` and `lib/utils.js` are the published
  bytes. The MIT licence and Jon Schlinkert's copyright stay with upstream.
- Patch: only the five `lib/` hunks of pull request micromatch/braces#72,
  head commit `d0d575e55e74a4e0218e5248fafb79efc3e54ebb`, authored by GitHub
  user `FSDevelop`. When it was pulled (2026-10-03T03:19:55Z) the pull request
  was OPEN and unmerged; its author has no association with the repository and
  its only approval came from another non-member. This is unmerged third-party
  code applied on top of released braces 3.0.3. It is not a braces release and
  not a maintainer-reviewed fix.
- Nothing else changed. The pull request's base commit carries two unreleased
  `lib/parse.js` changes (unpaired quotes, comma invalidity reset); they are
  not included. Its `.verb.md`, `README.md` and `test/` hunks are not part of
  the published package and are not vendored; their regression cases live in
  `master-reference/tests/source/bounded-braces.test.mjs`, which rebuilds the
  published files from these bytes and the recorded patch and checks every
  digest.
- The published `README.md` and `package.json` are replaced by this file and
  the Atlas manifest. The manifest keeps the CommonJS `index.js` entry, the
  absence of an `exports` map and the `fill-range` dependency.

## The bound

`lib/constants.js` adds `MAX_DEPTH: 100`. `parse` counts brace and parenthesis
nesting together and throws `SyntaxError: Input depth (101), exceeds max depth
(100)`. `compile`, `expand` and `stringify` throw `RangeError: AST depth (101),
exceeds max depth (100)` for a node with children deeper than 100, so an AST
passed in directly cannot bypass the parser. `options.maxDepth` can lower the
limit; larger values are capped at 100, and a non-finite value is ignored.

## Review of the patch (2026-10-03)

| File | Hunks | What the hunk does |
| --- | --- | --- |
| `lib/constants.js` | 1 | Adds the numeric constant `MAX_DEPTH: 100`. |
| `lib/parse.js` | 7 | Imports `MAX_DEPTH`; derives `maxDepth` from `options.maxDepth`, capped at 100; adds a `nesting` counter; before opening `(` or `{` throws when `nesting >= maxDepth`, then increments; decrements where a paren or brace block actually closes. |
| `lib/compile.js` | 2 | Imports `MAX_DEPTH`; adds a `depth` argument to the recursive walker, throws when a node with children is deeper than `maxDepth`, passes `depth + 1` to children that have children, and starts at 0 for a root node and 1 otherwise. |
| `lib/expand.js` | 3 | The same walker guard as `compile`. |
| `lib/stringify.js` | 2 | The same walker guard. The recursive call also passes the current node as `parent` where 3.0.3 passed none, and the file's trailing blank line is removed. |

- The patch adds no I/O, network access, `eval` or `Function`, dynamic
  `require`, prototype or global mutation, timer or dependency. Its only new
  `require` is the static `require('./constants')`.
- It does change behaviour beyond the depth bound in three places:
  1. `stringify` with `escapeInvalid: true` now consults the real parent, so
     `braces.stringify('{{a}}', { escapeInvalid: true })` returns `{{a}}` in
     3.0.3 and `\{\{a\}\}` here (likewise `{a}`, `a{b}c`, `{1..8}` and
     nested sets). During that call `utils.isInvalidBrace` also sets
     `invalid = true` on the parent node of the caller's AST.
  2. A fractional `maxDepth` is applied inconsistently: `parse` checks
     `nesting >= maxDepth` before incrementing while the walkers check
     `depth > maxDepth`, so `{ maxDepth: 1.5 }` lets `parse` admit depth 2 and
     `compile` refuse it. Integer limits, including the default, agree.
  3. A missing or non-object AST now fails with a `TypeError` reading `type`
     instead of `invalid` or `queue`.

  None of these is reachable from the installed consumers: fast-glob 3.3.3
  calls `micromatch.braces(pattern, { expand: true, nodupes: true,
  keepEscaping: true })`, and no package on the edge passes `escapeInvalid` or
  `maxDepth`. The contract test pins all three, so they stay visible.
- Kept unchanged from 3.0.3: `lib/compile.js` still calls
  `console.log('node.isClose', ...)` for an AST node marked `isClose`. Parsed
  patterns never carry that mark, so only a hand-built AST reaches it.

## What this does not establish

The tests prove the bound through the real consumer chain and the same output
as braces 3.0.3 for ordinary patterns. They are not an externally
authenticated advisory, applicability or VEX review. npm audit skips linked
packages and their targets, so its silence about `braces` is not evidence of
closure. The patch does not bound expansion size beyond upstream's
`rangeLimit`, and a hand-built AST whose `parent` chain cycles still makes
`expand` loop; neither is the advisory's recursion class, and parsed patterns
cannot produce the cycle. The override cannot reach braces code compiled into
another package: Vite 8.2.x bundles its own unbounded braces 3.0.3 for its
chokidar copy, and the release gate reports it separately. Remove this package
and its override once a maintainer-reviewed braces release carries an
equivalent bound.
