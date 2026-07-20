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
- **Confirm the 2026-07-05 credential rotation** actually happened, then delete
  `..\Enhancements_attic_2026-07-05\` (verified still present 2026-07-19; `raw\` now holds 1 file /
  ~1 KB). Rotation is an AAA-side action only the owner can perform.
- **Python-less-box smoke**: copy `portable\dist\Atlas\` to a stick (`portable/make_stick.ps1`
  does the layout), run `Atlas.exe --selftest` on a machine without Python — expect 8/8.

## Consequences

P1 ("one door, frozen-ready") is unblocked and fully specified: production entry module
(`uvicorn.run(app)`, `freeze_support()`, console build, no reload/workers), `assesshub` console
script serving the built frontend from package data, frozen-aware engine dispatch in
`webapp/backend/ingest.py` (child-process isolation and timeout preserved), ingest-from-folder,
demo seed, and a `--selftest` that fails loud on the silent-degrade assets (explorer template,
OUI/port KBs, docx/pptx). Registered here per the SSOT convention: this ADR owns the P0 decisions;
the atlas cites it.
