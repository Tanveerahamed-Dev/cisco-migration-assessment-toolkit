"""[W-FIB] SSOT drift guard for the explorer's embedded FIB tracer.

The explorer (cisco_toolkit/blast_radius_explorer.html) embeds a byte-identical JS port of fib.trace_fib_path so the
flow simulator can render the computed multi-hop RIB->FIB path. This guards the recurring cross-surface drift class:
every coverage-honest status string the Python tracer can emit MUST exist in the JS port, and the computed-path rung
MUST stay wired -- so a future Python status addition (or an accidental deletion) is caught at build time, not in a
client deliverable. Byte-identity itself is proven by the node cross-check harness (622 pairs); this is the cheap,
always-on, no-node guard that lives in the suite.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _block():
    expl = (ROOT / "cisco_toolkit" / "blast_radius_explorer.html").read_text(encoding="utf-8")
    m = re.search(r"FIB-TRACER-PORT START.*?FIB-TRACER-PORT END", expl, re.S)
    assert m, "explorer is missing the embedded FIB tracer port block"
    return expl, m.group(0)


def test_explorer_fib_port_mirrors_python_status_vocabulary():
    """Every status string fib.py can emit is present in the embedded JS port (no coverage-honesty drift)."""
    fib_src = (ROOT / "cisco_toolkit" / "fib.py").read_text(encoding="utf-8")
    expl, block = _block()
    statuses = set(re.findall(r'"(computed:[a-z_]+|lower_bound:[a-z_]+)"', fib_src))
    assert len(statuses) >= 10, f"expected the full status vocabulary in fib.py, found {sorted(statuses)}"
    missing = sorted(s for s in statuses if s not in block)
    assert not missing, f"explorer FIB port is STALE vs fib.py -- missing status string(s): {missing}"


def test_explorer_fib_rung_and_multihop_primitive_are_wired():
    """The computed-path flow-sim rung + the next-hop-owner resolver (the multi-hop primitive the explorer
    previously lacked) must stay present -- the whole point of the port."""
    expl, block = _block()
    assert "Network · computed path" in expl, "the computed-path flow-sim rung is not wired into buildFlowJourney"
    for fn in ("traceFibPath", "_fibTrace", "_fibHostsOwningIp", "_fibConnectedIndex", "_fibAdminDistance"):
        assert fn in block, f"embedded FIB port is missing {fn}"
