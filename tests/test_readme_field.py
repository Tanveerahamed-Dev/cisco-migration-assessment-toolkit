"""README-FIELD.txt — the stick's one-page field guide (ADR-0004 P3) — content ratchets.

The Project Atlas §15 exit gate, mechanized: the guide must keep covering the field scenarios,
stay ASCII-only (the make_stick.ps1 cp1252 lesson — this file gets opened in Notepad on arbitrary
Windows boxes), and never name a CLI flag the shipped argparse surfaces don't actually have
(the doc-rot class where a README teaches commands that no longer exist)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "portable" / "README-FIELD.txt"

_ADD_ARG = re.compile(r"""add_argument\(\s*['"](--[a-z][a-z0-9-]*)""")
_FLAG = re.compile(r"--[a-z][a-z0-9-]*")


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
        "COLLECT_PARSE_V3_23_0.py"))

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
    fails at runtime. Each `Atlas.exe --run-engine …` line must be all-engine flags."""
    engine_flags = set(_ADD_ARG.findall(
        (ROOT / "COLLECT_PARSE_V3_23_0.py").read_text(encoding="utf-8", errors="replace")))
    for line in GUIDE.read_text(encoding="ascii").splitlines():
        s = line.strip()
        if not s.startswith("Atlas.exe --run-engine"):
            continue
        used = set(_FLAG.findall(s)) - {"--run-engine"}
        unknown = used - engine_flags
        assert not unknown, f"engine command names non-engine flags {sorted(unknown)}: {s}"


def test_every_app_command_uses_only_app_flags():
    """The mirror of the engine check: an `Atlas.exe …` line WITHOUT the --run-engine sentinel is
    the app's own surface, so an engine-only flag there dies at argparse. Without this, only one
    direction of the two-surface confusion was guarded."""
    app_flags = set(_ADD_ARG.findall(
        (ROOT / "webapp" / "backend" / "serve.py").read_text(encoding="utf-8")))
    for line in GUIDE.read_text(encoding="ascii").splitlines():
        s = line.strip()
        if not s.startswith("Atlas.exe ") or "--run-engine" in s:
            continue
        unknown = set(_FLAG.findall(s)) - app_flags
        assert not unknown, f"app command names non-app flags {sorted(unknown)}: {s}"


def test_commands_are_copy_pasteable_on_one_line():
    """A command wrapped across indented continuation lines pastes into cmd.exe as several
    commands, the trailing ones garbage."""
    lines = GUIDE.read_text(encoding="ascii").splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("Atlas.exe ") and i + 1 < len(lines):
            nxt = lines[i + 1]
            assert not (nxt.startswith("            ") and nxt.strip().startswith("--")), \
                f"command continues onto line {i + 2} — join it: {line.strip()[:60]}"


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
