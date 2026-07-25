# 0004 — Atlas portable field app: P0 decisions

- **Status:** accepted (2026-07-19)
- **Deciders:** Tanveer Ahamed (scope explicitly; name, SSH mode and credential UX delegated to the
  engagement-lead session with "take the best possible decision")
- **Context:** the Project Atlas §15 plan turns the toolkit into a one-folder Windows app on a USB
  stick (PyInstaller one-folder; AssessHub as the single door). The 2026-07-18 adversarial
  feasibility audit sized the work (P1 3–5 sessions, P2 2–3 + signing lead time) and found the two
  frozen-build code gaps (production entry module; frozen-aware ingest dispatch). P0's exit gate is
  this ADR.

## D1 · Name: **Atlas**, bylined **"by Tanveer Ahamed"** (owner's call, "for now")

`Atlas.exe` in an `Atlas\` folder on the stick; cockpit/About title "Atlas — by Tanveer Ahamed".
Chosen by the owner after a deliberate exploration of historical/mythological candidates
(Theseus, Argus, Ariadne, Janus, Argonaut, Pharos, Netra, Drishti were weighed). Atlas is itself
mythological — the Titan who carries the world, as the stick carries the engagement — and it
deliberately shares one brand with the Project Atlas reference document: the app maps networks,
the document maps the project. "Project" is dropped from the binary (codename register, not a
shipped product). Known adjacency: "Atlas" is common in tech (MongoDB Atlas etc.) — acceptable
for a bylined field tool, revisit only if commercialized. The name lives in ONE brand constant
(`cisco_toolkit/brand_tokens.py` at build time) so a rename stays a one-line change.

## D2 · Field scope: the **full 12-document family**

Everything AssessHub serves today (owner: `cisco_toolkit/docmeta.py::FAMILY`) ships on the stick —
no code trimming. The `[docx]`/`[pptx]` extras are therefore **required** in the frozen bundle and
asserted by the P1 `--selftest`.

## D3 · Collection mode: **dual — offline-analysis default, opt-in live SSH**

The stick analyzes folders/ZIPs by default and may collect live when the engineer explicitly asks
("if we need any more information we can just collect it right away" — owner). Consequences:
- **Console build** (PyInstaller `console=True`): the credential prompt needs a real terminal —
  windowed builds crash at `sys.stdin.isatty()` (`COLLECT_PARSE_V3_23_0.py:1174`).
- Collection stays explicit opt-in per the read-only doctrine; the app never auto-collects.

## D4 · Credential UX: surface the existing chain — enter once, override per device, store never

The owner's requirement ("don't repeat for every device; some devices have separate credentials")
is **already the engine's design** — `COLLECT_PARSE_V3_23_0.py:1148-1181` resolves, in order:
1. per-device `password` (back-compat),
2. per-device `password_env` → named env var (the separate-credentials path),
3. global `$CISCO_PASS`,
4. one secure `getpass` **per username** (not per device) on a TTY — offline runs never prompt
   (`FIX-V3.23.177`).

AssessKit P1 surfaces this as a one-prompt fleet flow with a per-device override editor and
session-memory only — **credentials are never written to the stick** (P3 field discipline).
No engine change required; UI + docs only.

## D5 · Distribution: unsigned freeware build — signing DEFERRED indefinitely (amendment, 2026-07-20)

Owner's call ("I don't want to pay anything now"): the **$0 unsigned build is the operating
version**. Every tool in the stack is free/open-source; there is no license cost anywhere. This is
safe because the operating pattern never needs third-party code trust:

- Atlas runs from the stick **on the engineer's own laptop** — collections go out over SSH from
  there; client hardware never executes the exe.
- FAT32/exFAT sticks carry no Mark-of-the-Web, so SmartScreen does not prompt (P2 audit fact);
  an NTFS copy is at worst a one-time "More info → Run anyway".
- The one scenario that stays closed — an AppLocker/WDAC-locked third-party laptop — has **no
  free workaround by design** (that is the policy working). Legitimate paths: run on the
  engineer's laptop, or a client-IT exception.

**Revisit triggers:** distributing the exe to engineers outside the owner's control, or a hard
client-hardware deployment requirement. Cheap path when triggered: Azure Trusted Signing
(~$10/month, month-to-month, cancel after) rather than $300+/yr OV/EV certificates; self-signing
helps only on self-controlled fleets.

## Deferred to the owner (calendar items, not session work)

- ~~Order the code-signing certificate~~ — **superseded by D5** (deferred indefinitely, no spend).
- ~~Delete `..\Enhancements_attic_2026-07-05\`~~ — **DONE 2026-07-25, at the owner's instruction**,
  executed by session `local_0c935881`. The decision was the owner's and the session only the
  hands, so this stays an owner calendar item, consistent with the heading above; the 2026-07-24
  session had gated the action on "tell me and I'll delete", and that instruction is what
  authorized it. Sent to the Recycle Bin rather than hard-deleted, and **re-read there the same day
  to verify this bullet** — so the inventory is measured against the recovered bytes, not recalled.
  Full recursive contents, 3 files / 896,681 bytes:

  | file | bytes | credential-pattern scan |
  |---|---|---|
  | `blast_radius_explorer.html.stale-root-copy` | 896,156 | 71 keyword hits, **all authored text** — see below |
  | `raw\example_com.md` | 360 | clean |
  | `Syntys_BOQ.xlsx.lockfile` | 165 | clean (incl. UTF-16 decode) |

  **All three** were scanned, for password / passwd / secret / `enable secret` / token / api-key /
  private-key / `BEGIN … PRIVATE KEY` / SNMP community / Cisco type-5 + type-7 / pre-shared / PSK.
  The earlier claim — "a scan of the only candidate file matched nothing" — was wrong twice over:
  only one file had been scanned, and that file *does* match. Every one of its 71 hits is authored
  product text rather than captured state: CIS detector titles ("Local user password storage"),
  remediation prose ("Store local users with `secret` (Type-8/9)"), PPDIOO questionnaire items, and
  the explorer's own JS regex literal; both SNMP hits read `snmp-server community <redacted> RW`,
  i.e. the placeholder, not a community. It is the explorer carrying its built-in DEMO dataset, not
  a rendered client instance — zero data-injection markers (`__SNAPSHOT_JSON__`, data-script tag)
  and zero `AJ*` fleet hostnames. The file says as much itself: "The Python parser already redacted
  every secret value (SNMP communities, password hashes), so nothing sensitive is rendered."
  **Conclusion unchanged — no credential material — but the evidence is now complete.**

  **Final disposal — accounted for, and deliberately not carried as an open item.** "Deleted" here
  means the folder is in the Recycle Bin, not gone: all 896,681 bytes were still readable on
  2026-07-25 under `C:\$Recycle.Bin\<SID>\$RPY5CEQ`, which is exactly how the scan above was run
  (a deleted folder stays enumerable via `Shell.Application` `Namespace(0xA)` — the way to check a
  claim like this instead of trusting the record). Nothing schedules emptying it, and nothing needs
  to: the scan cleared all three files, and the two with content are a regenerable explorer copy
  carrying its DEMO dataset plus a 360-byte example.com stub. This paragraph exists so the bytes
  are *accounted for* rather than merely absent from the Desktop — had the scan found anything,
  this would be an open owner item above instead of a closed note here.

  **But the credentialed backup this folder existed to quarantine was not in it.** The 2026-07-05
  entry in `docs/log.md` ("Security pass") records the `devices.json` fleet credential stripped and
  the "credentialed backup quarantined to `..\Enhancements_attic_2026-07-05\`". The 3 files above
  are that entry's *Hygiene* quarantines instead (the stale explorer copy + the `raw\` egress
  artifact); no `devices.json` backup was in the folder — **confirmed against the recovered bytes,
  not inferred**, since the recursive listing above is the whole folder — and no copy was found
  elsewhere on the Desktop tree. It was removed sometime before the 2026-07-19 check — **by whom
  and to where is recorded nowhere**, so one plaintext copy of the pre-rotation credential for 303
  devices is unaccounted for. That raises the urgency of the rotation below rather than lowering
  it. What IS verified: the live `devices.json` (303 entries) carries no `password` field, so the
  07-05 strip held.

  **On the gate — its rationale is inferred, not recorded.** All that was ever written down is the
  ordering itself, "rotate the credential, then delete that backup" (`docs/log.md`, 2026-07-05).
  The natural reading is the standard one for a file holding a live secret: destroy the copy only
  once the secret it carries is dead. On that reading the gate was scoped to the backup — which was
  already gone before this deletion, so it is moot because the file was missing, not because there
  was nothing sensitive to protect.
- **Confirm the 2026-07-05 credential rotation** actually happened — **STILL OPEN**, and now
  independent of the attic (deleting that folder neither performed the rotation nor recorded it).
  The unaccounted-for backup above is why it still matters. Rotation is an AAA-side action only the
  owner can perform.
- **Python-less-box smoke**: copy `portable\dist\Atlas\` to a stick (`portable/make_stick.ps1`
  does the layout), run `Atlas.exe --selftest` on a machine without Python — expect
  `SELFTEST: PASS`.
- **Enable BitLocker-To-Go on the field stick** (one-time, admin, physical stick —
  `README-FIELD.txt` carries the steps). P3's loss-of-stick mitigation; until done, the stick
  must not carry client evidence off-site.

## Consequences

P1 ("one door, frozen-ready") is unblocked and fully specified: production entry module
(`uvicorn.run(app)`, `freeze_support()`, console build, no reload/workers), `assesshub` console
script serving the built frontend from package data, frozen-aware engine dispatch in
`webapp/backend/ingest.py` (child-process isolation and timeout preserved), ingest-from-folder,
demo seed, and a `--selftest` that fails loud on the silent-degrade assets (explorer template,
OUI/port KBs, docx/pptx). Registered here per the SSOT convention: this ADR owns the P0 decisions;
the atlas cites it.

## P3 addendum (2026-07-21): field discipline shipped; D4's UI fleet-flow DEFERRED

P3 delivered per `docs/atlas-p3-plan-2026-07-21.md`: boot unplug-safety
(`storage.Store(boot_hardening=True)` — `quick_check` refusing corrupt stores non-destructively,
rotating timestamped copies in `data\backups\`, pinned rollback-journal durability, friendly
write-locked-stick refusal in `serve.main`) and the shipped `portable/README-FIELD.txt` covering
the §15 exit-gate scenarios, ratchet-tested (`tests/test_readme_field.py`: ASCII-only, scenario
headings, every named flag exists in a shipped argparse).

Two decisions recorded:

- **D4's "AssessKit one-prompt fleet flow + per-device override editor" UI is deferred** (P4
  candidate with its own security review; nothing shipped in P1–P3 built it). The console chain
  IS the certified field path — D3 chose `console=True` precisely so `getpass` works. A browser
  flow would put SSH credentials on a new webapp secret-handling surface (logging/XSS/CSRF blast
  radius in a just-hardened app) for no field capability the terminal lacks. Revisit trigger:
  the owner asks for browser-driven live collection.
- **Delta vs the §15 sketch**: there is no separate `cisco-assess.exe` on the stick — the
  `--run-engine` sentinel makes `Atlas.exe` itself the CLI door (P1 design, proven in the P2
  smoke and the field redaction commands in README-FIELD.txt).

## P3 amendment (2026-07-22) — redaction is a first-class command; verification states its scope

Two decisions taken while hardening P3, recorded here because the ADR owns them, not the code.

### A · `--redact-folder` rather than shipping a template

P3 shipped a field guide whose redaction command **could not run**: `--redact` goes through the
engine, which hard-requires a `--template` workbook (`COLLECT_PARSE_V3_23_0.py:1719`) and a
`--devices-file` (`:1100`), and the bundle carries neither. Three options were weighed:

1. **ship a template in the bundle** — still leaves `devices.json` missing, and adds a binary
   asset to the manifest for one command;
2. **tell the engineer to bring both** (what the guide said as an interim) — honest, but makes the
   share-safety control depend on preparation done before travelling;
3. **synthesize both, as the ingest channel already does** — chosen.

`Atlas.exe --redact-folder <collection> --out <dir>` reuses `webapp/backend/ingest.py`'s existing
synthesis, so no new asset ships and the capability works with nothing extra on the stick. The
consequence to keep in mind: this is now the *only* supported way to redact from the field, so its
refusals (`--out` inside the bundle or containing the captures) are load-bearing, not cosmetic.

### B · A safety claim must name its own scope

The first version printed *"Every IP/MAC/serial is pseudonymized and this was verified"* while the
check matched private IPv4 in **one artifact**. Independent review proved by fault injection that a
redaction phase can fail silently — the engine's `_run_phase` logs and continues — so the workbook
ships client data while the checked snapshot stays clean. Standing rule for this app:

- verify the artifact that **can** fail, not the most convenient one, and check that the transform
  **ran** (phase ledger + engine log), not only that its output looks clean;
- a success message states what was checked, what was **not**, and what is kept **by design** —
  hostnames and descriptions survive redaction deliberately, and a deliverable full of anonymous
  boxes is unreadable, so the engineer must know the set still identifies the client.

Both edges of the checker are pinned mechanically (`webapp/tests/test_atlas_redaction.py`): no
false positive on real redacted fixtures, and a coverage floor — it has been wrong in *both*
directions, and judgement alone did not hold.
