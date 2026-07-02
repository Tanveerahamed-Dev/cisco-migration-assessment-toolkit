"""[Plan A / Tier-1 #3] Sentinel guard for the explorer's Parse Yield card.

snap['parse_yield'] (the zero-parse yield ledger cmdio.parse_yield_report() publishes and the
workbook's Collection Completeness sheet renders as its Parse Yield section) must be surfaced
read-only on the explorer too. Guards the recurring cross-surface drift class: the card function
exists, is back-compat guarded (no key -> no card), is actually MOUNTED in the Health view's
data-quality run (between the collection and capture-integrity cards), and the embedded demo
snapshot carries the ledger with the engine's coverage-honest note VERBATIM -- a wording change
in cmdio.py must turn up here, not drift silently between surfaces.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _html():
    return (ROOT / "cisco_toolkit" / "blast_radius_explorer.html").read_text(encoding="utf-8")


def test_parse_yield_card_wired_and_mounted():
    html = _html()
    assert "function parseYieldCard()" in html, "explorer is missing the Parse Yield card"
    assert "SNAP&&SNAP.parse_yield" in html, "card must be back-compat guarded (no key -> no card)"
    # mounted in the Health render's data-quality run: collection -> parse yield -> capture integrity
    # (what wasn't collected -> what was collected but didn't parse -> whether captures are trustworthy)
    assert re.search(r"\$\{collectionCard\(\)\}\s*\$\{parseYieldCard\(\)\}\s*\$\{captureIntegrityCard\(\)\}",
                     html), "parseYieldCard() must be mounted between collectionCard() and captureIntegrityCard()"


def test_parse_yield_demo_carries_engine_note_verbatim():
    """The demo ledger ships cmdio's own note VERBATIM (never a paraphrase) -- the same
    coverage-honest wording every real snapshot publishes. If cmdio.py rewords the note this
    fails, forcing the demo (and a reviewer's eyes) to move with the engine."""
    from cisco_toolkit import cmdio
    note = cmdio.parse_yield_report()["summary"]["note"]
    assert "never a device" in note          # the contract phrase itself (engine side)
    assert note in _html(), "explorer demo snapshot must carry the engine's coverage-honest note verbatim"


def test_parse_yield_card_never_verdicts_a_device():
    """The card's static wording keeps the collected-but-unparsed framing: a zero-yield row is a
    possible parser format gap, NEVER a device health verdict (the workbook section's wording)."""
    html = _html()
    assert "NEVER a device health verdict" in html
    # the suspect class is named like the workbook's red rows, so the two surfaces read identically
    assert "SUSPECT format gap" in html and "expected-empty" in html
