"""Reconcile guard for the brand-token SSOT (design/brand-tokens-prototype).

The brand navy was previously hardcoded independently across the deck, the
workbook, and the 7 DOCX generators + docmeta._kv (drift-by-copy — three
different blues). This guard asserts every navy is now defined ONCE in
cisco_toolkit.brand_tokens and that no generator re-hardcodes a raw literal —
the brand-color analogue of the Deliverable-Excellence ratchet
(tests/test_deliverable_excellence.py).

The three surface aliases are unified onto the canonical BRAND_NAVY (#1F3864);
changing the brand navy is now a one-line edit in brand_tokens.py.
"""
import glob
import os
import re

from cisco_toolkit import brand_tokens

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# raw brand-navy literals that must no longer appear outside brand_tokens.py
_STRAY = {
    "document navy RGBColor(0x1F,0x38,0x64)": re.compile(r"RGBColor\(\s*0x1F\s*,\s*0x38\s*,\s*0x64\s*\)"),
    'document navy "1F3864"': re.compile(r"""["']1F3864["']"""),
    "deck navy (0x1E,0x27,0x61)": re.compile(r"\(\s*0x1E\s*,\s*0x27\s*,\s*0x61\s*\)"),
    'workbook navy "1F497D"': re.compile(r"""["']1F497D["']"""),
}


def test_navies_unified_onto_canonical():
    """All three surface navies now resolve to the one canonical brand navy."""
    assert brand_tokens.BRAND_NAVY_RGB == (0x1F, 0x38, 0x64)
    assert brand_tokens.BRAND_NAVY_HEX == "1F3864"
    assert brand_tokens.DOC_NAVY_RGB == brand_tokens.BRAND_NAVY_RGB
    assert brand_tokens.DECK_NAVY_RGB == brand_tokens.BRAND_NAVY_RGB
    assert brand_tokens.WORKBOOK_NAVY_HEX == brand_tokens.BRAND_NAVY_HEX


def test_no_stray_brand_navy_literal_in_cisco_toolkit():
    """No cisco_toolkit source (except brand_tokens itself) may hardcode a brand
    navy; each call site must source it from brand_tokens."""
    failures = {}
    for f in glob.glob(os.path.join(ROOT, "cisco_toolkit", "*.py")):
        if os.path.basename(f) == "brand_tokens.py":
            continue
        with open(f, encoding="utf-8") as fh:
            src = fh.read()
        for label, pat in _STRAY.items():
            if pat.search(src):
                failures.setdefault(os.path.basename(f), []).append(label)
    assert not failures, (
        "stray hardcoded brand navy — import it from brand_tokens instead: "
        + "; ".join(f"{k}: {sorted(v)}" for k, v in sorted(failures.items()))
    )
