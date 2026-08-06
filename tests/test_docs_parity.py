"""Docs-parity gate (Plan A / Tier-2 #10) — the product surface must describe the
actual product.

The class this pins: the README froze at "eight analysis modes / Cisco-only", then one
later summary reached fourteen while the detailed section remained at eleven —
adoption-facing text drifting from shipped reality. Counts and mode names are DERIVED
from the explorer's MODES registry, so a future mode addition fails this test until every
product-facing roster catches up."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _registry_modes():
    expl = (ROOT / "cisco_toolkit" / "blast_radius_explorer.html").read_text(encoding="utf-8")
    block = re.search(r"MODES-REGISTRY START.*?const MODES\s*=\s*\[(.*?)\n\];", expl, re.S).group(1)
    keys = re.findall(r'\bkey:"([a-z0-9_]+)"', block)
    btns = re.findall(r'\bbtn:"([^"]+)"', block)
    return keys, btns


def _readme_explorer_section():
    match = re.search(
        r"^\*\*Explorer — (?P<count>\d+) modes over one topology\.\*\*.*?"
        r"(?=^The explorer is a single self-contained file)",
        README,
        re.M | re.S,
    )
    assert match, "README lost its detailed 'Explorer — N modes' section"
    return int(match.group("count")), match.group(0)


def test_readme_mode_count_matches_the_registry():
    keys, _ = _registry_modes()
    assert f"{len(keys)} analysis modes" in README, \
        f"README must state the real mode count ({len(keys)}) — derived from the MODES registry"
    assert "eight analysis modes" not in README, "the stale 'eight analysis modes' claim returned"


def test_readme_explorer_row_names_every_mode():
    """The artifact-table row (a Markdown '|' row, not the intro bullet) must name every
    mode the registry carries — the exact row that had frozen at eight names."""
    _, btns = _registry_modes()
    rows = [ln for ln in README.splitlines()
            if ln.lstrip().startswith("|") and "blast_radius_explorer.html" in ln]
    assert rows, "README lost the explorer artifact-table row"
    assert any(all(b in row for b in btns) for row in rows), \
        f"no README explorer row names every mode; wanted all of {btns}"


def test_readme_detailed_explorer_section_matches_the_registry():
    """The narrative roster is a second product-facing contract, independent of the
    compact artifact-table row. Pin its count, names, and order to the live registry so
    a correct claim elsewhere cannot mask this section drifting."""
    keys, btns = _registry_modes()
    count, section = _readme_explorer_section()
    listed = re.findall(r"^- \*\*([^*]+)\*\*", section, re.M)
    assert count == len(keys), (
        f"README detailed explorer count is {count}; registry carries {len(keys)} modes"
    )
    assert listed == btns, (
        "README detailed explorer roster/order is stale: "
        f"listed {listed}, registry carries {btns}"
    )


def test_readme_declares_the_multivendor_surface():
    for vendor in ("Arista", "Juniper", "FortiGate", "AWS", "ACI", "SD-WAN"):
        assert vendor in README, f"README must name the {vendor} ingestion surface"


def test_product_files_exist():
    assert (ROOT / "LICENSE").is_file(), "LICENSE is missing (all-rights-reserved must be formal)"
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "All rights reserved" in lic
    assert (ROOT / "CHANGELOG.md").is_file(), "CHANGELOG.md is missing"
    ch = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Unreleased" in ch
    # The shipped version must APPEAR in the changelog. The previous form asserted a hardcoded
    # "v3.23.176" — eight minor versions behind by the time this was caught, and permanently true
    # because CHANGELOG.md is append-only. That is an environment constant, not a property of the
    # release: every version from 3.24 to 3.31 could have gone unlogged with the test green. Derive
    # the expectation from pyproject, the way this file's sibling checks derive theirs from the
    # explorer MODES registry.
    version = re.search(r'^version\s*=\s*"([^"]+)"',
                        (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
                        re.M).group(1)
    assert version in ch, (
        f"pyproject version {version} has no entry in CHANGELOG.md — the changelog is stale "
        f"against the shipped release (this is what the old hardcoded-version assertion could "
        f"never detect)")
