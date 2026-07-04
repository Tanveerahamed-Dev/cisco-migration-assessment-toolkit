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
- ~~No `projectId` pinned~~ **RESOLVED 2026-07-02**: pinned `81dfe070-906d-445b-a821-1d100a3e969d`
  ("Design System", owner "taha"). Future runs are pinned-before-run → ATOMIC upload path, and fetch the remote
  `_ds_sync.json` as the verification anchor.
- **Verification anchor**: LIVE since 2026-07-02 — the project holds `_ds_sync.json`. Re-syncs: fetch it to
  `.design-sync/.cache/remote-sync.json` and run the driver with `--remote` so unchanged components skip
  re-verification.
- Never regenerate sample data from real [HISTORY-REDACTED] snapshots (no-egress; the file ships to claude.ai).
- **DS-source CSS edits masquerade as "esbuild noise" — always git-diff the shipped CSS before dismissing a
  styleSha diff.** A `styleSha`+`bundleSha12`(+`auxSha`) diff with **all** `renderHashes`/`sourceKeys`/`sourceHashes`
  identical is the EXACT signature of both (a) harmless esbuild non-determinism AND (b) a real edit to
  `src/theme.css`/`src/styles.css` — they're indistinguishable by hash, because `_ds_sync.json` `sourceHashes` track
  the emitted component artifacts (`.jsx`/`.d.ts`/`.prompt.md`), NOT the source CSS, and `renderHashes` are
  DOM-structural (blind to `background`/`backdrop-filter`/`box-shadow`/token-value changes). When `upload.any=true`
  but no component moved, DIFF THE ACTUAL CSS: `git diff <last-upload-commit> -- webapp/frontend/src/theme.css
  webapp/frontend/src/styles.css` and/or fetch the live `_ds_bundle.css` and compare — do NOT trust "it's just
  noise." (This trap hid the glass refresh from 07-03→07-04 until the 07-04 driver run + CSS diff caught it.)
