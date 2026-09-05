# Atlas portable build (ADR-0004 P2)

One-folder Windows bundle of the whole platform — engine + AssessHub + the registry-owned
pre-cutover artifact family and conditional post-execution PIR — designed to run with **no Python
installed on the host**. That physical Python-absent-host run remains an external field gate.
`Atlas.exe` is the one door:
it boots the server, opens the browser, and re-invokes itself as the engine CLI for ingest runs
(the `--run-engine` sentinel; see `webapp/backend/serve.py`).

## Build

Release candidates use the exact Windows x64 toolchain in `portable/toolchain.json` and the
hash-locked `portable/windows-x64-requirements.lock`, then run:

```text
python -m portable.build_release --output <fresh directory outside the repository>
```

The local controller also requires `ATLAS_NPM_TARBALL` to name the already-downloaded npm 11.16.0
tarball whose SHA-512 equals `portable/toolchain.json`; the hosted lane downloads then verifies those
bytes before extraction. It never executes a registry-fetched npm or Python package before its
tracked hash contract is checked.

The tracked Windows workflow first reproduces the SPA. The controller then invokes the real
PyInstaller build, runs the four-step smoke and additional Windows qualification, creates the
portable ZIP/member manifest/checksums/CycloneDX SBOM/toolchain/signing/qualification/provenance
receipts plus the complete available runtime license texts and three explicitly legal-review-pending
dataset notices, and reopens the ZIP through an independent verifier. `SELF_CONSISTENCY_PASS` is
not authenticated provenance; the manual draft lane separately verifies both GitHub provenance and
CycloneDX attestations. `python portable/build_atlas.py`
remains the focused developer build + smoke entry point.

The bundle lands at `portable/dist/Atlas/`. The build **refuses** to run with missing assets
(KB packs, explorer template, dist, sample fleet, pyproject) — the same fail-loud doctrine as
`--selftest`, applied before the field ever sees it. The smoke then proves the result like a
hostile reviewer: `--selftest` all green, `--version` (checkout release, never stale pip metadata),
`--run-engine --help` reaches the real engine argparse, and an HTTP pass over `/api/health`,
`/api/meta` (app-identity block) and `/` (the bundled SPA via the `_MEIPASS/webapp_dist` probe).
The PE `VERSIONINFO` is generated in memory from `pyproject.toml`, the Atlas brand owner, and
`LICENSE`; the real-binary smoke fails if Windows does not report the exact product, company,
original filename, and release strings used by publisher/version policy.

Manifest lives in [`atlas_bundle.py`](atlas_bundle.py) (pinned by `tests/test_atlas_bundle.py`
in the normal gate — no PyInstaller needed); [`atlas.spec`](atlas.spec) is a thin consumer.

## Stick layout (AssessKit)

```
E:\Atlas\            ← portable/dist/Atlas/, copied wholesale
  Atlas.exe            console app (D3: live-SSH credential prompts need a real terminal)
  README-FIELD.txt     the one-page field guide (ratchet-tested: tests/test_readme_field.py)
  LICENSE              project distribution terms
  _internal\           bundle internals — replaced on every update, never edited
  data\                created on first run — THE ONLY WRITABLE DIR (SQLite store; boot keeps
                       the newest 3 integrity-checked copies in data\backups\)
```

- **Update** = take an exclusive destination lock; copy a release ZIP onto the target volume;
  verify, extract, and reverify every installed member there; preflight a same-volume database
  copy; create a hash-bound backup receipt; detach `data\` into `Atlas.data-handoff`; switch whole
  application directories and finish executable verification; only then attach data with an exact
  directory rename under a recovery journal. `Atlas.previous` and an exact
  `Atlas.rollback-slot.json` binding are retained for rollback; the active tree is never mirrored
  in place. The receipts are unkeyed local consistency evidence, not authentication.
- **Field discipline** (P3, shipped): `README-FIELD.txt` beside the exe is the discipline —
  BitLocker-To-Go (client evidence lives on that stick), redaction before anything leaves the
  site, credentials prompted never stored (the engine's own chain, ADR-0004 D4), eject
  etiquette, corruption recovery from `data\backups\`.
- DB override: `--db` / `ASSESSHUB_DB`; frozen default is `data\assesshub.db` beside the exe.

## Redact before it leaves the site

```
Atlas.exe --redact-folder <collection folder> --out <dir>   [--redact-collection]
```

Renders the **complete engine CLI artifact set, pseudonymized**, from a local collection folder.
AssessHub-only pre-cutover artifacts and the conditional PIR are produced by their owning UI
workflows, not by this command. The engine hard-requires a `--template` workbook and a
`--devices-file` that the bundle does not carry, so both are synthesized into a private workdir
exactly as the AssessHub ingest channel already does (`webapp/backend/ingest.py`).

- **Verified, not trusted.** A run that silently failed to redact would look identical to success,
  so the produced snapshot is inspected and the run **fails loud** if private addresses survive in
  evidence — nothing is deleted, and the message names the JSON path.
- Refuses to write inside the bundle (an update would replace it) or inside the collection folder.
- `--redact-collection` is opt-in and separate: it rewrites the **raw captures in place** (still
  `--compare`/`--trend`-able).

## Lay out a stick

```powershell
powershell -File portable/make_stick.ps1 -Dest E:\ -Package C:\release\Atlas-<version>-windows-x64.zip
```

The package copy is hash-checked and verified before extraction, then the extracted tree and
`Atlas.incoming` are checked against the same source/member identity. The updater holds a persistent
`.Atlas.update.lock` handle through recovery and cleanup, refuses reparse indirection, retains an
older rollback slot until the new candidate and database copy pass, and uses `Directory.Move` so a
locked child cannot produce a partial data/application move. Executable fault-injection tests cover
the journaled update and rollback checkpoints, including first install, concurrent invocation,
locked data, candidate mutation, and failed rollback-candidate verification. No candidate process
is given client `data\` inside its application directory; the complete data-tree identity is
checked around executable steps and attached only after those checks finish.
A real power-loss/removable-media run is
still physical field evidence, not implied by those software injections.

Explicit rollback is `powershell -File portable/make_stick.ps1 -Dest E:\ -Rollback`. The older app
must first prove it can open a same-volume copy of the retained database. If it cannot, use
`-Rollback -RestorePreUpdateDatabase`: only the backup named and hashed by the exact rollback-slot
receipt is eligible, and the newer database is preserved with its own receipt before replacement.

Post-package Authenticode evidence is written outside the verified bundle so the receipt itself
cannot change the package member set:

```powershell
powershell -File portable/verify_signatures.ps1 -Bundle C:\candidate\Atlas -Manifest C:\candidate\Atlas\release-metadata\portable-member-manifest.json -OutReceipt C:\candidate-evidence\authenticode.json
```

Add `-ExpectedThumbprint <40-hex>` only when policy requires every PE to have one publisher;
otherwise the receipt preserves the exact per-member publisher set for controller policy review.

The local production-certificate preparation path preserves the unsigned tree and every pre-sign byte. Use fresh evidence,
staging, and output paths outside the repository:

```powershell
py -3.12 -m portable.prepare_signing --bundle C:\build\Atlas --out C:\evidence\pre-sign-manifest.json --toolchain-out C:\evidence\pre-sign-toolchain.json
powershell -File portable\sign_release.ps1 -Bundle C:\build\Atlas -SignedBundle C:\staging\Atlas.signed -Manifest C:\evidence\pre-sign-manifest.json -Thumbprint <40-hex> -TimestampUrl <https-rfc3161-url> -OutReceipt C:\evidence\signing.json -ProductionCertificate
py -3.12 -m portable.package_signed_release --bundle C:\staging\Atlas.signed --signing-receipt C:\evidence\signing.json --pre-sign-manifest C:\evidence\pre-sign-manifest.json --pre-sign-toolchain C:\evidence\pre-sign-toolchain.json --output C:\release\signed
```

The controller requires the pre-sign manifest/toolchain, proves every non-PE byte is unchanged,
normalizes only Authenticode-owned PE fields/alignment, independently re-runs Windows signature and
timestamp policy, then repeats the complete frozen qualification on the signed byte set. No signing
identity, timestamp, or production trust is implied until this exact path succeeds with externally
custodied credentials and the field packet closes.
The current GitHub workflow does not ingest or attach this signed set; v1 remains permanently
draft-only until a separate reviewed signed-candidate/promotion contract exists.

## Known limits (deliberate)

- **Unsigned candidates are draft-only.** Current Microsoft guidance says Smart App Control can
  check every executable, not merely downloaded files, and enterprise policy can prevent a
  SmartScreen bypass. FAT/exFAT therefore does not make unsigned execution broadly safe. The repo
  now carries explicit RSA Authenticode/RFC3161 signing and verification machinery, but no production
  certificate or key is bundled or inferred. Without signing evidence the receipt says
  `UNSIGNED_RELEASE_CANDIDATE`; a successfully signed set says
  `AUTHENTICODE_TIMESTAMPED_VERIFIED_NOT_PROMOTED`. Managed-policy results remain a separate field
  gate and do not rewrite either historical signing receipt. Publication remains blocked.
  The helper selects one explicit RSA certificate from the non-elevated `CurrentUser\My` store
  and verifies default Authenticode policy, every signature, timestamp presence, and the Windows
  10/11 baseline `/o 2:10.0.0`; its receipt remains explicitly non-promoting.
- Windows-only, x64-only (build host = target architecture). Updates are operator-initiated and
  staged; there is no unattended network updater.
- Python/npm package license texts are embedded when installed packages omit them through two
  source-pinned fallbacks. IANA/IEEE/Cisco dataset source/hash notices are also embedded, but IEEE
  OUI and Cisco-fact public redistribution authority remains an explicit legal-review gate; a draft
  candidate does not close it.
- The `(checkout)` suffix in `--version` is honest: the bundle reports the pyproject release it
  was built from.
