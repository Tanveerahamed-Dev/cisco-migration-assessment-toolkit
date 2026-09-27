"""Per-finding EVIDENCE POINTERS on every punch-list row (Atlas Scope SSOT program, A1 at the source).

Contract (owner: ``analyze.compute_migration_punchlist``; registry row: docs/ssot.md "per-finding
evidence pointers"):

* every row carries ``evidence_basis`` in {"record", "row", "absence"} -- ALWAYS written;
* every row carries ``evidence_refs``: a (possibly empty) list of
  ``{"kind", "host", "ref", "role", "cite"}`` where ``ref`` is an RFC 6901 JSON Pointer into the
  PUBLISHED snapshot -- a pointer, never a copy of the value it names;
* ``evidence_refs_total`` appears ONLY when the list was capped, and is the uncapped count.

The guards here are CLASS-wide, never a named subset: the resolution check walks EVERY punch-list
row of a real pipeline run (in-memory, on-disk and redacted forms), and the policy-completeness
check derives the categories the producer CAN emit from the producer's own AST.
"""
import ast
import inspect
import json
import os
import re
import sys
import tempfile

import pytest

import synthetic_fixtures as fx
from cisco_toolkit import analyze
from cisco_toolkit.analyze import (
    PUNCH_EVIDENCE_BASES,
    PUNCH_EVIDENCE_RECORD_KINDS,
    PUNCH_EVIDENCE_REF_KINDS,
    PUNCH_EVIDENCE_REFS_CAP,
    PUNCH_EVIDENCE_ROLES,
    _PUNCH_EVIDENCE_POLICY,
    _SECURITY_CHECK_EVIDENCE_BASIS,
    _json_pointer,
    compute_cross_layer_correlations,
    compute_migration_punchlist,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_GOLDEN_COLLECTION_STAMP = "20260807_000000"     # the golden harness's pinned evidence date
class _Missing:
    def __repr__(self):
        return "<missing>"


_MISSING = _Missing()


# ---------------------------------------------------------------------------------------------
# RFC 6901 resolution -- JSON semantics (object members are compared as strings), so the SAME
# resolver works on the in-memory snapshot (int dict keys, tuples) and on its JSON form.
# ---------------------------------------------------------------------------------------------
def _unescape(token):
    return token.replace("~1", "/").replace("~0", "~")


def resolve_pointer(doc, pointer):
    """The node `pointer` names in `doc`, or _MISSING."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return _MISSING
    node = doc
    for raw in pointer[1:].split("/"):
        tok = _unescape(raw)
        if isinstance(node, dict):
            hit = _MISSING
            for k, v in node.items():
                if str(k) == tok:
                    hit = v
                    break
            if hit is _MISSING:
                return _MISSING
            node = hit
        elif isinstance(node, (list, tuple)):
            if not tok.isdigit() or (len(tok) > 1 and tok[0] == "0"):
                return _MISSING
            i = int(tok)
            if i >= len(node):
                return _MISSING
            node = node[i]
        else:
            return _MISSING
    return node


def _sparse_on_disk_form(snap):
    """What COLLECT_PARSE writes: sparsify_interfaces + a compact JSON round trip."""
    from cisco_toolkit.html import sparsify_interfaces
    return json.loads(json.dumps(sparsify_interfaces(snap), default=str, separators=(",", ":")))


def explorer_embedded_form(snap):
    """The snapshot as the single-file explorer ACTUALLY embeds it: write the real explorer with
    html.write_html_explorer and parse its `EMBEDDED_SNAPSHOT` back out. That embed is a published
    copy of the punch list (AssessHub serves it too), and html._slim_for_embed RE-FILTERS lists there
    (physical_health drops its Info/OK rows) -- so an index into a re-filtered list dangles or names
    another device's row only in this form."""
    from cisco_toolkit.html import write_html_explorer
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "explorer.html")
        write_html_explorer(path, snap, "evidence-pointer check")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    marker = "const EMBEDDED_SNAPSHOT="
    start = text.index(marker) + len(marker)
    end = text.index(";\nload(EMBEDDED_SNAPSHOT", start)
    return json.loads(text[start:end])


def published_forms(in_memory, on_disk):
    """Every form a punch-list row's pointers are read against: the in-memory snapshot, the on-disk
    engine form (sparsify_interfaces + compact dump), the written file, the whole-snapshot redaction,
    and the explorer embed of both the plain and the redacted snapshot."""
    from cisco_toolkit.html import redact_snapshot
    forms = []
    if in_memory is not None:
        forms += [("in-memory", in_memory), ("sparsified+compact", _sparse_on_disk_form(in_memory))]
    redacted = redact_snapshot(on_disk)
    forms += [("on-disk", on_disk), ("redacted", redacted),
              ("explorer-embed", explorer_embedded_form(on_disk)),
              ("explorer-embed redacted", explorer_embedded_form(redacted))]
    return forms


def _ref_problems(ref, devices, row_label):
    out = []
    if not isinstance(ref, dict) or set(ref) != {"kind", "host", "ref", "role", "cite"}:
        return [f"{row_label}: malformed ref {ref!r}"]
    if ref["kind"] not in PUNCH_EVIDENCE_REF_KINDS:
        out.append(f"{row_label}: kind {ref['kind']!r} not in the enum")
    if ref["role"] not in PUNCH_EVIDENCE_ROLES:
        out.append(f"{row_label}: role {ref['role']!r} not in the enum")
    if not isinstance(ref["cite"], str):
        out.append(f"{row_label}: cite is not a string")
    if ref["host"] is not None and ref["host"] not in devices:
        out.append(f"{row_label}: ref host {ref['host']!r} is neither null nor in the row's devices")
    if not (isinstance(ref["ref"], str) and ref["ref"].startswith("/")):
        out.append(f"{row_label}: ref {ref['ref']!r} is not an RFC 6901 pointer")
    return out


_OWNER_KEYS = ("switch", "host", "hostname")          # a record owned by ONE device
_OWNER_LIST_KEYS = ("hosts", "devices")                 # a finding row spanning several devices


def _owners_along(doc, pointer):
    """(decoded tokens, the device-name SETS carried by every dict on the path) -- nearest last."""
    tokens = [_unescape(t) for t in pointer[1:].split("/")] if isinstance(pointer, str) and pointer else []
    owners, node = [], doc
    for tok in tokens:
        node = resolve_pointer(node, "/" + tok.replace("~", "~0").replace("/", "~1"))
        if node is _MISSING:
            break
        if not isinstance(node, dict):
            continue
        found = None
        for key in _OWNER_KEYS:
            val = node.get(key)
            if isinstance(val, str) and val and not val.startswith("("):
                found = {val}
                break
        if found is None:
            for key in _OWNER_LIST_KEYS:
                val = node.get(key)
                if isinstance(val, list) and any(isinstance(v, str) and v for v in val):
                    found = {v for v in val if isinstance(v, str)}
                    break
        if found is not None:
            owners.append(found)
    return tokens, owners


def _host_witness_problem(tokens, owners, host):
    """None when `host` owns the record the pointer reaches, else why not."""
    if owners:
        return None if host in owners[-1] else f"resolves to a record of {sorted(owners[-1])[:4]}"
    return None if host in tokens else "nothing on its path names that host"


# A fold's OWN derived-from row must be the row the finding was built from, not merely a row of the
# same list (an index shifted by a re-sort or an upstream filter still resolves). Each entry pairs a
# pointer shape with the producer-side identity the punch row copies from it.
_OWN_ROW_IDENTITY = (
    (r"^/cross_layer/\d+$", ("Cross-layer",), lambda node, row: node.get("title", node.get("id")) == row["title"]),
    (r"^/operational_drift/\d+$", None, lambda node, row: node.get("title") == row["title"]),
    (r"^/security/[^/]+/findings/\d+$", ("Security",),
     lambda node, row: node.get("status") == "fail" and node.get("title") == row["title"]),
    (r"^/l3_forwarding/\d+$", ("L3",),
     lambda node, row: row["title"].replace(" ", "-") in str(node.get("risk", ""))),
    (r"^/protocol_health/\d+$", ("Protocol",), lambda node, row: str(node.get("protocol")) in row["title"]),
    (r"^/health_scores/\d+$", ("Health",), lambda node, row: str(node.get("band")) in row["title"]),
    (r"^/(syslog_intelligence/detections|qos_audit/findings|software_risk/findings|platform_health/findings)/\d+$",
     ("Operational logs", "QoS", "Software exposure", "Platform capacity"),
     lambda node, row: row["title"] in (node.get("label"), node.get("kind"))),
    (r"^/device_dossiers/per_device/\d+/compound/\d+$", ("Compound risk",),
     lambda node, row: row["title"].startswith(f"{node.get('code', '')}:")),
)


def _identity_problems(snap, ref, node, row, label):
    """The resolved node is the record the ref CLAIMS, not merely some non-null node.

    Class-wide: a ref naming a host must be witnessed by its own path -- the nearest dict on the path
    that carries a device name (switch / host / hostname, or a hosts / devices list for a finding that
    spans several devices) must name that host, or, where no node on the path names a device
    (interface records, per-host maps), the host must be one of the path tokens."""
    out = []
    ptr, host = ref.get("ref"), ref.get("host")
    tokens, owners = _owners_along(snap, ptr)
    if host is not None:
        why = _host_witness_problem(tokens, owners, host)
        if why:
            out.append(f"{label}: ref {ptr!r} claims host {host!r} but {why}")
    if isinstance(node, dict):
        for shape, cats, same in _OWN_ROW_IDENTITY:
            if re.match(shape, ptr) and (cats is None or row.get("category") in cats) and not same(node, row):
                out.append(f"{label}: ref {ptr!r} resolves to a DIFFERENT row than the one this finding "
                           f"was built from ({str(node.get('title') or node.get('label') or node)[:60]!r})")
    return out


def punchlist_evidence_problems(snap, form):
    """Every contract violation over EVERY punch-list row (and the upstream rows whose refs it carries)."""
    problems = []
    rows = snap.get("punchlist")
    if not isinstance(rows, list) or not rows:
        return [f"[{form}] no punch-list rows to check"]
    for n, row in enumerate(rows):
        label = f"[{form}] punchlist[{n}] {row.get('category')}: {row.get('title')!r}"
        basis = row.get("evidence_basis", _MISSING)
        refs = row.get("evidence_refs", _MISSING)
        if basis not in PUNCH_EVIDENCE_BASES:
            problems.append(f"{label}: evidence_basis {basis!r} missing or not in the enum")
        allowed = _PUNCH_EVIDENCE_POLICY.get(row.get("category"))
        if allowed is None:
            problems.append(f"{label}: category has no _PUNCH_EVIDENCE_POLICY entry")
        elif basis not in allowed:
            problems.append(f"{label}: basis {basis!r} not allowed for its category ({sorted(allowed)})")
        if not isinstance(refs, list):
            problems.append(f"{label}: evidence_refs missing or not a list")
            continue
        devices = row.get("devices") or []
        for ref in refs:
            problems += _ref_problems(ref, devices, label)
            if isinstance(ref, dict):
                node = resolve_pointer(snap, ref.get("ref"))
                if node is _MISSING or node is None:
                    problems.append(f"{label}: ref {ref.get('ref')!r} does not resolve to a non-null node")
                else:
                    problems += _identity_problems(snap, ref, node, row, label)
        kinds = {r.get("kind") for r in refs if isinstance(r, dict)}
        if basis == "absence" and kinds & PUNCH_EVIDENCE_RECORD_KINDS:
            problems.append(f"{label}: basis=absence but carries record kinds {sorted(kinds & PUNCH_EVIDENCE_RECORD_KINDS)}")
        if basis == "record" and not kinds & PUNCH_EVIDENCE_RECORD_KINDS:
            problems.append(f"{label}: basis=record but no interface/acl_line/route/config_text ref")
        if basis == "row" and not refs:
            problems.append(f"{label}: basis=row but no ref to the row it was derived from")
        if len(refs) > PUNCH_EVIDENCE_REFS_CAP:
            problems.append(f"{label}: {len(refs)} refs exceeds the cap")
        if "evidence_refs_total" in row and not (len(refs) == PUNCH_EVIDENCE_REFS_CAP
                                                  and row["evidence_refs_total"] > len(refs)):
            problems.append(f"{label}: evidence_refs_total written although the list was not capped")
        keys = [(r.get("kind"), r.get("host"), r.get("ref"), r.get("role")) for r in refs if isinstance(r, dict)]
        if len(keys) != len(set(keys)):
            problems.append(f"{label}: duplicate refs")
    for section, key in (("cross_layer", "evidence_refs"), ("health_scores", "deduction_refs"),
                         ("operational_drift", "evidence_refs")):
        for n, up in enumerate(snap.get(section) or []):
            for ref in (up.get(key) or []) if isinstance(up, dict) else []:
                node = resolve_pointer(snap, ref.get("ref"))
                if node is _MISSING or node is None:
                    problems.append(f"[{form}] {section}[{n}].{key}: {ref.get('ref')!r} does not resolve")
                elif ref.get("host") is not None:
                    why = _host_witness_problem(*_owners_along(snap, ref.get("ref")), ref["host"])
                    if why:
                        problems.append(f"[{form}] {section}[{n}].{key}: {ref.get('ref')!r} claims host "
                                        f"{ref['host']!r} but {why}")
    return problems


def _run_inprocess(tmp_path, monkeypatch):
    """ONE real pipeline run through main(), capturing the IN-MEMORY snapshot handed to the writer."""
    import COLLECT_PARSE_V3_23_0 as cp
    from openpyxl import Workbook

    collection = fx.write_collection(str(tmp_path / _GOLDEN_COLLECTION_STAMP))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    wb = Workbook()
    wb.active.title = "Interface Data"
    wb.active.append(["Hostname", "Port", "Status"])
    wb.save(str(template))
    out_xlsx = tmp_path / "out.xlsx"
    captured = {}
    real_sparsify = cp.sparsify_interfaces

    def _capture(snap):
        captured["snap"] = snap
        return real_sparsify(snap)

    monkeypatch.setattr(cp, "sparsify_interfaces", _capture)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "cisco-assess", "--no-collect", "--collection-dir", collection,
        "--devices-file", str(devices), "--template", str(template),
        "--output", str(out_xlsx), "--workers", "1", "--no-html"])
    cp.main()
    with open(os.path.splitext(str(out_xlsx))[0] + ".snapshot.json", encoding="utf-8") as fh:
        on_disk = json.load(fh)
    return captured["snap"], on_disk


@pytest.fixture(scope="module")
def pipeline_forms(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    try:
        return _run_inprocess(tmp_path_factory.mktemp("evrefs"), mp)
    finally:
        mp.undo()


def test_every_punchlist_ref_resolves_in_memory_on_disk_and_after_redaction(pipeline_forms):
    """R3: EVERY row of the real pipeline run, in EVERY published form (in-memory, on-disk engine
    form, written file, redacted, and the explorer embed of plain + redacted), and each ref resolves
    to the record it claims -- not merely to some non-null node."""
    in_memory, on_disk = pipeline_forms
    assert in_memory["punchlist"], "the pipeline produced no punch-list rows to check"
    problems = []
    for form, snap in published_forms(in_memory, on_disk):
        problems += punchlist_evidence_problems(snap, form)
    assert not problems, "\n".join(problems[:40])


def test_redaction_leaves_every_evidence_pointer_byte_identical(pipeline_forms):
    """R9: the new keys carry paths + hostnames + port names only -- no IP / MAC / serial / email text,
    so the whole-snapshot pseudonymiser has nothing to rewrite in them."""
    from cisco_toolkit.html import redact_snapshot
    _in_memory, on_disk = pipeline_forms
    red = redact_snapshot(on_disk)
    for a, b in zip(on_disk["punchlist"], red["punchlist"]):
        assert a["evidence_refs"] == b["evidence_refs"]
        assert a["evidence_basis"] == b["evidence_basis"]


def test_pipeline_rows_reach_their_producer_named_records(pipeline_forms):
    """The run is not vacuous: interface records, literal config text and absence witnesses all occur."""
    _in_memory, on_disk = pipeline_forms
    rows = on_disk["punchlist"]
    kinds = {r["kind"] for row in rows for r in row["evidence_refs"]}
    assert {"interface", "config_text", "absence_witness", "analysis_row", "device_fact"} <= kinds
    by_cat = {}
    for row in rows:
        by_cat.setdefault(row["category"], set()).add(row["evidence_basis"])
    assert by_cat["L1"] == {"record"}
    assert by_cat["Config hygiene"] == {"record"}
    assert "absence" in by_cat["Security"] and "row" in by_cat["Security"]
    assert by_cat["QoS"] == {"absence"}


def test_pipeline_svi_folds_point_at_every_published_svi_key_they_reconstruct(pipeline_forms):
    """The index-gated folds (L3 gateway SVI, FHRP member SVI) must run on the PRODUCTION path, not
    only in direct-call unit tests: the pipeline hands compute_migration_punchlist its interface index,
    so every SVI key such a fold reconstructs AND the published snapshot carries is pointed at."""
    _in_memory, on_disk = pipeline_forms
    ifaces = on_disk["interfaces"]
    checked = 0
    for row in on_disk["punchlist"]:
        refs = {r["ref"] for r in row["evidence_refs"]}
        expected = set()
        for ref in refs:
            parts = [_unescape(t) for t in ref.split("/")[1:]]
            if row["category"] == "L3" and parts[0] == "l3_forwarding" and len(parts) == 2:
                src = on_disk["l3_forwarding"][int(parts[1])]
                host, port = src.get("switch"), f"Vlan{src.get('vlan')}"
            elif row["category"] == "FHRP" and parts[0] == "fhrp" and len(parts) == 4 \
                    and parts[2] == "members":
                src = on_disk["fhrp"][int(parts[1])]["members"][int(parts[3])]
                host, port = src.get("host"), src.get("interface")
            else:
                continue
            if isinstance(ifaces.get(host), dict) and port in ifaces[host]:
                expected.add(_json_pointer("interfaces", host, port))
        missing = expected - refs
        assert not missing, (row["category"], row["title"], sorted(missing))
        if expected:
            assert row["evidence_basis"] == "record", (row["category"], row["title"])
        checked += len(expected)
    assert checked, "no L3/FHRP fold reconstructed a published SVI key: the check never ran"


# ---------------------------------------------------------------------------------------------
# R2 -- policy completeness, derived STRUCTURALLY from the producer's own AST.
# ---------------------------------------------------------------------------------------------
def _module_ast(module):
    return ast.parse(inspect.getsource(module))


def _funcdef(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def _category_literals(func):
    """Every string a producer writes under a "category" key in a dict display."""
    out = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "category":
                    assert isinstance(v, ast.Constant) and isinstance(v.value, str), (
                        f"{func.name} writes a non-literal category -- extend the derivation")
                    out.add(v.value)
    return out


def _folded_producer(param):
    """The upstream compute_* that the PIPELINE feeds into punch-list parameter `param`, read from
    COLLECT_PARSE's own AST: `_actx.<param> = <name>` and `<name> = _run_phase(<label>, <func>, ...)`."""
    import COLLECT_PARSE_V3_23_0 as cp
    tree = _module_ast(cp)
    local = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Attribute) and node.targets[0].attr == param
                and isinstance(node.targets[0].value, ast.Name) and node.targets[0].value.id == "_actx"
                and isinstance(node.value, ast.Name)):
            local = node.value.id
    assert local, f"pipeline never feeds punch-list parameter {param!r} through _actx"
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == local for t in node.targets)
                and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "_run_phase" and len(node.value.args) >= 2
                and isinstance(node.value.args[1], ast.Name)):
            return node.value.args[1].id
    raise AssertionError(f"cannot find the producer of pipeline local {local!r}")


def emittable_categories():
    """Every category compute_migration_punchlist can emit, from its AST -- never a hand-kept list.
    Any add() call whose category argument has a shape this derivation does not understand FAILS the
    test (the derivation must be extended), so the class stays closed."""
    tree = _module_ast(analyze)
    fn = _funcdef(tree, "compute_migration_punchlist")
    params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    parents = {}
    for node in ast.walk(fn):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    fold = _funcdef(fn, "_fold_axis")
    fold_params = [a.arg for a in fold.args.args]
    cat_pos = fold_params.index("category")
    fold_cats = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_fold_axis":
            arg = node.args[cat_pos]
            assert isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            fold_cats.add(arg.value)
    cats, unresolved = set(), []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "add"):
            continue
        arg = node.args[1] if len(node.args) > 1 else next(
            (k.value for k in node.keywords if k.arg == "category"), None)
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            cats.add(arg.value)
        elif isinstance(arg, ast.Name) and arg.id == "category":
            cats |= fold_cats
        elif (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "get"
              and isinstance(arg.func.value, ast.Name) and len(arg.args) == 2
              and isinstance(arg.args[0], ast.Constant) and arg.args[0].value == "category"
              and isinstance(arg.args[1], ast.Constant)):
            cats.add(arg.args[1].value)
            loopvar, up, param = arg.func.value.id, parents.get(node), None
            while up is not None and param is None:
                if isinstance(up, ast.For) and loopvar in {n.id for n in ast.walk(up.target)
                                                           if isinstance(n, ast.Name)}:
                    found = [n.id for n in ast.walk(up.iter) if isinstance(n, ast.Name) and n.id in params]
                    param = found[0] if found else None
                up = parents.get(up)
            assert param, f"pass-through category at line {node.lineno} is not fed by a producer parameter"
            cats |= _category_literals(_funcdef(tree, _folded_producer(param)))
        else:
            unresolved.append(f"line {node.lineno}: {ast.dump(arg) if arg is not None else 'no category'}")
    assert not unresolved, "add() category shapes the derivation does not understand:\n" + "\n".join(unresolved)
    return cats


def test_policy_covers_every_category_the_producer_can_emit():
    emittable = emittable_categories()
    assert len(emittable) >= 20, f"derivation looks vacuous: {sorted(emittable)}"
    missing = emittable - set(_PUNCH_EVIDENCE_POLICY)
    assert not missing, f"categories with no evidence policy: {sorted(missing)}"
    stale = set(_PUNCH_EVIDENCE_POLICY) - emittable
    assert not stale, f"policy entries no fold can emit (stale): {sorted(stale)}"
    for cat, bases in _PUNCH_EVIDENCE_POLICY.items():
        assert bases and set(bases) <= set(PUNCH_EVIDENCE_BASES), cat


def test_security_basis_map_covers_the_check_registry_exactly():
    """Every parse_security check id is classified absence-vs-presence -- the registry, not a list."""
    from cisco_toolkit.parse import _SEC_CHECKS
    assert set(_SECURITY_CHECK_EVIDENCE_BASIS) == set(_SEC_CHECKS)
    assert set(_SECURITY_CHECK_EVIDENCE_BASIS.values()) <= {"absence", "row"}


# ---------------------------------------------------------------------------------------------
# Pointer grammar -- dotted FQDN hostnames and subinterface names (the named-subset trap).
# ---------------------------------------------------------------------------------------------
FQDN = "core1.site-a.example.net"
SUBIF = "Gi1/0/1.100"


def test_json_pointer_escapes_slash_and_tilde_and_round_trips_fqdn_subinterfaces():
    ptr = _json_pointer("interfaces", FQDN, SUBIF)
    assert ptr == "/interfaces/core1.site-a.example.net/Gi1~10~11.100"
    assert _json_pointer("x", "a~b/c") == "/x/a~0b~1c"
    doc = {"interfaces": {FQDN: {SUBIF: {"status": "up"}}}, "x": {"a~b/c": 1}}
    assert resolve_pointer(doc, ptr) == {"status": "up"}
    assert resolve_pointer(doc, "/x/a~0b~1c") == 1
    for bad in (None, 1.5, {"k": 1}, True, ""):
        assert _json_pointer("interfaces", bad) is None


def _ph(switch, port, risk):
    return {"switch": switch, "port": port, "risk": risk}


def test_l1_fold_points_at_every_port_record_with_fqdn_and_subinterface():
    rows = compute_migration_punchlist(
        [], {}, {}, [_ph(FQDN, SUBIF, "err-disabled"), _ph("acc2", "Gi0/2", "err-disabled")],
        [], [], {}, [], [])
    (row,) = [r for r in rows if r["category"] == "L1"]
    assert row["evidence_basis"] == "record"
    refs = {(r["kind"], r["host"], r["ref"], r["role"]) for r in row["evidence_refs"]}
    assert ("interface", FQDN, "/interfaces/core1.site-a.example.net/Gi1~10~11.100", "subject") in refs
    assert ("interface", "acc2", "/interfaces/acc2/Gi0~12", "subject") in refs
    # No index into physical_health: the explorer embed re-filters that list (Info/OK rows dropped),
    # so `/physical_health/<k>` would dangle or name another device's row there. The key-addressed
    # interface record is the stable pointer.
    assert not [r for r in row["evidence_refs"] if r["ref"].startswith("/physical_health")]
    snap = {"interfaces": {FQDN: {SUBIF: {}}, "acc2": {"Gi0/2": {}}}}
    assert all(resolve_pointer(snap, r["ref"]) is not _MISSING for r in row["evidence_refs"])


def test_every_row_always_carries_basis_and_refs_even_with_no_evidence():
    rows = compute_migration_punchlist(
        [{"id": "CL-03", "severity": "High", "title": "t", "detail": "d", "hosts": ["gw1"]}],
        {}, {}, [], [], [], {}, [], [])
    (row,) = rows
    assert row["evidence_basis"] == "row"
    assert row["evidence_refs"] == [{"kind": "analysis_row", "host": None, "ref": "/cross_layer/0",
                                     "role": "derived_from", "cite": "cross-layer rule CL-03 row"}]
    assert "evidence_refs_total" not in row


def test_cap_keeps_64_subjects_first_and_publishes_the_uncapped_total():
    where = [("sw1", f"Gi1/0/{i}", None) for i in range(1, 91)]
    l2 = {"addressing": {"dup_ip": [{"ip": "10.1.1.1", "where": where}], "dup_subnet": []}}
    (row,) = [r for r in compute_migration_punchlist([], {}, {}, [], [], [], {}, [], [], l2=l2)
              if r["category"] == "Addressing"]
    assert len(row["evidence_refs"]) == PUNCH_EVIDENCE_REFS_CAP
    assert row["evidence_refs_total"] == 91         # 90 interface subjects + the derived-from conflict row
    assert all(r["role"] == "subject" for r in row["evidence_refs"]), "a cap must keep what the finding is ABOUT"
    assert row["evidence_refs"] == sorted(row["evidence_refs"], key=lambda r: (r["kind"], r["host"], r["ref"]))


def test_security_absence_checks_carry_witnesses_and_presence_checks_their_row():
    sec = {"a1": {"findings": [{"id": "no-ntp", "status": "fail", "severity": "low", "title": "NTP"},
                               {"id": "insecure-snmp", "status": "fail", "severity": "high", "title": "SNMP"}]},
           "a2": {"findings": [{"id": "no-ntp", "status": "pass"},
                               {"id": "no-ntp", "status": "fail", "severity": "low", "title": "NTP"}]}}
    rows = {r["title"]: r for r in compute_migration_punchlist([], sec, {}, [], [], [], {}, [], [])}
    ntp, snmp = rows["NTP"], rows["SNMP"]
    assert ntp["evidence_basis"] == "absence"
    assert [(r["kind"], r["host"], r["ref"], r["role"]) for r in ntp["evidence_refs"]] == [
        ("absence_witness", "a1", "/security/a1/findings/0", "witness"),
        ("absence_witness", "a2", "/security/a2/findings/1", "witness")]
    assert snmp["evidence_basis"] == "row"
    assert [(r["kind"], r["ref"], r["role"]) for r in snmp["evidence_refs"]] == [
        ("device_fact", "/security/a1/findings/1", "derived_from")]


def test_config_hygiene_points_at_the_literal_referencing_line():
    hyg = {FQDN: {"undefined": [{"kind": "acl", "name": "7", "context": "ip nat inside source list 7"}]}}
    (row,) = compute_migration_punchlist([], {}, hyg, [], [], [], {}, [], [])
    assert row["evidence_basis"] == "record"
    got = {(r["kind"], r["ref"]) for r in row["evidence_refs"]}
    assert ("config_text", f"/config_hygiene/{FQDN}/undefined/0/context") in got
    assert resolve_pointer({"config_hygiene": hyg}, f"/config_hygiene/{FQDN}/undefined/0/context") \
        == "ip nat inside source list 7"


def test_trunk_link_and_addressing_folds_point_at_both_ends():
    l2 = {"trunk_native": [{"a_host": FQDN, "a_port": SUBIF, "a_native": "1",
                            "b_host": "acc9", "b_port": "Gi0/1", "b_native": "10"}],
          "link_phy": [{"a_host": "x1", "a_port": "Te1/1", "b_host": "x2", "b_port": "Te1/2",
                        "duplex": ("full", "half"), "speed": None}],
          "addressing": {"dup_ip": [{"ip": "10.9.9.9", "where": [("r1", "Vlan5", 5), ("r2", "Vlan5", 5)]}],
                         "dup_subnet": []}}
    rows = {r["category"]: r for r in compute_migration_punchlist([], {}, {}, [], [], [], {}, [], [], l2=l2)}
    trunk = {r["ref"] for r in rows["Trunk"]["evidence_refs"]}
    assert {"/trunk_native/0", f"/interfaces/{FQDN}/Gi1~10~11.100", "/interfaces/acc9/Gi0~11"} <= trunk
    assert {"/link_phy/0", "/interfaces/x1/Te1~11", "/interfaces/x2/Te1~12"} <= {
        r["ref"] for r in rows["Link L1"]["evidence_refs"]}
    addr = rows["Addressing"]
    assert addr["evidence_basis"] == "record"
    assert {"/addressing_conflicts/dup_ip/0", "/interfaces/r1/Vlan5", "/interfaces/r2/Vlan5"} <= {
        r["ref"] for r in addr["evidence_refs"]}
    assert all("10.9.9.9" not in r["cite"] for r in addr["evidence_refs"]), "a cite must never copy an IP"


def test_reconstructed_svi_names_are_pointed_at_only_when_an_interface_index_proves_them():
    l3 = [{"switch": "gw1", "vlan": 30, "risk": "single-gateway"}]
    fhrp = [{"vid": 10, "status": "review", "issues": ["x"],
             "members": [{"host": "gw1", "interface": "Vlan10"}, {"host": "gw2", "interface": "Vlan10"}]}]
    base = compute_migration_punchlist([], {}, {}, [], l3, [], {}, [], [], l2={"fhrp": fhrp})
    for row in base:
        assert not [r for r in row["evidence_refs"] if r["kind"] == "interface"], row["category"]
        assert row["evidence_basis"] == "row"
    index = {"gw1": ["vlan30", "Vlan10"], "gw2": ["Gi0/1"]}
    proven = {r["category"]: r for r in compute_migration_punchlist(
        [], {}, {}, [], l3, [], {}, [], [], l2={"fhrp": fhrp}, interface_index=index)}
    assert "/interfaces/gw1/vlan30" in {r["ref"] for r in proven["L3"]["evidence_refs"]}
    fh = {r["ref"] for r in proven["FHRP"]["evidence_refs"]}
    assert "/interfaces/gw1/Vlan10" in fh and "/interfaces/gw2/Vlan10" not in fh


def test_fleet_wide_absence_row_carries_per_device_witnesses_with_null_host():
    qos = {"per_device": [{"host": "a1", "assessable": True}, {"host": "a2", "assessable": False},
                          {"host": FQDN, "assessable": True}],
           "findings": [{"host": "(fleet)", "kind": "best-effort-fleet", "label": "No QoS configured anywhere",
                         "severity": "Low", "detail": "none", "evidence_basis": "absence"}]}
    (row,) = compute_migration_punchlist([], {}, {}, [], [], [], {}, [], [], qos_audit=qos)
    assert row["devices"] == [] and row["evidence_basis"] == "absence"
    wit = [r for r in row["evidence_refs"] if r["role"] == "witness"]
    assert [(r["kind"], r["host"], r["ref"]) for r in wit] == [
        ("absence_witness", None, "/qos_audit/per_device/0"), ("absence_witness", None, "/qos_audit/per_device/2")]
    assert not {r["kind"] for r in row["evidence_refs"]} & PUNCH_EVIDENCE_RECORD_KINDS


def test_software_risk_keeps_the_unfiltered_index_and_its_literal_evidence_line():
    sw = {"findings": [{"host": "c1", "kind": "telnet-vty", "label": "tv", "severity": "High"},
                       {"host": "c1", "kind": "http-server", "label": "Web UI", "severity": "High",
                        "detail": "d", "evidence": "ip http server"}]}
    (row,) = compute_migration_punchlist([], {}, {}, [], [], [], {}, [], [], software_risk=sw)
    got = {(r["kind"], r["ref"]) for r in row["evidence_refs"]}
    assert got == {("analysis_row", "/software_risk/findings/1"),
                   ("config_text", "/software_risk/findings/1/evidence")}
    assert row["evidence_basis"] == "record"


def _dep_for_graph_cut():
    """h2 is the only L2 transit between the gateway h1 and access switch h3 for VLAN 10."""
    from cisco_toolkit.model import InterfaceData

    def trunk(**kw):
        return InterfaceData(**{"switchport_mode": "Trunk", "trunk_allowed_vlans": "10",
                                "trunk_status": "trunking", **kw})
    ifaces = {
        "h1": {"Vlan10": InterfaceData(svi_ip="10.0.10.1/24"), "Gi1/0/1": trunk(cdp_neighbor="h2", neighbor_port="Gi1/0/1")},
        "h2": {"Gi1/0/1": trunk(cdp_neighbor="h1", neighbor_port="Gi1/0/1"),
               "Gi1/0/2": trunk(cdp_neighbor="h3", neighbor_port="Gi0/1")},
        "h3": {"Gi0/1": trunk(cdp_neighbor="h2", neighbor_port="Gi1/0/2"),
               "Gi0/5": InterfaceData(switchport_mode="Access", vlan="10", end_host_mac="aaaa.bbbb.cccc")},
    }
    return analyze.build_dependency_map(ifaces, [], [{"switch": "h1", "vlan": 10, "risk": "single-gateway"}])


def test_cl02_graph_cut_refs_are_derived_from_links_and_say_so():
    dep = _dep_for_graph_cut()
    cl = compute_cross_layer_correlations(dep)
    cl02 = [f for f in cl if f["id"] == "CL-02"]
    assert cl02, [f["id"] for f in cl]
    for f in cl02:
        assert f["evidence_refs"], f
        for r in f["evidence_refs"]:
            assert r["kind"] == "interface" and r["role"] == "derived_from" and r["host"] in f["hosts"]
            assert "graph cut" in r["cite"] and "not a config line" in r["cite"]
    cl03 = [f for f in cl if f["id"] == "CL-03"]
    assert cl03 and {r["ref"] for r in cl03[0]["evidence_refs"]} == {"/interfaces/h1/Vlan10"}
    rows = compute_migration_punchlist(cl, {}, {}, [], [], [], {}, [], [])
    for row, f in zip(rows, sorted(cl, key=lambda x: (-analyze._PUNCH_RANK.get(x["severity"], 0), x["title"]))):
        assert row["category"] == "Cross-layer"
    cut_rows = [r for r in rows if "only L2 transit" in r["title"]]
    assert cut_rows and all(any(x["role"] == "derived_from" and x["kind"] == "interface"
                                for x in r["evidence_refs"]) for r in cut_rows)
    # evidence_basis alone says "record" for these rows (the contract: >=1 interface ref). What keeps
    # that honest is that EVERY record-kind ref on a graph-cut row is role=derived_from and cites the
    # cut -- a consumer must render by kind+role, and none of these refs may pose as a config line.
    for r in cut_rows:
        record_refs = [x for x in r["evidence_refs"] if x["kind"] in PUNCH_EVIDENCE_RECORD_KINDS]
        if r["evidence_basis"] == "record":
            assert record_refs and all(x["role"] == "derived_from" and "graph cut" in x["cite"]
                                       and "not a config line" in x["cite"] for x in record_refs), r


def test_health_deduction_refs_follow_the_same_cut_as_the_prose():
    ph = [_ph("s1", f"Gi1/0/{i}", "err-disabled") for i in range(1, 12)]
    from cisco_toolkit.model import InterfaceData
    ifaces = {"s1": {f"Gi1/0/{i}": InterfaceData() for i in range(1, 12)}}
    (h,) = analyze.compute_health_scores(ifaces, ph, [], [], [])
    assert len(h["deductions"]) == 8 and len(h["deduction_refs"]) == 8
    for text, ref in zip(h["deductions"], h["deduction_refs"]):
        port = text.split(" @ ")[1].split(" (")[0]
        assert ref["ref"] == _json_pointer("interfaces", "s1", port)


def test_health_deduction_refs_are_an_order_preserving_subsequence_never_a_guess():
    """A deduction whose source names no usable record (a non-string port) contributes NO ref -- not a
    null, not a neighbour's ref. So `deduction_refs` is an order-preserving subsequence of the
    published deductions (documented at compute_health_scores): every ref names a port of a PUBLISHED
    deduction, in deduction order, and nothing past the [:8] cut leaks in."""
    from cisco_toolkit.model import InterfaceData
    ph = [_ph("s1", "Gi1/0/1", "err-disabled"), _ph("s1", 7, "err-disabled"),
          _ph("s1", "Gi1/0/3", "err-disabled")] + [_ph("s1", f"Gi2/0/{i}", "err-disabled") for i in range(1, 9)]
    ifaces = {"s1": {"Gi1/0/1": InterfaceData(), "Gi1/0/3": InterfaceData(),
                     **{f"Gi2/0/{i}": InterfaceData() for i in range(1, 9)}}}
    (h,) = analyze.compute_health_scores(ifaces, ph, [], [], [])
    published_ports = [t.split(" @ ")[1].split(" (")[0] for t in h["deductions"]]
    assert len(published_ports) == 8 and "7" in published_ports
    expected = [_json_pointer("interfaces", "s1", p) for p in published_ports if p != "7"]
    assert [r["ref"] for r in h["deduction_refs"]] == expected
    assert all(r is not None and r["host"] == "s1" for r in h["deduction_refs"])


def test_drift_native_vlan1_row_points_at_every_port_and_caps_honestly():
    from cisco_toolkit.model import InterfaceData
    ifaces = {"sw1": {f"Gi1/0/{i}": InterfaceData(trunk_status="trunking", trunk_native_vlan="1")
                      for i in range(1, 81)}}
    (nat1,) = [d for d in analyze.compute_operational_drift(ifaces, [], []) if "Native VLAN 1" in d["title"]]
    assert len(nat1["evidence_refs"]) == PUNCH_EVIDENCE_REFS_CAP and nat1["evidence_refs_total"] == 80
    (row,) = compute_migration_punchlist([], {}, {}, [], [], [], {}, [], [], drift=[nat1])
    assert row["evidence_basis"] == "record"
    assert row["evidence_refs_total"] == 81          # 80 port records + the drift row itself


def test_coverage_gap_row_is_absence_with_witnesses_only():
    from cisco_toolkit.model import InterfaceData
    ifaces = {"sw1": {"Gi1/0/1": InterfaceData()}}
    (cov,) = [d for d in analyze.compute_operational_drift(ifaces, [], ["sw1"]) if d["category"] == "Coverage"]
    (row,) = compute_migration_punchlist([], {}, {}, [], [], [], {}, [], [], drift=[cov])
    assert row["evidence_basis"] == "absence"
    assert {r["kind"] for r in row["evidence_refs"]} == {"absence_witness", "analysis_row"}


# ---------------------------------------------------------------------------------------------
# Direct-call producers the pipeline test does not reach on the golden (no rows there)
# ---------------------------------------------------------------------------------------------
def test_media_ptp_inventory_vtp_and_compound_folds_carry_refs():
    risks = [{"kind": "mac-alias", "severity": "High", "title": "m", "detail": "d",
              "evidence_refs": [{"kind": "analysis_row", "host": None, "ref": "/multicast_intelligence/mac_aliases/0",
                                 "role": "derived_from", "cite": "c"}]}]
    ptp = analyze.compute_ptp_readiness({"multicast": {"ptp": {"p1": {"operational": False}}}})
    dossiers = {"per_device": [{"host": "d1", "compound": [{"code": "CR-01", "title": "t", "severity": "High"}]}]}
    rows = {r["category"]: r for r in compute_migration_punchlist(
        [], {}, {}, [], [], [], {}, [], [], media_risks=risks, ptp_readiness=ptp,
        hostname_mismatches=[{"inventory": FQDN, "reported": "core1"}], device_dossiers=dossiers)}
    assert [r["ref"] for r in rows["Multicast/Media"]["evidence_refs"]] == ["/multicast_intelligence/mac_aliases/0"]
    assert [r["ref"] for r in rows["Timing/PTP"]["evidence_refs"]] == ["/service_map/multicast/ptp/p1"]
    assert [r["ref"] for r in rows["Inventory"]["evidence_refs"]] == [f"/devices/{FQDN}"]
    assert {r["ref"] for r in rows["Compound risk"]["evidence_refs"]} == {
        "/device_dossiers/per_device/0/compound/0", "/device_dossiers/per_device/0"}
    for cat in ("Multicast/Media", "Timing/PTP", "Inventory", "Compound risk"):
        assert rows[cat]["evidence_basis"] == "row"
    mc = analyze.compute_multicast_intelligence({"multicast": {"classified_groups": [], "igmp_queriers": []}})
    assert isinstance(mc["risks"], list)


# ---------------------------------------------------------------------------------------------
# Folds the golden fleet emits NO rows for (Addressing, Trunk, Link L1, Inventory, VTP, Coverage,
# Timing/PTP, Multicast/Media): drive each from its REAL producer, assemble the sections exactly as
# the pipeline publishes them (COLLECT_PARSE: snapshot_state devices/interfaces, the excel L2
# checks, operational_drift, service_map, multicast_intelligence, the EMBEDDED VTP receipt), and run
# the same class-wide checker over every published form -- never hand-built producer output.
# ---------------------------------------------------------------------------------------------
def _real_producer_fleet(tmp_path):
    from cisco_toolkit.excel import (compute_addressing_conflicts, compute_duplex_speed_mismatches,
                                     compute_trunk_native_mismatches)
    from cisco_toolkit.html import snapshot_state
    from cisco_toolkit.model import DevicePhysical, InterfaceData
    from cisco_toolkit.vtp_safety import embedded_vtp_safety_baseline
    from test_vtp_safety_engine import _owner

    def trunk(**kw):
        return InterfaceData(**{"switchport_mode": "Trunk", "trunk_status": "trunking",
                                "trunk_allowed_vlans": "10,30", "status": "connected", **kw})
    ifaces = {
        FQDN: {
            "Gi1/0/1": trunk(cdp_neighbor="acc2", neighbor_port="Gi0/1", trunk_native_vlan="10",
                             duplex="a-full", speed="a-1000"),
            SUBIF: InterfaceData(svi_ip="10.9.9.9/24"),
            "Vlan30": InterfaceData(svi_ip="10.30.0.1/24", multicast_info="PIM sparse-mode"),
            "Vlan40": InterfaceData(svi_ip="10.40.0.1/24"),
        },
        "acc2": {
            "Gi0/1": trunk(cdp_neighbor=FQDN, neighbor_port="Gi1/0/1", duplex="a-half", speed="a-1000"),
            "Vlan5": InterfaceData(svi_ip="10.9.9.9/24"),
            "Vlan41": InterfaceData(svi_ip="10.40.0.2/24"),
        },
    }
    physical = [DevicePhysical(hostname=FQDN, reported_hostname="core1-renamed"),
                DevicePhysical(hostname="acc2", reported_hostname="acc2")]
    service_map = {"multicast": {
        "ptp": {FQDN: {"operational": False}},
        "classified_groups": [{"group": "239.1.1.1", "name": "Flow A"}, {"group": "224.1.1.1", "name": "Flow B"}],
        "igmp_queriers": []}}
    multicast = analyze.compute_multicast_intelligence(service_map, ifaces)
    media = [r for r in multicast["risks"] if r.get("kind") in ("mac-alias", "querier-gap")]   # the pipeline's filter
    ptp = analyze.compute_ptp_readiness(service_map)
    drift = analyze.compute_operational_drift(ifaces, physical, ["acc2"])
    l2 = {"addressing": compute_addressing_conflicts(ifaces), "fhrp": [],
          "trunk_native": compute_trunk_native_mismatches(ifaces),
          "link_phy": compute_duplex_speed_mismatches(ifaces)}
    vtp_baseline, vtp_health, vtp_receipt = _owner(tmp_path)
    rows = compute_migration_punchlist(
        [], {}, {}, [], [], vtp_health, {}, [], [], l2=l2,
        hostname_mismatches=analyze.compute_hostname_mismatches(physical), drift=drift,
        ptp_readiness=ptp, media_risks=media, protocol_assessability=vtp_receipt,
        vtp_safety_baseline=vtp_baseline)
    snap = snapshot_state(ifaces, physical)
    snap.update({
        "addressing_conflicts": compute_addressing_conflicts(ifaces),
        "trunk_native": compute_trunk_native_mismatches(ifaces),
        "link_phy": compute_duplex_speed_mismatches(ifaces),
        "fhrp": l2["fhrp"], "operational_drift": drift, "service_map": service_map,
        "multicast_intelligence": multicast, "protocol_health": vtp_health,
        "vtp_safety_baseline": embedded_vtp_safety_baseline(vtp_baseline), "punchlist": rows})
    return snap


def test_every_fold_driven_by_its_real_producer_points_into_the_published_section(tmp_path):
    snap = _real_producer_fleet(tmp_path)
    cats = {r["category"] for r in snap["punchlist"]}
    wanted = {"Addressing", "Trunk", "Link L1", "Inventory", "VTP", "Coverage", "Timing/PTP", "Multicast/Media"}
    assert wanted <= cats, f"fleet no longer triggers {sorted(wanted - cats)} -- the check would be vacuous"
    on_disk = json.loads(json.dumps(_sparse_on_disk_form(snap)))
    problems = []
    for form, published in published_forms(snap, on_disk):
        problems += punchlist_evidence_problems(published, form)
    assert not problems, "\n".join(problems[:40])
    by_cat = {}
    for row in snap["punchlist"]:
        by_cat.setdefault(row["category"], []).append(row)
    for cat in ("Addressing", "Trunk", "Link L1"):          # both ends / every `where` port is a record
        assert all(r["evidence_basis"] == "record" for r in by_cat[cat]), cat
    trunk_refs = {x["ref"] for x in by_cat["Trunk"][0]["evidence_refs"]}
    assert {"/interfaces/core1.site-a.example.net/Gi1~10~11", "/interfaces/acc2/Gi0~11"} <= trunk_refs
    dup_ip = [r for r in by_cat["Addressing"] if r["title"].startswith("Duplicate")]
    assert dup_ip and "/interfaces/core1.site-a.example.net/Gi1~10~11.100" in {
        x["ref"] for x in dup_ip[0]["evidence_refs"]}, "a subinterface key must survive the pointer grammar"
    assert [r["evidence_basis"] for r in by_cat["Coverage"]] == ["absence"]
    assert [r["evidence_basis"] for r in by_cat["VTP"]] == ["row"]
    assert {x["ref"] for x in by_cat["Inventory"][0]["evidence_refs"]} == {"/devices/core1.site-a.example.net"}


def test_vtp_refs_index_the_published_projection_even_when_the_receipt_is_rejected(tmp_path):
    """The punch list reads the RAW current-run receipt, but the pipeline publishes
    embedded_vtp_safety_baseline(receipt). A receipt that fails validation publishes as the EMPTY
    unavailable projection, so a witness indexing the raw receipt's coverage would dangle."""
    from copy import deepcopy
    from cisco_toolkit.vtp_safety import embedded_vtp_safety_baseline
    from test_vtp_safety_engine import _owner
    baseline, health, receipt = _owner(tmp_path)
    tampered = deepcopy(dict(baseline))
    tampered["summary"] = dict(tampered["summary"], baseline_sha256="0" * 64)
    published = embedded_vtp_safety_baseline(tampered)
    assert published["coverage"] == [] and published["rows"] == [], "precondition: rejected receipt"
    assert tampered["coverage"], "precondition: the raw receipt still carries coverage cells"
    rows = [r for r in compute_migration_punchlist(
        [], {}, {}, [], [], health, {}, [], [], protocol_assessability=receipt,
        vtp_safety_baseline=tampered) if r["category"] == "VTP"]
    assert rows, "the abstention row must still be raised"
    snap = {"vtp_safety_baseline": published, "protocol_health": health, "punchlist": rows}
    assert not punchlist_evidence_problems(snap, "rejected-receipt")


def test_ip_literal_hostname_pointers_stay_resolvable_and_leak_nothing_after_redaction():
    """A device inventoried by IP: its refs carry that IP as a host/path token. The whole-snapshot
    redaction rewrites keys and strings with ONE consistent map, so the pointer still resolves on the
    redacted snapshot and the real address survives nowhere in the new keys."""
    from cisco_toolkit.html import redact_snapshot
    host = "10.20.30.40"
    rows = compute_migration_punchlist([], {}, {}, [_ph(host, "Gi0/1", "err-disabled")], [], [], {}, [], [])
    snap = {"interfaces": {host: {"Gi0/1": {"status": "err-disabled"}}}, "punchlist": rows}
    assert not punchlist_evidence_problems(snap, "plain")
    red = redact_snapshot(snap)
    assert not punchlist_evidence_problems(red, "redacted")
    assert host not in json.dumps(red["punchlist"]), "the real address leaked through the evidence pointers"
