"""Regression gate for the directly-opened explorer's Content-Security-Policy (Plan-A #9 / Tier-1 #4
completion). The template already ships a strict, no-egress CSP (default-src 'none'; inline style/script
only; connect-src 'none'); this pins it so a future edit can't silently weaken or drop it — on BOTH the
template and the snapshot-embedded HTML that write_html_explorer emits.

Deliberately does NOT require `frame-ancestors` — the AssessHub webapp iframes the explorer (sandboxed),
so locking frame-ancestors would break that embed. `default-src 'none'` already covers frame-src.
"""
import json
import os
import re
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "cisco_toolkit", "blast_radius_explorer.html")


def _csp(html):
    m = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', html)
    return m.group(1) if m else None


def _directives(csp):
    return {d.strip().split(" ", 1)[0]: d.strip() for d in csp.split(";") if d.strip()}


def _assert_strict(csp, where):
    """The strictness contract itself, applied to WHICHEVER artifact is under test."""
    assert csp, f"{where} must carry a Content-Security-Policy meta tag"
    d = _directives(csp)
    assert d.get("default-src") == "default-src 'none'", where     # deny by default
    assert "'none'" in d.get("connect-src", ""), where             # no egress — the air-gapped doctrine
    assert "'none'" in d.get("object-src", ""), where              # no plugins
    assert "'none'" in d.get("base-uri", ""), where                # no <base> hijack
    assert "http:" not in csp and "https:" not in csp, where       # no external origin is ever allowed


def test_explorer_template_has_strict_no_egress_csp():
    _assert_strict(_csp(open(TEMPLATE, encoding="utf-8").read()), "explorer template")


def test_embedded_explorer_preserves_csp():
    """write_html_explorer injects the live snapshot but must NOT strip *or weaken* the head CSP.

    NON-VACUITY (mutation-proved, 2026-07-28): this used to assert only that _csp() returned
    something truthy. A one-line `html.replace("default-src 'none'", "default-src * https:")`
    inside write_html_explorer — which turns the emitted, client-shipped deliverable into a
    fully egress-capable page — left this test GREEN, and no other test in the repo mentions
    Content-Security-Policy. Presence is not the property; STRICTNESS is, and it must be
    asserted on the emitted file, because that is the artifact an engineer opens and sends.
    Equality with the template is the stronger form: it also catches a directive being
    reordered/dropped that the per-directive checks do not name."""
    from cisco_toolkit.html import write_html_explorer
    snap = json.load(open(os.path.join(HERE, "golden", "snapshot.json"), encoding="utf-8"))
    template_csp = _csp(open(TEMPLATE, encoding="utf-8").read())
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "explorer.html")
        write_html_explorer(out, snap, "CSP regression test")
        emitted = _csp(open(out, encoding="utf-8").read())
        _assert_strict(emitted, "emitted explorer")
        assert emitted == template_csp, (
            "the emitted explorer's CSP no longer matches the template's — the snapshot "
            f"injection rewrote it.\n  template: {template_csp}\n  emitted:  {emitted}")
