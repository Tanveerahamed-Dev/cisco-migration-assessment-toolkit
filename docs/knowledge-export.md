# Hosted ATLAS knowledge export

The manual `.github/workflows/knowledge-export.yml` workflow produces review data in this repository. It does not update application software, modify a source branch, write a device or the personal vault, create a release, or grant publication/merge authority. The GitHub-only execution rule remains unchanged: do not run the producer, exporter or verification controller locally.

## Source selection and authority

This first reviewed job accepts **only merged RC7 `3401627f6fd69bb838a2c921d7f95c77b2373623`**, tree `1aaa1cb7d87712d8cfcbb19a42e0c4a7ec68d5a8`. The required `source_commit` input has that default and refuses every other value. A future source revision needs a reviewed pin change; selecting a moving branch name does not choose a new source.

Two separate checkouts prevent workflow repair code from being mistaken for RC7 product source: `controller` is the dispatched workflow revision; `source` is the fixed RC7 commit. Both full identities and the GitHub run/attempt are recorded. The source has its own physical `.git` directory, must be clean before and after generation, and may not carry a preexisting owner graph. Nothing from the Windows canonical checkout, untracked probe, owner memory, old notes or personal vault is uploaded as an input. The canonical local checkout need not move.

The workflow is `workflow_dispatch` only, on an ephemeral `ubuntu-24.04` runner, with `contents: read`, no secrets, no persisted checkout credentials and immutable action revisions. Ordinary PR checks exercise its controller and wiring tests; opening/pushing this repair does not run knowledge generation. An operator must separately approve and dispatch the merged workflow. It is not a new required branch-protection context.

## What runs on the hosted runner

The controller `.github/scripts/knowledge_export.py` verifies the source and environment, probes the existing Graphifyy 0.9.51 producer guard, and runs the source repository's privacy checker. It then uses the already reviewed forms:

```text
python -I -B tools/graphify_guarded.py extract . --code-only
python -I -B tools/graphify_guarded.py update .
```

Bootstrap creates a graph in the fresh standalone checkout; the full update adds AST-capable document structure and heals the documented incremental cross-file-edge loss. There is no `--force`, partial-output override, semantic extraction, LLM labeling, URL ingestion or API backend. The subprocess environment excludes provider keys, GitHub tokens and inherited Graphify/Git controls. Guard pending/complete/status receipts bind matching clean source endpoints; the installed package is not patched on disk.

Next the controller runs the **unchanged** `tools/verify_graph_report.py` and requires exit zero **and** `status: pass`. It checks the graph source stamp, IDs, edges and AST origins, and invokes the existing `tools/export_graphify_obsidian.py` into a fresh temporary vault. It independently checks the export receipt/member digest, node-note identity coverage, case-fold uniqueness, Windows destination budget, wikilinks and Canvas references. Source and graph bytes are reread before publication.

Only complete success uploads `atlas-knowledge-3401627f6fd69bb838a2c921d7f95c77b2373623-<run>-<attempt>`, containing `obsidian.zip`, graph/report/label/receipt inputs, command logs, `verification.json` and a SHA-256 member manifest. The manifest excludes itself; this is run-bound integrity bookkeeping, not a signed attestation or proof of semantic completeness.

On refusal, the job fails and uploads only `atlas-knowledge-BLOCKED-<run>-<attempt>` with fixed-code diagnostics and the report auditor's result when available. A partial output directory is never uploaded as an importable knowledge artifact. No `continue-on-error`, failure waiver or output forced shrink is used.

## Existing capacity blocker remains separate

The existing Windows graph is stamped `c27a39b1`, matching its older canonical source, not current merged RC7. Separately, its 2,636,819 lexical JSON values exceed the report verifier's **2,000,000** value limit. That budget refusal is not evidence of stale source, malformed JSON or corrupt graph edges. The new workflow does not raise the bound or map refusal to PASS.

Actual RC7 generation has not yet run. If its unchanged report gate also refuses at capacity, use the hosted diagnostic evidence for a separate independently reviewed verifier-capacity repair; do not use a BLOCKED artifact as a verified refresh. The pinned upstream producer still has the documented memory-ignore override and authored-`build`-directory pruning gaps. Markdown is structural only. `verification.json` explicitly withholds global corpus completeness and local dirty-worktree coverage.

## Operator dispatch, download and open

After this repair is reviewed/merged and a human separately authorizes generation, use the repository's **ATLAS knowledge export** Actions page, select the reviewed workflow ref and enter the exact full RC7 source above. Confirm that both selected source and controller identities in the resulting artifact match the intended operation. This PR itself is not dispatch authority.

Wait for the terminal job result. A green job with a success artifact is required; a BLOCKED diagnostic artifact is not an export. On the artifact's GitHub page, check its source, run and attempt. Download only that successful artifact into a **new staging folder**. With the existing GitHub CLI, the download operation is:

```powershell
gh run download <successful-run-id> --repo Tanveerahamed-Dev/cisco-migration-assessment-toolkit --name atlas-knowledge-3401627f6fd69bb838a2c921d7f95c77b2373623-<successful-run-id>-<attempt> --dir <fresh-staging-folder>
```

Read `verification.json`, `knowledge-manifest.json` and the embedded README. Do not run Graphify or a local verification controller. Under the existing GitHub-only rule, custody/receipt verification belongs on the hosted runner; downloading/reading/copying these files is a GitHub/file operation, not a new local attestation.

Extract `obsidian.zip` into a **fresh, previously nonexistent destination**, for example `C:\ATLAS-Knowledge\RC7-<run>`. Keep the destination's absolute path at most **120 UTF-16 code units** as required by the hosted path check. Refuse an existing destination before extracting; do not use overwrite/merge options. The ZIP contains its `.obsidian` configuration as well as generated notes and `graph.canvas`.

In Obsidian, choose **Open folder as vault** for that fresh folder. Keep `graphify-out\obsidian`, its hand-written release notes, existing links and unrelated vault content unchanged. This job does not sync into `C:\Vaults\brain`; any generic lesson promotion still follows ADR 0001: repo bridge candidate, then separate vault-cwd sanitized ingestion. A successful project-vault artifact does not grant a personal-vault write.
