# Atlas portable build (ADR-0004 P2)

One-folder Windows bundle of the whole platform — engine + AssessHub + the 12-document deliverable
family — that runs from a USB stick with **no Python on the host**. `Atlas.exe` is the one door:
it boots the server, opens the browser, and re-invokes itself as the engine CLI for ingest runs
(the `--run-engine` sentinel; see `webapp/backend/serve.py`).

## Build

```bash
pip install -e .[webapp,docx,pptx,build]                    # web layer + doc family + PyInstaller
cd webapp/frontend && npm ci && npm run build && cd ../..   # the SPA must exist first
python portable/build_atlas.py                              # build + 4-step smoke, exit ≠ 0 on any failure
```

The bundle lands at `portable/dist/Atlas/`. The build **refuses** to run with missing assets
(KB packs, explorer template, dist, sample fleet, pyproject) — the same fail-loud doctrine as
`--selftest`, applied before the field ever sees it. The smoke then proves the result like a
hostile reviewer: `--selftest` 8/8, `--version` (checkout release, never stale pip metadata),
`--run-engine --help` reaches the real engine argparse, and an HTTP pass over `/api/health`,
`/api/meta` (app-identity block) and `/` (the bundled SPA via the `_MEIPASS/webapp_dist` probe).

Manifest lives in [`atlas_bundle.py`](atlas_bundle.py) (pinned by `tests/test_atlas_bundle.py`
in the normal gate — no PyInstaller needed); [`atlas.spec`](atlas.spec) is a thin consumer.

## Stick layout (AssessKit)

```
E:\Atlas\            ← portable/dist/Atlas/, copied wholesale
  Atlas.exe            console app (D3: live-SSH credential prompts need a real terminal)
  _internal\           bundle internals — replaced on every update, never edited
  data\                created on first run — THE ONLY WRITABLE DIR (SQLite store)
```

- **Update** = replace everything **except `data\`** (client evidence lives there).
- **Field discipline** (P3): BitLocker-To-Go the stick — snapshots are client data. Credentials
  are prompted per engagement and never stored (the engine's own chain, ADR-0004 D4).
- DB override: `--db` / `ASSESSHUB_DB`; frozen default is `data\assesshub.db` beside the exe.

## Known limits (deliberate, this slice)

- **Unsigned.** AppLocker/WDAC-locked laptops will refuse the exe until it is code-signed —
  the signing certificate is the owner's open calendar item. SmartScreen/MOTW is a non-issue on
  FAT32/exFAT sticks.
- Windows-only, single-arch (build host = target arch). No auto-update.
- The `(checkout)` suffix in `--version` is honest: the bundle reports the pyproject release it
  was built from.
