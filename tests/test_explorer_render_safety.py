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
