"""README-FIELD.txt — the stick's one-page field guide (ADR-0004 P3) — content ratchets.

The Project Atlas §15 exit gate, mechanized: the guide must keep covering the field scenarios,
stay ASCII-only (the make_stick.ps1 cp1252 lesson — this file gets opened in Notepad on arbitrary
Windows boxes), and never name a CLI flag the shipped argparse surfaces don't actually have
(the doc-rot class where a README teaches commands that no longer exist)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "portable" / "README-FIELD.txt"

_ADD_ARG = re.compile(r"""add_argument\(\s*['"](--[a-z][a-z0-9-]*)""")
_FLAG = re.compile(r"--[a-z][a-z0-9-]*")
_ATLAS = re.compile(r"Atlas\.exe\b.*")


def _atlas_commands():
    """(lineno, command-text, flags) for every `Atlas.exe …` invocation the guide shows —
    wherever on the line it sits.

    NON-VACUITY (mutation-proved 2026-07-28). The per-surface checks below used to anchor on
    ``line.strip().startswith("Atlas.exe ")``. The guide writes two of its five commands
    mid-sentence ("2. Run:  Atlas.exe --selftest", "Afterwards run  Atlas.exe --selftest
    once."), so those were invisible — and because the guide shows no ``--run-engine`` command
    at all, ``test_every_engine_command_uses_only_engine_flags`` iterated ZERO lines: no change
    to the guide or to the engine's argparse surface could make it fail. Rewriting a guide line
    to hand the server-only ``--redact-folder`` to ``--run-engine`` — verbatim the failure that
    test's docstring claims to catch — left all eleven tests in this file GREEN."""
    out = []
    for n, line in enumerate(GUIDE.read_text(encoding="ascii").splitlines(), 1):
        m = _ATLAS.search(line)
        if not m:
            continue
        cmd = m.group(0).strip()
        flags = set(_FLAG.findall(cmd))
        if flags:                       # a bare "Double-click Atlas.exe" names no surface
            out.append((n, cmd, flags))
    return out


def test_the_command_scan_sees_every_invocation_the_guide_shows():
    """Guard the guard: the two per-surface checks are LOOPS, and an empty loop passes both
    while proving nothing. Reconcile the scanner against a raw text sweep so an anchoring bug
    can never quietly make them inert again."""
    lines = GUIDE.read_text(encoding="ascii").splitlines()
    raw = {n for n, line in enumerate(lines, 1)
           if "Atlas.exe" in line and _FLAG.search(line[line.index("Atlas.exe"):])}
    found = {n for n, _c, _f in _atlas_commands()}
    assert found == raw, (
        f"the Atlas.exe command scan misses invocations the guide shows on line(s) "
        f"{sorted(raw - found)} — the per-surface checks below would skip them silently")
    assert len(found) >= 5, (
        f"only {len(found)} Atlas.exe command(s) found; the guide documents the selftest, the "
        f"redaction run and the two manifest-verification forms. If it really lost them, the "
        f"per-surface reconciliation below has nothing left to check.")


def test_every_atlas_command_is_routed_to_exactly_one_surface():
    """The engine-surface check has no live subject today (the guide shows no `--run-engine`
    command), so on its own it is inert. This makes the inertness SAFE rather than silent:
    every command the guide shows is accounted for by one of the two surface checks, so a new
    engine command cannot appear unreconciled."""
    cmds = _atlas_commands()
    engine = [c for c in cmds if "--run-engine" in c[2]]
    app = [c for c in cmds if "--run-engine" not in c[2]]
    assert len(engine) + len(app) == len(cmds) and cmds


def test_field_guide_is_ascii_only():
    """PS 5.1 / cp1252 consoles and bare Notepad must render it verbatim — no smart quotes,
    no em-dashes, no box drawing (the class that TERMINATED strings in make_stick.ps1)."""
    raw = GUIDE.read_bytes()
    assert all(b <= 0x7F for b in raw), "README-FIELD.txt must stay pure ASCII"


def test_field_guide_covers_the_exit_gate_scenarios():
    """Artifact §15 'done when': loss-of-stick, read-only, corruption, redaction and update —
    plus the two standing disciplines (eject, credentials)."""
    text = GUIDE.read_text(encoding="ascii")
    for heading in ("LOSS OF STICK", "READ-ONLY STICK", "CORRUPTION", "REDACTION", "UPDATE",
                    "EJECT DISCIPLINE", "CREDENTIALS"):
        assert heading in text, f"field guide lost its '{heading}' section"
    assert "BitLocker" in text and "data\\backups\\" in text and "SELFTEST: PASS" in text


def test_every_quoted_app_message_is_really_printed():
    """The guide quotes what the engineer sees on screen at the moment things go wrong. Two of
    these had drifted from the code (an em-dash vs a hyphen, and a message printed nowhere) —
    a quoted string that does not match is worse than none, because it reads as 'not my case'."""
    sources = "\n".join((ROOT / p).read_text(encoding="utf-8", errors="replace") for p in (
        "webapp/backend/serve.py", "webapp/backend/storage.py", "portable/make_stick.ps1",
        "COLLECT_PARSE_V3_23_0.py", "webapp/backend/ingest.py"))

    def emitted(phrase: str) -> bool:
        # Messages are f-string-composed across files ("refusing to start - " in serve.py,
        # "integrity check failed" in storage.py), so a whole-phrase match is too strict —
        # every segment either side of a dynamic join must appear.
        if phrase in sources:
            return True
        parts = [p.strip() for p in re.split(r" - |: ", phrase) if p.strip()]
        return len(parts) > 1 and all(p in sources for p in parts)

    # Only phrases the guide CLAIMS the app emits — not Windows UI labels the engineer clicks.
    claims = re.compile(r"\b(prints?|reports?|say\w*|stops with|fail\w* with)\b", re.I)
    missing = []
    for line in GUIDE.read_text(encoding="ascii").splitlines():
        if not claims.search(line):   # same line only: a claim must not capture its neighbour's
            continue                  # quotes (that swept in Windows UI labels like Eject)
        for q in re.findall(r'"([^"\n]{4,})"', line):
            if not emitted(q):
                missing.append(q)
    assert not missing, f"guide quotes messages the code never prints: {missing}"


def test_every_engine_command_uses_only_engine_flags():
    """Per-SURFACE check. The union test below proves a flag exists *somewhere*; it would pass a
    line that hands a server-only flag to the engine (or drops the --run-engine sentinel), which
    fails at runtime. Each `Atlas.exe --run-engine …` command must be all-engine flags."""
    engine_flags = set(_ADD_ARG.findall(
        (ROOT / "COLLECT_PARSE_V3_23_0.py").read_text(encoding="utf-8", errors="replace")))
    for n, cmd, used in _atlas_commands():
        if "--run-engine" not in used:
            continue
        unknown = used - {"--run-engine"} - engine_flags
        assert not unknown, \
            f"line {n}: engine command names non-engine flags {sorted(unknown)}: {cmd}"


def test_every_app_command_uses_only_app_flags():
    """The mirror of the engine check: an `Atlas.exe …` command WITHOUT the --run-engine sentinel
    is the app's own surface, so an engine-only flag there dies at argparse. Without this, only
    one direction of the two-surface confusion was guarded."""
    app_flags = set(_ADD_ARG.findall(
        (ROOT / "webapp" / "backend" / "serve.py").read_text(encoding="utf-8")))
    checked = 0
    for n, cmd, used in _atlas_commands():
        if "--run-engine" in used:
            continue
        checked += 1
        unknown = used - app_flags
        assert not unknown, f"line {n}: app command names non-app flags {sorted(unknown)}: {cmd}"
    assert checked, "no app-surface command was checked — this loop went inert"


def test_commands_are_copy_pasteable_on_one_line():
    """A command wrapped across indented continuation lines pastes into cmd.exe as several
    commands, the trailing ones garbage."""
    lines = GUIDE.read_text(encoding="ascii").splitlines()
    for n, cmd, _flags in _atlas_commands():
        if n < len(lines):
            nxt = lines[n]              # `n` is 1-based, so lines[n] is the NEXT line
            assert not (nxt.startswith("            ") and nxt.strip().startswith("--")), \
                f"command continues onto line {n + 1} — join it: {cmd[:60]}"


def test_every_flag_the_guide_names_exists_in_a_shipped_argparse():
    serve_src = (ROOT / "webapp" / "backend" / "serve.py").read_text(encoding="utf-8")
    engine_src = (ROOT / "COLLECT_PARSE_V3_23_0.py").read_text(encoding="utf-8")
    valid = set(_ADD_ARG.findall(serve_src)) | set(_ADD_ARG.findall(engine_src))
    sentinel = re.search(r'ENGINE_SENTINEL\s*=\s*"(--[a-z-]+)"', serve_src)
    assert sentinel, "serve.ENGINE_SENTINEL moved — update this reconciler"
    valid.add(sentinel.group(1))  # checked pre-argparse by design
    named = set(_FLAG.findall(GUIDE.read_text(encoding="ascii")))
    unknown = named - valid
    assert not unknown, f"field guide names flags no shipped surface has: {sorted(unknown)}"


def test_field_guide_artifact_denominators_match_the_canonical_registry():
    """The static field guide must not become a second, drifting artifact catalogue."""
    from cisco_toolkit.docmeta import ARTIFACT_SPECS, CLI_ARTIFACT_SUFFIX, WEB_ONLY_KINDS, artifact_spec

    number_words = {
        0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
        6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    }
    cli_specs = [spec for spec in ARTIFACT_SPECS if spec.key in CLI_ARTIFACT_SUFFIX]
    cli_docx = [spec for spec in cli_specs if spec.ext == "docx"]
    guide = " ".join(GUIDE.read_text(encoding="ascii").lower().split())

    assert cli_specs and len(cli_specs) in number_words
    assert f"this command produces {number_words[len(cli_specs)]} items" in guide
    assert f"{number_words[len(cli_docx)]} word documents" in guide
    assert WEB_ONLY_KINDS == {"cutover", "nrfu"}
    assert "cutover plan" in guide and "nrfu / acceptance test plan" in guide

    pir = artifact_spec("pir")
    assert pir.conditional and pir.cli_suffix is None
    assert "post-implementation review (pir) is conditional post-execution" in guide
    assert "not a cli artifact" in guide


# ── the field guide's claim about the DRAFT stamp must stay TRUE ────────────────

#: Writers whose output opens with a Document Control table (docmeta.add_document_control), and
#: writers that produce a deliverable with NO such marking. README-FIELD tells the engineer which
#: is which, so drift in EITHER direction makes the field guide lie.
_STAMPED = ("design", "mop", "crd", "engagement", "archreview", "ops", "runbook")
_UNSTAMPED = ("excel", "html", "deck")


def test_field_guide_draft_stamp_claim_matches_the_writers():
    """README-FIELD says the seven Word documents carry a draft Status row and that the workbook,
    explorer and deck do NOT — the deck being the one most likely shown to a client.

    That paragraph replaced an earlier one claiming EVERY document was stamped, which was false in
    exactly the direction that matters. Source-level, so it fails when a writer is added or when
    one of the three unstamped renderers quietly gains (or the seven quietly lose) the table."""
    # Match the CALL, not the name: every stamped writer also NAMES add_document_control on its
    # `from cisco_toolkit.docmeta import ...` line, so a substring scan passed even with the call
    # deleted. Verified by gutting ops.py's call while keeping the import — this file stayed green.
    _CALL = re.compile(r"(?<!import )\badd_document_control\s*\(")
    src = {m: (ROOT / "cisco_toolkit" / f"{m}.py").read_text(encoding="utf-8", errors="ignore")
           for m in _STAMPED + _UNSTAMPED}
    missing = [m for m in _STAMPED if not _CALL.search(src[m])]
    unexpected = [m for m in _UNSTAMPED if _CALL.search(src[m])]

    # ...and the claim side. The first version of this test never opened the guide at all: the
    # whole paragraph could be deleted, or rewritten to "every document is stamped", and it passed
    # while its own docstring claimed "drift in EITHER direction makes the field guide lie".
    # Whitespace-NORMALISED: the guide is hard-wrapped to ~70 columns, so any phrase long enough to
    # be worth pinning will straddle a line break sooner or later. Asserting the raw text made this
    # check depend on where the wrap happened to fall — re-flowing the paragraph (not changing a
    # word of its meaning) turned it red.
    guide = " ".join(GUIDE.read_text(encoding="ascii").split())
    assert "seven Word documents" in guide, \
        "the guide no longer states the count this test pins (or changed its wording)"
    assert "carry NO such marking" in guide, (
        "the guide must keep naming the artifacts that are NOT stamped — the deck is the one most "
        "likely shown to a client, and an earlier version of this paragraph claimed EVERY document "
        "was stamped, which was false in exactly that direction")
    assert not missing, (
        f"README-FIELD promises a Document Control status row these writers no longer emit: "
        f"{missing}. Fix the writer or the guide — an engineer is told to take it literally.")
    assert not unexpected, (
        f"README-FIELD tells the engineer {unexpected} carry NO draft marking, but they now do. "
        f"Update the guide: under-claiming teaches them to distrust it.")
    assert len(_STAMPED) == 7, "the guide says 'seven Word documents' — keep the count in step"


def test_the_draft_status_row_really_reaches_a_rendered_document(tmp_path):
    """Non-vacuity for the test above: prove the row is in the FILE, not just the source. The
    guide's whole point is that the engineer can open the document and see it."""
    pytest.importorskip("docx")
    import docx

    from cisco_toolkit import design

    out = tmp_path / "d.docx"
    design.write_design_doc_docx(str(out), {"devices": {"SW1": {"model": "C9300"}}}, "Meridian")
    text = "\n".join(c.text for t in docx.Document(str(out)).tables
                     for r in t.rows for c in r.cells)
    assert "Status" in text, "the Document Control table lost its Status row"
    assert "DRAFT" in text and "not yet reviewed" in text, (
        f"the rendered document no longer says it is an unreviewed draft, which is what "
        f"README-FIELD tells the engineer to rely on. Table text:\n{text[:600]}")


def test_the_guide_does_not_promise_the_whole_folder_is_safe():
    """The short-set paragraph is where an UNCONDITIONAL safety promise does the most damage.

    A run whose redaction check fails leaves DO-NOT-SEND-NOT-REDACTED.txt and its unredacted
    documents in the folder (nothing is deleted, by design). Re-rendering into that folder with
    --reuse-out and losing one writer leaves that earlier run's UNREDACTED file under the canonical
    name, reported only as STALE. The guide used to tell the engineer, flatly, that a short set is
    "safe to share" — and this file is the only documentation they have on site, so it is the last
    place that claim can go unqualified. Scope it to what the run wrote, and name the exception."""
    text = GUIDE.read_text(encoding="ascii")
    # Matched on WHITESPACE-NORMALISED text, never line by line. This guide is hard-wrapped at ~70
    # columns, so any phrase long enough to be worth asserting will eventually straddle a newline —
    # and for a NEGATIVE assertion that is the silent direction: the banned sentence comes back,
    # wraps one word earlier, and the guard passes having checked nothing. (Verified: the phrase
    # below sits on one line in the version this test was written against, and stops matching if
    # that sentence re-wraps by a single word.)
    flat = " ".join(text.split()).lower()
    assert "what is in the folder is redacted and safe" not in flat, (
        "README-FIELD claims the whole --out folder is safe; scope it to what THIS RUN wrote "
        "(a document left by an earlier uncertified run can still be sitting in it)")
    assert "DO-NOT-SEND-NOT-REDACTED.txt" in text, (
        "the guide must name the marker it tells the engineer to look for")
    assert "unredacted" in flat, (
        "the guide must say the STALE case can be UNREDACTED, not only that it may name "
        "another client")


def test_the_guide_does_not_promise_total_redaction_verification():
    """The REDACTION section's opening paragraph is where the engineer forms their mental model,
    BEFORE they run anything — so an over-broad verification claim there outranks the accurate
    paragraph fifteen lines further down.

    It used to read "if anything is still unredacted it FAILS and says so rather than handing you a
    file that looks safe". The code checks exactly two things (serve.run_redaction, and it prints
    them): that the engine's redaction phases RAN, and that no private RFC 1918 address survives in
    the SNAPSHOT. MACs, serials, public/IPv6 addresses and the workbook's own cells are not
    inspected, and hostnames are kept BY DESIGN. serve.py already carries this lesson in a comment
    ("certified roughly three times what the code inspects") — it had been applied to the console
    output but not to the one document the engineer has on site.

    Whitespace-NORMALISED, per this file's own hard-wrap lesson: a negative assertion on raw text
    silently stops matching when the banned sentence comes back wrapped one word differently."""
    flat = " ".join(GUIDE.read_text(encoding="ascii").split()).lower()
    assert "still unredacted it fails" not in flat, (
        "README-FIELD claims the redaction check catches anything unredacted. It checks two things: "
        "that the engine's redaction phases ran, and that no private address survives in the "
        "snapshot. Scope the claim or the engineer sends a set believing it was fully verified.")
    assert "narrower" in flat, (
        "the guide must say up front that the verification is narrower than it sounds - that "
        "sentence is what sends the engineer to the WHAT REDACTION DOES NOT REMOVE section")
    # ...and the section it points at must still carry the two facts that make it worth reading.
    assert "kept on purpose" in flat, "the guide lost the hostnames-are-kept disclosure"
    assert "does not certify every field of every file" in flat, (
        "the guide lost the scope of what Atlas actually verifies")
