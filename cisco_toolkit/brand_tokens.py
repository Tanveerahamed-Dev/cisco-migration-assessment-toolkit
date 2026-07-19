"""Brand tokens — the single source of truth for cisco-toolkit / AssessHub brand
color (and, incrementally, typography).

Values are extracted **appearance-preserving** from literals previously
duplicated across the deliverable generators; every generated surface now reads
ONE definition. This module has **no docx / openpyxl dependency**: colors are
exposed as RGB int-tuples and hex strings, and each generator builds its own
``RGBColor(...)`` / ``Font(...)`` / fill from them (matching how those files
already import the libraries locally).

Registered in ``docs/ssot.md``; guarded by
``tests/test_brand_tokens_reconcile.py`` — the brand-color analogue of the
Deliverable-Excellence ratchet PR #289 established for the DOCX furniture.

CANONICAL BRAND NAVY = ``#1F3864`` (decided 2026-07-04: the plurality — the whole
DOCX document family already used it — and a clean, professional navy). The deck
(formerly ``#1E2761``) and the workbook (formerly ``#1F497D``) are unified onto
it here — the single brand blue the SSOT thesis calls for. To re-brand, edit
``BRAND_NAVY_RGB`` ONCE below, not the (formerly ~13) call sites.
"""


def hex_of(rgb):
    """``(r, g, b)`` 0-255 ints -> ``'RRGGBB'`` uppercase hex (openpyxl / CSS form)."""
    return "%02X%02X%02X" % rgb


# --- Application identity (ADR-0004 D1: the ONE brand constant — a rename is an edit here) ---
APP_NAME = "Atlas"
APP_BYLINE = "by Tanveer Ahamed"
APP_TITLE = f"{APP_NAME} — {APP_BYLINE}"

# --- THE canonical brand navy (one lever; edit here to re-brand) ---
BRAND_NAVY_RGB = (0x1F, 0x38, 0x64)       # #1F3864
BRAND_NAVY_HEX = hex_of(BRAND_NAVY_RGB)   # "1F3864"

# Per-surface aliases — all unified onto the canonical navy (2026-07-04).
DOC_NAVY_RGB = BRAND_NAVY_RGB             # 7 DOCX generators + docmeta._kv
DECK_NAVY_RGB = BRAND_NAVY_RGB            # executive deck (deck.py; was #1E2761)
WORKBOOK_NAVY_HEX = BRAND_NAVY_HEX        # Excel / diff workbooks (was #1F497D)

DOC_NAVY_HEX = BRAND_NAVY_HEX             # "1F3864"
DECK_NAVY_HEX = BRAND_NAVY_HEX
