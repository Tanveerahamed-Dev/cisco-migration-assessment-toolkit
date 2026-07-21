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
hostile reviewer: `--selftest` all green, `--version` (checkout release, never stale pip metadata),
`--run-engine --help` reaches the real engine argparse, and an HTTP pass over `/api/health`,
`/api/meta` (app-identity block) and `/` (the bundled SPA via the `_MEIPASS/webapp_dist` probe).

Manifest lives in [`atlas_bundle.py`](atlas_bundle.py) (pinned by `tests/test_atlas_bundle.py`
in the normal gate — no PyInstaller needed); [`atlas.spec`](atlas.spec) is a thin consumer.

## Stick layout (AssessKit)

```
E:\Atlas\            ← portable/dist/Atlas/, copied wholesale
  Atlas.exe            console app (D3: live-SSH credential prompts need a real terminal)
  README-FIELD.txt     the one-page field guide (ratchet-tested: tests/test_readme_field.py)
  _internal\           bundle internals — replaced on every update, never edited
  data\                created on first run — THE ONLY WRITABLE DIR (SQLite store; boot keeps
                       the newest 3 integrity-checked copies in data\backups\)
```

- **Update** = replace everything **except `data\`** (client evidence lives there).
- **Field discipline** (P3, shipped): `README-FIELD.txt` beside the exe is the discipline —
  BitLocker-To-Go (client evidence lives on that stick), `--redact` before anything leaves the
  site, credentials prompted never stored (the engine's own chain, ADR-0004 D4), eject
  etiquette, corruption recovery from `data\backups\`.
- DB override: `--db` / `ASSESSHUB_DB`; frozen default is `data\assesshub.db` beside the exe.

## Lay out a stick

```powershell
powershell -File portable/make_stick.ps1 -Dest E:\        # first copy AND updates
```

Copies the built bundle to `E:\Atlas\`. On an existing stick it is the **update flow**: everything
is replaced **except `data\`** (the client-evidence store survives every update — robocopy
`/MIR /XD data`). Then, on the target machine: `E:\Atlas\Atlas.exe --selftest` → expect
`SELFTEST: PASS`.

## Known limits (deliberate)

- **Unsigned — by decision, not by omission** (ADR-0004 D5, 2026-07-20: the $0 build is the
  operating version). The designed pattern never needs third-party code trust: Atlas runs from
  the stick on the *engineer's own* laptop; client hardware never executes it. SmartScreen/MOTW
  is a non-issue on FAT32/exFAT sticks. The one closed door: AppLocker/WDAC-locked third-party
  laptops refuse unsigned exes and have no free workaround by design — use your own laptop or a
  client-IT exception. If signing is ever actually needed: Azure Trusted Signing (~$10/mo,
  cancellable) beats yearly certificates.
- Windows-only, single-arch (build host = target arch). No auto-update.
- The `(checkout)` suffix in `--version` is honest: the bundle reports the pyproject release it
  was built from.
