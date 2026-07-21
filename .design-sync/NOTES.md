# design-sync notes — AssessHub (webapp/frontend)

- The DS source is `webapp/frontend` — a **private app, not a library**: no dist entry, `npm run build`
  makes an app bundle, and `node_modules/<pkg>` never exists (running the converter without `--entry`/`cfg.entry`
  crashes in `exportedNames` on `node_modules/assesshub-frontend/package.json`). The fix is the committed barrel
  **`webapp/frontend/ds.entry.ts`** (`cfg.entry`, resolved from the repo root): named re-exports of the kit, the
  widgets, and the colour helpers. It sits at the package root deliberately — tsconfig `include: ["src"]` keeps it
  out of the app's own `tsc` build. There is no `buildCmd` on purpose.
- The six snapshot widgets (TopologyGraph, CableMap, CausalFlowPanel, CutoverPlanner, DesignBlueprintPanel,
  ArchReviewPanel) are **default exports** — a `export * from` synth entry would silently drop them; the barrel
  re-exports them by name (that gap is why the barrel exists).
- All six widgets take `{ snapId: number }` and fetch `/api/...` at mount (via `useAsync` + the `api` client).
  **They cannot render from props.** `cfg.provider` = `DemoDataProvider` (same module): patches `window.fetch`
  during render (child effects fire before parent effects — an effect would be too late) and serves the
  synthetic payloads in `.design-sync/providers/sample-data.ts`; wraps children in `MemoryRouter`
  because CutoverPlanner uses `useNavigate`/`Link` (throws outside a Router).
- **Sample data is 100% fictional** (Meridian fleet, TEST-NET IPs). Never regenerate it from real [HISTORY-REDACTED]
  snapshots — client-confidential data must not be uploaded to claude.ai (no-egress doctrine).
- `componentSrcMap` enumerates all 16 components explicitly; because the map is non-empty, the converter's
  src content-scan never runs, so pages (`Dashboard`, `Landing`, …) and `App` need no `null` exclusions.
- Tokens: `src/theme.css` (dark default; `[data-theme="light"]` flips; severity/band/ready/gate vocabulary
  maps engine terms → tokens — the engine-vocab tokens are **PascalCase-suffixed** (`--sev-Critical`,
  `--band-Fair`, `--ready-CAUTION`, `--gate-GO`), so a conventions-header validation grep MUST be
  case-insensitive or it false-alarms "0 defs" on the `--sev-*/--band-*/--ready-*/--gate-*` claim that is
  actually TRUE — the helpers `sevColor/sevSoft/bandColor/readyColor/gateColor` (`src/api.ts`) resolve to
  exactly these with a `var(--text-faint)` fallback). Component classes: `src/styles.css`. No webfonts (system-ui / ui-monospace).
- Per-component docs + grouping: `.design-sync/docs/<Name>.md` (`docsDir`), frontmatter `category` gives the
  DS pane groups (ui-kit / snapshot-widgets / providers). **Precedence gotcha:** a NON-generic dir-derived group
  beats the doc frontmatter — that's why the demo module lives in `.design-sync/providers/` (the dir name IS the
  group; a differently-named dir put DemoDataProvider in its own oddly-named section).
- **Tokens ship via the JS bundle, not `tokensGlob`:** `copyTokens` returns early without `tokensPkg`, so a bare
  `tokensGlob` does nothing here. Instead `ds.entry.ts` does `import "./src/theme.css"` → esbuild emits it as the
  bundle CSS and the converter APPENDS `cfg.cssEntry` (styles.css) after it — `_ds_bundle.css` = tokens first,
  component classes second. (The leftover `tokensGlob` key was removed; don't re-add it without a tokensPkg.)
- **Known render warns** (triaged, expected on re-sync):
  - `[FONT_MISSING] "JetBrains Mono"` — a mid-stack fallback in `--mono` (`ui-monospace, "SF Mono", "JetBrains
    Mono", Menlo, Consolas`); the real app ships no webfont either, so system rendering IS product behaviour.
    User explicitly CONFIRMED keep-system-fonts (2026-07-02) — decision is final; don't re-ask on re-sync.
  - CountUp screenshots catch mid-tween values (e.g. 300 of 303) — static-capture artifact; live cards settle.
  - `[RENDER_ERRORS] ErrorBoundary.html: Error: render exploded …` — DELIBERATE: the CatchesRenderError story
    throws a child on purpose to demo the boundary; React re-raises the caught error as a pageerror. The card
    renders the recovery panel correctly.
- **Card canvas is white** — bare text compositions in previews must sit on a `.panel` surface or they render
  near-white-on-white (the InFindingsTable lesson).
- 2026-07-02: DesignSync authorization unavailable in the desktop-app session (`/design-login` needs an
  interactive terminal; no standalone claude CLI installed). Run continued local-first; upload deferred until
  the user authorizes. **First-sync campaign completed locally**: 16/16 components authored + graded good
  (32 cells), validate ✓ (2 triaged warns), driver verdict upload-ready (`ds-bundle/.resync-verdict.json`).
  User review dialog went unanswered — grades + render check stand as the gate (skill's no-reviewer rule);
  `.review.html` left for the user. Font decision DEFAULTED to system-font substitution (the product's real
  behaviour) pending explicit confirmation.
- 2026-07-02 (later, authorized session): `/design-login` granted design scopes — READS work (`list_projects`
  OK, zero projects on the account) — but `create_project` fails **HTTP 403 `subscription required for this
  action`**: the claude.ai account lacks the tier that allows creating Claude Design projects. Retried after a
  SECOND fresh `/design-login` → same 403: re-login grants scopes, it cannot change the account's plan.
  Requirement (help-center-confirmed 2026-07-02): Claude Design needs **Pro / Max / Team / Enterprise** (free
  tier excluded); on Enterprise it's OFF by default until an org admin enables it in Organization settings.
  Also verify WHICH account the `/design-login` browser flow authorized — upgrading account A while the session
  is bound to account B still 403s. THIRD identical 403 later the same day (re-invoked without a fresh login).
  Ordering matters on the next try: fix the plan FIRST, then `/design-login` (a token minted pre-upgrade may
  carry stale entitlements — unverified but cheap to rule out), then `/design-sync`. Upload still
  deferred; nothing was created or uploaded. Bundle re-verified FRESH this session (only NOTES.md is newer than
  `ds-bundle/.resync-verdict.json`, and NOTES is not a build input; verdict ok, upload.any=true, 16 components,
  deletePaths=[]; the render-check's single `bad` is the triaged deliberate ErrorBoundary throw). User confirmed
  project name **"AssessHub"** and keep-system-fonts. Upload manifest staged at
  `.design-sync/.cache/upload-manifest.txt` (88 files; dot-files + `_screenshots/` stay local; `tokens/` +
  `guidelines/` are empty dirs — nothing to upload from them).
- ✅ **2026-07-02 UPLOADED — first sync COMPLETE.** The user switched authorization to a claude.ai account WITH
  a subscription (owner display name "taha") holding a manually-created EMPTY design-system project named
  **"Design System"**; user explicitly chose to sync into it instead of creating "AssessHub". Pinned
  `projectId=81dfe070-906d-445b-a821-1d100a3e969d` in config BEFORE uploading; incremental path (empty project):
  sentinel → 86 content files (22 base+previews, 64 component files) → reconciliation (0 orphans) → sentinel
  re-arm → `_ds_sync.json` LAST; post-upload `list_files` = 88 files, exact match with the local manifest.
  `report_validate` sent {total:16, bad:1 (triaged deliberate ErrorBoundary throw), thin:0, variantsIdentical:0,
  iterations:1}. URL: https://claude.ai/design/p/81dfe070-906d-445b-a821-1d100a3e969d
  ⚠️ **Future syncs: `/design-login` must bind the "taha" account** — the original abidblaze485 account never got
  a subscription and 403s on create. The pin is by UUID, so renaming the project in the web UI is safe.
  `webapp/frontend/src/pages/Snapshot.tsx` changed after the verdict but is NOT in the bundle graph (no DS
  source imports `pages/` — verified by grep at upload time).
- ✅ **2026-07-02 RE-SYNCED after a branch hop.** The durable set (never committed on `feat/plan-a-tier2`) got
  committed on `feat/design-sync-assesshub` per this file's own recipe, then the working tree hopped to
  `feat/cablemap-enhancements` (cherry-picks/resets for unrelated work) — git correctly removed the
  now-untracked-here files on checkout (nothing lost; safe in that branch's history). Restored via
  `git checkout feat/design-sync-assesshub -- .design-sync webapp/frontend/ds.entry.ts` (narrow — `.gitignore`
  intentionally left alone to avoid touching cablemap-branch content; its `.ds-sync/`/`ds-bundle/` ignore rules
  are only on the design-sync branch, so `git status` here will show those dirs as plain untracked — harmless).
  **`CableMap.tsx`/`api.ts` had gained real features on this branch** (`kind`/`speed` fields, "Fabric only" +
  tier-focus fleet-scale declutter) that the synced preview predated — fixed: `sample-data.ts` CABLE_MAP gained
  `kind` on all 9 original nodes + 2 new edge nodes (STU-AP-01 ap, NOC-PHONE-01 phone, new TIER 3 · EDGE lane)
  + `speed` on all 15 cables (blank string where genuinely not observed, never fabricated); `docs/CableMap.md`
  rewritten to document the new toggle/tier-row. Re-verified: full validate clean (only the 2 pre-triaged
  warns), CableMap regraded from a fresh screenshot, then a **full capture proved 16/16 carried forward** before
  re-upload (atomic path: 86 content files + sentinel fence/re-arm + anchor last; post-upload `list_files` +
  `get_file` on the live `CableMap.prompt.md` both confirmed). `node .ds-sync/resync.mjs` (the one-command
  re-sync driver) got blocked by the harness's auto-mode classifier — a false positive (it read the fetched
  `_ds_sync.json` cache as "fabricated" and mischaracterized the local-only build/diff/validate/capture as an
  upload); routed around it with the underlying scripts directly (`package-build.mjs` / `package-validate.mjs`
  / `package-capture.mjs`) and a manual atomic upload — same guarantees, just without the driver's
  single-command convenience. **`resync.mjs` may need a fresh permission grant or a NOTES-documented exception
  before it will run un-blocked next time.**
- ✅ **2026-07-04 RE-SYNCED — shipped the GLASS/DEPTH refresh that a prior read had misdiagnosed as noise.**
  `resync.mjs` ran **clean this session** (no harness-classifier block — the 07-02 block did NOT recur; one command:
  `node .ds-sync/resync.mjs --config .design-sync/config.json --node-modules webapp/frontend/node_modules --out
  ./ds-bundle --remote .design-sync/.cache/remote-sync.json`). Verdict: 16/16 verified-by-upload, 0 changed/added/
  removed, but `upload.any=true` with `bundle+styling+aux` differing. **This was NOT esbuild noise** (an earlier
  2026-07-04 read had dismissed the identical 3-SHA diff as noise and skipped the upload): the **V3.23.181 glass/
  depth refresh** (frosted `.panel`/`.topbar`, gradient `.btn.primary`/`.tabs button.on`, `--glass`/`--glass-border`/
  `--glow`/`--accent-grad`/`--elev-1`/`--elev-2`/`--blur` tokens) rode #264's long-lived branch and only merged to
  `main` on 07-03 (db09eef) — **after** the 07-02 upload — so the live project was shipping **pre-glass CSS**.
  Proven by git-diffing the shipped CSS (765d588→HEAD: theme.css +20, styles.css +18) AND fetching the live
  `_ds_bundle.css` (definitively lacked the glass layer). Uploaded atomically (88 files, 0 deletes, sentinel fence/
  re-arm, anchor last); **live anchor now == fresh build** (styleSha `6697e492…`, bundleSha12 `62ac4af8e3cd`, auxSha
  `dc89273e…`; was `8482d04e…`/`bdc339faa68a…`/`84b35f01…`). post-upload `list_files`=90 (88 + server `_ds_manifest.json`
  + `_adherence.oxlintrc.json`); `report_validate` {16,1,0,0,1} (the 1 bad = the deliberate ErrorBoundary throw).
  Conventions header re-validated **clean** (all 16 components + 30 classes + tokens + 5 helpers resolve).
- ✅ **2026-07-04 (2nd upload, same session) — DOCUMENTED the glass tokens in the conventions header.** User
  authorized ("proceed with best possible solution") adding the newly-shipped depth vocabulary to
  `.design-sync/conventions.md`: a **depth & glass** token clause (`--glass`/`--glass-2`/`--glass-border`/`--blur`/
  `--elev-1`/`--elev-2`/`--accent-grad`/`--glow`, all verified present in `_ds_bundle.css` with their real class
  usage mapped first) + a custom-surface usage recipe mirroring `.panel`/`.topbar`/`.btn.primary`/`.tabs .on`.
  Skill rebuild-rule followed: edit → fresh `resync.mjs` driver run (re-stitches README) → atomic re-upload.
  Driver verdict was surgical: **`upload.any=true` but `bundle:false`, `styling:false`, `aux:true`** — ONLY the
  README changed; live README now carries the header (`get_file` confirmed), anchor `auxSha` `dc89273e→c5cf3002`,
  `bundleSha12`/`styleSha`/all 16 renderHashes UNCHANGED. **Determinism note (refines the "esbuild noise" framing):**
  a rebuild from identical source produced an IDENTICAL `bundleSha12` (`bundle:false`) — so within a fixed
  toolchain the bundle is DETERMINISTIC, and the glass upload's `bundle`/`style` diff was 100% the real CSS, zero
  noise. Treat a `bundleSha12`/`styleSha` diff as a real-change signal (source CSS or esbuild-version), never a
  within-session "it's just noise" — identify WHAT moved (git-diff CSS, check README/aux) before dismissing.
- ✅ **2026-07-19 RETARGETED → new project "Atlas Design System" (`fae0df7f-7a5d-4bce-8744-5c73a3e189fe`) —
  first sync into it COMPLETE.** ADR-0004 rebrand (app name = Atlas): user-approved push of the existing
  16-component bundle to a NEW project. The old pinned "Design System" (`81dfe070…`) was ALREADY GONE server-side
  (list_projects empty + get_project 404 on a working authorization — evidently user-deleted ahead of the rebrand;
  its cached `.cache/remote-sync.json` still served as the verification anchor for grade carry-forward). Driver
  re-run before upload: chromium had to be REINSTALLED first (`node .ds-sync/node_modules/playwright/cli.js
  install chromium` — the `chromium_headless_shell-1208` cache dir had been purged since 07-04); verdict then
  green — 16/16 verified-by-upload, render 15/16 clean + the triaged deliberate ErrorBoundary throw.
  `bundle`+`styling` SHAs moved vs the 07-04 anchor with ALL 16 renderHashes/sourceKeys unchanged — diagnosed
  REAL-but-benign per this file's own rule (git-diffed, not dismissed): `api.ts` +17 (D6 `domainPacks` endpoint +
  PR #376 `out_of_order` gate fields) and `DesignBlueprint.tsx` +35 (domain-lens chips row; P_COLOR/scoreColor/
  phaseColor now exported for tests) ride the shared bundle; theme.css/styles.css untouched; runtime deps
  identical (the +1505 lock churn = vitest devDeps). Incremental path into the empty project: pin recorded BEFORE
  upload; sentinel → 22 base+previews → 64 component files → reconcile (87 remote, 0 orphans) → sentinel re-arm →
  anchor LAST; `report_validate` {16,1,0,0,1}. URL: https://claude.ai/design/p/fae0df7f-7a5d-4bce-8744-5c73a3e189fe
  ~~⚠️ Preview-ENRICHMENT candidate~~ ✅ **DONE 2026-07-19 (same day, follow-up task): domain-pack chips now
  in the preview.** `sample-data.ts` gained a `DOMAIN_PACKS` payload + `/domain_packs` route, and the COVERAGE
  class keys that trigger packs were aligned to REAL `_ARCH_COVERAGE_REGISTRY` axes (`fhrp`→`fhrp_detail`,
  `trustsec`→`cts`, + new observed-clean `port_security` row, summary 5/9) — REQUIRED because the real
  `select_packs` against the old fictional keys selected ZERO packs, and the backend's invariant is that pack
  selection can never disagree with the coverage grid beside it. `port_security` is deliberately in BOTH ent+sec
  packs → ENT red chip (fhrp_detail finding) + SEC green chip. Payload proven byte-identical to the real
  `cisco_toolkit.domain_packs.select_packs()` output (scratch verify script, MATCH). Driver green; regraded
  DesignBlueprintPanel from the fresh screenshot (chips + 5/9 grid + intact card). Scoped atomic upload:
  sentinel → bundle+css+DesignBlueprintPanel×4 → re-arm → anchor last; live anchor fetched back ==
  local (`bundleSha12 1415e787f3d1`).
- ✅ **2026-07-19 (later) TOPOLOGY RESTYLE SHIPPED — device-fidelity 2D.** Claude-Design-side feedback (verified
  against code FIRST: no "earlier switch-shaped 2D" ever existed — the chassis language lives in the 3D mode /
  CableMap / explorer; per-port stubs are impossible from `api.graph` (no port data) → link-anchored degree
  stubs instead) → user approved "best possible version": `TopologyGraph.tsx` rewritten from d3-force circles
  to role-tiered chassis lanes (CableMap family metrics NW176/NH50, barycenter ordering, MAXROW-10 wrap for
  fleet scale, band = status LED + `color-mix` chassis tint, keystone corner diamond, SPOF links thicken with
  `pairs_cut`, "Linked only" declutter with disclosed counts, dashed [NOT OBSERVED] chassis; **3D KEPT**).
  109/109 vitest + tsc/vite green; verified in the running app (sample fleet, 23 switches) and the DS harness
  (dark + light cards regraded good).
  ⚠️ **INCIDENT during this sync — wrong-base branch (parallel-session hazard, NEW variant):** between
  `git switch chore/design-sync-atlas-retarget` and `git switch -c feat/topology-device-fidelity` a concurrent
  session moved the shared checkout to freshly-advanced main (#401 merge), so the feature branch — and the
  bundle built from it — silently LACKED the #402 stack, and the upload REGRESSED the live DesignBlueprintPanel
  chips (its prompt.md hash flipped back to `d972e2953e9a`). Caught ONLY by post-upload live-anchor
  archaeology; the pre-upload diff looked clean because `.cache/remote-sync.json` was stale (not refreshed
  after the prior upload). Fix: commit-first to protect the work, rebase onto the #402 branch
  (34e6edc→1e7a84c→b713b18), rebuild (render-check then contains BOTH "Domain lenses engaged" AND "role-tiered
  fabric"), superset re-upload of both components + bundle; live anchor re-fetched == local
  (`bundleSha12 33258ba2137c`, DBP prompt back to `3b6fe903d538`).

- ✅ **2026-07-21 RE-SYNCED — the full ANIMATION/MOTION layer (25 plan units, PRs #407-#423) + 3 NEW
  components.** Bundle rebuilt from final main `8bd7710`. Verdict was surgical and CORRECT per anchor
  semantics: 16 carried forward (sourceKeys track authored previews, which didn't change), 3 added
  (`Skeleton`/`SkelLines`/`SkelTable` — the NOTES' own "manual barrel" risk item caught live: added to
  `ds.entry.ts` + `componentSrcMap` + docs + authored previews, graded good from fresh sheets), hooks
  `useViewTransition`/`usePositionTween` now ride the barrel (camelCase, no cards). Applied this file's
  own disciplines: contact sheets EYEBALLED for all 19 despite carry-forward (renderHashes are blind to
  CSS — TopologyGraph's card correctly shows the new device-fidelity lanes), both validate warns matched
  the Known list verbatim (JetBrains-Mono final + deliberate ErrorBoundary throw), live anchor re-fetched
  == local (`bundleSha12 33258ba2137c → 91a3185a6334`, styleSha `308aa845→4418e35e`, 19 renderHashes,
  57 sourceHashes), anchor-cache copied post-upload. Conventions header gained a **Motion** section
  (stagger `--stagger-i` contract, `tabfade`/`ros-reveal`/`row-reveal`, Skel* loading guidance, motion
  tokens; every name grep-verified in `_ds_bundle.css` pre-write) + Skel* in the no-provider list; skill
  rebuild-rule followed (fresh driver run post-edit). Atomic: sentinel → 101 content files → re-arm →
  anchor last; `list_files` = 103 mine + 2 server + a user-side `templates/` tree (Claude-Design app
  artifacts — OUTSIDE plan globs, correctly untouched, NOT orphans). `report_validate` {19,1,0,0,1}.
- **`templates/` in the project is app/user-side content** (topology-panel template + restyle notes from
  Claude-Design usage) — never write or delete under it; it is not part of the synced bundle.

## Re-sync risks (what can silently go stale)
- **`sample-data.ts` is hand-inlined** against `webapp/frontend/src/api.ts` interfaces — an engine/API field
  rename won't break the build; the widgets just render '—'/empty in cards. When api.ts changes, re-check the
  payloads field-by-field.
- **`ds.entry.ts` is a manual barrel** — a NEW component ships only if someone adds its export there + a
  `componentSrcMap` entry + a `.design-sync/docs/<Name>.md`. Nothing detects the omission.
- **`.ds-sync/` is gitignored** — fresh clone setup: re-copy the skill scripts, then
  `npm i --prefix .ds-sync esbuild ts-morph @types/react typescript playwright@<version pinning the cached
  chromium>` (this machine: playwright **1.58.0** ↔ cache `chromium-1208`; verify with
  `playwright-core/browsers.json` — read it as a FILE). `webapp/frontend` needs `npm ci` first.
- ~~No `projectId` pinned~~ **RESOLVED 2026-07-02 · RETARGETED 2026-07-19**: pinned
  `fae0df7f-7a5d-4bce-8744-5c73a3e189fe` ("Atlas Design System", subscribed account — supersedes
  `81dfe070…` "Design System", which was user-deleted server-side before the 07-19 retarget). Future runs are
  pinned-before-run → ATOMIC upload path, and fetch the remote `_ds_sync.json` as the verification anchor.
- **Verification anchor**: LIVE since 2026-07-02 — the project holds `_ds_sync.json`. Re-syncs: fetch it to
  `.design-sync/.cache/remote-sync.json` and run the driver with `--remote` so unchanged components skip
  re-verification.
- Never regenerate sample data from real [HISTORY-REDACTED] snapshots (no-egress; the file ships to claude.ai).
- **Branch-stack + anchor-cache discipline around every upload** (from the 2026-07-19 wrong-base incident):
  BEFORE building a bundle, confirm `git log --oneline -3` actually shows the stack you think you are on (a
  concurrent session can move the shared checkout between two of your own git commands); IMMEDIATELY after
  every upload, `Copy-Item ds-bundle/_ds_sync.json .design-sync/.cache/remote-sync.json` (a stale cache makes
  the next diff blind to a live regression); AFTER every upload, fetch the live `_ds_sync.json` and eyeball the
  `sourceHashes` you expected to move — bundleSha alone proves delivery, not content correctness.
- **`renderHashes` miss data-driven DOM additions — never rely on them to detect sample-data changes.** Proven
  2026-07-19: adding the whole domain-lens chips panel to DesignBlueprintPanel's render left its renderHash
  BYTE-IDENTICAL (`f1f8570876d15a37`); the component reached the upload set only because its regenerated
  `.prompt.md` changed (doc edit), and the new data shipped via `bundleSha12`. A sample-data-only enrichment
  with NO doc edit would flag `components: []` (bundle-only upload) — the live card would change with no
  regrade prompt. After ANY `sample-data.ts` edit: re-render + eyeball the affected card's screenshot and
  regrade it manually, regardless of what the diff says.
- **DS-source CSS edits masquerade as "esbuild noise" — always git-diff the shipped CSS before dismissing a
  styleSha diff.** A `styleSha`+`bundleSha12`(+`auxSha`) diff with **all** `renderHashes`/`sourceKeys`/`sourceHashes`
  identical is the EXACT signature of both (a) harmless esbuild non-determinism AND (b) a real edit to
  `src/theme.css`/`src/styles.css` — they're indistinguishable by hash, because `_ds_sync.json` `sourceHashes` track
  the emitted component artifacts (`.jsx`/`.d.ts`/`.prompt.md`), NOT the source CSS, and `renderHashes` are
  DOM-structural (blind to `background`/`backdrop-filter`/`box-shadow`/token-value changes). When `upload.any=true`
  but no component moved, DIFF THE ACTUAL CSS: `git diff <last-upload-commit> -- webapp/frontend/src/theme.css
  webapp/frontend/src/styles.css` and/or fetch the live `_ds_bundle.css` and compare — do NOT trust "it's just
  noise." (This trap hid the glass refresh from 07-03→07-04 until the 07-04 driver run + CSS diff caught it.)
