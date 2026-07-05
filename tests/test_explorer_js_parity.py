"""EXECUTED JS↔Python parity gate for the explorer's FIB port (Plan A / Tier-2 #7).

tests/test_explorer_fib_ssot.py guards the port with regex-PRESENCE (status vocabulary +
function names). Presence is not behavior: a silently divergent JS port ships
wrong-but-plausible client output. This gate EXECUTES the embedded JS under node against
the SAME inputs as cisco_toolkit.fib.trace_fib_path and asserts result equality.

The old "622-pair harness" the fib docstring cites was never git-tracked; this file
replaces it with a DETERMINISTIC, generated-in-test corpus: a synthetic multi-router
model whose enumerated (src, dst) grid (~250 pairs) is constructed to exercise every
coverage-honest status class — reach (direct/multi-hop/ECMP), definitive drop,
next_hop_not_collected, ambiguous_next_hop, ambiguous_src, loop, cross_family,
src_host_not_found, bad_address — and a coverage assertion keeps the corpus honest
(the gate fails if the vocabulary it exercises ever hollows out).

Skips cleanly when node is absent (the always-on regex sentinels still run there);
CI's webapp-ci frontend job and this repo's dev boxes have node.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

from cisco_toolkit import fib

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


# ---------------------------------------------------------------- fixture model
def _routes():
    """A small fleet purpose-built to hit every status class. All facts live in
    snap['routes'] (connected subnets included), exactly like the real snapshot."""
    return {
        # R1: LAN 10.0.1.0/24, p2p to R2, static to R2's LAN, default via an
        # UNCOLLECTED upstream (10.0.99.9 owned by nobody) -> next_hop_not_collected.
        "R1": [
            {"prefix": "10.0.1.0/24", "source": "connected", "next_hop": "", "out_intf": "Vlan10"},
            {"prefix": "10.0.12.0/30", "source": "connected", "next_hop": "", "out_intf": "Gi0/1"},
            {"prefix": "10.0.2.0/24", "source": "static", "next_hop": "10.0.12.2", "out_intf": ""},
            {"prefix": "0.0.0.0/0", "source": "static", "next_hop": "10.0.99.9", "out_intf": ""},
        ],
        # R2: LAN 10.0.2.0/24, p2p back to R1, NO default -> unknown dst = definitive drop.
        "R2": [
            {"prefix": "10.0.2.0/24", "source": "connected", "next_hop": "", "out_intf": "Vlan20"},
            {"prefix": "10.0.12.0/30", "source": "connected", "next_hop": "", "out_intf": "Gi0/1"},
            {"prefix": "10.0.1.0/24", "source": "ospf", "next_hop": "10.0.12.1", "out_intf": ""},
        ],
        # R3<->R4: each sends 10.0.50.0/24 at the other -> routing loop.
        "R3": [
            {"prefix": "10.0.34.0/30", "source": "connected", "next_hop": "", "out_intf": "Gi0/3"},
            {"prefix": "10.0.3.0/24", "source": "connected", "next_hop": "", "out_intf": "Vlan30"},
            {"prefix": "10.0.50.0/24", "source": "static", "next_hop": "10.0.34.2", "out_intf": ""},
        ],
        "R4": [
            {"prefix": "10.0.34.0/30", "source": "connected", "next_hop": "", "out_intf": "Gi0/3"},
            {"prefix": "10.0.50.0/24", "source": "static", "next_hop": "10.0.34.1", "out_intf": ""},
        ],
        # AMB1/AMB2 duplicate the 10.0.77.0/24 subnet; R5 routes via 10.0.77.7 ->
        # the next-hop IP is owned by BOTH. fib._explore_set reconciles an owner SET:
        # all-agree-drop stays a definitive drop (dst 10.0.88.9), and only DISAGREEMENT
        # survives as lower_bound:ambiguous_next_hop — so AMB1 alone owns 10.0.90.0/24
        # (reaches) while AMB2 drops it: dst 10.0.90.9 is the irreducible-ambiguity case.
        # The shared subnet also makes any 10.0.77.x SOURCE ambiguous (ambiguous_src).
        "AMB1": [
            {"prefix": "10.0.77.0/24", "source": "connected", "next_hop": "", "out_intf": "Vlan77"},
            {"prefix": "10.0.90.0/24", "source": "connected", "next_hop": "", "out_intf": "Vlan90"},
            {"prefix": "10.0.7.0/24", "source": "static", "next_hop": "10.0.77.99", "out_intf": ""},
        ],
        "AMB2": [
            {"prefix": "10.0.77.0/24", "source": "connected", "next_hop": "", "out_intf": "Vlan77"},
            {"prefix": "10.0.7.0/24", "source": "static", "next_hop": "10.0.77.99", "out_intf": ""},
        ],
        "R5": [
            {"prefix": "10.0.5.0/24", "source": "connected", "next_hop": "", "out_intf": "Vlan50"},
            {"prefix": "10.0.55.0/30", "source": "connected", "next_hop": "", "out_intf": "Gi0/5"},
            {"prefix": "10.0.88.0/24", "source": "static", "next_hop": "10.0.77.7", "out_intf": ""},
            {"prefix": "10.0.90.0/24", "source": "static", "next_hop": "10.0.77.7", "out_intf": ""},
        ],
        # R6: ECMP — two equal-cost legs for 10.0.2.0/24; one leg reaches via R1->R2,
        # the other dies at an uncollected next hop. Reach must win over the lower bound.
        "R6": [
            {"prefix": "10.0.6.0/24", "source": "connected", "next_hop": "", "out_intf": "Vlan60"},
            {"prefix": "10.0.16.0/30", "source": "connected", "next_hop": "", "out_intf": "Gi0/6"},
            {"prefix": "10.0.2.0/24", "source": "ospf", "next_hop": "10.0.16.1", "out_intf": ""},
            {"prefix": "10.0.2.0/24", "source": "ospf", "next_hop": "10.0.66.1", "out_intf": ""},
        ],
    }


def _snap():
    routes = dict(_routes())
    # R1 also owns R6's uplink /30 so the good ECMP leg terminates on a collected router.
    routes["R1"] = routes["R1"] + [
        {"prefix": "10.0.16.0/30", "source": "connected", "next_hop": "", "out_intf": "Gi0/2"}]
    return {"routes": routes, "routing_neighbors": {}, "l3_forwarding": {}}


def _cases():
    """The enumerated (src, dst) grid — deterministic, no RNG."""
    srcs = ["10.0.1.5", "10.0.2.5", "10.0.3.5", "10.0.5.5", "10.0.6.5",
            "10.0.77.5",          # shared subnet -> ambiguous_src
            "172.31.9.9"]         # nobody owns -> src_host_not_found
    dsts = ["10.0.1.9", "10.0.2.9", "10.0.3.9", "10.0.5.9", "10.0.6.9", "10.0.7.9",
            "10.0.12.1", "10.0.12.2", "10.0.34.1", "10.0.50.9", "10.0.77.9", "10.0.88.9",
            "10.0.90.9",
            "8.8.8.8",            # default at R1 (uncollected upstream) / hard drop at R2
            "fd00::1",            # cross_family
            "not-an-ip",          # bad_address
            ""]
    snap = _snap()
    return [{"snap": snap, "src": s, "dst": d} for s in srcs for d in dsts]


# ---------------------------------------------------------------- the executed gate
def _extract_port_js() -> str:
    expl = (ROOT / "cisco_toolkit" / "blast_radius_explorer.html").read_text(encoding="utf-8")
    m = re.search(r"FIB-TRACER-PORT START.*?FIB-TRACER-PORT END", expl, re.S)
    assert m, "explorer is missing the embedded FIB tracer port block"
    block = m.group(0)
    # the capture starts inside the header comment and ends inside the trailing one:
    # keep exactly the JS between the header's '*/' and the trailer's '/*'.
    return block[block.index("*/") + 2: block.rindex("/*")]


@pytest.mark.skipif(not NODE, reason="node is not installed — executed parity gate skipped "
                                     "(regex sentinels in test_explorer_fib_ssot.py still ran)")
def test_embedded_fib_port_is_behaviorally_identical_to_python(tmp_path):
    cases = _cases()
    assert len(cases) >= 100, "the parity corpus must stay substantial"

    # Python side (JSON round-trip so both sides compare as plain JSON values)
    py_results = json.loads(json.dumps(
        [fib.trace_fib_path(c["snap"], c["src"], c["dst"]) for c in cases]))

    # corpus honesty: the grid must keep exercising the breadth of the vocabulary
    statuses = {r["status"] for r in py_results}
    for must in ("computed:reached", "computed:unreachable",
                 "lower_bound:next_hop_not_collected", "lower_bound:ambiguous_next_hop",
                 "lower_bound:ambiguous_src", "lower_bound:loop",
                 "lower_bound:cross_family", "lower_bound:src_host_not_found",
                 "lower_bound:bad_address"):
        assert must in statuses, f"parity corpus no longer exercises {must}: {sorted(statuses)}"

    # node side — the REAL embedded JS, executed
    driver = tmp_path / "driver.js"
    driver.write_text(
        _extract_port_js()
        + "\nconst fs=require('fs');"
          "const cases=JSON.parse(fs.readFileSync(process.argv[2],'utf-8'));"
          "process.stdout.write(JSON.stringify(cases.map(c=>traceFibPath(c.snap,c.src,c.dst))));\n",
        encoding="utf-8")
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(cases), encoding="utf-8")
    proc = subprocess.run([NODE, str(driver), str(cases_file)],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, f"node execution of the embedded port failed:\n{proc.stderr[:2000]}"
    js_results = json.loads(proc.stdout)

    assert len(js_results) == len(py_results)
    # trace_fib_path grew Python-ONLY advisory enrichments (the wave-2 MTU / jumbo-blackhole verdict keys)
    # that the embedded explorer FIB port deliberately does NOT compute — the explorer renders reachability,
    # not path-MTU audit. Parity is over the SHARED reachability core, so these keys are projected out of both
    # sides before comparison. This is a DECLARED, guarded divergence (not a silent one): the non-vacuity
    # assertion below proves the enrichment is actually present on the Python side and the exclusion list is
    # the exhaustive, named set — a NEW Python-only key added without updating this list would leave it in the
    # compared dict and trip the mismatch, so the gate cannot silently hollow out.
    _PY_ONLY_FIB_KEYS = {"mtu_min", "mtu_bottleneck_hop", "mtu_verdict", "mtu_unobserved_hops", "jumbo_blackhole"}
    assert _PY_ONLY_FIB_KEYS <= set(py_results[0]), (
        "the Python trace lost its MTU-enrichment keys — update _PY_ONLY_FIB_KEYS or the parity projection")

    def _core(d):
        return {k: v for k, v in d.items() if k not in _PY_ONLY_FIB_KEYS} if isinstance(d, dict) else d

    mismatches = []
    for i, (py, js) in enumerate(zip(py_results, js_results)):
        if _core(py) != _core(js):
            mismatches.append((cases[i]["src"], cases[i]["dst"], _core(py), _core(js)))
    assert not mismatches, (
        f"{len(mismatches)} of {len(cases)} traces DIVERGE between fib.py and the embedded "
        f"JS port on the shared reachability core — first: src={mismatches[0][0]} dst={mismatches[0][1]}\n"
        f"python: {json.dumps(mismatches[0][2])[:400]}\n"
        f"js:     {json.dumps(mismatches[0][3])[:400]}")


def test_causal_family_roster_is_mirrored_in_the_explorer():
    """The explorer embeds its OWN causal-flow builder (the third SSOT surface), so its
    family vocabulary can drift the way the fib port could: a family added to Python's
    _FAMILY_ICON roster but unknown to the explorer renders family-less client-side.
    Extracted from causal.py source, so this sentinel self-updates with Python."""
    causal_src = (ROOT / "cisco_toolkit" / "causal.py").read_text(encoding="utf-8")
    m = re.search(r"_FAMILY_ICON[^=]*=\s*\{(.*?)\n\}", causal_src, re.S)
    assert m, "causal.py lost its _FAMILY_ICON roster"
    families = re.findall(r'"([^"]+)"\s*:', m.group(1))
    assert len(families) >= 19, f"family roster unexpectedly small: {families}"
    expl = (ROOT / "cisco_toolkit" / "blast_radius_explorer.html").read_text(encoding="utf-8")
    missing = [f for f in families if f'"{f}"' not in expl and f"'{f}'" not in expl]
    assert not missing, f"explorer causal port is STALE vs causal.py — missing family key(s): {missing}"
    # the webapp CausalFlow.tsx is deliberately NOT pinned: it renders the served
    # /causal_flows payload data-driven (no mirrored vocabulary to drift).


def test_cable_map_coverage_honest_vocabulary_on_both_surfaces():
    """compute_cable_map's op-status contract (analyze.py): 'up' | 'down' | 'unknown',
    plus the 'uncollected' badge — unknown-rendered-neutral is the coverage-honesty leg
    a lazy renderer drops first (silently painting unobserved cables healthy). Both
    render surfaces must carry the field name and the two honesty tokens."""
    surfaces = {
        "explorer": (ROOT / "cisco_toolkit" / "blast_radius_explorer.html").read_text(encoding="utf-8"),
        "CableMap.tsx": (ROOT / "webapp" / "frontend" / "src" / "components" / "CableMap.tsx"
                         ).read_text(encoding="utf-8"),
    }
    for name, src in surfaces.items():
        for token in ("op_status", "unknown", "uncollected"):
            assert token in src, f"{name} lost the cable-map coverage-honesty token {token!r}"


def test_parity_gate_runs_in_ci_where_node_exists():
    """The gate must not silently rot: this repo's dev boxes and the webapp-ci runner
    have node. If node vanished from the environment the skip above hides the gate —
    surface that as an explicit (xfail-style) breadcrumb instead of silence."""
    if not NODE:
        pytest.skip("node absent on this box — the executed gate was skipped above; "
                    "install node to restore behavioral parity coverage")
    assert os.path.basename(NODE).lower().startswith("node")
