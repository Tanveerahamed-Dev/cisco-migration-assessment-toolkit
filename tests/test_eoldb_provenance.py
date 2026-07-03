"""Plan-A #19: pin eoldb's evidence discipline as a regression guard.

Every lifecycle row must cite its Cisco bulletin; every still-active row must ABSTAIN on
dates (empty eos/ldos) rather than assert a fake one — the exact 3560-CX / 2960-CX cry-wolf
class the curated table exists to avoid; and the table must carry a machine-readable review
vintage so a stale 'active' claim is auditable, not silently trusted."""
import datetime as _dt

from cisco_toolkit import eoldb


def test_review_vintage_is_a_valid_iso_date():
    _dt.date.fromisoformat(eoldb._EOL_REVIEWED)   # raises ValueError if malformed / absent


def test_every_row_cites_a_source():
    missing = [r.get("pat") for r in eoldb._EOL if not str(r.get("source", "")).strip()]
    assert not missing, f"eoldb rows with no source citation (provenance gap): {missing}"


def test_every_row_has_a_known_confidence():
    bad = [(r.get("pat"), r.get("conf")) for r in eoldb._EOL
           if r.get("conf") not in ("confirmed", "derived", "active")]
    assert not bad, f"eoldb rows with an unrecognised conf tag: {bad}"


def test_active_rows_abstain_on_dates():
    """A conf='active' row (still-supported product) must NOT assert eos/ldos — leaving them
    empty is the coverage-honest abstention that prevents a fake Past-LDoS cry-wolf."""
    offenders = [r.get("pat") for r in eoldb._EOL
                 if r.get("conf") == "active" and (r.get("eos") or r.get("ldos"))]
    assert not offenders, f"active rows must leave eos/ldos empty (no fake date): {offenders}"


def test_active_rows_exist_so_the_guard_is_not_vacuous():
    n = sum(1 for r in eoldb._EOL if r.get("conf") == "active")
    assert n >= 1, "expected at least one active (still-supported) lifecycle row"
