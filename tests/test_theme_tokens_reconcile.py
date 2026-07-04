"""Reconcile guard: the webapp theme.css must not drift from the explorer's tokens.

`webapp/frontend/src/theme.css` declares itself "mirrored verbatim from
cisco_toolkit/blast_radius_explorer.html" (theme.css line 1). That makes the
explorer's `:root` the OWNER of the digital design-token palette and theme.css a
*guarded cache* (per the docs/ssot.md doctrine: a copy must cite its owner and be
reconcile-guarded). This test fails CI if any custom property the two files BOTH
declare diverges in value — so the two surfaces can never silently drift apart.

This is the digital-palette analogue of tests/test_brand_tokens_reconcile.py
(which guards the print-deliverable navy). It passes today because the palettes
are already consistent; its job is to keep them that way.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPLORER = os.path.join(ROOT, "cisco_toolkit", "blast_radius_explorer.html")
THEME = os.path.join(ROOT, "webapp", "frontend", "src", "theme.css")

# a CSS custom-property declaration:  --name: value ;
_DECL = re.compile(r"--([a-z0-9-]+)\s*:\s*([^;{}]+);", re.I)


def _tokens(path):
    """name -> whitespace-normalised value for the FIRST declaration of each token
    (both files declare the dark/default palette first, so this compares like with like)."""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    out = {}
    for name, val in _DECL.findall(src):
        out.setdefault(name.lower(), re.sub(r"\s+", "", val))
    return out


def test_theme_css_does_not_drift_from_explorer():
    explorer = _tokens(EXPLORER)
    theme = _tokens(THEME)
    shared = sorted(set(explorer) & set(theme))
    # non-vacuous: the two really do share a substantial palette
    assert len(shared) >= 15, f"expected a substantial shared token palette; got {len(shared)}: {shared}"
    drift = {n: {"explorer": explorer[n], "theme.css": theme[n]} for n in shared if explorer[n] != theme[n]}
    assert not drift, (
        "theme.css has DRIFTED from the explorer (the token owner). Reconcile the "
        f"values below (explorer is the source of truth):\n{drift}"
    )
