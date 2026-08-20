"""EXECUTED render-safety gate for the Blast-Radius Explorer's rendering half.

The explorer builds its whole UI from a snapshot whose every string is DEVICE-derived
(hostnames, interface descriptions, CDP names, MAC/ARP-learned endpoint addresses) plus a
URL hash. ``html._script_safe_json`` stops that text breaking OUT of the ``<script>`` block;
it says nothing about what the page then does with it at runtime. These are the two runtime
classes that survived that hardening:

  1. **Injection into an EXPORTED artifact.** ``fsimExportSvg()`` hand-assembles an SVG
     string and downloads it. An SVG opened from disk executes inline script, so an
     unescaped address in the title turned a "deliverable" into an executable payload.
     The in-page renderer escapes the same values — only the export path did not.
  2. **Absence rendered as health** (CLAUDE.md guardrail 3). Two cards fail OPEN on missing
     evidence: the trunk detectors default an uncollected native VLAN to "1" (so two
     uncollected ends "agree") and used to print a green ✓ "no mismatches"; and the
     forwarding map counted ``excel.HEALTH_NOT_OBSERVED`` rows as findings while its
     severity breakdown counted none of them, so it read "N at risk · 0 high · 0 medium ·
     0 low" with no word that anything went unassessed.

Regex sentinels cannot catch either — both are behaviours of the assembled output — so this
gate EXECUTES the real embedded ``<script>`` under node against a minimal DOM stub, the same
pattern tests/test_explorer_js_parity.py uses for the FIB port. Skips cleanly without node.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXPLORER = ROOT / "cisco_toolkit" / "blast_radius_explorer.html"
NODE = shutil.which("node")


def test_demo_does_not_publish_lifecycle_bands_without_lifecycle_evidence():
    """The automatic first-run demo must agree with its own LC-1 not-assessable verdict."""
    html = EXPLORER.read_text(encoding="utf-8")
    start = html.index("function demoSnapshot(){")
    end = html.index("\nfunction distinctDeg", start)
    demo = html[start:end]
    assert "lifecycle_risk:" not in demo
    bands = re.findall(r'eol_band:\s*"([^"]+)"', demo)
    assert bands and set(bands) == {"Unknown"}, bands
    assert 'id:"LC-1"' in demo
    assert 'verdict:"not-assessable"' in demo
    assert "Lifecycle analysis is absent from this snapshot." in demo


@pytest.mark.skipif(not NODE, reason="node is not available")
def test_lifecycle_census_uses_canonical_order_and_future_bands_fail_closed(tmp_path):
    out = _run("""
      const counts={Unknown:5,"Past-EoS":3,"Future-Band":6,Active:4,"Past-LDoS":1,"Near-LDoS":2};
      const entries=__EV("lifecycleBandEntries")(counts);
      const census=__EV("abqCensus")(Object.fromEntries(entries),"device(s)",
        __EV("lifecycleBandLabel"),k=>k==="Unknown"||k==="Future-Band");
      console.log(JSON.stringify({
        order:entries.map(([k])=>k),
        future:__EV("lifecycleBandLabel")("Future-Band"),
        gap:census&&census.gap,total:census&&census.total,text:census&&census.ev
      }));
    """, tmp_path)
    assert out["order"] == [
        "Past-LDoS", "Near-LDoS", "Past-EoS", "Active", "Unknown", "Future-Band"
    ]
    assert out["future"].startswith("NOT ASSESSED (unrecognized band:")
    assert out["gap"] == 11 and out["total"] == 21
    assert out["text"].index("Past-LDoS") < out["text"].index("Near-LDoS")
    assert "coverage gap" in out["text"]

# A DOM stub just rich enough for the explorer's load()/render path. Every element accepts any
# attribute/handler and records innerHTML; nothing is asserted through the DOM — the assertions
# read the STRINGS the render functions return, which is where the defects live.
_DOM_STUB = r"""
const _mk=t=>{const e={tagName:String(t||"div").toUpperCase(),children:[],childNodes:[],attributes:{},
  dataset:{},_h:"",textContent:"",value:"",hidden:false,
  style:{_p:{},setProperty(k,v){this._p[k]=v;},getPropertyValue(k){return this._p[k]||"";},removeProperty(k){delete this._p[k];}},
  classList:{_s:new Set(),add(...c){c.forEach(x=>this._s.add(x));},remove(...c){c.forEach(x=>this._s.delete(x));},
    toggle(c,f){if(f===undefined){this._s.has(c)?this._s.delete(c):this._s.add(c);}else if(f)this._s.add(c);else this._s.delete(c);},
    contains(c){return this._s.has(c);}},
  setAttribute(k,v){this.attributes[k]=String(v);},getAttribute(k){return k in this.attributes?this.attributes[k]:null;},
  removeAttribute(k){delete this.attributes[k];},hasAttribute(k){return k in this.attributes;},
  appendChild(c){this.children.push(c);this.childNodes.push(c);return c;},
  insertBefore(c){this.children.push(c);this.childNodes.push(c);return c;},
  removeChild(c){const i=this.children.indexOf(c);if(i>=0)this.children.splice(i,1);return c;},
  remove(){},addEventListener(){},removeEventListener(){},dispatchEvent(){return true;},
  querySelector(){return _mk("div");},querySelectorAll(){return [];},closest(){return null;},contains(){return false;},
  getBoundingClientRect(){return {x:0,y:0,left:0,top:0,right:800,bottom:600,width:800,height:600};},
  focus(){},blur(){},click(){},scrollIntoView(){},getContext(){return null;},
  insertAdjacentHTML(p,h){this._h+=h;},cloneNode(){return _mk(t);},getTotalLength(){return 100;},
  getPointAtLength(){return {x:0,y:0};},getComputedTextLength(){return 10;},
  animate(){return {cancel(){},finished:Promise.resolve()};}};
  Object.defineProperty(e,"innerHTML",{get(){return this._h;},set(v){this._h=String(v);}});
  Object.defineProperty(e,"outerHTML",{get(){return this._h;},set(v){this._h=String(v);}});
  Object.defineProperty(e,"className",{get(){return [...this.classList._s].join(" ");},
    set(v){this.classList._s=new Set(String(v).split(/\s+/).filter(Boolean));}});
  Object.defineProperty(e,"firstChild",{get(){return this.children[0]||null;}});
  Object.defineProperty(e,"parentNode",{get(){return null;}});
  Object.defineProperty(e,"parentElement",{get(){return null;}});
  return e;};
const _REG={};
globalThis.document={documentElement:_mk("html"),body:_mk("body"),head:_mk("head"),title:"",
  visibilityState:"visible",
  getElementById:id=>(_REG[id]||(_REG[id]=_mk("div"))),
  querySelector:()=>_mk("div"),querySelectorAll:()=>[],createElement:_mk,createElementNS:(n,t)=>_mk(t),
  createTextNode:t=>({nodeValue:t,textContent:t}),createDocumentFragment:()=>_mk("frag"),
  addEventListener(){},removeEventListener(){},execCommand(){return true;},activeElement:null};
const _store={};
globalThis.localStorage={getItem:k=>(k in _store?_store[k]:null),setItem(k,v){_store[k]=String(v);},
  removeItem(k){delete _store[k];},clear(){for(const k in _store)delete _store[k];},
  key:i=>Object.keys(_store)[i]||null,get length(){return Object.keys(_store).length;}};
globalThis.sessionStorage=globalThis.localStorage;
globalThis.location={hash:"",href:"file:///x.html",search:"",protocol:"file:",origin:"null"};
globalThis.history={replaceState(){},pushState(){}};
globalThis.navigator={clipboard:{writeText:()=>Promise.resolve()},userAgent:"node",platform:"node"};
globalThis.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){},addListener(){}});
globalThis.requestAnimationFrame=()=>0; globalThis.cancelAnimationFrame=()=>{};
// timers are no-ops: the simulator arms a playback interval on open, which would otherwise
// keep the node process alive past the driver's last write and hang the subprocess.
globalThis.setTimeout=()=>0; globalThis.clearTimeout=()=>{};
globalThis.setInterval=()=>0; globalThis.clearInterval=()=>{};
globalThis.getComputedStyle=()=>({getPropertyValue:()=>""});
globalThis.devicePixelRatio=1; globalThis.innerWidth=1200; globalThis.innerHeight=800;
globalThis.performance=globalThis.performance||{now:()=>Date.now()};
globalThis.alert=()=>{}; globalThis.confirm=()=>true; globalThis.prompt=()=>null;
globalThis.atob=s=>Buffer.from(s,"base64").toString("binary");
globalThis.btoa=s=>Buffer.from(s,"binary").toString("base64");
globalThis.__BLOBS=[];
globalThis.Blob=function(parts){globalThis.__BLOBS.push(parts.map(String).join(""));};
globalThis.URL.createObjectURL=()=>"blob:x"; globalThis.URL.revokeObjectURL=()=>{};
globalThis.addEventListener=()=>{}; globalThis.removeEventListener=()=>{};
globalThis.dispatchEvent=()=>true; globalThis.scrollTo=()=>{};
globalThis.window=globalThis; globalThis.self=globalThis; globalThis.top=globalThis;
"""

# eval() inside the script's own scope is the only way to reach its top-level `let`/`function`
# bindings from the driver (they are lexical, not properties of globalThis).
_EPILOGUE = "\n;globalThis.__EV=function(__s){return eval(__s);};\n"


def _script_js() -> str:
    html = EXPLORER.read_text(encoding="utf-8")
    m = re.search(r"^<script>\n(.*)\n</script>", html, re.S | re.M)
    assert m, "explorer no longer has a single top-level <script> block"
    return m.group(1)


def _run(driver_body: str, tmp_path, payload=None):
    driver = tmp_path / "driver.js"
    # the driver shares the script's top-level scope, which already declares svg/load/el/… —
    # run it inside an IIFE so its own locals cannot collide with the file under test.
    src = _DOM_STUB + _script_js() + _EPILOGUE + "\n;(()=>{" + driver_body + "\n})();\n"
    driver.write_text(src, encoding="utf-8")
    argv = [NODE, str(driver)]
    if payload is not None:
        pf = tmp_path / "payload.json"
        pf.write_text(json.dumps(payload), encoding="utf-8")
        argv.append(str(pf))
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, f"node run of the embedded explorer JS failed:\n{proc.stderr[:3000]}"
    return json.loads(proc.stdout)


def test_vpc_domain_grouping_is_explicitly_candidate_only() -> None:
    """The compatibility pair generator must never promote a shared domain ID to identity."""
    html = EXPLORER.read_text(encoding="utf-8")
    start = html.index("/* V3.23.125 compatibility visualization")
    end = html.index("function _mlagPeerOf", start)
    block = html[start:end]

    assert 'return {tag:"candidate"' in block
    assert '"confirmed"' not in block.casefold()
    assert "A domain ID is an attribute, never pair identity" in block
    assert "explicit reciprocal peer identities" in block
    assert "both local legs (one on each proven peer)" in block
    assert "matching remote LACP system and aggregation/key identity" in block
    assert "CONFIRMED vPC pair" not in html


_VPC_CANDIDATE_DRIVER = """
const EV=globalThis.__EV;
globalThis.__P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
EV('SNAP=globalThis.__P');
const pairs=[...EV('vpcPairs')()].sort();
const details=pairs.map(k=>{const p=k.split('||'),ev=EV('_mlagEvidence')(p[0],p[1]);
  const J={src:{},dst:{},nodes:[{host:p[0],mlagPeer:p[1],role:'transit',label:'Transit',layers:[]}]};
  return {pair:k,tag:EV('_mlagTag')(p[0],p[1]),note:ev.note,
    rendered:EV('_fsimStackHtml')({showFrame:false,useBackup:false,both:false},J,0,false,false)};});
process.stdout.write(JSON.stringify({pairs,details}));
"""


@pytest.mark.parametrize(
    ("hosts", "expected_pairs"),
    [
        (["site-a", "site-b", "site-c"], 3),
        (["site1-a", "site1-b", "site2-a", "site2-b"], 6),
    ],
)
@pytest.mark.skipif(not NODE, reason="node is not available")
def test_reused_vpc_domain_collisions_render_every_combination_unverified(
    tmp_path, hosts: list[str], expected_pairs: int
) -> None:
    """Three-host collisions and cross-site domain reuse stay visible, but never confirmed."""
    payload = {host: {"domain_id": 10} for host in hosts}
    out = _run(_VPC_CANDIDATE_DRIVER, tmp_path, payload={"vpc": payload})

    assert len(out["pairs"]) == expected_pairs
    assert len(out["details"]) == expected_pairs
    for detail in out["details"]:
        assert detail["tag"] == "candidate"
        assert f"{len(hosts)} hosts report this domain" in detail["note"]
        assert "every pairwise combination is ambiguous" in detail["note"]
        assert "explicit reciprocal peer identities" in detail["note"]
        assert "both local legs (one on each proven peer)" in detail["note"]
        assert "matching remote LACP system and aggregation/key identity" in detail["note"]
        assert "pl-watch" in detail["rendered"]
        assert "unverified vPC/MLAG candidate" in detail["rendered"]
        assert "confirmed" not in detail["rendered"].casefold()


# --------------------------------------------------------------------------- fixtures
def _fabric() -> dict:
    """Two access switches uplinked to a core, one endpoint whose ARP-learned address is
    hostile. Deliberately carries NO trunk evidence (no trunk_native_vlan / allowed list)."""
    def acc(n, ip):
        return {
            "Gi0/1": {"cdp_neighbor": "core1", "neighbor_port": "Gi1/0/%d" % n,
                      "switchport_mode": "trunk", "status": "connected"},
            "Gi0/2": {"switchport_mode": "access", "vlan": "10", "status": "connected",
                      "end_host_mac": "0011.2233.44%02d" % n, "end_host_ip": ip},
        }
    return {
        "schema": "collect_parse_snapshot/1",
        "interfaces": {
            "core1": {
                "Gi1/0/1": {"cdp_neighbor": "access1", "neighbor_port": "Gi0/1",
                            "switchport_mode": "trunk", "status": "connected"},
                "Gi1/0/2": {"cdp_neighbor": "access2", "neighbor_port": "Gi0/1",
                            "switchport_mode": "trunk", "status": "connected"},
                "Vlan10": {"svi_ip": "10.0.10.1 255.255.255.0"},
            },
            "access1": acc(1, "10.0.10.50"),
            "access2": acc(2, "10.0.10.51"),
        },
    }


_XSS = '10.0.10.99"/><script>alert(1)</script>'


# Driver bodies deliberately use no regex literals and no backslash escapes — everything
# hostile arrives through the JSON payload file, so the driver text stays trivially quotable.

# --------------------------------------------------------------------------- 1. exported SVG
_SVG_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
EV('load')(P.snap,'T',false);
const eps=EV('EPALL');
const bad=eps.find(e=>e.ip&&e.ip.indexOf('<')>=0);
const good=eps.find(e=>e.ip&&e.ip.indexOf('<')<0);
globalThis.__s=bad; globalThis.__d=good;
EV('FLOW_SRC=globalThis.__s;FLOW_DST=globalThis.__d;FLOWRES=flowBetween(FLOW_SRC,FLOW_DST);'
  +'if(FLOWRES)openFlowSim(FLOWRES);');
globalThis.__BLOBS.length=0;
EV('fsimExportSvg')();
const doc=globalThis.__BLOBS.join('');
process.stdout.write(JSON.stringify({
  payload_reached_model: !!(bad&&bad.ip),
  simulator_open: !!EV('FLOWSIM'),
  exported: doc.length>0,
  raw_script: doc.indexOf('<script')>=0,
  escaped: doc.indexOf('&lt;script')>=0}));
"""


def test_flow_svg_export_escapes_device_derived_addresses(tmp_path):
    """A hostile ARP/MAC-learned address must not reach the downloaded .svg as live markup.

    Without the esc() on fsimExportSvg's title the emitted file contains a real <script>
    element, and an SVG opened from disk runs it.
    """
    if not NODE:
        pytest.skip("node absent — executed render-safety gate skipped")
    snap = _fabric()
    snap["interfaces"]["access1"]["Gi0/2"]["end_host_ip"] = _XSS
    out = _run(_SVG_DRIVER, tmp_path, payload={"snap": snap})
    assert out["payload_reached_model"], "fixture never got the hostile address into EPALL"
    assert out["simulator_open"] and out["exported"], (
        "fsimExportSvg produced no file — the probe proved nothing")
    assert not out["raw_script"], (
        "fsimExportSvg wrote a LIVE <script> element into the downloaded SVG from a "
        "device-derived endpoint address — opening that 'deliverable' executes it")
    assert out["escaped"], "the address should still appear, HTML-escaped, in the title"


_HASH_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
EV('load')(P.snap,'T',false);
const src=EV('EPALL').find(e=>e.ip);
EV('FLOWSIM=null');
EV('openFlowFromHash')(src.ip+'~'+P.hostile+'~tcp~443');
const opened_hostile=!!EV('FLOWSIM');
EV('FLOWSIM=null');
EV('openFlowFromHash')(src.ip+'~239.10.10.10~udp~5004');
const opened_real=!!EV('FLOWSIM');
process.stdout.write(JSON.stringify({opened_hostile,opened_real,
  mc_ok:EV('isMulticastIp')('239.1.1.1'), mc_junk:EV('isMulticastIp')(P.hostile)}));
"""


def test_flow_deeplink_rejects_a_non_address_multicast_destination(tmp_path):
    """#flow=<src>~<dst>~… fed the multicast branch on a first-octet test alone, so
    '239.1.1.1"><script>…' parsed as 239 and became FLOW_DST.ip verbatim."""
    if not NODE:
        pytest.skip("node absent — executed render-safety gate skipped")
    out = _run(_HASH_DRIVER, tmp_path,
               payload={"snap": _fabric(), "hostile": '239.1.1.1"/><script>alert(1)</script>'})
    assert not out["opened_hostile"], (
        "a non-dotted-quad 'multicast group' from the URL hash was accepted as FLOW_DST")
    assert out["opened_real"], "a genuine multicast group must still deep-link (guard over-rejects)"
    assert out["mc_ok"] and not out["mc_junk"], "isMulticastIp must require a dotted quad"


# --------------------------------------------------------------------------- 2. absence != health
_TRUNK_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
const shot=s=>{EV('load')(s,'T',false); const c=EV('trunkConsistencyCard')();
  return {findings:EV('trunkConsistency()').length, evidence:EV('trunkEvidence()'),
          clean:c.indexOf('>clean<')>=0,
          asserts_no_mismatch:c.indexOf('No native-VLAN mismatches')>=0,
          not_observed:c.indexOf('NOT OBSERVED')>=0};};
process.stdout.write(JSON.stringify({bare:shot(P.bare), observed:shot(P.observed)}));
"""


def test_trunk_consistency_does_not_claim_clean_without_trunk_evidence(tmp_path):
    """_nativeVlan() defaults an uncollected native VLAN to '1', so two uncollected ends
    always agree and the detector returns []. The card must then say [NOT OBSERVED], never
    the green ✓ 'No native-VLAN mismatches …' it used to print."""
    if not NODE:
        pytest.skip("node absent — executed render-safety gate skipped")
    bare = _fabric()                     # no trunk_native_vlan / trunk_allowed_vlans anywhere
    observed = json.loads(json.dumps(bare))
    for _host, ports in observed["interfaces"].items():
        for _port, d in ports.items():
            if d.get("switchport_mode") == "trunk":
                d["trunk_native_vlan"] = "1"
                d["trunk_allowed_vlans"] = "1-4094"
    out = _run(_TRUNK_DRIVER, tmp_path, payload={"bare": bare, "observed": observed})
    b = out["bare"]
    assert b["findings"] == 0 and not b["evidence"], "fixture is not the zero-evidence case"
    assert not b["clean"] and not b["asserts_no_mismatch"], (
        "trunk consistency printed a green 'clean' / '✓ No native-VLAN mismatches' for a "
        "collection that carries NO trunk evidence at all — absence rendered as health")
    assert b["not_observed"], "the zero-evidence card must name the blind spot"
    o = out["observed"]
    assert o["evidence"] and o["clean"] and not o["not_observed"], (
        "with real trunk evidence and no mismatch the card must still read 'clean' — "
        "the guard must not swallow a genuine pass")


_FWD_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
const shot=s=>{EV('load')(s,'T',false); const c=EV('forwardingCard')();
  return {rendered:c.length>0,
          at_risk:c.indexOf(' at risk')>=0,
          all_redundant:c.indexOf('all redundant')>=0,
          not_observed_badge:c.indexOf('[NOT OBSERVED]</span>')>=0,
          marker_in_rows:c.indexOf('NOT OBSERVED')>=0};};
process.stdout.write(JSON.stringify({blind:shot(P.blind), real:shot(P.real)}));
"""


def test_forwarding_map_separates_not_observed_rows_from_findings(tmp_path):
    """excel.write_l3_forwarding_sheet emits '[NOT OBSERVED] - no show track evidence…'
    (severity Info). Counting it as a finding produced 'N at risk' beside '0 high · 0
    medium · 0 low' — a risk headline with nothing behind it and no blind-spot wording."""
    if not NODE:
        pytest.skip("node absent — executed render-safety gate skipped")
    marker = "[NOT OBSERVED] - no 'show track' evidence; object tracking NOT assessed"
    blind = dict(_fabric(), l3_forwarding=[
        {"switch": "core1", "vlan": 10, "svi_ip": "10.0.10.1 255.255.255.0", "fhrp": "HSRP",
         "role": "Active", "vip": "10.0.10.254", "routing_source": "connected",
         "next_hop": "Vlan10", "tracking": "", "risk": marker, "severity": "Info"}])
    real = dict(_fabric(), l3_forwarding=[
        {"switch": "core1", "vlan": 10, "svi_ip": "10.0.10.1 255.255.255.0", "fhrp": "none",
         "role": "", "vip": "", "routing_source": "connected", "next_hop": "Vlan10",
         "tracking": "2 obj", "risk": "single-gateway", "severity": "Medium"}])
    out = _run(_FWD_DRIVER, tmp_path, payload={"blind": blind, "real": real})
    b = out["blind"]
    assert b["rendered"], "forwardingCard rendered nothing — the probe proved nothing"
    assert not b["at_risk"], (
        "a gateway whose ONLY 'risk' is the [NOT OBSERVED] marker was counted 'at risk', "
        "while the severity breakdown beside it counted 0 of them")
    assert not b["all_redundant"], "a blind spot must never be summarised as 'all redundant'"
    assert b["not_observed_badge"] and b["marker_in_rows"], (
        "the not-assessed gateways must be surfaced as their own third state")
    r = out["real"]
    assert r["at_risk"] and not r["not_observed_badge"], (
        "a genuine single-gateway finding must still count as 'at risk'")




# --------------------------------------------------------------------------- 3. storage scoping
_STORAGE_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
const store=()=>Object.keys(globalThis.localStorage).length; // unused; keys read below
// engagement A: answer one interview question, then hand-pin a node
EV('load')(P.a,'Migration_Assessment.xlsx',false);
const qid=EV('AB_QBANK')[0].id;
EV('ABQ').res[qid]={st:'no',ev:'CLIENT-A evidence note'};
EV('abqSave')();
EV('PINNED={};PINNED[MODEL.hosts[0]]={x:11,y:22};savePins();');
const keyA=EV('pinsKey()');
// engagement B: a DIFFERENT fleet uploaded under the SAME filename/label
EV('load')(P.b,'Migration_Assessment.xlsx',false);
const keyB=EV('pinsKey()');
const inherited=EV('ABQ').res[qid];
process.stdout.write(JSON.stringify({
  same_label: true,
  pins_key_collides: keyA===keyB,
  a_pins_survived: !!globalThis.localStorage.getItem(keyA),
  interview_inherited: inherited===undefined?null:inherited,
  b_sees_own_pins: JSON.stringify(EV('PINNED'))}));
"""


def test_persisted_state_is_scoped_per_snapshot_not_per_label(tmp_path):
    """AssessHub's label falls back to the UPLOADED FILENAME and every client's explorer is
    served from one origin, so label-only keys collide across engagements. The interview was
    worse — one global 'nme-interview' key — so engagement B opened holding A's answers and
    abqMinutes() exported them under B's label."""
    if not NODE:
        pytest.skip("node absent — executed render-safety gate skipped")
    a = _fabric()
    b = json.loads(json.dumps(_fabric()))                 # a DIFFERENT fleet, same label
    b["interfaces"]["core1"]["Gi1/0/3"] = {"cdp_neighbor": "access3", "neighbor_port": "Gi0/1",
                                           "switchport_mode": "trunk", "status": "connected"}
    b["interfaces"]["access3"] = {
        "Gi0/1": {"cdp_neighbor": "core1", "neighbor_port": "Gi1/0/3",
                  "switchport_mode": "trunk", "status": "connected"},
        "Gi0/2": {"switchport_mode": "access", "vlan": "10", "status": "connected",
                  "end_host_mac": "0011.2233.4403", "end_host_ip": "10.0.10.52"}}
    out = _run(_STORAGE_DRIVER, tmp_path, payload={"a": a, "b": b})
    assert out["interview_inherited"] is None, (
        "engagement B inherited engagement A's interview answers (incl. free-text evidence) "
        "from a snapshot-agnostic localStorage key — and abqMinutes() exports them under B's label")
    assert not out["pins_key_collides"], (
        "two different fabrics uploaded under the same label shared one pins key")
    assert out["a_pins_survived"], (
        "loading B pruned and rewrote A's pin store — a destructive cross-engagement write")


# --------------------------------------------------------- 3. lifecycle "Unknown" suppressed the panel
_LC_DRIVER = """
const EV=globalThis.__EV;
globalThis.__P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
EV('SNAP=globalThis.__P');
const sect=EV('deviceIntelSection');
const out={};
['unknown_only','active_only','past_ldos'].forEach(k=>{ out[k]=sect(k); });
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(not NODE, reason="node is not available")
def test_device_panel_is_not_suppressed_when_the_only_signal_is_an_unbanded_lifecycle(tmp_path):
    """Absence rendered as health, in its quietest form: the panel simply did not render.

    `deviceIntelSection` early-returns "" when it judges there is nothing to say. Its lifecycle term,
    `lcConcern`, tested `band!=="Active" && band!=="Unknown"` -- while the pill that PRINTS the band,
    twenty-odd lines below, tests only `band!=="Active"` and happily renders Unknown. The two
    predicates disagreed, so a device whose only signal was an undetermined lifecycle band hit the
    early return and the pill never got the chance to say so. The reader saw a device with no panel:
    identical to a device with nothing wrong.

    Executed, not grepped -- the defect is a behaviour of the assembled output, and a regex over the
    source would pass on a predicate that had been "fixed" in only one of the two places.
    """
    def dev(band):
        return {"host": band, "band": band, "model": "WS-C6509-E"}

    payload = {"schema": "collect_parse_snapshot/1", "interfaces": {},
               "lifecycle_risk": {"per_device": [dev("unknown_only"), dev("active_only"),
                                                 dev("past_ldos")]}}
    # bands are carried on the record, hosts are just labels for the lookup
    payload["lifecycle_risk"]["per_device"] = [
        {"host": "unknown_only", "band": "Unknown", "model": "WS-C6509-E"},
        {"host": "active_only", "band": "Active", "model": "C9300-48P"},
        {"host": "past_ldos", "band": "Past-LDoS", "model": "WS-C4948E"},
    ]
    out = _run(_LC_DRIVER, tmp_path, payload)

    assert out["unknown_only"], "the panel is suppressed entirely for an unbanded device"
    assert "NOT ASSESSED" in out["unknown_only"], \
        "the band is rendered as a bare 'Unknown', which reads as a mild band rather than a gap"

    # Non-vacuity, both directions: a genuinely Active device must STILL be suppressed (otherwise the
    # gate has simply been opened for everything and proves nothing), and a real adverse band must
    # still render as it always did.
    assert out["active_only"] == "", "the gate stopped gating -- a healthy device now renders a panel"
    assert out["past_ldos"] and "Past-LDoS" in out["past_ldos"]
    assert "NOT ASSESSED" not in out["past_ldos"], "a real band was relabelled as a coverage gap"


_LC_WORDING_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
EV('load')(P.snap,'T',false);
globalThis.__IT={id:'lc-01',domain:'Routing & Switching',question:P.q,go_no_go:false};
const auto=EV('abqAuto')(globalThis.__IT);
process.stdout.write(JSON.stringify({
  cockpit:EV('cockpitCard')(),
  profile:EV('abH_profile')(P.active).html,
  migrate:EV('abH_migrate')(P.active).html,
  unknown_profile:EV('abH_profile')(P.unknown).html,
  fleet:EV('abH_fleet')().html,
  eol:EV('abH_eol')().html,
  auto:auto&&auto.ev||''
}));
"""


@pytest.mark.skipif(not NODE, reason="node is not available")
def test_lifecycle_views_render_active_as_date_position_and_unknown_as_a_class(tmp_path):
    active, unknown, past_ldos, past_eos = "active-sw", "unknown-sw", "ldos-sw", "eos-sw"
    payload = {
        "q": _LC_Q,
        "active": active,
        "unknown": unknown,
        "snap": {
            "schema": "collect_parse_snapshot/1",
            "interfaces": {active: {}, unknown: {}, past_ldos: {}, past_eos: {}},
            "devices": {active: {"model": "C9300-48P"}, unknown: {"model": "UNMATCHED-1"},
                        past_ldos: {"model": "OLD-1"}, past_eos: {"model": "SALE-1"}},
            "lifecycle_risk": {
                "asof": "2026-08-07",
                "summary": {
                    "n_devices": 4,
                    "n_active": 1,
                    "n_unknown": 1,
                    "n_past_ldos": 1,
                    "n_near": 0,
                    "n_past_eos": 1,
                    "by_band": {"Active": 1, "Unknown": 1, "Past-LDoS": 1, "Past-EoS": 1},
                    "by_platform": [
                        {"platform": "Catalyst 9300", "count": 1, "band": "Active", "ldos": "2030-01-01"},
                        {"platform": "UNMATCHED-1", "count": 1, "band": "Unknown", "ldos": ""},
                    ],
                },
                "per_device": [
                    {"host": active, "band": "Active", "eos": "2028-01-01", "ldos": "2030-01-01",
                     "status": "Active (no end-of-life announced)"},
                    {"host": unknown, "band": "Unknown", "status": "Unknown model"},
                    {"host": past_ldos, "band": "Past-LDoS", "status": "past support"},
                    {"host": past_eos, "band": "Past-EoS", "status": "past sale"},
                ],
            },
        },
    }
    out = _run(_LC_WORDING_DRIVER, tmp_path, payload=payload)

    for surface in ("cockpit", "profile", "migrate", "fleet", "eol", "auto"):
        assert "Pre-EoS date band" in out[surface], (surface, out[surface])
    for surface in ("cockpit", "fleet", "eol", "auto", "unknown_profile"):
        assert "NOT ASSESSED" in out[surface] or "No authoritative lifecycle band" in out[surface], \
            (surface, out[surface])
    assert "support entitlement not assessed" in out["profile"]
    assert "support entitlement not assessed" in out["migrate"]
    assert "no exact EoX bulletin row matched" in out["unknown_profile"]
    assert "retained source proof/complete dates did not verify" in out["unknown_profile"]
    assert "Past end-of-support" in out["eol"] and past_ldos in out["eol"]
    assert "Past end-of-sale (LDoS still future)" in out["eol"] and past_eos in out["eol"]
    end_support = out["eol"].split("Past end-of-support", 1)[1].split("Past end-of-sale", 1)[0]
    assert past_eos not in end_support
    rendered = " ".join(out.values())
    assert "Active (no end-of-life announced)" not in rendered
    assert "Unknown model" not in rendered


# --------------------------------------------------------------------------- 4. asset risk register
# U1-2: compute_device_dossiers() correctly ABSTAINS on an axis it has no evidence for (state "na"), and
# abstention is weighted ZERO in the exposure score. So an asset whose EoL / software / control-plane /
# logs / CIS / hygiene / drift / QoS axes were all un-collected scores risk_index 0 -> band "Low" ->
# GREEN pill, GREEN bar, "no stacked risk" badge. The engine's own "Unassessed" band made it worse:
# _RR_PILL knew that band, _RR_TOK did NOT, so it fell through `||"ok"` to the green bar. The two maps
# disagreed about the same band and the green one won the most visible element.
_RR_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
function card(dd){globalThis.__SNAP={device_dossiers:dd};EV('SNAP=globalThis.__SNAP');
  return EV('riskRegisterCard')();}
function probe(h){return {len:h.length,
  green_badge:h.indexOf('b-ok')>=0, green_pill:h.indexOf('pill pl-ok')>=0,
  green_bar:h.indexOf('var(--ok)')>=0,
  gap_pill:h.indexOf('axes NOT ASSESSED')>=0,
  coverage_badge:h.indexOf('coverage-limited')>=0};}
const blind=probe(card(P.blind)), clean=probe(card(P.clean));
process.stdout.write(JSON.stringify({blind,clean}));
"""


def _dossiers_for_explorer(blind: bool) -> dict:
    """From the REAL producer (analyze.compute_device_dossiers), not a hand-shaped stub: a hand-written
    dossier in the shape the renderer expects would make the fixture agree with whatever the renderer
    does. `blind=True` = health score collected, platform unmatched in the EoX KB, nothing else."""
    from cisco_toolkit.analyze import compute_device_dossiers
    hosts = ["sw0", "sw1", "sw2"]
    hs = [{"switch": h, "band": "Good", "score": 88, "role": "access"} for h in hosts]
    if blind:
        return compute_device_dossiers(
            health_scores=hs,
            lifecycle_risk={"per_device": [{"host": h, "band": "Unknown", "model": "WS-XYZ",
                                            "platform": "cat", "sw_version": "16.9.1"} for h in hosts]})
    return compute_device_dossiers(
        health_scores=hs,
        lifecycle_risk={"per_device": [{"host": h, "band": "Active", "model": "C9300-48P",
                                        "platform": "C9300", "sw_version": "17.9.4"} for h in hosts]},
        software_risk={"per_device": [{"host": h, "band": "Current", "sw_version": "17.9.4"} for h in hosts],
                       "findings": []},
        platform_health={"per_device": [{"host": h, "collected": True, "cpu_5min": 12,
                                         "mem_free_pct": 55, "band": "Healthy"} for h in hosts],
                         "findings": []},
        syslog_intelligence={"per_device": [{"host": h, "n_events": 4} for h in hosts], "detections": []},
        qos_audit={"per_device": [{"host": h, "policies": 1} for h in hosts], "findings": []},
        golden_drift={"per_device": [{"host": h, "compliance_pct": 100, "n_missing": 0} for h in hosts],
                      "summary": {"n_baseline": 20}},
        security={h: {"findings": [{"status": "pass", "id": "x"}]} for h in hosts},
        config_hygiene={h: {"undefined_refs": [], "scanned": True, "findings": []} for h in hosts})


def test_risk_register_does_not_paint_an_unassessed_asset_green(tmp_path):
    """[U1-2 false-health] Measured pre-fix, blind fixture: the card rendered `b-ok` "no stacked risk",
    `pill pl-ok` on every row and a `var(--ok)` green bar -- indistinguishable from the fully-assessed
    fleet, on assets where 8 of 11 risk axes were never collected."""
    if not NODE:
        pytest.skip("node absent — executed render-safety gate skipped")
    out = _run(_RR_DRIVER, tmp_path,
               payload={"blind": _dossiers_for_explorer(True), "clean": _dossiers_for_explorer(False)})
    blind, clean = out["blind"], out["clean"]
    assert blind["len"] > 0 and clean["len"] > 0, "the card rendered nothing — the probe proved nothing"

    assert not blind["green_badge"], (
        "the asset risk register still badges a fleet with 8-of-11 un-collected axes 'no stacked risk' "
        "in the clean-green tone — that is a collection gap read as a clean bill of health")
    assert not blind["green_pill"] and not blind["green_bar"], (
        "the band pill / risk bar are still green for an asset banded on absent evidence")
    assert blind["gap_pill"] and blind["coverage_badge"], (
        "the coverage gap is not disclosed anywhere on the card")

    # NON-VACUITY: an actually-assessed Low asset must KEEP the green treatment, or the guard is
    # always-on and proves nothing.
    assert clean["green_badge"] and clean["green_pill"] and clean["green_bar"], (
        "the fix greyed out a genuinely assessed clean fleet — the disclosure is unconditional")
    assert not clean["gap_pill"] and not clean["coverage_badge"], (
        "a fully-assessed fleet acquired the coverage-gap disclosure")


# --------------------------------------------------------------------------- 5. interview auto-answer
# U1-3: the assessment-brief interview auto-answers a question when an ABQ_AUTO rule returns a truthy
# string. The lifecycle rule returned a BAND CENSUS -- on an all-Unknown fleet that is the string
# "Unknown: 12", which is truthy. The question was stamped with a green "evidence" pill, counted as
# "auto-answered from collected evidence" and skipped out of "left for the humans in the room": the
# coverage gap was used as the proof that there is no gap.
_ABQ_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
function ask(snap){globalThis.__SNAP=snap;EV('SNAP=globalThis.__SNAP');
  globalThis.__IT={id:"lc-01",domain:"Routing & Switching",question:P.q,go_no_go:false};
  const r=EV('abqAuto')(globalThis.__IT);
  return r?{ev:String(r.ev||""),gap:+r.gap||0,total:+r.total||0}:null;}
process.stdout.write(JSON.stringify({
  all_unknown:ask(P.all_unknown), partial:ask(P.partial), clean:ask(P.clean)}));
"""

_LC_Q = "What is the hardware lifecycle / end-of-life status of the installed switches?"


def test_interview_never_auto_answers_from_an_all_unassessed_census(tmp_path):
    """[U1-3 false-health] An all-Unknown lifecycle census is not evidence about lifecycle. Pre-fix the
    rule returned the truthy string "Unknown: 12" and the question left the human queue."""
    if not NODE:
        pytest.skip("node absent — executed render-safety gate skipped")
    payload = {
        "q": _LC_Q,
        "all_unknown": {"lifecycle_risk": {"summary": {"by_band": {"Unknown": 12},
                                                       "n_unknown": 12, "n_devices": 12}}},
        "partial": {"lifecycle_risk": {"summary": {"by_band": {"Active": 9, "Unknown": 3},
                                                   "n_unknown": 3, "n_devices": 12}}},
        "clean": {"lifecycle_risk": {"summary": {"by_band": {"Active": 10, "Past-EoS": 2},
                                                 "n_unknown": 0, "n_devices": 12}}},
    }
    out = _run(_ABQ_DRIVER, tmp_path, payload=payload)

    assert out["all_unknown"] is None, (
        "an all-Unknown band census still auto-answers the EoL question: " + repr(out["all_unknown"]))

    # a PARTIAL census is still usable evidence — but it must be labelled, and it must say for how many
    # devices it does NOT answer the question.
    part = out["partial"]
    assert part is not None, "a mostly-assessed census should still auto-answer"
    assert part["gap"] == 3 and part["total"] == 12, part
    assert "NOT ASSESSED" in part["ev"] and "coverage gap" in part["ev"], part["ev"]

    # NON-VACUITY: a fully-assessed census answers exactly as before, with NO coverage qualification —
    # otherwise the guard is always-on and the label means nothing.
    clean = out["clean"]
    assert clean is not None and clean["gap"] == 0, clean
    assert "NOT ASSESSED" not in clean["ev"] and "coverage gap" not in clean["ev"], clean["ev"]
    assert "Pre-EoS date band: 10" in clean["ev"], clean["ev"]


# --------------------------------------------------------------------------- 6. three-mirror coverage rule
# review r8 F1. The dossier axis-coverage rule exists THREE times -- cisco_toolkit/excel.py::dossier_coverage
# (canonical), the explorer's rrCoverage() and webapp/frontend/src/pages/Snapshot.tsx::dossierCoverage. The
# previous round shipped all three as `thin = n_axes && na*2 >= n_axes`, which evaluates FALSE when n_axes is
# 0 -- i.e. on exactly the input the n_na fallback branch beside it was written for. A dossier with NO axis
# data therefore reported "not thin", and an asset nobody could assess rendered as an assessed one: absence
# rendered as health, inside the guard that exists to close absence rendered as health.
#
# Python, embedded JS and TSX cannot import one module, so "one rule" is enforced by EXECUTION: this gate
# drives all three implementations over the single case table excel.DOSSIER_COVERAGE_CASES and fails the
# moment any mirror disagrees with the canonical Python. A regex over the sources could not do this -- it
# would pass on a rule "fixed" in one file and reverted in another.
_TSX = ROOT / "webapp" / "frontend" / "src" / "pages" / "Snapshot.tsx"

_MIRROR_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
const dossierCoverage=new Function(P.tsx_src+"\\nreturn dossierCoverage;")();
const out={explorer:{},tsx:{}};
for(const k of Object.keys(P.cases)){
  const d=P.cases[k];
  const a=EV('rrCoverage')(d); out.explorer[k]=[a.na,a.n,!!a.thin];
  const b=dossierCoverage(d);  out.tsx[k]=[b.na,b.n,!!b.thin];}
process.stdout.write(JSON.stringify(out));
"""


def _tsx_dossier_coverage_js() -> str:
    """The TSX mirror as runnable JS: the real function body out of the real file, with its TypeScript
    annotations removed. If the strip is wrong node throws and _run() fails the test loudly; if the
    extraction grabbed the wrong text the case-table comparison fails. Neither can pass silently."""
    src = _TSX.read_text(encoding="utf-8")
    m = re.search(r"^function dossierCoverage\(.*?^\}", src, re.S | re.M)
    assert m, "Snapshot.tsx no longer declares a top-level `function dossierCoverage(`"
    body = m.group(0)
    assert "exposures" in body and "n_na" in body and "thin" in body, body
    body = re.sub(r"\)\s*:\s*\{[^{}]*\}\s*\{", ") {", body, count=1)   # return-type annotation
    body = body.replace(": any", "")                                    # parameter annotations
    assert ":" not in body.split("{", 1)[0], f"a type annotation survived the strip: {body!r}"
    return body


@pytest.mark.skipif(not NODE, reason="node is not available")
def test_dossier_coverage_rule_is_identical_in_all_three_mirrors(tmp_path):
    """One rule, three runtimes, executed against one table.

    Pre-fix all three returned thin=False for every no-census case ("no_exposures_key",
    "exposures_empty_list", "exposures_not_a_list", "no_census_but_n_na", "no_census_n_na_junk"), so a
    dossier that published no axis data at all rendered exactly like a fully assessed one.
    """
    from cisco_toolkit.excel import DOSSIER_COVERAGE_CASES, dossier_coverage

    cases = {k: v[0] for k, v in DOSSIER_COVERAGE_CASES.items()}
    expected = {k: list(v[1]) for k, v in DOSSIER_COVERAGE_CASES.items()}

    # NON-VACUITY of the table itself: it must exercise BOTH verdicts, or "all three agree" could be
    # satisfied by three implementations that always say the same single thing.
    thins = {k for k, v in expected.items() if v[2]}
    assert thins and (set(expected) - thins), expected
    # and it must contain the regression's own input class: a census-absent dossier expected THIN.
    assert expected["no_exposures_key"] == [0, 0, True], expected["no_exposures_key"]

    py = {k: list(dossier_coverage(d)) for k, d in cases.items()}       # canonical
    assert py == expected, f"the canonical Python rule drifted from its own table: {py!r}"

    out = _run(_MIRROR_DRIVER, tmp_path,
               payload={"cases": cases, "tsx_src": _tsx_dossier_coverage_js()})
    assert out["explorer"] == expected, (
        "blast_radius_explorer.html::rrCoverage disagrees with cisco_toolkit/excel.py::dossier_coverage "
        f"(canonical): {out['explorer']!r}")
    assert out["tsx"] == expected, (
        "webapp/frontend/src/pages/Snapshot.tsx::dossierCoverage disagrees with "
        f"cisco_toolkit/excel.py::dossier_coverage (canonical): {out['tsx']!r}")


# --------------------------------------------------------------------------- 7. the assistant's four exits
# review r8 F5. riskRegisterCard() was qualified in the previous round; the assistant panel renders the SAME
# dossier fact through FOUR more exits in the SAME file -- abH_profile, abH_migrate, abH_risky and abH_fleet
# -- each of which passed risk_band straight to abPill(). AB_PILL maps "low" -> pl-ok, so an asset whose 8
# of 11 risk axes were never collected answered a direct question ("tell me about sw0", "what if I migrate
# sw0", "top risky devices", "fleet overview") with the clean-green pill. A fix applied to one card is not
# a fix: every exit rendering the fact has to carry the qualification.
_EXITS_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
function kv(h,label){const i=h.indexOf('>'+label+'<'); if(i<0)return "";
  const j=h.indexOf('</div>',i); return j<0?h.slice(i):h.slice(i,j+6);}
function shot(snap){
  globalThis.__S=snap; EV('load')(globalThis.__S,'T',false);
  const profile=EV('abH_profile')(P.host).html, migrate=EV('abH_migrate')(P.host).html;
  const risky=EV('abH_risky')().html, fleet=EV('abH_fleet')().html;
  const cell=(h,l)=>{const c=kv(h,l);return {found:c.length>0,green:c.indexOf('pl-ok')>=0,
    gap:c.indexOf('NOT ASSESSED')>=0};};
  return {profile:cell(profile,'Compound risk'), migrate:cell(migrate,'Compound risk'),
          fleet:cell(fleet,'Risk bands'),
          risky:{found:risky.length>0, green:risky.indexOf('pill pl-ok')>=0,
                 gap:risky.indexOf('NOT ASSESSED')>=0}};}
process.stdout.write(JSON.stringify({blind:shot(P.blind),clean:shot(P.clean)}));
"""

_EXIT_HOSTS = ["sw0", "sw1", "sw2"]


def _dossier_fabric(blind):
    """A snapshot the assistant panel can actually answer from: a real (tiny) topology over the same
    hosts the REAL dossier producer was run on, so MODEL / failureImpact resolve and the four handlers
    render their normal output instead of an early 'not in this snapshot' stub."""
    ifaces = {"core1": {}}
    for i, h in enumerate(_EXIT_HOSTS, 1):
        ifaces["core1"]["Gi1/0/%d" % i] = {"cdp_neighbor": h, "neighbor_port": "Gi0/1",
                                           "switchport_mode": "trunk", "status": "connected"}
        ifaces[h] = {
            "Gi0/1": {"cdp_neighbor": "core1", "neighbor_port": "Gi1/0/%d" % i,
                      "switchport_mode": "trunk", "status": "connected"},
            "Gi0/2": {"switchport_mode": "access", "vlan": "10", "status": "connected",
                      "end_host_mac": "0011.2233.44%02d" % i, "end_host_ip": "10.0.10.%d" % (50 + i)},
        }
    devices = {h: {"model": "C9300-48P", "sw_version": "17.9.4", "collected": True}
               for h in _EXIT_HOSTS + ["core1"]}
    return {"schema": "collect_parse_snapshot/1", "interfaces": ifaces, "devices": devices,
            "device_dossiers": _dossiers_for_explorer(blind)}


def test_assistant_dossier_exits_all_qualify_a_band_computed_on_absent_evidence(tmp_path):
    """[r8 F5] Four exits, one fact. Each must disclose that the band rests on axes nobody collected."""
    if not NODE:
        pytest.skip("node absent - executed render-safety gate skipped")
    out = _run(_EXITS_DRIVER, tmp_path,
               payload={"host": _EXIT_HOSTS[0],
                        "blind": _dossier_fabric(True), "clean": _dossier_fabric(False)})
    blind, clean = out["blind"], out["clean"]
    for exit_name in ("profile", "migrate", "risky", "fleet"):
        assert blind[exit_name]["found"], (
            "abH_%s rendered no dossier cell at all - the probe proved nothing" % exit_name)
        assert clean[exit_name]["found"], "abH_%s (clean fixture) rendered no dossier cell" % exit_name
        assert blind[exit_name]["gap"], (
            "abH_%s renders the dossier risk band of an asset whose axes were 8-of-11 un-collected "
            "with NO coverage qualification - a collection gap answered as a result" % exit_name)
        # NON-VACUITY: the fully-assessed fleet must NOT acquire the disclosure, or it is unconditional
        # and means nothing.
        assert not clean[exit_name]["gap"], (
            "abH_%s put the coverage-gap wording on a fully-assessed fleet" % exit_name)

    # the green pill is the fastest read: gone on the blind fixture, intact on the clean one
    for exit_name in ("profile", "migrate", "risky"):
        assert not blind[exit_name]["green"], (
            "abH_%s still paints the un-evidenced band with the clean-green pill" % exit_name)
        assert clean[exit_name]["green"], (
            "abH_%s greyed out a genuinely assessed Low asset - the guard is unconditional" % exit_name)


_FLEET_ABSENT_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
globalThis.__S=P.snap; EV('load')(globalThis.__S,'T',false);
const h=EV('abH_fleet')().html;
const i=h.indexOf('>Risk bands<'), j=h.indexOf('</div>',i);
const cell=i<0?"":h.slice(i,j+6);
process.stdout.write(JSON.stringify({found:cell.length>0,gap:cell.indexOf('NOT ASSESSED')>=0}));
"""


def test_fleet_band_census_without_a_per_asset_census_is_not_assessed_not_clean(tmp_path):
    """FAIL-CLOSED companion: a snapshot publishing the risk-band ROLLUP but no per-asset axis census
    gives no basis to say how much of that rollup rests on evidence. A count of 0 thin assets there
    means 'not measured', and must not read as 'nothing wrong'."""
    if not NODE:
        pytest.skip("node absent - executed render-safety gate skipped")
    snap = _dossier_fabric(False)
    snap["device_dossiers"] = {"summary": snap["device_dossiers"]["summary"]}   # rollup only, no per_device
    out = _run(_FLEET_ABSENT_DRIVER, tmp_path, payload={"snap": snap})
    assert out["found"], "abH_fleet rendered no risk-band cell - the probe proved nothing"
    assert out["gap"], (
        "abH_fleet published a risk-band census with no per-asset coverage census behind it and made no "
        "coverage claim either way - the reader cannot tell a measured 0 from an unmeasured one")


# --------------------------------------------------------------------------- #
# R8 / on-air renderers: the multicast "on-air" classification is CURATED
# --------------------------------------------------------------------------- #
# `on_air` / `has_av` come ENTIRELY from the offline registry's curated broadcast/category fields
# (analyze.compute_multicast_intelligence), and `has_av` is what promotes a MAC-alias clash to High.
# The explorer rendered a bare "on-air" pill, a bare group name/category pill and a bare
# "N broadcast/AV" headline, so a curated hypothesis reached the reader in the same voice as an
# observed measurement. These probes EXECUTE the real render functions and read the emitted HTML.


def _real_multicast_snapshot(groups):
    """A snapshot whose multicast half comes from the REAL producers, not a hand-shaped dict.

    portdb decides that 224.0.1.129 is the curated-only "PTP-primary" (Broadcast-AV,
    semantics_authoritative False) and that 225.0.1.129 / 239.70.70.70 match nothing at all; the
    Vlan30 interface carries real `multicast_info`, which is what makes the section render."""
    from cisco_toolkit.analyze import compute_multicast_intelligence, compute_service_map
    from cisco_toolkit.model import InterfaceData
    svi = InterfaceData(port="Vlan30")
    svi.multicast_info = "PIM sparse-mode"
    ifaces = {"access1": {"Vlan30": svi}}
    sm = compute_service_map({}, ifaces, igmp_groups=list(groups))
    mi = compute_multicast_intelligence(sm, ifaces)
    snap = _fabric()
    snap["service_map"] = sm
    snap["multicast_intelligence"] = mi
    return snap


_MCAST_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
EV('load')(P.snap,'T',false);
const html=EV('serviceMapSection')();
const eps=EV('EPALL');
const src=eps[0]||{host:'access1',port:'Gi0/2',vlan:'10',ip:'10.0.10.50',mac:'0011.2233.4401'};
const J=EV('buildMulticastJourney')(src,P.group);
const b64=s=>Buffer.from(String(s||""),'utf8').toString('base64');
// base64 so stdout stays pure ASCII: the rendered strings carry em-dashes and this
// process is decoded with the Windows console codepage.
process.stdout.write(JSON.stringify({html:b64(html),journey:b64(J?JSON.stringify(J):""),
  app_why:b64((J&&J.app&&J.app.why)||"")}));
"""


def _render(snap, tmp_path, group="224.0.1.129"):
    import base64
    raw = _run(_MCAST_DRIVER, tmp_path, payload={"snap": snap, "group": group})
    return {k: base64.b64decode(v).decode("utf-8") for k, v in raw.items()}


def test_explorer_multicast_render_discloses_the_curated_basis(tmp_path):
    """Every on-air surface in the drawer + the multicast flow journey must name what the label
    rests on. The severity is NOT re-scored - the fix is disclosure."""
    if not NODE:
        pytest.skip("node absent - executed render-safety gate skipped")
    snap = _real_multicast_snapshot(["224.0.1.129", "225.0.1.129", "239.70.70.70"])
    mi = snap["multicast_intelligence"]
    # fixture non-vacuity: the PRODUCER really hands the page a non-authoritative on-air label
    assert mi["summary"]["n_av_groups"] == 1 and mi["summary"]["n_av_groups_authoritative"] == 0
    assert mi["mac_aliases"][0]["has_av"] is True
    assert mi["mac_aliases"][0]["has_av_authoritative"] is False

    out = _render(snap, tmp_path)
    html = out["html"]
    assert html, "serviceMapSection rendered nothing - the probe proved nothing"
    # 1. the AV headline
    assert "ALL curated, NOT an authoritative source" in html, html[-1600:]
    assert "2 unclassified (no registry match)" in html, html[-1600:]
    # 2. the MAC-alias on-air pill (the flag the producer promotes the clash to High on)
    assert "on-air (curated)" in html, html[-1600:]
    assert "raises the clash to High severity" in html, html[-1600:]
    # 3. the classified-group pills: curated vs a group with no registry match at all
    assert "&gt;curated&lt;" not in html          # the pill is markup, not escaped text
    assert ">curated</span>" in html, html[-1600:]
    assert ">unclassified</span>" in html, html[-1600:]
    # 4. the flow journey's L7 rungs
    assert "classified Broadcast-AV / on-air by curated offline registry semantics" in out["app_why"], out["app_why"]
    assert "NOT an authoritative source" in out["journey"], out["app_why"]
    assert "rests on the media classification (curated)" in out["journey"]


def test_explorer_multicast_render_clean_case_gains_no_caveat(tmp_path):
    """NON-VACUITY: with no on-air member the page must NOT acquire the curated-AV language, or the
    disclosure is always-on and carries no information."""
    if not NODE:
        pytest.skip("node absent - executed render-safety gate skipped")
    snap = _real_multicast_snapshot(["239.70.70.70", "238.70.70.70"])
    assert snap["multicast_intelligence"]["summary"]["n_av_groups"] == 0
    assert snap["multicast_intelligence"]["mac_aliases"][0]["has_av"] is False
    out = _render(snap, tmp_path, group="239.70.70.70")
    html = out["html"]
    assert "0 broadcast/AV" in html, html[-1200:]
    assert "ALL curated, NOT an authoritative source" not in html, html[-1200:]
    assert "on-air (curated)" not in html, html[-1200:]
    assert "raises the clash to High severity" not in html, html[-1200:]
    assert "Broadcast-AV / on-air" not in out["app_why"], out["app_why"]


def test_explorer_multicast_render_says_verified_when_the_registry_vouches(tmp_path):
    """NON-VACUITY (second axis): the tag is a FUNCTION of the producer's labels, not the constant
    "curated". Nothing in the shipped pack is semantics-authoritative, so the branch is exercised by
    flipping the producer's own labels on the producer's own records."""
    if not NODE:
        pytest.skip("node absent - executed render-safety gate skipped")
    snap = _real_multicast_snapshot(["224.0.1.129", "225.0.1.129"])
    mi = snap["multicast_intelligence"]
    for g in mi["groups"] + snap["service_map"]["multicast"]["classified_groups"]:
        if g["group"] == "224.0.1.129":
            g["assignment_authoritative"] = True
            g["semantics_authoritative"] = True
            g["on_air_authoritative"] = True
    mi["mac_aliases"][0]["has_av_authoritative"] = True
    mi["summary"]["n_av_groups_authoritative"] = 1
    out = _render(snap, tmp_path)
    html = out["html"]
    assert "1 registry-verified" in html, html[-1400:]
    assert "ALL curated" not in html, html[-1400:]
    assert "on-air (registry-verified)" in html, html[-1400:]
    # a group the registry fully vouches for loses its caveat pill entirely (nothing to disclose);
    # the one that still matches nothing keeps its own, distinct state.
    assert ">curated</span>" not in html, html[-1400:]
    assert ">unclassified</span>" in html, html[-1400:]
    assert "registry-verified media semantics" in out["app_why"], out["app_why"]


def test_explorer_multicast_render_fails_closed_without_a_published_basis(tmp_path):
    """COVERAGE-HONEST: an older snapshot publishes no basis. Absence must read "not published",
    never as verified. The "older" shape is produced by DELETING fields from real producer output."""
    if not NODE:
        pytest.skip("node absent - executed render-safety gate skipped")
    snap = _real_multicast_snapshot(["224.0.1.129", "225.0.1.129"])
    mi = snap["multicast_intelligence"]
    for g in mi["groups"] + snap["service_map"]["multicast"]["classified_groups"]:
        for k in ("assignment_authoritative", "semantics_authoritative", "overlay_status",
                  "on_air_authoritative"):
            g.pop(k, None)
    mi["mac_aliases"][0].pop("has_av_authoritative", None)
    mi["summary"].pop("n_av_groups_authoritative", None)
    out = _render(snap, tmp_path)
    html = out["html"]
    assert "classification basis not published" in html, html[-1400:]
    assert "on-air (basis not published)" in html, html[-1400:]
    assert "registry-verified" not in html, html[-1400:]
    assert "classification basis not published by this snapshot" in out["app_why"], out["app_why"]


# ------------------------------------------------------- 6. the PUNCH-LIST's severity basis
# review r10 EXIT Y. compute_migration_punchlist's media fold publishes, per ITEM, why the row holds
# the severity it does: `severity_basis` + `evidence_confidence` (analyze.py :4386). It exists because
# a mac-alias row is raised Medium->High purely on a CURATED, explicitly non-authoritative on-air
# classification -- not on a measurement. The fold ALSO appends that prose into `detail`, which is what
# the workbook's Detail column and AssessHub's PunchTable print; `punchlistCard` renders
# severity/priority/title/category and NEVER `detail`, so on THIS surface the structured keys reached
# nothing and a curated High was byte-identical to a measured one. These gates EXECUTE the card.
_PUNCH_DRIVER = """
const EV=globalThis.__EV;
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
EV('load')(P.snap,'T',false);
const card=EV('punchlistCard')();
const cnt=(h,s)=>h.split(s).length-1;
// A build with NO basis consumer at all has no punchBasis/PL_* bindings. Probe defensively so the
// test that runs against it fails on the RENDERED CARD (the defect) instead of dying in the driver.
const get=n=>{try{return EV(n);}catch(e){return null;}};
const pb=get('punchBasis');
const res={card:card, has_consumer:!!pb,
  published_notes:cnt(card,'>severity basis</span>'),
  unpublished_notes:cnt(card,'>severity basis NOT published</span>'),
  // punchBasis() per item, aligned with SNAP.punchlist order; null = the item declares no basis
  // at all, which is what an ordinary (non-media) row must stay.
  basis:pb?(EV('SNAP').punchlist||[]).map(i=>pb(i)):[],
  basis_const:get('PL_BASIS_UNPUBLISHED'), conf_const:get('PL_CONFIDENCE_UNPUBLISHED'),
  // does the JS classifier agree with the PRODUCER's own two sentinels, and does it leave a real
  // basis alone? (the coupling that makes 'not published' a distinguishable state at all)
  py_sentinel_unpublished:pb?pb({severity_basis:P.py_basis,evidence_confidence:P.py_conf}).published:null,
  real_basis_published:pb?pb({severity_basis:P.real_basis}).published:null};
// base64 so stdout stays pure ASCII: the producer's prose carries em-dashes and this process is
// decoded with the Windows console codepage.
process.stdout.write(JSON.stringify(
  {b64:Buffer.from(JSON.stringify(res),'utf8').toString('base64')}));
"""


def _punchlist_snapshot(groups=("224.0.1.129", "225.0.1.129"), drift=True):
    """A snapshot whose punch-list is REAL producer output, not a hand-shaped list.

    `_real_multicast_snapshot` already drives compute_service_map -> compute_multicast_intelligence;
    its risks are then folded by the real compute_migration_punchlist. That one fixture yields BOTH
    contract states, because the producer itself is asymmetric: the mac-alias row publishes a curated
    basis, and `querier-gap` publishes none (its High is a measurement) so the fold stamps its
    fail-closed sentinel. The drift row is an ordinary punch-list item that touches no media at all --
    the non-vacuity control.
    """
    from cisco_toolkit.analyze import compute_migration_punchlist
    snap = _real_multicast_snapshot(list(groups))
    risks = [r for r in snap["multicast_intelligence"]["risks"]
             if r.get("kind") in ("mac-alias", "querier-gap")]
    d = [{"severity": "High", "category": "False-health", "devices": ["core1"],
          "title": "Interface counters frozen", "detail": "counters stopped advancing",
          "remediation": "re-seat / replace"}] if drift else []
    snap["punchlist"] = compute_migration_punchlist([], {}, {}, [], [], [], {}, [], [],
                                                    media_risks=risks, drift=d)
    return snap


def _punch_render(snap, tmp_path):
    import base64
    from cisco_toolkit.analyze import PUNCH_BASIS_UNPUBLISHED, PUNCH_CONFIDENCE_UNPUBLISHED
    real = next((i.get("severity_basis") for i in snap["punchlist"]
                 if "NOT an authoritative source" in str(i.get("severity_basis", ""))),
                "raised to High because a member group is classified Broadcast-AV / on-air by "
                "curated offline registry semantics")
    raw = _run(_PUNCH_DRIVER, tmp_path,
               payload={"snap": snap, "py_basis": PUNCH_BASIS_UNPUBLISHED,
                        "py_conf": PUNCH_CONFIDENCE_UNPUBLISHED, "real_basis": real})
    return json.loads(base64.b64decode(raw["b64"]).decode("utf-8"))


def _by_title(snap, out):
    assert out["has_consumer"], (
        "punchlistCard exposes no severity-basis consumer at all — the producer's `severity_basis` "
        "/ `evidence_confidence` reach nothing on this surface")
    return {i["title"]: b for i, b in zip(snap["punchlist"], out["basis"])}


def test_punchlist_card_shows_that_a_high_row_rests_on_a_curated_classification(tmp_path):
    """The card ranked a curated-basis High and a measured High identically and said nothing about
    the difference -- the whole reason the producer publishes the two keys."""
    if not NODE:
        pytest.skip("node absent — executed render-safety gate skipped")
    snap = _punchlist_snapshot()
    # fixture non-vacuity, asserted on the PRODUCER: the High really does rest on a curated label
    ali = snap["multicast_intelligence"]["mac_aliases"][0]
    assert ali["has_av"] and not ali["has_av_authoritative"], ali
    mac = next(i for i in snap["punchlist"] if i["title"].startswith("Multicast MAC-address overlap"))
    assert mac["severity"] == "High" and "NOT an authoritative source" in mac["severity_basis"]

    out = _punch_render(snap, tmp_path)
    card = out["card"]
    assert card, "punchlistCard rendered nothing — the probe proved nothing"
    assert mac["title"] in card, "the row under test is not even on the card"
    assert "NOT an authoritative source" in card, (
        "the punch-list card renders a High whose severity rests on a CURATED, explicitly "
        "non-authoritative on-air classification with no sign of it — identical to a measured "
        "High. The producer published the reason in `severity_basis`; nothing here read it.\n"
        + card[-1800:])
    assert "curated, unverified" in card, "`evidence_confidence` never reached the page:\n" + card[-1800:]
    assert out["published_notes"] == 1, out["published_notes"]
    # the roll-up reads the same structured keys as data, over the WHOLE list
    assert "2 items carry one — 1 published, 1 not" in card, card[:900]

    # NON-VACUITY: the ordinary row must not acquire any of this. It declares no basis, so
    # punchBasis() returns null for it and it gets no note at all.
    bt = _by_title(snap, out)
    assert bt["Interface counters frozen"] is None, bt["Interface counters frozen"]
    assert bt[mac["title"]]["published"] is True
    assert "Interface counters frozen" in card
    notes = out["published_notes"] + out["unpublished_notes"]
    assert notes == sum(1 for b in out["basis"] if b), (
        "the number of rendered basis notes disagrees with the number of items that actually "
        "declare a basis — rows are gaining or losing the disclosure")


def test_punchlist_card_keeps_an_unpublished_basis_distinguishable(tmp_path):
    """`querier-gap` publishes no basis of its own (its High IS a measurement), so the fold stamps
    the producer's sentinel. That row must render as its own visibly different state -- not as a
    published basis, and not as silence."""
    if not NODE:
        pytest.skip("node absent — executed render-safety gate skipped")
    snap = _punchlist_snapshot()
    gap = next(i for i in snap["punchlist"] if "IGMP querier" in i["title"])
    assert "NOT published by this snapshot" in gap["severity_basis"], gap

    out = _punch_render(snap, tmp_path)
    card = out["card"]
    assert "severity basis NOT published by this snapshot" in card, (
        "a row whose basis the snapshot never published renders exactly like one that did:\n"
        + card[-1800:])
    # the two states must not render through the same pill
    assert ">severity basis NOT published</span>" in card
    assert ">severity basis</span>" in card
    assert out["unpublished_notes"] == 1 and out["published_notes"] == 1, out
    bt = _by_title(snap, out)
    assert bt[gap["title"]]["published"] is False, bt[gap["title"]]


def test_punchlist_card_fails_closed_on_a_declared_but_unusable_basis(tmp_path):
    """FAIL CLOSED on the VALUE, not on the key. A null / blank / non-string basis satisfies a
    key-PRESENCE test and then renders as an empty field a reader takes for 'nothing to disclose'.
    (Today's producer always writes a usable string, so this state is only reachable from a
    hand-edited or future snapshot -- which is exactly why the renderer must not trust it.)"""
    if not NODE:
        pytest.skip("node absent — executed render-safety gate skipped")
    for bad in (None, "   ", {"a": 1}, 0, []):
        snap = _punchlist_snapshot()
        mac = next(i for i in snap["punchlist"] if i["title"].startswith("Multicast MAC-address"))
        mac["severity_basis"] = bad
        mac["evidence_confidence"] = bad
        out = _punch_render(snap, tmp_path)
        card = out["card"]
        # not rendered as a blank field, and not as though the severity had been measured
        assert "severity basis NOT published by this snapshot" in card, (bad, card[-1500:])
        assert "evidence confidence NOT published by this snapshot" in card, (bad, card[-1500:])
        assert out["published_notes"] == 0, (bad, card[-1500:])
        assert out["unpublished_notes"] == 2, (bad, card[-1500:])
        assert "NOT an authoritative source" not in card, (
            bad, "the curated prose survived a value that is no longer usable")
        bt = _by_title(snap, out)
        assert bt[mac["title"]] is not None, (bad, "the row silently left the basis contract")
        assert bt[mac["title"]]["published"] is False, (bad, bt[mac["title"]])


def test_punchlist_card_adds_nothing_to_a_fleet_with_no_media_rows(tmp_path):
    """NON-VACUITY, the whole-card axis: on a fleet whose punch-list carries no basis-bearing row
    the card must be exactly what it always was — no per-row note AND no roll-up line. A disclosure
    that is always on carries no information."""
    if not NODE:
        pytest.skip("node absent — executed render-safety gate skipped")
    from cisco_toolkit.analyze import compute_migration_punchlist
    pl = compute_migration_punchlist(
        [], {}, {}, [], [], [], {}, [], [],
        drift=[{"severity": "High", "category": "False-health", "devices": ["core1"],
                "title": "Interface counters frozen", "detail": "counters stopped advancing",
                "remediation": "re-seat / replace"}])
    assert pl and not any("severity_basis" in i or "evidence_confidence" in i for i in pl), pl
    out = _punch_render(dict(_fabric(), punchlist=pl), tmp_path)
    card = out["card"]
    assert "Interface counters frozen" in card, "the card did not render — the probe proved nothing"
    assert out["published_notes"] == 0 and out["unpublished_notes"] == 0, card
    assert "Severity basis:" not in card, card
    assert "not published" not in card.lower(), card
    assert all(b is None for b in out["basis"]), out["basis"]


def test_punchlist_card_basis_sentinel_matches_the_producers_wording(tmp_path):
    """The explorer and the workbook must never disagree about what an unpublished basis MEANS, so
    the card's fallback text is the producer's own constant and its 'not published' classifier is
    pinned to the producer's own wording. A re-word on either side fails here instead of silently
    turning the fail-closed state back into a blank."""
    if not NODE:
        pytest.skip("node absent — executed render-safety gate skipped")
    from cisco_toolkit.analyze import PUNCH_BASIS_UNPUBLISHED, PUNCH_CONFIDENCE_UNPUBLISHED
    out = _punch_render(_punchlist_snapshot(), tmp_path)
    assert out["basis_const"] == PUNCH_BASIS_UNPUBLISHED, out["basis_const"]
    assert out["conf_const"] == PUNCH_CONFIDENCE_UNPUBLISHED, out["conf_const"]
    assert out["py_sentinel_unpublished"] is False, (
        "the card no longer recognises analyze.PUNCH_BASIS_UNPUBLISHED as 'not published' — it "
        "would render the producer's absence-disclosure as though a basis had been published")
    assert out["real_basis_published"] is True, (
        "a genuine published basis is being classified as unpublished — the guard over-rejects "
        "and the distinction it exists to draw is gone")


_PLU_DRIVER = """
const EV=globalThis.__EV;
const f=EV('_plUnpublished'), u=EV('_plUsable');
const P=JSON.parse(require('fs').readFileSync(process.argv[2],'utf-8'));
process.stdout.write(JSON.stringify({unpub:P.map(s=>!!f(s)), usable:P.map(s=>!!u(s))}));
"""


@pytest.mark.skipif(not NODE, reason="node is not available")
def test_an_unpublished_basis_is_detected_by_the_sentinel_marker_not_by_ordinary_prose(tmp_path):
    """The published/not-published split is the one distinction this consumer exists to make, and it
    was decided by `/not\s+published/i` -- a substring ORDINARY PROSE contains.

    A real basis reading "the vendor advisory was not published at capture time" is an EXPLANATION;
    matching it would relabel it as the ABSENCE of an explanation, i.e. silently convert a finding
    that states its grounds into one that says it has none. Two states separated by whether the
    sentence happens to contain two common words.

    Matched instead on "published by this snapshot" -- the marker both producer sentinels carry and no
    ordinary sentence does. Pinned against the REAL producer constants so a re-word fails here.
    """
    from cisco_toolkit.analyze import PUNCH_BASIS_UNPUBLISHED, PUNCH_CONFIDENCE_UNPUBLISHED

    sentinels = [PUNCH_BASIS_UNPUBLISHED, PUNCH_CONFIDENCE_UNPUBLISHED]
    prose = ["the vendor advisory was not published at capture time",
             "PSIRT bulletin not published for this train",
             "raised to High because a member group is classified Broadcast-AV / on-air"]
    blank = ["", "   ", "\t\n "]
    out = _run(_PLU_DRIVER, tmp_path, payload=sentinels + prose + blank)

    n_s, n_p = len(sentinels), len(prose)
    assert all(out["unpub"][:n_s]), "a producer sentinel was not recognised as an unpublished basis"
    assert not any(out["unpub"][n_s:n_s + n_p]), (
        "ordinary basis prose containing 'not published' was misread as HAVING NO BASIS")

    # NON-VACUITY: real prose must still register as a usable basis, or the guard has simply been
    # turned off rather than tightened.
    assert all(out["usable"][n_s:n_s + n_p]), "a real basis stopped counting as usable"
    # and genuinely empty/whitespace input is rejected UPSTREAM by _plUsable -- the two helpers divide
    # the work, so neither is asserted to do the other's job.
    assert not any(out["usable"][n_s + n_p:]), "blank/whitespace passed the usability check"
