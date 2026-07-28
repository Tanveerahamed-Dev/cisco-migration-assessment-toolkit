"""EXECUTED JS<->Python parity gate for the explorer's REASONING CORE (buildModel / linkCarries /
vlanComponents / failureImpact / causalityChains / tracePath / compareModels).

Why this file exists. The explorer carries a SECOND, independent implementation of the reachability
model that cisco_toolkit/analyze.py owns, and the engineer reads the EXPLORER, not the Python. The
two gates that already guarded this file -- test_explorer_fib_ssot.py (regex PRESENCE of status
strings + function names) and test_explorer_js_parity.py (executed, but only over
fib.trace_fib_path) -- pinned NOTHING about the model core: both were green while the two
implementations disagreed about the answer. They did, on real input:

  * a no-IP SVI was a GATEWAY here and not in Python, so pulling a VLAN's only real gateway read
    "No impact / Info" in the drawer while compute_failure_impact read "Hard partition / High";
  * a VLAN whose gateway was never collected produced a definite "Hard partition / High" for EVERY
    switch in the fleet (including switches that touch neither the VLAN nor its endpoints), where
    Python abstains with "Blast radius INDETERMINATE ... a coverage gap, not a clean bill";
  * a switch reachable only over links with NO trunk/STP evidence read a clean "No impact";
  * endpoints were counted per PORT, not per learned MAC, so tests/golden/snapshot.json's own
    access tier under-counted the stranded-endpoint headline.

So this gate asserts BEHAVIOUR, and its central assertion is the doctrine one (CLAUDE.md: "'Not
observed' never silently becomes 'healthy'"): THE EXPLORER MAY NEVER READ HEALTHIER THAN
analyze.py. Equality is asserted where the two surfaces genuinely share a fact (the gateway set,
the endpoint census); the severity comparison is one-sided by design, with the single permitted
softening declared and narrow.

Skips cleanly when node is absent (as the sibling executed gate does).
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from cisco_toolkit import analyze
from cisco_toolkit.model import InterfaceData

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
EXPLORER = ROOT / "cisco_toolkit" / "blast_radius_explorer.html"


# --------------------------------------------------------------------------- corpus
def _trunk(nbr, nbr_port, **kw):
    return {"port": kw.get("port", ""), "cdp_neighbor": nbr, "neighbor_port": nbr_port,
            "switchport_mode": "Trunk", "endpoint_type": "Switch", "status": "connected",
            "stp_fwd_vlans": kw.get("fwd", ""), "stp_blk_vlans": kw.get("blk", ""),
            "trunk_allowed_vlans": kw.get("allowed", ""), "trunk_native_vlan": kw.get("native", ""),
            "port_channel": kw.get("pc", "")}


def _svi(vid, ip="", hsrp=""):
    return {"port": "Vlan%d" % vid, "svi_ip": ip, "vlan": str(vid), "hsrp_behavior": hsrp,
            "switchport_mode": "", "end_host_mac": ""}


def _eps(vid, n, base=1, macs=1):
    out = {}
    for i in range(n):
        p = "Gi1/0/%d" % (base + i)
        out[p] = {"port": p, "switchport_mode": "Access", "vlan": str(vid), "status": "connected",
                  "end_host_mac": ",".join("aa:bb:cc:%02x:%02x:%02x" % (vid % 256, base + i, k)
                                           for k in range(macs))}
    return out


def _m(*ds):
    o = {}
    for d in ds:
        o.update(d)
    return o


def _corpus():
    """Deterministic snapshots, each aimed at one coverage-honesty seam, PLUS the real
    golden snapshot (a fixture from the real producer, not hand-shaped to the parser)."""
    cases = {}

    # (1) a VLAN whose ONLY real gateway is one switch, while a peer carries an L2-only (no-IP)
    #     SVI for the same VLAN. The no-IP SVI must NOT be a gateway on either surface.
    cases["l2_only_svi_is_not_a_gateway"] = {"interfaces": {
        "DIST1": _m({"Vlan50": _svi(50, "10.0.50.1")},
                    {"Gi1/0/1": _trunk("ACC1", "Gi1/0/24", port="Gi1/0/1", fwd="1-100", allowed="all"),
                     "Gi1/0/2": _trunk("DIST2", "Gi1/0/2", port="Gi1/0/2", fwd="1-100", allowed="all")}),
        "DIST2": _m({"Vlan50": _svi(50, "")},
                    {"Gi1/0/2": _trunk("DIST1", "Gi1/0/2", port="Gi1/0/2", fwd="1-100", allowed="all"),
                     "Gi1/0/3": _trunk("ACC1", "Gi1/0/23", port="Gi1/0/3", fwd="1-100", allowed="all")}),
        "ACC1": _m(_eps(50, 3), {"Gi1/0/24": _trunk("DIST1", "Gi1/0/1", port="Gi1/0/24", fwd="1-100", allowed="all"),
                                 "Gi1/0/23": _trunk("DIST2", "Gi1/0/3", port="Gi1/0/23", fwd="1-100", allowed="all")}),
    }}

    # (2) the uplink carries NO per-VLAN L2 evidence at all (switchport/spanning-tree not collected).
    cases["uplink_with_no_vlan_evidence"] = {"interfaces": {
        "DIST": _m({"Vlan10": _svi(10, "10.0.10.1")}, _eps(10, 4, base=5),
                   {"Gi1/0/1": _trunk("ACC1", "Gi1/0/24", port="Gi1/0/1")}),
        "ACC1": {"Gi1/0/24": _trunk("DIST", "Gi1/0/1", port="Gi1/0/24")},
    }}

    # (3) VLAN 70's gateway device was never collected; FAR touches neither the VLAN nor its endpoints.
    cases["gateway_device_not_collected"] = {"interfaces": {
        "ACC1": _m(_eps(70, 2), {"Gi1/0/24": _trunk("ACC2", "Gi1/0/24", port="Gi1/0/24", fwd="1-100", allowed="all")}),
        "ACC2": _m(_eps(70, 2), {"Gi1/0/24": _trunk("ACC1", "Gi1/0/24", port="Gi1/0/24", fwd="1-100", allowed="all")}),
        "FAR": _m({"Vlan10": _svi(10, "10.0.10.1")}, _eps(10, 2, base=5)),
    }}

    # (4) several MACs behind one access port, and an access port whose endpoint also speaks CDP.
    cases["multi_mac_and_cdp_speaking_endpoints"] = {"interfaces": {
        "DIST": _m({"Vlan10": _svi(10, "10.0.10.1")},
                   {"Gi1/0/1": _trunk("ACC1", "Gi1/0/24", port="Gi1/0/1", fwd="1-100", allowed="all")}),
        "ACC1": _m(_eps(10, 1, base=1, macs=3),
                   {"Gi1/0/2": {"port": "Gi1/0/2", "switchport_mode": "Access", "vlan": "10",
                                "status": "connected", "end_host_mac": "aa:bb:cc:dd:ee:01",
                                "cdp_neighbor": "AP-floor1", "endpoint_type": "Switch"},
                    "Gi1/0/24": _trunk("DIST", "Gi1/0/1", port="Gi1/0/24", fwd="1-100", allowed="all")}),
    }}

    # (5) a healthy dual-homed fabric with a real STP-blocked backup (the must-not-over-alarm case).
    cases["dual_homed_with_stp_backup"] = {"interfaces": {
        "DIST1": _m({"Vlan10": _svi(10, "10.0.10.2", "HSRP grp10 active vIP 10.0.10.1")},
                    {"Gi1/0/1": _trunk("ACC1", "Gi1/0/24", port="Gi1/0/1", fwd="1-100", allowed="all")}),
        "DIST2": _m({"Vlan10": _svi(10, "10.0.10.3", "HSRP grp10 standby vIP 10.0.10.1")},
                    {"Gi1/0/1": _trunk("ACC1", "Gi1/0/23", port="Gi1/0/1", blk="1-100", allowed="all")}),
        "ACC1": _m(_eps(10, 5),
                   {"Gi1/0/24": _trunk("DIST1", "Gi1/0/1", port="Gi1/0/24", fwd="1-100", allowed="all"),
                    "Gi1/0/23": _trunk("DIST2", "Gi1/0/1", port="Gi1/0/23", blk="1-100", allowed="all")}),
    }}

    golden = json.loads((ROOT / "tests" / "golden" / "snapshot.json").read_text(encoding="utf-8"))
    cases["golden_snapshot"] = {"interfaces": golden["interfaces"]}
    return cases


def _py_interfaces(snap):
    return {h: {p: InterfaceData.from_sparse(d) for p, d in ports.items()}
            for h, ports in snap["interfaces"].items()}


# --------------------------------------------------------------------------- node driver
def _extract_core_js() -> str:
    src = EXPLORER.read_text(encoding="utf-8")
    m = re.search(r"REASONING-CORE-PORT START.*?REASONING-CORE-PORT END", src, re.S)
    assert m, "explorer is missing the REASONING-CORE-PORT markers"
    block = m.group(0)
    return block[block.index("*/") + 2: block.rindex("/*")]


_DRIVER = """
const fs=require('fs');
const cases=JSON.parse(fs.readFileSync(process.argv[2],'utf-8'));
const out={};
for(const [name,snap] of Object.entries(cases)){
  const M=buildModel(snap);
  const fi={};
  for(const h of M.hosts){const r=failureImpact(M,h);
    fi[h]={worst:r.worst,hardStranded:r.hardStranded,healable:r.healable,
           perVlan:r.perVlan.map(x=>({vid:x.vid,cls:x.cls,sev:x.sev,strandedActive:x.strandedActive}))};}
  out[name]={
    hosts:M.hosts,
    gateways:Object.fromEntries([...M.gateways].map(([v,s])=>[String(v),[...s].sort()])),
    endpoints:Object.fromEntries([...M.endpoints].flatMap(([h,m])=>[...m].map(([v,n])=>[h+"|"+v,n]))),
    endpointTotal:M.endpointTotal,
    failureImpact:fi,
    chains:causalityChains(M).map(c=>({type:c.type,sev:c.sev,switch:c.switch,vid:c.vid})),
  };
}
process.stdout.write(JSON.stringify(out));
"""


def _run_node(cases, tmp_path):
    driver = tmp_path / "driver.js"
    driver.write_text(_extract_core_js() + _DRIVER, encoding="utf-8")
    payload = tmp_path / "cases.json"
    payload.write_text(json.dumps(cases), encoding="utf-8")
    proc = subprocess.run([NODE, str(driver), str(payload)],
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, f"node execution of the reasoning core failed:\n{proc.stderr[:3000]}"
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------- the gate
#: How healthy a verdict reads. The explorer's number must never be LOWER than Python's.
_HEALTH_RANK = {"Info": 0, "Indeterminate": 1, "Low": 2, "Medium": 3, "High": 4}

#: The ONE declared, narrow place the explorer may read softer than analyze.py: Python labels the
#: removal of ANY gateway that has an FHRP peer "FHRP-covered / Low", while the explorer only does
#: so for the ACTIVE router -- pulling the STANDBY causes no failover, so it stays "No impact".
#: Deliberate and MORE precise, not drift. Anything else softer is a coverage-honesty regression.
def _is_declared_softening(js_worst, py_rec):
    return js_worst == "Info" and py_rec["severity"] == "Low" and "FHRP-covered" in py_rec["detail"]


def _py_verdict(rec):
    """analyze.compute_failure_impact encodes an abstention as severity Info + an INDETERMINATE
    detail; flatten that to the same vocabulary the explorer's `worst` uses."""
    if rec["severity"] == "Info" and "INDETERMINATE" in rec["detail"]:
        return "Indeterminate"
    return rec["severity"]


@pytest.mark.skipif(not NODE, reason="node is not installed — executed model-parity gate skipped")
def test_reasoning_core_never_reads_healthier_than_analyze_py(tmp_path):
    cases = _corpus()
    js = _run_node(cases, tmp_path)

    softer, seen_abstentions, seen_high = [], 0, 0
    for name, snap in cases.items():
        py = {r["host"]: r for r in analyze.compute_failure_impact(_py_interfaces(snap))}
        for host, rec in py.items():
            pv, jv = _py_verdict(rec), js[name]["failureImpact"][host]["worst"]
            seen_abstentions += pv == "Indeterminate"
            seen_high += pv == "High"
            if _HEALTH_RANK[jv] < _HEALTH_RANK[pv] and not _is_declared_softening(jv, rec):
                softer.append((name, host, jv, pv, rec["detail"][:150]))
    assert not softer, (
        "the explorer reads HEALTHIER than analyze.py for %d (snapshot, switch) pair(s) — "
        "'not observed' silently became 'healthy' on the surface the engineer actually reads:\n%s"
        % (len(softer), "\n".join("  %s / %s: explorer=%s  python=%s  (%s)" % s for s in softer)))

    # Non-vacuity: the corpus must keep exercising BOTH the abstention and the definite-High arms,
    # or the invariant above passes by never being tested.
    assert seen_abstentions >= 2, "corpus no longer produces Python abstentions — the gate is hollow"
    assert seen_high >= 1, "corpus no longer produces a Python High — the gate is hollow"


@pytest.mark.skipif(not NODE, reason="node is not installed — executed model-parity gate skipped")
def test_reasoning_core_does_not_fabricate_a_definite_verdict(tmp_path):
    """The OTHER half of coverage honesty, and the half a one-sided "never healthier" rule misses:
    "not observed" must not become a definite verdict EITHER. It did — a VLAN with no in-scan
    gateway sent every host down the `gwOther.length===0` arm, so removing ANY switch in the fleet
    (including one that touches neither that VLAN, its endpoints, nor a link carrying it) rendered
    "Hard partition · High" and minted a matching Chain-B "transit articulation" row. Both rules
    below are generic, not fixture-shaped:
      (a) where Python abstains, the explorer must abstain too;
      (b) where Python has full evidence and finds NO impact, the explorer must not invent one."""
    cases = _corpus()
    js = _run_node(cases, tmp_path)

    fabricated, abstentions, clean_bills = [], 0, 0
    for name, snap in cases.items():
        py = {r["host"]: r for r in analyze.compute_failure_impact(_py_interfaces(snap))}
        for host, rec in py.items():
            pv, jv = _py_verdict(rec), js[name]["failureImpact"][host]["worst"]
            if pv == "Indeterminate":
                abstentions += 1
                if jv != "Indeterminate":
                    fabricated.append((name, host, jv, pv, "Python abstains; the explorer does not"))
            elif pv == "Info":
                clean_bills += 1
                if jv in ("High", "Medium"):
                    fabricated.append((name, host, jv, pv, "Python finds no impact with full evidence"))
    assert not fabricated, (
        "the explorer states a DEFINITE blast-radius verdict analyze.py does not support for %d "
        "(snapshot, switch) pair(s):\n%s"
        % (len(fabricated), "\n".join("  %s / %s: explorer=%s  python=%s  — %s" % f for f in fabricated)))

    assert abstentions >= 2 and clean_bills >= 1, "corpus no longer exercises both arms — gate is hollow"


@pytest.mark.skipif(not NODE, reason="node is not installed — executed model-parity gate skipped")
def test_gateway_set_and_endpoint_census_match_analyze_py(tmp_path):
    """Two facts the surfaces genuinely SHARE, so they are asserted as equality, not one-sided.
    Both were wrong: a no-IP SVI counted as a gateway here (inventing an L3 peer that does not
    exist), and endpoints were counted per port rather than per learned MAC."""
    cases = _corpus()
    js = _run_node(cases, tmp_path)

    gw_bad, ep_bad = [], []
    for name, snap in cases.items():
        model = analyze.build_network_model(_py_interfaces(snap))
        py_gw = {str(v): sorted({g["host"] for g in gs}) for v, gs in model["gw"].items() if gs}
        if py_gw != js[name]["gateways"]:
            gw_bad.append((name, py_gw, js[name]["gateways"]))
        py_ep = {"%s|%d" % (h, v): n for (h, v), n in model["endpoints"].items() if n}
        if py_ep != js[name]["endpoints"]:
            ep_bad.append((name, py_ep, js[name]["endpoints"]))
    assert not gw_bad, "gateway set diverges from analyze.build_network_model: %s" % (gw_bad,)
    assert not ep_bad, "endpoint census diverges from analyze.build_network_model: %s" % (ep_bad,)


@pytest.mark.skipif(not NODE, reason="node is not installed — executed model-parity gate skipped")
def test_a_single_homed_path_is_not_reported_as_an_stp_transient(tmp_path):
    """tracePath's `backupPath` feeds the path drawer's "a backup path would re-converge after STP
    (transient outage)" vs "No backup path — loss is a permanent partition" copy. Computing it over
    fwd+blk WITHOUT removing the SPOF just re-finds the ACTIVE path, so it was always truthy and the
    permanent-partition branch was dead code: a bare daisy chain was reported as a transient blip."""
    chain = {"interfaces": {
        "DIST": _m({"Vlan10": _svi(10, "10.0.10.1")},
                   {"Gi1/0/1": _trunk("MID", "Gi1/0/1", port="Gi1/0/1", fwd="10", allowed="all")}),
        "MID": {"Gi1/0/1": _trunk("DIST", "Gi1/0/1", port="Gi1/0/1", fwd="10", allowed="all"),
                "Gi1/0/2": _trunk("ACC", "Gi1/0/1", port="Gi1/0/2", fwd="10", allowed="all")},
        "ACC": _m(_eps(10, 1), {"Gi1/0/1": _trunk("MID", "Gi1/0/2", port="Gi1/0/1", fwd="10", allowed="all")}),
    }}
    ring = json.loads(json.dumps(chain))
    ring["interfaces"]["DIST"]["Gi1/0/9"] = _trunk("ACC", "Gi1/0/9", port="Gi1/0/9", blk="10", allowed="all")
    ring["interfaces"]["ACC"]["Gi1/0/9"] = _trunk("DIST", "Gi1/0/9", port="Gi1/0/9", blk="10", allowed="all")

    driver = tmp_path / "trace.js"
    driver.write_text(_extract_core_js() + """
const fs=require('fs');const cs=JSON.parse(fs.readFileSync(process.argv[2],'utf-8'));
const out={};
for(const [n,s] of Object.entries(cs)){const M=buildModel(s);const t=tracePath(M,10,'ACC','DIST',false);
  out[n]={reachable:t.reachable,spof:t.bridges.length+t.artic.length,backup:t.backupPath};}
process.stdout.write(JSON.stringify(out));
""", encoding="utf-8")
    payload = tmp_path / "trace.json"
    payload.write_text(json.dumps({"chain": chain, "ring": ring}), encoding="utf-8")
    proc = subprocess.run([NODE, str(driver), str(payload)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[:2000]
    res = json.loads(proc.stdout)

    assert res["chain"]["reachable"] and res["chain"]["spof"] > 0, "the chain fixture lost its SPOF"
    assert res["chain"]["backup"] is None, (
        "a daisy chain with NO redundant link reports a backup path %r — the drawer tells the "
        "engineer a single-fiber loss is a transient STP re-converge" % (res["chain"]["backup"],))
    assert res["ring"]["reachable"] and res["ring"]["spof"] > 0, "the ring fixture lost its SPOF"
    assert res["ring"]["backup"], "a genuine STP-blocked backup must still be found (no over-correction)"
    assert "MID" not in res["ring"]["backup"], (
        "the backup must be the ALTERNATE route, not the active path re-found: %r" % (res["ring"]["backup"],))


@pytest.mark.skipif(not NODE, reason="node is not installed — executed model-parity gate skipped")
def test_compare_models_sees_a_pulled_parallel_link(tmp_path):
    """compareModels keyed a link on the host PAIR, so every parallel link between two switches
    collapsed into one Map entry and pulling one of two fibers reported no topology change at all."""
    before = {"interfaces": {
        "DIST1": _m({"Vlan10": _svi(10, "10.0.10.1")},
                    {"Gi1/0/1": _trunk("DIST2", "Gi1/0/1", port="Gi1/0/1", fwd="1-100", allowed="all"),
                     "Gi1/0/2": _trunk("DIST2", "Gi1/0/2", port="Gi1/0/2", fwd="1-100", allowed="all")}),
        "DIST2": _m(_eps(10, 3, base=5),
                    {"Gi1/0/1": _trunk("DIST1", "Gi1/0/1", port="Gi1/0/1", fwd="1-100", allowed="all"),
                     "Gi1/0/2": _trunk("DIST1", "Gi1/0/2", port="Gi1/0/2", fwd="1-100", allowed="all")}),
    }}
    after = json.loads(json.dumps(before))
    del after["interfaces"]["DIST1"]["Gi1/0/2"]
    del after["interfaces"]["DIST2"]["Gi1/0/2"]

    driver = tmp_path / "cmp.js"
    driver.write_text(_extract_core_js() + """
const fs=require('fs');const c=JSON.parse(fs.readFileSync(process.argv[2],'utf-8'));
const A=buildModel(c.before),B=buildModel(c.after);const d=compareModels(A,B);
process.stdout.write(JSON.stringify({nA:A.links.length,nB:B.links.length,
  added:d.linksAdded,removed:d.linksRemoved}));
""", encoding="utf-8")
    payload = tmp_path / "cmp.json"
    payload.write_text(json.dumps({"before": before, "after": after}), encoding="utf-8")
    proc = subprocess.run([NODE, str(driver), str(payload)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[:2000]
    res = json.loads(proc.stdout)

    assert (res["nA"], res["nB"]) == (2, 1), "the fixture no longer models two parallel links: %s" % (res,)
    assert len(res["removed"]) == 1 and not res["added"], (
        "pulling one of two parallel DIST1<->DIST2 links reported linksRemoved=%r — a silent "
        "'no topology change' on the cutover diff" % (res["removed"],))


def test_reasoning_core_markers_and_gate_are_not_silently_skipped():
    """Always-on, node-free: the extraction contract must survive edits to a 10k-line file, and a
    vanished node must be an explicit breadcrumb rather than silence (the sibling gate's rule)."""
    src = EXPLORER.read_text(encoding="utf-8")
    assert src.count("REASONING-CORE-PORT START") == 1 and src.count("REASONING-CORE-PORT END") == 1
    block = _extract_core_js()
    for fn in ("buildModel", "linkCarries", "vlanComponents", "failureImpact",
               "causalityChains", "tracePath", "compareModels", "linkHasVlanEvidence"):
        assert fn in block, "the reasoning-core block lost %s" % fn
    if not NODE:
        pytest.skip("node absent on this box — the executed gates above were skipped; "
                    "install node to restore behavioural model-parity coverage")
