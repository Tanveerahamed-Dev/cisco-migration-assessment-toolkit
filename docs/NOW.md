# NOW: the one live work board

This file is the single tracked answer to four questions: **what are we building right now, on
which branch, who holds it, and what is next.** Every session reads it first and updates it last,
whether it runs in Claude Code or Codex.
- Dated plans, handoffs, chats and agent memories are history, not work queues (see the precedence
  list in root `AGENTS.md`).
- Where this board and live Git disagree, live Git wins. Correct the board in the same change.
- Read the board from `main` (`git show origin/main:docs/NOW.md`). A work branch's copy may be
  behind.

Last reconciled: **2026-10-05** (Codex). Reasoning behind the current direction:
`docs/ui-direction-verdict-2026-09-29.md` (dated record).

---

## The one product

There is **one application**: the `main` branch of this repository on GitHub.

- **Intelligence (target):** the Python engine (`cisco_toolkit/` + `COLLECT_PARSE_V3_23_0.py`)
  must become the only owner of every analysis fact. Screens render engine output; they never
  invent, restate or default a fact (`docs/ssot.md`). Some screens still compute facts
  themselves; see the dated verdict.
- **The one door:** AssessHub (`webapp/`). Atlas Scope (`atlas-scope/`) is its integrated
  preview 3-D investigation module.
- **Other surfaces:**
  - The engine HTML explorer stays an offline deliverable.
  - Atlas (`portable/`) packages AssessHub for the USB stick.
  - `master-reference/` and the MCP server are existing derivatives, not further products.
- **Not allowed:** a new app, repository, product line or long-lived parallel branch.

## Working rules (Claude Code and Codex alike)

1. **`main` is the application.** Work that is not merged into `main` does not exist yet.
2. **Work only on a branch listed in the Active table below.** New work gets its row in the same
   pull request as the work. Never use an unlisted branch, worktree or project.
3. **One writer per workstream: the "Held by" column.** Do not edit a branch another row holds.
   To take over, record the handoff in the log below.
4. **Start of a session.**
   - Run `git fetch`, then read this board from `main`, root `AGENTS.md` and `CLAUDE.md`.
   - **Work in the checkout that already has the row's branch.** Git refuses to check out one
     branch in two places.
   - In the Codex app, open that folder as the project and use **Local** mode there. Do not start
     a new Worktree thread: each one begins on a detached copy per chat, and that is how the old
     copies piled up ([Codex worktrees](https://developers.openai.com/codex/app/worktrees)).
   - If the checkout is on a branch not in the table, or `git status` shows edits you did not
     make, stop and record it here. Do not build on them.
5. **End of a session, including when a quota is about to run out.**
   - Commit to the row's branch (never directly to `main`).
   - **Push only with the owner's explicit authority for this session** (root `AGENTS.md`), and
     never for a row marked local-only. Rule 7 applies first. If you did not push, say so in your
     handoff line: the work then exists only on this machine.
   - Update the row's Status and Next columns, and add one handoff line.
   - Board edits ride in the work's own pull request. On a conflict in this file, keep every
     handoff line and the newest Status per row.
6. **Merge small and often.** Open a pull request, preserving merge commits (`CLAUDE.md`, *Shared
   Git and host operating doctrine*), and ask the owner to merge within a few days. Never leave a
   week of work on one laptop only.
7. **The repository is public.** Before the first push of any branch:
   - Run `py -3.12 -I -B .github/scripts/verify_repository_privacy.py --root .` (Git index and
     stable working tree, including non-ignored untracked files; not commit history).
   - Scan every new commit's message and patch (`git log -p origin/main..HEAD`) with
     `cisco_toolkit.distribution_verify._client_marker_patterns()`. Intermediate and imported
     commits are published too.
8. **When a row's pull request merges,** the next session deletes the row and adds a handoff line.

## Active workstreams

| # | Workstream | Branch | Held by | Status (as of) | Next step |
|---|---|---|---|---|---|
| W10 | Atlas Scope overturn fixes: repair every PASS the re-grade overturned (A3, A5, A6, B2, B3 in wave 1; B5, B7, C4, C6, D2, D4, E4, E5, F2, F4, F6 in wave 2) and record them in `atlas-scope/docs/open-issues.md` | `fix/scope-regrade-overturns` (pushed 2026-10-04 at `5abad966`, no PR yet) in `.claude/worktrees/scope-fix-int` | Claude Code session (the Atlas Scope session) | Wave 1 verified: gates, engine and browser replays hold, with one major (A5 x B2: the multi-line verdict label covers its own hop's chassis at 1280 px and below). Wave-2 fixes for B5, B7, C4/D4, C6, D2, F4 and F6/F2 are merged into the branch; only F4's has been upheld by its refuter. E4 and E5 are uncommitted in their worktrees. Paused by the owner on 2026-10-03 (laptop overloaded); RESUMED on the owner's go on 2026-10-04 with at most 3 agents and a free-memory guard; the continuation run is refuting and finishing the fixes. #591 is on `main`, so `main` may now be merged into the integration branch (2026-10-04). | On the owner's go, at most a few agents at once: refute the wave-2 fixes, fix A5 x B2, finish E4 and E5 (their acceptance timing needs the reference laptop idle), write the open-issues record, then open the PR. Merge under the owner's standing authority (2026-10-03) once every required check is green on the exact head. |

## Owner decisions

**Decided — W11 owns braces remediation (owner instruction 2026-10-03):**
- Do not implement the proposed braces fork in #591. The Claude Atlas Scope session already owns board row W11 on `claude/master-ref-bounded-braces`; its source, dependency and advisory work stays with that owner.
- Keep #591 focused on Scope integration, exact architecture links and its concrete proof/shape corrections. After W11 merges, merge current main into #591 and rerun its exact-head gates before the authorized green-only merge. W7 follows W2e.
- The local fork proposal is superseded by this ownership decision. #591 authors no braces repair; the W11 owner's remedy now arrives only through merged main after #594. No audit suppression, downgrade or gate weakening is introduced. The approved jsonschema-rs decision below remains unchanged.

**Decided — #586 native dependency APPROVED (owner decision 2026-10-02, relayed in chat 2026-10-03):**
- The owner explicitly approved adding pinned `jsonschema-rs==0.58.4` to the product and Atlas bundle exactly as designed: Python fallback, fail-closed `_RefResolver` version guard, pinned lock, notice and SBOM custody.
- The dependency approval hold is lifted. Commit, privacy gates, push and CI remain authorized. **Merge #586 only when every required check on the exact final head and the unchanged hosted 300 ms performance gate pass.** Preserve the existing merge-commit and tree-reconciliation rules.
- The private `jsonschema.validators._RefResolver` import must remain bound to its explicitly reviewed jsonschema version, with a test that fails closed on version drift. This approval does not relax runner security, privacy, packaging or release gates and does not authorize release publication, signing or deployment.
- W2e and W7 still follow W2d's authorized merge. W5/#582 and W8/#587 remain with their owner.

**Decided later 2026-10-02 (current owner instruction):**
- Master Reference is the owner's internal code-repository reference; an unverified hosting-size quota must not hold back the application.
- Remove the aggregate hosting quota from internal artifact validation. Preserve complete source/member accounting, hashes, privacy, mutation checks and bounded member/receipt/decompression safeguards. Keep the existing required correctness check; do not bypass failures or change branch protection.
- Report actual verified artifact size separately from hosting eligibility, which remains unassessed. No larger platform limit is asserted. R2 migration and Site deployment are outside this internal-reference fix.
- This supersedes the earlier verified-limit/R2 prerequisite for W6. Continue W6, then merge main into #586 and resume W2d, W2e and W7 under the existing green-only merge authority. W5/#582 and W8/#587 remain untouched.

**Earlier decision, 2026-10-02 (hosting prerequisite superseded above):**
- Work in order **W6, W2d, W2e, W7**. W6 is the immediate shared finalization prerequisite.
- A cap increase requires a verified actual Codex Sites deployment limit, at least 4 MiB of margin, and the source cited in code. The repository's 248 MiB constant is not itself platform-limit evidence.
- If 248 MiB is verified as the platform limit, show the R2 migration plan before implementation and retain receipt/privacy boundaries.
- #586's optional measurement job uses GitHub-hosted `windows-latest`; never weaken the self-hosted-runner test.
- After W6 merges, merge main into #586 and rerun CI before the authorized green-only merge. W5/#582 and W8/pypdf/#587 remain with the Atlas Scope session.

**Decided 2026-09-30** (full record and reasoning: `docs/decisions/0007-one-application-direction.md`):

- **D0: Release 1 is frozen as a draft candidate.** The UI program proceeds on `main`. The next
  release candidate is cut from `main` after the core-screens milestone (P3).
- **D9: Facts in Python, geometry in the browser.**
  - Every on-screen fact comes from the engine through a typed projection
    (`cisco_toolkit/ui_projection.py`).
  - Scope's compiler owns only 3-D geometry, layout and visual encoding.
  - Browser-side and webapp verdict logic become renderers or are parity-pinned.
- **D10: Raw evidence is retained, secret-scrubbed.**
  - Retention happens only after the engine's raw-capture scrubber runs and the independent
    verifier proves the capture clean.
  - A retention indicator and a per-campaign purge are shown.
  - Implementation waits for W1 to merge (`webapp/backend/ingest.py` is on its freeze list).
- **D11: Publishing the Atlas Scope branch is approved.** The W1 holder pushes and opens the PR
  after phase 3.5 is committed, the rule-7 checks pass, and the remaining FAIL items are listed as
  preview scope.

**Still open, owned by `CLAUDE.md` and not restated here:** the carried-forward review-tail items,
publishing the master-reference site, and the Claude Design pixel-baseline promotion.

### Earlier W6 verification and R2 proposal (historical; superseded for internal builds)

Current native Site metadata and saved-version records expose no numeric deployment
ceiling. Saved archive sizes are measurements, not limits. The installed 25-operation
Sites tool catalog/packager and [official Sites documentation](https://learn.chatgpt.com/docs/sites)
also supply no deployment-byte maximum or counting formula. The repository's
260,046,848-byte aggregate guard is verified; its status as a platform maximum is not.
No increase is justified by this evidence. Any verified higher limit must retain at
least 4,194,304 bytes of margin using the same counting basis.

Proposed fallback, retaining the current repository budget pending the owner's decision:
1. Keep all projection source/modules and compressed/decoded byte hashes in the offline family. Split hosted objects into a separately closed, versioned receipt; do not merely exclude them from the existing physical-member census.
2. Bind an immutable R2 namespace to the exact source/projection digests. Add the logical storage binding and a read-only module adapter while retaining existing virtual URLs, GET/HEAD behavior, gzip bytes/MIME/manual encoding, security headers and explicit missing-object failures.
3. Build a bounded authenticated transfer path because the available Sites tools have no object-upload operation. A first-use private bootstrap/maintenance version and its impact must be reviewed before any live migration; implementation approval alone does not assert deployed storage readiness.
4. Verify every uploaded object's compressed and decoded hashes/lengths, complete inventory, namespace and source identity before activation. Refuse missing, extra, truncated, conflicting or cross-version objects. Preserve privacy gates and complete offline reconstruction.
5. Activate only an exact saved reader version after that evidence closes. Retain the previous saved version and immutable object namespace for rollback; do not assume code rollback reverses storage or environment changes.

The verified platform maximum remains unknown. The owner's later internal-reference
decision removes that dependency from this workstream; the proposal is retained as
history, not an implementation queue. No storage, Site access, deployment or
protected-PR change is part of the resumed W6 scope.

## Handoff log (newest first)

- 2026-10-05, Codex (W7 frozen candidate complete; local documentation closeout): Selected current main `fa384d2d1ebb24f5eb7096e777f8d1fe87cc356b`, tree `af1122a969176f1d1070a0fb30f76c52095e25e6`. Fresh hosted run `37246571595` passed source/frontend and binary jobs with `attach_draft=false`; receiver/draft jobs skipped. All 15 protected current-main contexts from app 15368 passed. Independently selected pre-download expectations, canonical exact-source/source-root/ZIP/material receiver and 865-member/8-metadata/12-file closure passed. Fresh RAM before the canonical receiver: 2,752,471,040 bytes; receiver exit 0 in 8.484 seconds. Verified ZIP: 51,578,747 bytes, SHA-256 `2f6b8130cc255a616c6f96334d2c33596bf3e1eed80b837c2bdfe17b7ceba838`; receipt SHA-256 `8522eabd3c98f75f29151b252524500e54b3eae0cbae8946a7a93e4280bb9453`. Regenerated stock update/rollback instructions for this selected source, with no executed stick commands. Unsigned, all 14 external qualification gates pending; local receiver stdlib-only, fresh hosted strict CycloneDX evidence retained. Earlier verified `d326` candidate, its transport timeout and the unpublished premature closeout `abf8725d` remain preserved separately; no receipt transferred to `fa384` or this later documentation commit. W7 removed under rule 8; W9 removed because #590 is already merged, preserving its complete owner history and leaving W10 untouched. This closeout is LOCAL-ONLY/not pushed and exists on the owned branch; frozen selected candidate source remains main `fa384d2d`, with publication/main reconciliation of these later records separate. No tag, signing, release publication/attachment, deployment, Atlas execution or device/vault write occurred locally.

- 2026-10-05, Claude Code (#595 merged into #590):
  - #595 (W7 release preparation) merged as `d326a0d9` while #590 waited on its last green run, so `main` is merged in
    a third time. Main's rows are kept as `main` has them (Codex removed W2e after #591), with this branch's W9 and W10
    rows, and every handoff line from both sides.

- 2026-10-04, Codex (W2e merged; W7 active): #591 merged as `583552ad888d73f51eaf28181c17f127cc285b2a` after all 15 protected contexts from app 15368, all six applicable workflows and the manual performance workflow passed at exact head `05464ac4`. Its tree `e67d7de5bf54043266859fc0fb6b5133520a3315` equals both tested merge `a805f5de` and approved head. Full Scope passed every step; sample gates passed at 198.4147/200.8995 ms under the unchanged 300 ms threshold. Independent package review rehashed 865 runtime members and eight metadata files; actual producer is the tested merge, with direct committed-byte material proof and explicit source-root/local-schema limits. It remains unsigned with 14 external gates pending. Removed W2e under rule 8 and activated reserved W7 in the same checkout.

- 2026-10-04, Codex (W7 candidate metadata checkpoint): Fresh release/tag checks found RC4 unused; prepare `3.33.0rc4` with candidate name `v3.33.0-rc.4`, preserving schema `3.23.0` and all previous draft assets. Seven lightweight version/schema/example/PE checks and independent metadata review pass. The earlier root Vitest cache is preserved byte-for-byte outside the checkout for exact-source verification; no ignore rule or custody check is weakened. The owner's delegated supervisor directs heavy release construction and frozen smoke to GitHub-hosted runners while W10 uses the laptop; local work stays light, and any heavy local step waits below 1.5 GB free RAM. Full publication privacy gates and fresh exact-head CI precede merge. The canonical final build uses `attach_draft=false`; independent source/package verification and stick-update instructions remain open. No release publication, tag, signing, deployment or device/vault write is authorized.

- 2026-10-04, Claude Code (#591 merged into #590; W10 resumed):
  - #591 (W2e) merged as `583552ad`. Merged it into #590 again, keeping Codex's W2e and W7 rows as `main` has them,
    this branch's W9 and W10 rows with their newest status, and every handoff line from both sides.
  - The owner resumed W10 on 2026-10-04 ("resume as the supervisor described"): at most 3 agents, heavy work behind a
    2-slot lock that waits while the host has under 1.5 GB free. `main` is merged into W10 only now that #591 has landed.

- 2026-10-04, Codex (W2e post-W11 validation checkpoint): Integration `c8863bc0` preserves W11 production and registry bytes exactly from `0fba4f45`, W2e governance/PDF owners and the LF policy, and both parents' test coverage. Independent source review is clear. The pinned release interpreter passed 105 focused version/PDF-loader/release-refusal/registry/SBOM/Vite BLOCK cases and all 14 commit-bound byte-policy cases, zero failures/errors/skips, with stable source hashes. Host memory pressure excludes another full local build; no hosted gate is waived. Final privacy/history/body scans, publication, every protected check, full Scope workflow and a fresh unchanged 300 ms measurement remain required. W7 stays queued; its current preflight confirms both frontend inventories are already owned by merged #582 and the next candidate version must be rechecked at the cut.

- 2026-10-04, Codex (W11 merged; W2e integration resumed): W11 #594 merged as `0fba4f45b9258733b25e5796c1589589b6d798af` at 18:19:22 UTC. Merged current main into #591 from `48307d7e`; kept the newer W2e/W7 rows and both complete handoff histories. W0/W2d/W5 remain removed, and the now-merged W11 row is removed under rule 8. W11 production code and its closed bounded-substitution registry remain upstream-owned; Vite compiled-copy and external-review release BLOCK states remain. Independent integration review, focused compatibility checks and all fresh final-head hosted gates precede merge. No receipt is transferred across the changed source.

- 2026-10-04, Claude Code (W11 merged; #590 brought up to date):
  - #594 (W11) merged as `0fba4f45` under the owner's direct go, once all 15 required checks were green on the exact
    head `09d857ca`; `main^{tree}` equals that head's tree (`09d0659a`). W11's row is deleted (rule 8). `main`'s
    braces advisory (GHSA-vfj7-8cjw-p6xm) is closed on the current lock graph; Vite's own compiled braces copy keeps
    the master-reference release gate blocked, as W11 records.
  - `main` merged into #590 so its Dependency audit and master-reference contracts can pass; the owner ordered the
    merge once every required check is green.
  - The owner paused all other work on 2026-10-03 because the laptop was overloaded; W10 resumes only on the owner's go.

- 2026-10-04, Claude Code (W5 merged; W11 opened):
  - #582 (W5) merged as `e50c3cde` on 2026-10-03 once all 15 required checks were green on the exact head
    `2709ec1e`; `main^{tree}` equals that head's tree. W5's row is deleted (rule 8).
  - `main`'s required Dependency audit then went red for every PR: GHSA-vfj7-8cjw-p6xm was re-ranged on 2026-10-02 to
    every published braces release, reached only through master-reference's Vinext build tooling. W11 repairs it with
    the bounded-vendor method `CLAUDE.md` prescribes (no waiver, suppression or downgrade); the owner gave a direct
    merge go once the required checks are green.
  - The re-grade report (#590, W9) and the overturn repairs (W10) carry their own rows in their own pull requests.

- 2026-10-03, Codex (W2e Windows shared-source byte fix): Windows job `111141613684` at `18ef5354` retained one failure, 10,683 passes, 43 skips and one expected failure. Git and a real checkout reproduce the unpinned shared source's LF-to-CRLF conversion; the runner bytes were not retained, so that is reproduction rather than direct capture. Added one exact LF rule inside the owned policy and reconciled its mechanical receipt: 180 to 181 LF paths, 142 to 143 broader paths, unchanged 38 derived owners, domains and publisher exceptions. The raw HEAD-blob guard and all scope/mutation checks remain unchanged. The pre-fix failure is retained; all nine targeted post-fix cases, Ruff and independent review passed. All 14 commit-bound policy/mutation checks passed at `62b20d68`; publication gates follow before push; W11 remains with its owner and all final combined-source checks are still required.

- 2026-10-03, Codex (W2e architecture-schema consumer repair): Required reference run `37096035583` exposed the PDF loader's two stale architecture `2.0.0` checks after the owner contract advanced to `2.1.0`. Schema support and unsupported-version refusal now belong to `governance.architecture.validate_contract`; both PDF input routes delegate there. The release pipeline already delegates to that loader and is byte-identical, leaving W11's bounded-substitution gate untouched. All 406 Master Reference release tests passed with zero skips on frozen source and the pinned release toolchain; 55 governance/continuity checks and three final refusal checks also passed within their recorded scopes. Independent review found and closed an unknown-schema/foreign-field refusal regression; the interrupted first release attempt is retained without a pass claim. Commit/push follows fresh privacy checks; final hosted gates and the post-W11 main integration remain required.

- 2026-10-03, Codex (owner-directed board reconciliation): W0 is done; removed the W0, W2d and W5 Active rows under rule 8 (W2d was already absent in this branch). W2d/#586 and W5/#582 remain recorded in history. Braces remediation is W11, held by the Claude Atlas Scope session on `claude/master-ref-bounded-braces`; #591 will integrate its merged main and rerun exact-head checks, without duplicating that work.

- 2026-10-03, Codex (W2e published and hosted findings):
  - Published #591 at `998fa5ff` on `e50c3cde` after the full index/working-tree privacy gate. All four commits and five complete parent patches were scanned. Raw vendor-identifier matches are retained; independent review confirms only the existing minified-bundle identity exclusion applies, with every other pattern active. PR-body scanning passed. No privacy rule or history was changed.
  - Performance run `37093209993` passed the unchanged sample gate at both page limits; independent verification rehashed artifact `11262998230` and all 12 source inputs, all 42 shapes and five repeats. This does not erase the earlier local 434.1103 ms result or certify later source edits. Synthetic/path measurements retain their diagnostic scope.
  - Full Scope CI retained six failures (7,250 passed, 27 skipped): focus custody, initial-payload census, test-mock declaration, test-support boundary and wrapping policy. Required reference compilation reports 15 undeclared static cross-component imports. Python 3.13 retained three failures (10,569 passed, 153 skipped, one expected failure): canonical portable shape ownership and two projection receipt-proof guards. These are concrete repair work, not waived tests.
  - The separate required dependency-audit failure is the braces advisory described under Owner decisions. Its six high findings describe one affected dependency chain. All earlier Python/frontend/Scope audit steps were clean within their stated existing ignores. The local remediation plan is reviewable; adopting fork maintenance awaits the owner. No other owner's branch was edited, no release/tag was created and no deployment occurred.

- 2026-10-03, Codex (current main integrated after Scope owner merged #582):
  - Main advanced to `e50c3cde` while W2e's publication gates ran. The obsolete privacy run was deliberately stopped without a passing claim; the history scan refused the changed base. Integrating the owner's merge preserves the stricter shell reader and packaging custody. The app conflict keeps W2e's additive capability declaration alongside the new markup-refusal owner; this board keeps both handoff histories.
  - Existing `090c3bc0` build/browser receipts remain bound to that earlier source. The combined source passed 25 capability/mount checks, ten malformed/valid health-band cases, a fresh hub build and desktop/mobile real-browser proof; native schema hashes remain unchanged. Its single shared protocol module receives an exact committed-source attribution allowance while unknown outside modules remain refused. Final publication/hosted gates are still required. No change was made to the owner's branch. W7's earlier frontend-inventory omission is already corrected by #582 and must not be reimplemented from the stale preflight.

- 2026-10-03, Codex (W2e local integration ready for publication):
  - Implementation checkpoint `a40f59ee` and presentation correction `090c3bc0` retain engine-owned facts and joins. Both pinned production builds, the nine committed-source guard cases, desktop/mobile real-hub integration and screenshot review passed. Scope framing's initial 190-pass/one-failure run was corrected without weakening its bounds; 191 focused cases, eight final scene cases and typecheck passed. The earlier cancelled full Scope run remains explicitly incomplete.
  - The local 42-shape, five-repeat sample diagnostic at limit 200 reached 434.1103 ms and is not acceptance. All exact-head protected checks, the complete hosted Scope workflow and unchanged hosted 300 ms gate at limits 50/200 must pass before merge. Final publication/privacy receipts and later hosted outcomes are separate from this local checkpoint. W7 remains queued; other owners' branches were untouched.

- 2026-10-03, Codex (W2e local implementation checkpoint):
  - Engine topology/path facts, source custody, same-hub contract mode and the fifth core screen are implemented. Source review corrected evidence absence/partiality, caveat locations, the existing eight-example impact-prose disclosure, client alias/identity/page guards, and renderer teardown. Engine regression passed 574 cases after retaining the original 568-pass/six-failure result; complete API passed 143, capability checks 10, frontend 370 and its production build. Native eligibility/provider/fallback are unchanged; two schema hashes changed only after independent static and differential review.
  - The local full Scope run is intentionally incomplete: 46 passing files, three adapter property-inspection failures, one new-file/HEAD custody failure and 182 unfinished files were retained. Stopped only that owned local run after confirming the existing hosted Scope workflow runs the complete suite. Adapter code now uses the unchanged safe-access helper; full typecheck and 188 focused/guard checks pass. No verifier exemption or guard weakening was used. The committed-source check awaits this checkpoint; full Scope validation remains open until the actual exact-head hosted workflow passes.
  - This checkpoint is local, not pushed. Hub build, real parent/child browser proof, final generation/latency checks, publication privacy/history/body scans and all exact-head CI remain required. The original untracked root test cache and other owners' worktrees are preserved. W7 follows the authorized W2e merge; release publication/signing/device/vault authority is unchanged.

- 2026-10-03, Codex (W2d merged / W2e started):
  - [PR #586](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/586) merged as `828847f14c908fa7b725fe97fdff9cee5f115178` after all 15 required contexts from the expected provider and all six latest applicable workflows passed on `18fac335`. The authorized exact-head admin merge preserved the existing policy. Main tree `179710d24c3eb11772d6223bbae4ec252deab155` exactly equals the tested merge/head tree. Removed W2d's active row under rule 8.
  - Hosted performance run `37067520985` passed the unchanged sample gates: 50-row maximum 91.8337 ms; 200-row maximum 143.6550 ms. Independent review verified all source hashes, five repeats of 36 request shapes per dataset and 108 response bodies identical to the earlier failed hosted baseline. Cold loading and the synthetic 300-device profile retain their separate diagnostic scope; no earlier failure is erased.
  - Portable run `37067501879` passed both source/frontend and actual-binary jobs. Independent custody rehashed 860 members and eight receipts, bound the native binary/MIT/upstream SBOM, and verified two real frozen native/private-guard HTTP runs. Its actual producer was the tested PR merge `87584774`, with the same tree as the approved head. The candidate remains unsigned with its 14 external gates pending. The older same-head webapp cancellation and failed dependent checks are preserved, superseded by the successful current run.
  - Reused the existing checkout for reserved W2e from merged main. Engine/transport, AssessHub and same-hub Scope work have separate file owners; schema-pin updates require explicit delta review, and path validation starts on Python. The existing untracked root test cache is preserved. W7 follows W2e; W5/#582 and W8/#587 remain with their owner.

- 2026-10-03, Claude Code (W5 merged; W9 and W10 opened):
  - #582 (W5) merged as `e50c3cde` under the owner's 2026-10-02 authority, once all 15 required checks were green
    on the exact head `2709ec1e`. `main^{tree}` equals that head's tree (`d9e9588b`). W5's row is deleted (rule 8).
  - W9 lands the 39-criterion re-grade report. The graded `atlas-scope/` tree and sample data are unchanged from
    the graded `de6b9b76` through `e50c3cde`, so the report describes `main`'s Atlas Scope.
  - W10 repairs the 16 overturned PASSes on a local branch; it is not pushed yet.

- 2026-10-03, Claude Code (W5 brought up to date after W2d):
  - #586 (W2d) merged as `828847f1`. Merged it into #582 in a separate checkout (the re-grade's refuters were still
    reading the W5 checkout), keeping both sides of three real conflicts: `portable/release_contract.py` keeps W5's
    `_TOOLCHAIN_MATERIALS` and `_manifest_summary` owners with #586's `jsonschema-rs` licence material and native-runtime
    member checks; `portable/build_atlas.py` keeps W5's derived `selftest_gap` and adds #586's
    `ui-projection-legacy-resolver` line to `REQUIRED_SELFTEST_LINES`; this board keeps every handoff line.
  - #586's `_smoke_ui_projection(base, instance_nonce)` broke W5's smoke harness stub, which now records and pins both.
    #586 changes neither `atlas-scope/` nor the sample data, so the re-grade still describes this head's application.

- 2026-10-03, Codex (current-main audit changes integrated before publication):
  - The Scope owner's #587 merged upstream as `fea045f6b03819edec2a08d0357a27ec9f026039`. Merged current main into W2d; CI, pyproject, SSOT, the release pin and the new dependency-audit contract merged automatically. Only this board conflicted; every handoff line from both parents and the owner's W8 row are retained. No work on the W8 branch, alerts, follow-ups or #582 occurred.
  - The API/native tests and packaging source remain unchanged from their reviewed hashes. Fresh integrated audit/runner checks and full publication privacy/history/body gates precede push. The earlier e59 privacy scan was interrupted because it became obsolete when main advanced; it is not a passing receipt. Hosted checks and performance must bind the integrated head.

- 2026-10-03, Codex (approved native integration prepared for hosted gates):
  - Final API `1d96342cb543d74994d42b6ac75b01c64484ed1cfa144de8e3acc6233cd4bede` passes 119 tests, ten private-version checks, nine generation-policy checks, Ruff and diff checks. Actual OpenAPI and generated TypeScript are unchanged. The private resolver loader refuses unreviewed or missing jsonschema versions before private import/use; the frozen selftest also exercises the loader.
  - Packaging passes 253 focused tests with nine explicit platform/tool skips, followed by eight final guard/filter delta checks. The reviewed native pin/Windows wheel hash, Python fallback, MIT fallback, upstream SBOM custody and exact metadata selection are present. Installer-added metadata is removed only from the two reviewed validator directories; required metadata/licenses/SBOM and unrelated metadata are retained.
  - Independent native/ownership/reference/hostile-HTTP review passed on the pre-guard source, and the final private-version/metadata deltas passed on the final source hashes. All earlier failed probes and correction scopes are retained. No remaining source finding is open. The combined checkpoint still needs fresh privacy/history/body gates, publication and exact-head hosted CI/performance.
  - No local frozen-build result is claimed. Observed low memory/high CPU makes another heavy local build inappropriate; the canonical isolated hosted Windows job must close exact-source assets, executable/native HTTP proof and private-version proof. Merge remains authorized only after every required final-head check and the hosted 300 ms gate pass; W2e and W7 follow.

- 2026-10-03, Codex (native dependency approved):
  - Owner relayed the explicit 2026-10-02 approval in chat for pinned jsonschema-rs 0.58.4 with Python fallback, fail-closed private-resolver guard and lock/notice/SBOM custody. Updated the pending decision above to approved and lifted only that dependency hold.
  - Every required exact-head check and the hosted 300 ms gate must still pass before #586 merges. The final private-version and metadata-filter checks are completing locally; the combined committed source will receive privacy scans and hosted Windows frozen/native proof. Local host resource pressure makes an additional local heavy build inappropriate; no required gate is waived.

- 2026-10-02, Codex (native merge hold / private API version guard):
  - The supervisor note explicitly withholds native dependency adoption authority. Keep #586 as a reviewable proposal; local commits, publication privacy checks, push and CI may continue, but no merge is allowed until the owner approves jsonschema-rs in chat. This supersedes broad green-only merge authority for the native addition.
  - The API worker owns a narrow fixed-version/fail-closed check around the private `_RefResolver` import after the current independent replay reaches its terminal checkpoint. All earlier source hashes/results retain their scope. Combined commit and authoritative frozen build wait for that guard's validation and review.

- 2026-10-02, Codex (W2d compiled-validator integration selected):
  - The external trial on committed `3b286f6f` used pinned `jsonschema-rs==0.58.4`, verified Windows wheel bytes/RECORD/AMD64 identity and an isolated target installation. Three paired repeats preserved exact HTTP bodies and every other response guard: Findings/list 200-row medians fell from 448.3/468.1 ms to 176.4/194.0 ms. These are diagnostic, not hosted acceptance. Untimed counters prove one native call per response validation on all three tested payloads.
  - Native acceptance is restricted before evaluation to the audited unchanged schema profile and exact JSON builtins: safe-53-bit integers, no floats/cycles/depth above 128, no line terminators or surrogates in strings/keys. Formats are disabled and retrieval is offline. All 155 differential probes and nine real paired-engine-field cases preserve the required behavior within this boundary; eight observed differences are excluded before native acceptance. Unknown/mutated schemas and unsupported inputs use Python, with closed-registry fallback also refusing HTTP/file retrieval.
  - The wheel lacks license text. The pinned upstream MIT text and wheel-provided 203-component SBOM are retained for reviewed notice/material custody; that SBOM is declared upstream metadata, not independent linked-component or legal closure. The native path requires pinned dependencies, a reviewed portable lock/inventory update, metadata/native-extension custody and a frozen HTTP proof of actual native use. No version, release tag, signing or publication action is included.
  - API and packaging work have separate file owners, with an independent reviewer. Canonical schemas, all per-response guards, the 300 ms gate and the GitHub-hosted-only runner remain intact. The smaller pure-Python compiler is not selected: it ignores current dependentRequired constraints without an additional schema adapter. #582/#587 and W7's separate Scope inventory correction remain outside this implementation.

- 2026-10-02, Codex (W2d traversal correctness checkpoint):
  - Direct private descent and uniquely selected alternative validation now reuse complete retained keyword plans without retrying invalid subtrees. Public failures still replay through the original stock validator. API SHA-256 is `215c97cd62b8e52eb4c437cf5359ab82f69f52a7dcb63055dd3e6c465ac0572a`; 106 focused API tests, 16 targeted checks, Ruff and diff checks pass.
  - Independent review passes 17 ownership/context groups, 73 reference/recursion/error cases, 200 concurrent validations, off-page faults and five warmed HTTP corruption/retry probes. Both invalid-depth families are linear through depth 20 with full public error parity. At depth 8, the unique-alternative case uses 26 type evaluations instead of the published helper's 1,038 (stock 17). The body remains exactly 938,913 bytes with the hosted SHA-256. Counter-instrumentation failures are preserved; portable non-generator keyword counters retain the original bounds.
  - Schema call count fell from 1,644,040 to 1,221,774, but shared-host timing is not acceptance evidence: the final bounded HTTP observations were 600.5/514.8 ms. The authoritative hosted 200-row failure remains open. This checkpoint is local and not pushed; no successful latency claim or merge follows from correctness alone.
  - A separate external feasibility trial may assess pinned `jsonschema-rs` with offline retrieval, full per-response validation, conservative Python-stock eligibility and error fallback. It must establish semantics and packaging suitability before any repository dependency change; no production schema, dependency, lock or runtime profile has changed for that trial. W2e/W7 remain after W2d; #582/#587 remain untouched.

- 2026-10-02, Codex (W2d hosted failure isolated to traversal):
  - Published integrated `2a50978a` after stable repository privacy, the complete 11-commit/per-parent history scan (367,511 bytes, 12 patterns), the final PR-body scan and all nine runner-security/mutation checks passed. The original self-hosted-runner guard is unchanged; measurement uses the fixed GitHub-hosted `windows-latest` matrix.
  - Dispatch `37046103736`, measurement job `110967825775`, failed the unchanged sample timing gate. Independently verified artifact `11244541464` matches all 11 source hashes, fixture identities and 36 request shapes with five repeats per profile. Sample 50-row maximum was 192.9263 ms; sample 200-row Findings first-list maximum was 445.9400 ms and repeated maximum 436.7247 ms. Synthetic 300-device cold projection was 17,831.5462 ms, first lazy device 831.2178 ms and repeated maximum 361.3736 ms. All 108 response byte counts/hashes match the earlier hosted build; no payload change or passing timing is inferred.
  - An external CPython 3.12.10 environment matches all 80 hosted third-party package versions. A bounded diagnostic request preserved the exact 938,913-byte body and found one response validation and one schema validation: the schema walk occupied 418 ms of a 509 ms instrumented HTTP request. Profiling is not acceptance timing. Repeated keyword traversal, rather than duplicate framework validation, is the measured dominant cost.
  - The next correction reuses private retained child validators' existing rule lists while still evaluating every constraint; all public failures remain replayed through stock validation. Review rejected probe-then-retry because it could repeat invalid subtrees recursively. Root owns this record, the implementation worker owns the API and focused tests, and an independent reviewer owns parity/refutation and diagnostic profiling. New-source local/hosted gates remain pending; no threshold or validation guard is relaxed.

- 2026-10-02, Codex (W6 merged / W2d resumed):
  - W6 [PR #588](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/588) merged with the authorized exact-head merge commit as `0577aaf5818af866f6d6df8c2069bc34801f0f88`. All 15 required checks passed on `1080bfa5`; main tree `1053dd8a13b96bb0cd7aa85449ed6e4187774914` equals the tested merge/head tree. Removed W6's active row under rule 8.
  - Exact-source reference run `37035942130` passed compiler/schema verification, 284 reference contracts, 43 rendered checks, lint/audit, deterministic artifact-family/PDF build and receipt reconciliation. It finalized 14,827 members and 260,145,929 physical bytes, above the former 260,046,848-byte quota. Integrity, privacy and resource bounds remain; hosting eligibility is unevaluated. W6 CI coverage was 86.29%; Windows reported 10,265 passes, 40 skips and one expected failure. All earlier failed/cancelled evidence retains its scope.
  - Reused the existing checkout for W2d and merged current main. The only conflict was this board; every pre-existing handoff line is preserved. Final reviewed API SHA-256 remains `7c9226a594d3c53aeed1ab99a1efe3ca411ad6ff96ae479b34c6f2610222d537`. The opt-in measurement job remains restricted to the single GitHub-hosted `windows-latest` matrix value; the self-hosted-runner guard is unchanged.
  - The integrated W2d head requires fresh publication privacy/history scans and new hosted performance/CI results. No old timing result is transferred to it. W2e and W7 follow its green merge; #582/#587, their branches, devices and the vault remain outside this session.

- 2026-10-02, Claude Code (W8 merged; W5 brought up to date):
  - The owner authorized merging #582 and #587 once green, in this Claude Code session. #587 merged as `fea045f6` with
    `--merge --admin --match-head-commit 5fc797b2` after all 15 required checks succeeded on that exact head and no
    other check failed; `main`'s tree equals the tested head's tree. W8's row is deleted under rule 8.
  - Closed Dependabot #585 as superseded by #587. Alerts #9 to #15 still read open right after the merge, while
    GitHub's dependency graph re-scans `main`; confirm they read `fixed` rather than assuming it.
  - Merged the new `main` into #582 (only this board conflicted; every handoff line kept). #582 merges under the same
    authority once every required check is green on its new head.

- 2026-10-02, Claude Code (W8 merged main after W6):
  - #588 (W6) merged as `0577aaf5`, so the internal reference no longer fails on the hosting size cap. Merged
    `origin/main` into this branch with a merge commit; the only conflict was this board, resolved keeping every row and
    handoff line from both sides. Re-running all required checks on the new head.
  - The coordination session relayed the next steps. The admin merge itself waits for the owner's explicit authority in
    this Claude Code session: the standing admin-merge authority recorded on this board belongs to Codex's W2 session
    and excludes #582. Once merged: close Dependabot #585 as superseded and confirm alerts #9 to #15 read `fixed`.

- 2026-10-02, Claude Code (W5 merged main after W6):
  - #588 (W6) merged as `0577aaf5`, so the internal reference no longer fails on the hosting size cap, the only check
    this branch failed. Merged `origin/main` with a merge commit; the only conflict was this board, resolved keeping
    every row and handoff line from both sides and dropping W2c, which main deleted under rule 8 (#584 merged).
  - #588 changes neither `atlas-scope/` nor the sample data, so the re-grade of `de6b9b76` still describes this head's
    application tree. That run (32 of 39 criteria graded before the previous session ended) resumes from its cache.
  - The admin merge waits for the owner's explicit authority in this Claude Code session; the standing admin-merge
    authority recorded on this board belongs to Codex's W2 session and excludes #582.

- 2026-10-02, Codex (W6 resumed as internal-reference policy correction):
  - Owner explicitly directed proceeding: Master Reference is internal repository documentation and must not impose a hosting-size blocker on application work. This supersedes the earlier conditional Sites-limit/R2 decision; no further approval is needed for this bounded internal validation change.
  - Revalidated the W6 branch and main `db9d8534`. Separate internal artifact integrity from hosting eligibility without changing required-check names or branch protection. Preserve receipt schema 1.2/census/digest semantics, safe byte arithmetic, privacy, mutation and bounded-read/expansion protections. No fake higher Sites limit or R2 deployment is introduced.
  - Final implementation passes 150 deployment/compression contracts, 46 targeted review-closure checks, lint/syntax/diff checks, and the Python SSOT-registry/census selection. The initial 138-pass/one-fail test run is retained: only the new assertion was corrected to expect the existing redacted bounded-read error; no guard changed.
  - Independent review built and publicly verified a distinct real 268,439,398-byte artifact (268,436,352 member bytes; 134 members plus outer receipt). An alternate valid outer representation changed physical bytes exactly while preserving the conceptual receipt. Same-size tampering, fully rehashed omitted members, invalid/overflowed byte totals and hostile reporting options all failed. Receipt schema/hash rules, remaining resource/concurrency bounds and compiler coverage policy are unchanged.
  - Full exact-source reference build/rendered validation and required hosted checks remain pending for publication; focused results do not close them. Fresh stable-tree/history/PR-body privacy gates precede push. W2d remains preserved at `6f415c72`; #582/#587 and unrelated checkouts remain untouched.

- 2026-10-02, Codex (W6 blocked audit):
  - Revalidated W6 at `fc6cab2e` and unchanged main `db9d8534`; tracked source was clean, with the original untracked cache preserved. No new human authorization or authoritative Sites limit evidence has arrived after the plan-first request.
  - The same conditional-implementation blocker has persisted for three consecutive goal turns. There is no live owned W6 operation to wait on and no remaining authorized implementation that resolves this boundary. Mark the full goal blocked, not complete; do not infer approval from automatic continuations or repeat the same research.
  - Resume from this branch after the owner decision or verified service-limit evidence. W2d remains preserved at `6f415c72`; subsequent order is W6, W2d, W2e, W7. No cap, Site/storage/deployment, #582, #587, device or vault change occurred. This handoff is local and not pushed.

- 2026-10-02, Codex (W6 active / platform limit unverified):
  - Created the reserved W6 branch from current main `db9d8534` in the existing UI checkout after preserving W2d at `6f415c72`. This branch carries the board handoff only; W2d application/workflow changes remain on their branch.
  - Native Site metadata and recent saved-version records expose artifact measurements, not deployment ceilings. The installed Sites tooling and fresh official documentation review supply no numeric maximum. Neither a higher limit nor a true 248 MiB platform maximum is verified, so no cap change is justified yet.
  - A reviewable R2 plan is being prepared with immutable object namespaces, complete compressed/decoded receipts, unchanged virtual URLs, exact-byte transfer verification, retained offline content and rollback. Implementation must respect the owner's verified-limit condition and plan-first instruction. No Site/storage/deployment write or protected-PR change occurred.

- 2026-10-02, Codex (owner advances W6):
  - Owner explicitly reordered work to W6 first, then W2d, W2e and W7. Revalidated main `db9d8534`; the reserved W6 branch will start from it in the same checkout after this W2d handoff is committed. W2d construction work is preserved at local `bce1d47a`; its repository/history/body privacy scans passed, but it was not pushed or measured before the order change.
  - Changed only the optional performance job's runner to `windows-latest` as expressly requested; the runner-policy test and all production guards remain intact. No further W2d implementation/measurement is started before W6.
  - Re-read the manifest and queried the existing Site with native tooling: active, owner role, custom access, version 9; no deployment limit/quota/capacity fields are exposed. Verification continues without treating the local 248 MiB cap as a platform fact. No Site, storage, access, credential or deployment write occurred.
  - W5/#582 and W8/#587 are excluded from this session. After W6 merges, merge main into #586, rerun its required checks and performance measurement, and merge only when green. Preserve all earlier failed/cancelled evidence.

- 2026-10-02, Codex (W2d construction reuse independently closed):
  - Reuse a bounded private graph of child validators and proven resolver contexts while retaining stock descent, every keyword and every HTTP validation. Fingerprinting and fresh-stock fallback close the five baseline schema/context mismatches; public errors and `evolve` expose no private graph. Direct context assignment is rejected explicitly by the private facade.
  - Final API `7c9226a5` passes 99 focused tests, 17 independent mutation/context/identity groups, and fresh reference/resource/concurrent/warmed-HTTP refutations. The bounded profile removes 40,190 repeated constructions while preserving 40,265 descents and exact HTTP bytes. This is functional/construction evidence, not a new latency pass.
  - Corrected the published CI runner-format failure by unquoting the same hosted runner and scoping its mutation test to the named installed-runtime job. All eight rejection cases and production guards are unchanged; 42 policy checks and independent decoy/owner-targeting probes pass. Prior hosted and intermediate failures remain in the validation record.
  - The correction is prepared for publication and a new exact-source hosted measurement under the existing W2d authority. Required checks and the 300 ms target remain open until their actual results. The W6 order/R2 question is unanswered; later workstreams, #582 and external deployment/storage remain untouched.

- 2026-10-02, Codex (W2d first hosted measurement / remaining construction cost):
  - Published `492e4284` after repository privacy, complete eight-commit history (145,204 bytes / 12 patterns / zero hits), and PR-body scans passed. Dispatched CI `37009338445` with its exact source SHA; measurement job `110845046509` executed both profiles and failed the 200-row gate. Sample 50-row maximum: 164.4 ms; 200-row maximum: 406.8 ms. The 300-device repeat maximum was 371.1 ms, cold projection 17.01 s and first lazy device 799.9 ms. Newer hosted dependencies and sequential-ASGI scope are explicit in the validation record.
  - Independent verification matched the artifact ZIP, all 15 members, all 11 source hashes, both fixture digests, clean source identities and all 36 shapes/five repeats. Local failed timings remain evidence. Superseded `4a2671db` CI ended cancelled with 11 passing jobs and Windows Python 3.12 cancelled during testing; it is not recorded as a full pass.
  - A bounded profile on frozen `492e4284` reproduced the exact Findings response and identified 40,190 repeated child-validator/resource constructions. Work now targets construction reuse while retaining complete validation. Five baseline private-helper mutation/context mismatches were preserved; private schema ownership, mutation fallback and canonical errors are part of independent review. No further local acceptance replay is inferred from the instrumented profile.
  - Current implementation work stays within W2d. The W6 reordering/R2 implementation question remains unanswered; no cap, gate, #582, device, vault, storage or deployment action is authorized by this result.

- 2026-10-02, Codex (W2d hosted performance measurement):
  - The further local 200-row sample replay completed all 36 shapes/five repeats with stable source and responses, but failed at 2,648.3 ms; post-run paging was observed without proving a sole cause. No synthetic run or immediate retry followed. Reference run `37003241563` also failed at finalization on `4a2671db`, after 269 Node contracts, compiler schema validation and projection passed. The earlier byte overage is not transferred to this new source.
  - Added a default-off measurement job to the existing CI workflow, using a separate hosted Windows runner and exact expected-commit checks. Both unchanged benchmark profiles execute even after a timing failure; logs/receipts/outcomes are retained and failures remain nonzero. LF checkout plus raw Git-blob/working-file hash checks close the independently found newline-custody gap. Existing required jobs and the benchmark are unchanged.
  - Forty existing policy tests and 21 independent failure-case probes pass; initial policy/probe setup failures are preserved with their bounded corrections in the validation record. No hosted performance success is claimed. This change needs fresh privacy/history scans, publication and an exact-commit measurement dispatch. Existing `4a2671db` checks retain their source scope.
  - The W6 order/R2 implementation question remains unanswered. W2e/W6/W7 retain their requested sequence; no cap, gate, #582, device, vault, storage or deployment change is made.

- 2026-10-02, Codex (W2d corrected source published):
  - Pushed `4a2671db` to existing draft #586 after the repository Git-index/working-tree privacy verifier passed, all six new commit messages/patches passed the 12-pattern scan (114,709 bytes), and the PR description passed its separate marker scan. Before push, current remote main remained `db9d8534`; source ancestry and the exact target branch were verified. The PR description separates current focused proof, earlier broad/performance evidence, and the missing timing/cap gates.
  - Current-head hosted runs are CI `37003241672`, Master Reference `37003241563`, portable `37003241700`, and webapp `37003241647` with a same-head edited-event successor `37003291624`. All were live/pending at this handoff; old-head results do not close them. No merge occurred.
  - Corrected timing remains unverified: the post-reproduction readiness check saw 100% CPU / 719 MiB free memory and launched no benchmark; a later check still saw 100% CPU. Read-only inspection found no surviving processes from this task's completed reference reproduction. No unrelated process was stopped.
  - The owner question on advancing W6 and implementing the R2 proposal is unanswered; W2e/W6/W7 retain their requested order. This publication handoff is committed locally after the push and awaits its own publication gates. No #582, cap, device, vault, R2 or deployment change was made.

- 2026-10-02, Codex (W2d reference capacity diagnosis):
  - The clean exact-source reproduction passed compiler, schema, projection and Vinext stages, then reproduced finalization failure. The unchanged internal builder reports the aggregate cap: 260,505,355 bytes versus 260,046,848, before an outer receipt. Source remains `a1bcc46d` / tree `ab6df5bf`; preserved private evidence is outside the checkout. Hosted cause is a supported same-boundary inference because its exception is redacted.
  - Sites tooling and official documentation supply no verified numeric deployment limit. The fallback is the reviewed R2 proposal in the validation record, retaining offline bytes, digest custody, stable URLs and rollback. Reordering W6 and implementing that proposal need an owner decision; no cap, gate, R2 storage or deployment change is made. #582 remains untouched.
  - Published #586 is still draft at `b54a59be`; all checks except reference finalization passed. The concurrency correction at `7dc60099` and this diagnosis remain local and need fresh privacy/history gates before publication. Corrected-source quiet-host timing is still required; earlier passing measurements and the later failure retain their distinct scope. W2e/W6/W7 remain queued in the requested order.

- 2026-10-02, Codex (W2d concurrency correction / reference failure):
  - The all-host sample sweep passed its warm target, then a synchronized probe exposed cached reads waiting behind an unrelated cold device build. Short publication locking closes that scheduling defect; 84 focused tests and independent concurrency/custody refutations pass. The later timing replay failed under high host load; a controlled old/new comparison shows similar slowdowns, not a lock-specific regression. Fresh quiet-host timing remains pending.
  - Required reference run `36985790137` failed at finalization on hosted merge `a1bcc46d` (tree equal to PR head `b54a59be`). The redacted log cannot establish cause. A clean, read-only verification copy on this workstream's branch is reserved under the task test-run directory and is rebuilding that exact source with fresh artifacts; no other checkout or #582 is changed.
  - The correction and this handoff are local pending publication. The reference cap is unchanged, no merge is allowed while its gate is red, and W2e/W6/W7 remain ordered. The prior b54 tests and measurements retain their own scope.

- 2026-10-02, Codex (W2d published):
  - Pushed `ad2c0b3b` and opened draft #586 after the stable Git-index/working-tree privacy scan passed and the complete three-commit message/patch scan found zero markers across 83,113 bytes and 12 patterns.
  - Required hosted Python, coverage, distribution, reference and portable checks are running. Local performance, focused/independent, full backend/custody and API-generation results are recorded in the validation document. No hosted completion or merge is claimed.
  - This publication handoff changes documentation only; it requires fresh privacy/history checks before push and all required checks on the resulting head before merge. The old untracked root test-cache file remains preserved and excluded. W2e, W6 and W7 retain their ordered rows; #582 is outside this session.

- 2026-10-02, Codex (W2d local implementation):
  - Cached one validated owner document per stored-byte digest and runtime/projection namespace, with lazy exact-host device documents and single-flight admission. Every call still verifies current stored-byte authority and all applicable HTTP response constraints; source and output aliases are isolated.
  - Final focused suite: 83 passed. Independent review closed reference/resource/dialect/dynamic-scope and alias counterexamples, including 73 reference cases, 200 concurrent validator runs and warmed-HTTP mutations. API generation, repository Ruff and diff checks pass. Default and maximum-page sample timing gates pass; the 300-device fleet is measured. Earlier setup and 200-row performance failures remain in the validation record.
  - Full backend/custody validation passed 1,357 tests with one Windows symlink-privilege skip; real Scope toolchain/hub/markup gates were required. The initial privacy scan refused reviewer test databases placed inside the checkout and detected their relocation; all 70 evidence files are preserved outside source with hashes verified. Rule 7 now accurately describes the verifier's working-tree scope. Publication requires a fresh stable-tree scan; final-head hosted gates remain mandatory. No golden/sample/Scope source changed, and #582 remains untouched. W7 preflight also records the bundled Scope dependency-notice/material gap for correction before its candidate build.

- 2026-10-02, Codex (W2c merged / W2d started):
  - Live GitHub confirms #584 merged as `db9d8534` from `61961ca3`; both trees are identical. Removed W2c under rule 8 and reserved the ordered W2d, W2e, W6 and W7 branches in this change.
  - Reuse the existing UI checkout, whose tracked tree is clean. Its existing untracked root `node_modules/` test cache is preserved and excluded. The old engine-defects checkout and its untracked agent configuration are preserved.
  - Owner authorized one PR per workstream and exact-head admin merge commits only after all required checks are green. #582 remains outside this session. No new implementation or performance result is claimed by this start entry.

- 2026-10-02, Claude Code (W8 renumbered):
  - Renumbered this row from W6 to W8 at the coordination session's request: Codex's #586 reserves W6 (Verified
    Sites size cap) and W7 (Atlas release candidate).
  - #587 and #582 fail `Exact-source compiler, reference, and release contracts` only in
    `build/finalize-deployment.mjs` ("deployment manifest build failed") after every contract test passes; main passes
    the same job at `db9d8534`. Codex reproduced the cause as the projection exceeding the Sites size cap. Neither PR is
    being shrunk to fit; both merge `origin/main` and re-run CI after W6 lands.

- 2026-10-02, Claude Code (W8 started; W2c merged):
  - #584 merged as `db9d8534`; its W2c row is deleted here (rule 8).
  - GitHub opened seven high Dependabot alerts for pypdf 6.17.0 in `master-reference/requirements-release.txt`. Four
    independent researchers and a completeness critic verified every advisory against GitHub and OSV: 6.19.0 is the
    first release closing all seven, and nothing published affects it. The required master-reference job passes on
    hosted CI with both pins, and a strict-mode text, metadata and diagnostic comparison of the generated PDFs is
    identical on 6.17.0 and 6.19.0.
  - Root cause: the required dependency audit installed only `.[dev]`, so no required check had ever audited the release
    toolchain, the hash-locked set inside Atlas.exe, the transition pins, the `mcp`/`eval` extras or `wheel` from
    `[build-system].requires`. Each tracked requirements file and lock is now audited by its own `pip_audit --strict`
    step, or through the environment when it only installs this project editable; the environment installs every
    non-empty extra except [build] (whose set is the audited Atlas lock) and the build requirements.
    `tests/test_python_dependency_audit_contract.py` derives the declarations from git and from every file a pip command names,
    and holds every audit step to a closed grammar, so no condition, masked exit code, injected environment or
    unnamed suppression can neutralise it by accident. The new release step fails on the old pin with exactly the
    seven advisories and passes on the new one.
  - Stated limits: inline `pip install` pins in workflow files (graphifyy, build, twine) are not yet audited, and
    covering them means moving them into an audited requirements file used by the release workflows (its own
    change); `tomli`, installed only on the Python 3.10 test lane, has no audited 3.10 set.
  - Five independent refutation rounds ran (four on frozen snapshots, the fifth on the pushed head); every blocker
    and major they proved was fixed and re-tested, and each fix carries a mutation that fails without it.
  - The paramiko PYSEC-2026-2858 suppression is scoped to the shipped lock, which still pins paramiko 4.0.0; netmiko
    4.8.0 lifted its paramiko cap, so the floating environment resolves 5.0.0 and is audited without it.
  - Dependabot's #585 makes the same one-line bump and is green; this PR supersedes it and the pypdf line of #572.
  - Pushed `fix/pypdf-advisories` after the repository privacy verifier and the client-marker scan of every new commit
    and of the PR text passed; opened #587. Owner review and merge (merge commit) follow hosted CI.

- 2026-10-02, Codex (W2c hosted integration corrections):
  - The completed Linux jobs at `2525e58b` agree on three failures; none is a linked-worktree exception. The webapp, CodeQL, dependency/distribution and portable-build gates passed on that head.
  - Kept the public Design inventory and canonical `vitest run` contract intact: moved application-only helpers into the feature folder and gated generation-policy tests through `api:check`. Reconciled the LF receipt to the exact two new backend files without changing owner/attribute policy. Focused guards, 306 frontend tests, nine policy tests and 14 custody tests pass; runtime app bytes and generated types are unchanged.
  - Independent review closed all three corrections, including failing-policy short-circuit, a rejected undeclared public component, and omitted/extra/swapped LF-path counterexamples. The follow-up needs fresh privacy gates and exact-head CI. Earlier failures and partial/cancelled runs remain distinct evidence. Protected fixtures and W1 remain untouched.

- 2026-10-02, Codex (W2c published):
  - Pushed `c5519bdf` after the repository privacy verifier and full four-commit marker scan both exited zero; opened draft #584. The endpoint, generated types, core screens, evidence drawer and portable runtime are implemented and independently reviewed. Required hosted CI must close on the final head before readiness/merge.
  - Closed the JSON-native/finite HTTP refutation with 89 focused passes, independent negative/positive replay, 1,281 full backend passes and fresh frozen smoke. Closed the four reference architecture edges by using the existing adapter and relocating the exporter; no architecture policy changed. The complete reference build and its existing size gate passed with 322,332 bytes of headroom at `c5519bdf`.
  - This documentation handoff follows the implementation without changing app/runtime bytes. Fresh privacy gates remain mandatory for its push. The generated root test cache remains untracked after automatic approval review rejected cleanup; it is excluded from publication. W1 and golden/sample/Scope data remain untouched.

- 2026-10-02, Codex (W2c local validation and final boundary probe):
  - Committed the endpoint/runtime checkpoint as `a4c898a9`; no W2c push or PR yet. Core screens now consume generated engine-contract types and preserve source-bound evidence, withheld rows and exact reference joins. Final frontend gates: 306 unit tests, nine generator-policy tests, six E2E passes with one existing opt-in skip, and 22 unchanged visual comparisons.
  - Independent review closed wrong-host/stale-context pagination, stale evidence identity, retry-offset, interface-order, Scope-link normalization and offline-generator resource-resolution findings. Live browser checks covered the actual synthetic-fleet app, drawer keyboard behavior and corrected 390-pixel layout. The full UI-bearing frozen smoke passed.
  - A later producer-fault probe showed a published NaN could escape the actual HTTP boundary as null despite direct model rejection. Publication remains held for explicit JSON-native/finite guards, independent replay and fresh backend/frozen evidence. Earlier successful paths remain scoped in the validation record; no golden/sample regeneration or W1 changes.

- 2026-10-02, Codex (W2b merged / W2c started):
  - All 15 required checks passed on `b2c13407`; all 28 check runs were terminal (26 successful, two inapplicable draft-publication jobs skipped). Merged #583 with the authorized exact-head merge command as `a0c727bd`. Main's tree `b2adece2e21c4ea44f2eae0c009c0a92ae882b49` equals the tested head. Removed W2b's row under rule 8.
  - Final local complete Master Reference deployment, including its outer receipt: 256,488,364 bytes, with 3,558,484 bytes of headroom under the unchanged limit. Hosted Master Reference validation also passed; exact receipts and residual limits are in the W2b validation record. Golden/sample/Scope fixture bytes retain their single reviewed generation.
  - Created the already-listed `codex/core-screens` branch from current main in the clean existing UI checkout. Backend owns only contract transport and exact-store binding; the engine remains the fact owner. Implementation order remains endpoint, independent contract validation, then core screens. W1 and the protected root checkout remain untouched.

- 2026-10-02, Claude Code (W5):
  - #582's two red checks (Windows tests and the full source/frontend gate, both on `windows-2025`) were one test:
    the `/scope` XML-asset source scan read every quoted string as an import, and the hosted Windows registry types
    `.config` as XML, so the command id `select.config` was flagged there and nowhere else. The scan now counts only
    path-shaped references or references to a real file, covers the package's HTML entries, and a new test pins it on
    every host by forcing `.config` into the suffix set. A mutation that restores the old behaviour fails it.
  - Merged `main` after #583 (`a7016984`); conflicts in `analyze.py` and this board resolved by keeping both sides.
    The sample fleet is fresh against the merged engine.
  - The first re-grade (`b342a05d`) lost 35 of 39 graders to the account usage limit; it is re-run on this head.

- 2026-10-02, Codex (compaction source freeze):
  - Closed the metadata-string numeric overflow refutation and generated-decoder EOL drift test-first. Final projection suite: 90 passed / one existing POSIX-only skip; TypeScript, lint and diff checks passed.
  - Independent bounded review and a repeated all-chunk payload/gzip comparison preserve record values, ordering, indexes, digests, text and terminators. The original chunk partition and limits remain. The explicit pre-existing legacy fallback key limitation is recorded rather than claimed repaired.
  - Full deployment size is still pending. Source-chunk savings alone are not a successful deployment gate. Golden/sample/Scope fixture bytes remain unchanged.

- 2026-10-02, Codex (approved W2b compaction):
  - Owner approved the pending bounded lossless Master Reference compaction request. It is now part of W2b on the existing branch and checkout.
  - Scope: existing projection encoder/generated decoder, round-trip and hostile-input tests, documentation and exact-source rebuild validation. Public payloads, all source records/text/digests/terminators/census denominators, the decoded 256 KiB ceiling and the existing deployment/privacy gates stay intact. Net savings must be measured after decoder and receipt overhead.
  - No additional golden/sample regeneration, W1 changes, new branch/worktree, release publication or qualification authority is included. W2c follows the already reserved route after #583 merges.

- 2026-10-01, Claude Code (W1, closing):
  - #579 merged as `d92fcb1f` on the owner's instruction, after every required check was green on head
    `0345eb1d` and `main`'s tree was confirmed equal to that head's. Row W1 deleted (rule 8).
  - The W1 branch and its worktree stay until #582 lands; the main checkout's launch configuration still
    points at that worktree (W0).
  - #582 (W5) retargeted to `main` while open, and `main` merged in.

- 2026-10-01, Claude Code (W5):
  - Ran the W5 repair wave and its W5b follow-up, each with independent verifiers and refuters.
  - Re-ran the engine gate after a network drop killed it mid-wave.
  - A whole-branch refuter found no blocker or major; its minors are fixed or recorded in O78.
  - Pushed after the rule-7 checks passed (0 hits over 50 commits since `main`) and opened #582, stacked on #579.

- 2026-10-01, Codex (W2b Master Reference capacity gate):
  - The final-head Master Reference run `36918999658` passed compiler/schema validation and 264 contract tests, then failed deployment finalization. Its public error is intentionally redacted; there were no retained CI artifacts.
  - Reproduced from the same tracked tree and compiler census locally. The compressed deployment is 260,473,519 bytes before its outer receipt, exceeding the unchanged 260,046,848-byte limit by 426,671. The private existing diagnostic confirms the aggregate-size rejection. No tracked source or fixture changed during reproduction.
  - Requested owner approval for lossless projection compaction because the earlier board assigns that follow-up to its owner and the current W2 queue does not list it. No compaction edits, budget increase or coverage reduction have been made. Remaining CI is allowed to finish; the PR is held.

- 2026-10-01, Codex (W2b PR publication):
  - Repository privacy passed; the complete marker scan passed across all ten new commits and 2,104,617 patch/message bytes. Pushed `087b00c8` and opened #583 against main `8000adce`.
  - Hosted Python, coverage, distribution, portable, Master Reference and UI checks are in progress. This board update records the publication; its final head must receive its own successful checks before the authorized merge. W2c remains held until that merge.

- 2026-10-01, Codex (W2b single regeneration):
  - Regenerated golden, sample and four Scope bindings once from reviewed source `e4be15f1`, preserving LF. Independent review reconciled the finding/risk changes and all 807 sample evidence references.
  - The sheet guard initially rejected a summary-banner count change. Review proved all 74 sheets and columns unchanged; accepted the exact saved candidate through the documented reviewed-change path without rerunning the pipeline. The initial failure is retained.
  - Projection/sample 665 tests, golden 22 tests, frontend 274 unit tests, five E2E tests and 22 visual checks pass. Backend: 1,224 passed / one Windows privilege skip. Final Scope: 6,992 passed / one sample-inapplicable skip; independent review verified every remapped assertion without weakening coverage. Earlier failures are preserved. No hosted W2b or merge pass is claimed.
  - Integration is committed on this branch for publication, gated by fresh repository privacy and complete new-commit marker checks. Next: open W2b's PR and await the exact-head hosted gates before the authorized merge.

- 2026-10-01, Codex (W2b consumer source freeze):
  - Closed the projection's G13 labels, G15 owner metadata/pointers/readiness scope and G49 input-state handling test-first. Independent final-source refutation found no residual actionable defects.
  - Engine selection: 178 passed. Projection selection: 307 passed with one sample-signature check deferred until regeneration; independent regression replay: 70 passed. Scope synthetic absence controls: 162 passed, zero skipped.
  - Consumer integration is committed locally before the one regeneration pass; no protected fixture has been regenerated. Fresh privacy gates are required before the next push.

- 2026-10-01, Codex (W2a merged / W2b integration):
  - Marked #580 ready after all 15 required checks passed on `1e6268f3`; the applicable webapp and CodeQL checks also passed. Merged with the authorized merge-commit command as `8000adce`. Its tree `3a99bc64d24b5892d4880810ab59a2da3c0280ab` equals the tested head's tree. Removed W2a's active row under rule 8.
  - Merged current main into the existing W2b checkout. The only conflict was this board; every handoff line from both parents is retained. W1's branch/folder remain untouched.
  - W2b now owns projection/Scope consumer reconciliation and the single fixture-regeneration pass. Reserved W2c's concrete branch and existing folder here before creation; it starts only after W2b merges.

- 2026-10-01, Codex (W2a hosted gate):
  - Pushed implementation `c8a78732` after repository privacy and all seven new commits' marker scans passed. Updated draft #580 to its complete scope.
  - Five completed Linux full-suite jobs found the same sole receipt-reader classification gap. The projection's section-level dependency needs a mechanical SSOT-delegation proof; the guard remains mandatory. The scoped correction now passes the final 32-test protocol suite and independent refutation, including later-row, aggregate and shadowing counterexamples. Production source is unchanged.
  - The full local coverage cancellation and hosted failure receipts remain explicit in the validation record. W2b integration still waits for #580 to pass and merge.

- 2026-10-01, Codex (W2a evidence integration):
  - Projected finding evidence and health deduction references with closed schemas, owner-vocabulary parity, cap disclosure, source-failure precedence and legacy handling. Independent review closed the refutations; final focused and frontend results are in the validation record.
  - The instrumented full local suite was cancelled incomplete at about 38% after 1,628.78 seconds. Seven reported failures remain unclassified; no full-suite or coverage pass is claimed. Required hosted CI must close those gates before #580 is ready or merged.
  - Golden, sample-data and frontend distribution bytes were preserved. W2b remains pushed through `f950f888`; its consumer repairs and regeneration wait for #580.

- 2026-10-01, Codex (W2a):
  - Verified #579 merged as `d92fcb1f`; its tree equals tested head `0345eb1d`. Removed W1's active row under rule 8; its branch, checkout and follow-ups remain with their owner.
  - Merged current main into the existing `feat/ui-projection-slice2` checkout with a merge commit. Preserved every handoff entry from both sides of the board conflict.
  - W2b is pushed through `f950f888`: engine fixes and full-suite refutations are saved on that branch. W2a now owns evidence-reference projection and its gates; W2b integration/regeneration follows W2a's merge.

- 2026-10-01, Codex (W2 full-suite refutation):
  - Full JUnit result at `e74a4c42`: 9,684 passed, 40 skipped, 20 failed. Classified eight listed context failures, nine deferred golden/sample comparisons, and three actionable failures. The log wrapper's Unicode printing failure is preserved in the validation record; the completed XML is the count source.
  - Closed the three actionable failures: G49 now consumes the protocol conclusion owner; two simulator fixtures now describe a consistent incumbent root. All assertions retained. Post-fix focused suite: 146 passed; repository-wide ruff and diff checks pass.
  - No golden/sample regeneration. #579 checks are green but it remains unmerged under W1 ownership. W2a implementation still waits; read-only API and prototype-source preflights are in `docs/one-app-w2-integration-preflight-2026-10-01.md`.

- 2026-10-01, Codex (approved W2 publication):
  - Owner approved the six-command path-only repair and push of `fix/engine-contract-defects`. Repaired only the untracked hook command values, preserved an external local backup, and independently verified six syntax checks plus 12 path-resolution probes; no hooks executed.
  - Repository privacy verifier and full new-commit message/patch marker scan passed. Publication is authorized and gated on fresh successful reruns; local tooling stays untracked.
  - #581 exact-main CI `36858426410` and Master Reference `36858426344` both completed successfully on `497e26b6`.
  - W1 advanced to `0345eb1d`; #579 remains unmerged. W2a implementation and W2b golden/sample regeneration remain held for its merge.

- 2026-10-01, Codex (W2 blocked audit):
  - The same hook-repair approval and W1 merge dependency remain after three consecutive goal turns. #579 is still open/behind; the local hook marker is still present. Goal marked blocked, not complete.
  - The fixes and handoff are committed locally; no push is permitted until the mandatory privacy verifier passes. The existing approval request remains pending.
  - Stopped only the two local `gh run watch` clients. Hosted #581 main runs `36858426410` and `36858426344` remain live; query their terminal verdicts on resume. No W1 or fixture changes.

- 2026-10-01, Codex (W2 continuation):
  - Re-fetched and confirmed #579 remains open/behind; #581 is merged, with exact-main CI run `36858426410` and Master Reference run `36858426344` still live.
  - Prepared and independently reviewed the six-command hook-path repair read-only; approval remains pending. No hooks were executed or modified. Concrete replacement and limits are in the W2b validation record.
  - `ebb5a368` and this handoff remain local only; the mandatory privacy failure still prevents push. No new implementation or fixture changes.

- 2026-10-01, Codex (W2):
  - Merged docs-only #581 at `6a817777` after every required check passed; merge `497e26b6` has the tested head tree.
  - Took over W2b, finished G13/G15/G49 test-first and closed independently reproduced refutations; 1,022 related tests pass. Details and preserved negative evidence: `docs/engine-defects-validation-2026-10-01.md`.
  - No golden/sample refresh and no W1 branch/folder changes. #579 remains open/behind main; W2a and the W2b integration/PR wait for its owning session.
  - Fixes are **local only, not pushed**: the required privacy gate rejects pre-existing untracked `.codex/hooks.json`. Requested approval for a path-only local repair; `.agents/` and `.codex/` were preserved and excluded from staging.

- 2026-10-01, Claude Code (W1):
  - Made #579's CI honest. Each red check was fixed at its root, with a test that fails without the fix:
    - a cross-drive `relpath` in a test helper;
    - a case-folding test that assumed the file system;
    - CodeQL;
    - the master-reference contract, its allowlist, its TypeScript resolution and its size bounds.
  - The CodeQL finding led to a snapshot-name defect class that three independent refuters widened until it was
    closed by structure.
  - `atlas-scope/` is censused at identity depth in the master reference, with a named BLOCK category. The
    reference's deployment bundle is at 256 of 260 MB. Compact per-line encoding is urgent for its owner.
  - The required dependency audit now covers every tracked npm lockfile.
  - Merged #578. Regenerated the demo fleet and re-bound Atlas Scope to it.
  - Pushed. The owner lifted "finish 3.5 only" in chat; that preview-scope work is row W5, stacked on this branch.

- 2026-09-30, Claude Code (W1):
  - The owner confirmed D11 in the W1 session. Phase 3.5 is committed, and `main` is merged in (#573, #574,
    #575, #577).
  - Found while merging, and fixed in the branch:
    - The assessability guard now tells #575's census vocabulary apart from the receipt's.
    - Importing the engine no longer opens its audit log, which removes the `-n auto` collection
      `PermissionError`.
  - Rule-7 checks passed. Pushed the branch and opened #579 with the preview scope listed.

- 2026-09-30, Claude Code:
  - Merged #574 (npm advisories), #575 (engine honesty) and #573 (this board + ADR 0007); deleted
    rows W3 and W4 (rule 8).
  - Opened #577 (`ui_projection/1` slice 1).

- 2026-09-30, Claude Code:
  - The owner delegated D0/D9/D10/D11 with full authority; recorded in ADR 0007.
  - Opened #574 to clear new npm advisories, which were failing a required check for every pull
    request.
  - W2 started.

- 2026-09-30, Claude Code:
  - Merged #577 (`ui_projection` slice 1) and #578 (`ssot` owner robustness).
  - The owner confirmed D11, so W1 is published as PR #579; its compile diagnosis was sent to its
    holder.
  - Slice 2 is held as a draft until W1 merges.

- 2026-09-29, Claude Code:
  - Created this board and recorded the direction verdict (dated record linked above).
  - Removed idle worktrees, fully merged local branches and empty orphan directories, preserving
    all uncommitted work.
  - W1 continues in its own session. W2 waits on the owner decisions above.

## W2 handoff notes (2026-10-01)

W2 was transferred from Claude Code to Codex. The Active table is now the current queue.
W1 / #579 has merged; its follow-ups remain with its own holder.

**Notes for the W2 holder (verified on this host):**
- **Linked worktrees always show 8 test failures:** `test_graphify_guarded` (4), `test_graph_invariants` (3) and
  `test_atlas_r2_authority_decision_binding` (1). They fail identically on an unchanged `main` in a linked
  worktree, so they are environment failures. A rare `make_stick` / venv-redirector failure under load
  passes when re-run alone.
- **Adding a `cisco_toolkit` module moves two zero-egress attestation strings in the golden snapshot** ("across N
  modules"). RUN `tests/test_pipeline_golden.py`; a byte-identical golden file proves nothing.
- **Do not run a full `UPDATE_GOLDEN=1` regeneration on Windows:** it rewrites every line ending to CRLF (tens of
  thousands of churned lines). Regenerate, then compare with `git diff --ignore-cr-at-eol`, and commit LF bytes
  that change only the real content.
- **Merges:**
  - Use merge commits (never squash or rebase) and `gh pr merge <n> --merge --admin --match-head-commit <tested sha>`.
  - Only do this after every required check is green and with the owner's standing merge authority: branch
    protection needs one review, and authors cannot self-approve.
  - Merging one PR puts the others behind `main` (the strict rule), so merge `main` in again.
  - A clean 3-way merge of the same two commits always gives the same tree. Confirm it after merging:
    `git rev-parse origin/main^{tree}` must equal the tested merge's tree.
- **Before every push (public repo):**
  - `py -3.12 -I -B .github/scripts/verify_repository_privacy.py --root .`
  - a scan of `git log -p origin/main..HEAD` with `cisco_toolkit.distribution_verify._client_marker_patterns()`
  - Gate each step on its exit code; never chain gates with `;`.
