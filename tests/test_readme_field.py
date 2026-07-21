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
