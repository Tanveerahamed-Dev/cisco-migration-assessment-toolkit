"""roadmap D3: the zero-egress attestation panel (cisco_toolkit/attestation.py).

The engine's moat — read-only / no-egress / no-LLM by construction — is RE-DERIVED at build
time with the same mechanics as tests/test_readonly_and_no_egress.py and published as
snap['attestation'] + the 'Trust & Sovereignty' workbook sheet. These tests pin:
- every runnable claim HOLDS on the real codebase (the panel and the doctrine test agree);
- a synthetic tampered module tree (a fake package importing `requests` / an LLM SDK)
  drives the import-walk claims to VIOLATED, naming the offending file — falsifiable,
  never a hardcoded badge;
- a missing source tree / missing collector module yields NOT_EVALUATED with a reason —
  results are COMPUTED, never defaulted (absence of evidence is never a pass);
- every claim id is ALWAYS present, in a stable order;
- the frozen golden snapshot carries the key (the panel ships on every default run);
- W59 PR-2 (T9): every no-egress charter exclusion is paired with its own published floor claim, the
  texts derive from that one mapping, and `legacy_ssh_confined` falsifies under planted mutations.
"""
import json
import os
import re

import pytest

from cisco_toolkit.attestation import (
    ATTESTATION_SCHEMA,
    CLAIM_IDS,
    HOLDS,
    NOT_EVALUATED,
    VIOLATED,
    compute_attestation,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _by_id(att):
    return {c["id"]: c for c in att["claims"]}


# ------------------------------------------------------------------ shape ---
def test_all_claim_ids_always_present_in_stable_order():
    att = compute_attestation()
    assert att["schema"] == ATTESTATION_SCHEMA == "attestation/1"
    assert att["generated_at"]
    assert [c["id"] for c in att["claims"]] == list(CLAIM_IDS) == [
        "read_only_command_surface", "no_egress_import_graph",
        "rest_collect_get_only", "no_llm_runtime", "legacy_ssh_confined"]
    for c in att["claims"]:
        assert c["result"] in {HOLDS, VIOLATED, NOT_EVALUATED}
        assert c["method"] and c["detail"], f"{c['id']}: method/detail must never be empty"


def test_claim_ids_present_even_when_nothing_is_evaluable(tmp_path):
    """The ids are structural: a run where NO check can execute still publishes every
    claim — each as an explicit NOT_EVALUATED with a reason, never a silent drop."""
    att = compute_attestation(toolkit_dir=str(tmp_path / "no-such-package"),
                              collector_module="no_such_collector_module_xyz")
    by = _by_id(att)
    assert set(by) == set(CLAIM_IDS)
    for cid in CLAIM_IDS:
        assert by[cid]["result"] == NOT_EVALUATED, f"{cid} must abstain, not default"
        assert by[cid]["detail"], f"{cid}: NOT_EVALUATED must carry its reason"


# ------------------------------------------- the real codebase: all HOLD ---
def test_all_runnable_claims_hold_on_the_real_codebase():
    """The doctrine test (tests/test_readonly_and_no_egress.py) and the shipped panel share
    grammar/mechanics — if the doctrine holds there, every claim must HOLD here too."""
    att = compute_attestation()
    by = _by_id(att)
    for cid in CLAIM_IDS:
        assert by[cid]["result"] == HOLDS, f"{cid}: {by[cid]['detail']}"


def test_read_only_claim_detail_carries_real_counts():
    """The evidence is counted, never vacuous: the registry surface is large and re-derived
    (mirrors the doctrine test's own >=100-commands sanity floor)."""
    c = _by_id(compute_attestation())["read_only_command_surface"]
    m = re.search(r"all (\d+) registry commands", c["detail"])
    assert m, f"detail must state the re-derived command count: {c['detail']}"
    assert int(m.group(1)) >= 100
    assert "COMMANDS_" in c["detail"]


def test_no_egress_claim_names_its_documented_exceptions():
    """Coverage-honesty: every charter exclusion and exception is DISCLOSED in the claim.

    Derived from the LIVE sets, not restated. This test used to hardcode two filenames, and when
    `NO_EGRESS_EXCEPTIONS` was emptied it went on passing — satisfied by a stale METHOD paragraph
    that still announced an exception the DETAIL simultaneously reported as unnecessary. A test that
    names the thing it is checking cannot notice the thing being removed; it pinned a
    self-contradicting client-facing claim in place instead of catching it.
    """
    from cisco_toolkit.attestation import NO_EGRESS_EXCEPTIONS, NO_EGRESS_EXCLUDE, NO_EGRESS_PERMITTED_IMPORTS

    c = _by_id(compute_attestation())["no_egress_import_graph"]
    published = c["method"] + c["detail"]
    for name in sorted(NO_EGRESS_EXCLUDE | NO_EGRESS_EXCEPTIONS | set(NO_EGRESS_PERMITTED_IMPORTS)):
        assert name in published, (
            f"{name!r} is excluded or exempted by the charter but is not disclosed in the "
            f"published claim — a subtraction the reader cannot see: {published!r}"
        )
    # Non-vacuity: with both sets empty the loop above would assert nothing at all.
    assert NO_EGRESS_EXCLUDE, "no exclusions left — this test can no longer prove disclosure"
    # And the claim must not announce an exception that is no longer in the set (the defect above).
    for stale in ("gen_port_registry.py",):
        if stale not in {n.rsplit("/", 1)[-1] for n in NO_EGRESS_EXCEPTIONS}:
            assert stale not in published, (
                f"the published claim still names {stale!r} as an exception, but it is not in "
                "NO_EGRESS_EXCEPTIONS — METHOD and DETAIL now contradict each other"
            )


def test_no_egress_walk_reaches_subpackages_and_the_exception_is_not_dead():
    """The walk must be RECURSIVE, and its documented exception must be doing real work.

    Regression: `_iter_py` enumerated `os.listdir` (top level only), so
    `cisco_toolkit/data/gen_port_registry.py` — which imports `urllib.request` and fetches
    iana.org — was never opened, and `NO_EGRESS_EXCEPTIONS` was DEAD CODE. The panel published
    "0 network-library imports across N analysis modules" over a file it had not read, on the
    client-facing Trust & Sovereignty sheet. Two halves, both load-bearing: the scan REACHES the
    subpackage file (it is a real offender before the exception is subtracted), and the claim
    reports the exception as APPLIED rather than as matching nothing."""
    from cisco_toolkit.attestation import (NETWORK_IMPORTS, NO_EGRESS_EXCEPTIONS,
                                           NO_EGRESS_EXCLUDE, NO_EGRESS_PERMITTED_IMPORTS, scan_imports)
    pkg = os.path.join(ROOT, "cisco_toolkit")
    n, offenders = scan_imports(pkg, NETWORK_IMPORTS, exclude=NO_EGRESS_EXCLUDE)

    # Recursion is proven STRUCTURALLY, against an independent enumeration — not by naming one
    # subpackage file and checking it is an offender. The original form did the latter, using
    # `data/gen_port_registry.py` (which then imported urllib). When that generator was made
    # offline the assertion started demanding a defect that had been REPAIRED, and the test failed
    # for the best possible reason. A guard anchored to one file's current contents expires when
    # that file improves; anchored to the walk itself, it cannot.
    # COMPARE SETS, NOT COUNTS. The first version of this test asserted `n == len(expected)` against
    # an enumeration that differed from `_iter_py` in TWO ways — it kept dot-directories (the impl
    # prunes them) and excluded by BASENAME (the impl excludes by RELPATH). Those divergences point
    # in opposite directions and CANCEL, so the count matched while the sets did not: a
    # `.vendored/hidden_egress.py` importing `requests` was never opened by the scan and the guard
    # stayed green. Equal counts are not equal coverage.
    from cisco_toolkit.attestation import _iter_py

    scanned = {rel for rel, _path in _iter_py(pkg, NO_EGRESS_EXCLUDE)}
    assert len(scanned) == n, "scan_imports did not scan exactly what _iter_py yielded"

    expected = set()
    for dirpath, dirs, files in os.walk(pkg):
        dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".")]
        for f in files:
            if not f.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), pkg).replace(os.sep, "/")
            if rel not in NO_EGRESS_EXCLUDE:      # RELPATH, matching the implementation
                expected.add(rel)
    assert scanned == expected, (
        "the scan's file set differs from an independent recursive enumeration.\n"
        f"  missed by the scan : {sorted(expected - scanned)}\n"
        f"  scanned but unexpected: {sorted(scanned - expected)}\n"
        "A file the walk never opened must never be counted as one it cleared."
    )
    assert any("/" in rel for rel in expected), (
        "no subpackage .py files exist any more, so this test can no longer prove recursion at all"
    )
    # Both enumerations share `os.walk` with followlinks=False and both prune dot-directories, so a
    # divergence hidden INSIDE those shared choices cannot be caught by comparing sets either. Pin
    # the conditions under which that could matter, so they fail loudly the day they arise instead
    # of silently shrinking the evidence behind a client-facing claim.
    hidden = [os.path.relpath(os.path.join(dp, d), pkg)
              for dp, dirs, _f in os.walk(pkg) for d in dirs
              if d.startswith(".") or os.path.islink(os.path.join(dp, d))]
    assert not hidden, (
        f"dot-directories or directory symlinks under the analysis package: {hidden}. Both "
        "enumerations skip these by construction, so their contents are UNSCANNED while the claim "
        "reads '0 network-library imports'. Decide explicitly whether they must be walked."
    )

    # W59 PR-2: a per-file charter permission (legacy_ssh.py -> paramiko) keeps its file IN the walk, so the file
    # is an offender here before the permission is applied -- and ONLY for its permitted roots.
    permitted = {rel: bad for rel, bad in offenders.items() if rel in NO_EGRESS_PERMITTED_IMPORTS}
    assert set(permitted) == set(NO_EGRESS_PERMITTED_IMPORTS), (permitted, "a permission is not doing real work")
    for rel, bad in permitted.items():
        assert {b.split(".")[0] for b in bad} <= NO_EGRESS_PERMITTED_IMPORTS[rel], (rel, bad)
    assert set(offenders) - set(permitted) <= set(NO_EGRESS_EXCEPTIONS), f"undocumented egress import: {offenders}"
    c = _by_id(compute_attestation())["no_egress_import_graph"]
    assert c["result"] == HOLDS
    # The charter is EMPTY on purpose (see NO_EGRESS_EXCEPTIONS): nothing under the package imports
    # a network library, so the claim carries no caveat. Both halves still matter — a stale
    # exception must still be reported as such, and there must be none to report.
    assert "no documented exception was needed" in c["detail"]
    assert "matched nothing" not in c["detail"], "a never-firing exception is a stale charter"


def test_network_import_in_a_SUBPACKAGE_is_violated(tmp_path):
    """A banned import one directory down must flip the claim, naming its relative path — the
    top-level-only walk reported HOLDS over exactly this shape."""
    pkg = _fake_pkg(tmp_path, {"clean.py": "X = 1\n"})
    sub = tmp_path / "fakepkg" / "sub"
    sub.mkdir()
    (sub / "evil.py").write_text("import socket\n", encoding="utf-8")
    c = _by_id(compute_attestation(toolkit_dir=pkg,
                                   collector_module="no_such_collector_module_xyz"))[
        "no_egress_import_graph"]
    assert c["result"] == VIOLATED
    assert "sub/evil.py" in c["detail"] and "socket" in c["detail"]


def test_charter_exclusion_is_path_scoped_not_basename_scoped(tmp_path):
    """`rest_collect.py` is excluded as a top-level charter case; a same-named file in a
    SUBPACKAGE is a different module and must still be judged (a basename-keyed exclusion would
    silently exempt it)."""
    pkg = _fake_pkg(tmp_path, {"rest_collect.py": 'import requests\n'})
    sub = tmp_path / "fakepkg" / "vendor"
    sub.mkdir()
    (sub / "rest_collect.py").write_text("import requests\n", encoding="utf-8")
    c = _by_id(compute_attestation(toolkit_dir=pkg,
                                   collector_module="no_such_collector_module_xyz"))[
        "no_egress_import_graph"]
    assert c["result"] == VIOLATED and "vendor/rest_collect.py" in c["detail"]


def test_rest_get_only_claim_counts_the_single_login_post():
    c = _by_id(compute_attestation())["rest_collect_get_only"]
    assert c["result"] == HOLDS
    assert "POST" in c["detail"] and "GET" in c["detail"]


# ------------------------------------------------- tampering -> VIOLATED ---
def _fake_pkg(tmp_path, files):
    pkg = tmp_path / "fakepkg"
    pkg.mkdir()
    for name, src in files.items():
        (pkg / name).write_text(src, encoding="utf-8")
    return str(pkg)


def test_tampered_tree_with_requests_import_is_violated(tmp_path):
    """A stray network import in the analysis tree flips no_egress to VIOLATED and NAMES
    the offending module — including a LAZY in-function import (any nesting depth)."""
    pkg = _fake_pkg(tmp_path, {
        "innocent.py": "import os\nX = os.sep\n",
        "evil.py": "def fetch():\n    import requests\n    return requests\n",
    })
    att = compute_attestation(toolkit_dir=pkg, collector_module="no_such_collector_module_xyz")
    c = _by_id(att)["no_egress_import_graph"]
    assert c["result"] == VIOLATED
    assert "evil.py" in c["detail"] and "requests" in c["detail"]
    assert "innocent.py" not in c["detail"]


def test_tampered_tree_with_llm_sdk_import_is_violated(tmp_path):
    """An LLM/GenAI SDK import anywhere in the analysis tree flips no_llm_runtime to
    VIOLATED, naming the module — the 'no LLM in the runtime pipeline' claim is computed."""
    pkg = _fake_pkg(tmp_path, {
        "clean.py": "Y = 2\n",
        "brain.py": "from openai import OpenAI\n",
    })
    att = compute_attestation(toolkit_dir=pkg, collector_module="no_such_collector_module_xyz")
    c = _by_id(att)["no_llm_runtime"]
    assert c["result"] == VIOLATED
    assert "brain.py" in c["detail"] and "openai" in c["detail"]


def test_tampered_rest_collect_with_write_verb_is_violated(tmp_path):
    """A rest_collect.py that grows a DELETE (or a second POST) loses the GET-only claim."""
    pkg = _fake_pkg(tmp_path, {
        "rest_collect.py": ('def bad(u):\n'
                            '    return _open(u, method="POST")\n'
                            'def worse(u):\n'
                            '    return _open(u, method="DELETE")\n'),
    })
    att = compute_attestation(toolkit_dir=pkg, collector_module="no_such_collector_module_xyz")
    c = _by_id(att)["rest_collect_get_only"]
    assert c["result"] == VIOLATED
    assert "DELETE" in c["detail"]


def test_second_post_in_rest_collect_is_violated(tmp_path):
    pkg = _fake_pkg(tmp_path, {
        "rest_collect.py": ('def login(u):\n    return _open(u, method="POST")\n'
                            'def sneaky_write(u):\n    return _open(u, method="POST")\n'),
    })
    c = _by_id(compute_attestation(toolkit_dir=pkg,
                                   collector_module="no_such_collector_module_xyz"))["rest_collect_get_only"]
    assert c["result"] == VIOLATED and "2" in c["detail"]


def test_write_command_in_registry_is_violated():
    """A write verb smuggled into a COMMANDS_* registry flips read_only_command_surface to
    VIOLATED, naming the registry and the command — same falsifier as the doctrine test."""
    import types
    fake = types.ModuleType("fake_collector_with_write_cmd")
    fake.COMMANDS_IOS = ["show version", "configure terminal"]
    import sys
    sys.modules["fake_collector_with_write_cmd"] = fake
    try:
        c = _by_id(compute_attestation(collector_module="fake_collector_with_write_cmd"))[
            "read_only_command_surface"]
        assert c["result"] == VIOLATED
        assert "configure terminal" in c["detail"] and "COMMANDS_IOS" in c["detail"]
    finally:
        del sys.modules["fake_collector_with_write_cmd"]


def test_a_write_tacked_onto_a_read_verb_violates_the_published_claim():
    """The falsifier above uses a BARE write verb, which the verb-anchored regex already caught —
    so it never probed the class that actually threatens this claim: a string that OPENS with a
    legitimate read verb and then writes, egresses or chains.

    `READ_ONLY_CMD.match()` accepts every command below (asserted, so this test fails loudly if
    that premise ever changes). Until the claim was moved onto is_read_only_command(), each of them
    made compute_attestation publish `read_only_command_surface: HOLDS` — the engine certifying a
    read-only command surface while carrying a command that writes to bootflash, TFTPs the running
    config off the box, or types `configure terminal` at the exec prompt on the next line.
    """
    import sys
    import types
    from cisco_toolkit.attestation import READ_ONLY_CMD
    for cmd in ("show running-config | redirect bootflash:pwn.txt",  # NX-OS WRITES that file
                "show running-config | tftp://10.0.0.9/pwn.txt",     # ships the config off-box
                "show version ; reload",
                "show version > bootflash:out.txt",
                "show version\nconfigure terminal\nhostname PWNED"):
        assert READ_ONLY_CMD.match(cmd.strip()), \
            f"premise changed: {cmd!r} no longer passes the verb-anchored regex"
        name = "fake_collector_tacked_on_write"
        fake = types.ModuleType(name)
        fake.COMMANDS_IOS = ["show version", cmd]
        sys.modules[name] = fake
        try:
            c = _by_id(compute_attestation(collector_module=name))["read_only_command_surface"]
            assert c["result"] == VIOLATED, \
                f"attestation published {c['result']} for a registry containing {cmd!r}"
            assert "COMMANDS_IOS" in c["detail"]
        finally:
            del sys.modules[name]


# --------------------------------------------- missing source -> abstain ---
def test_missing_package_source_is_not_evaluated_with_reason(tmp_path):
    att = compute_attestation(toolkit_dir=str(tmp_path / "wheel-without-sources"))
    by = _by_id(att)
    for cid in ("no_egress_import_graph", "rest_collect_get_only", "no_llm_runtime",
                "legacy_ssh_confined"):
        assert by[cid]["result"] == NOT_EVALUATED
        assert "source" in by[cid]["detail"].lower() or "not" in by[cid]["detail"].lower()
    # the registry claim imports the collector MODULE (not the tree) so it still runs
    assert by["read_only_command_surface"]["result"] == HOLDS


def test_unimportable_collector_is_not_evaluated_with_reason():
    c = _by_id(compute_attestation(collector_module="no_such_collector_module_xyz"))[
        "read_only_command_surface"]
    assert c["result"] == NOT_EVALUATED
    assert "no_such_collector_module_xyz" in c["detail"]


def test_registryless_collector_is_not_evaluated_not_vacuously_holding():
    """A collector module with NO COMMANDS_* registries proves nothing — the claim must
    abstain, never pass vacuously on an empty surface."""
    import sys
    import types
    sys.modules["fake_collector_no_registries"] = types.ModuleType("fake_collector_no_registries")
    try:
        c = _by_id(compute_attestation(collector_module="fake_collector_no_registries"))[
            "read_only_command_surface"]
        assert c["result"] == NOT_EVALUATED
    finally:
        del sys.modules["fake_collector_no_registries"]


# ------------------------------------------------------------------ golden ---
def test_golden_snapshot_carries_the_attestation_key():
    """The panel ships on every default run: the frozen golden carries snap['attestation']
    with every claim HOLDING (the golden run executes on this very codebase). The
    nested generated_at is stripped by the golden harness as the one volatile field."""
    with open(os.path.join(ROOT, "tests", "golden", "snapshot.json"), encoding="utf-8") as f:
        golden = json.load(f)
    att = golden.get("attestation")
    assert isinstance(att, dict), "golden snapshot must carry the attestation key"
    assert att.get("schema") == ATTESTATION_SCHEMA
    assert "generated_at" not in att, "volatile stamp must be stripped from the golden"
    assert [c["id"] for c in att["claims"]] == list(CLAIM_IDS)
    assert all(c["result"] == HOLDS for c in att["claims"]), att["claims"]


# ------------------------------------------------------------ excel twin ---
def test_trust_sheet_renders_claims_and_honest_abstention(tmp_path):
    from openpyxl import Workbook

    from cisco_toolkit.excel import ATTESTATION_SHEET_NAME, write_attestation_sheet
    wb = Workbook()
    write_attestation_sheet(wb, compute_attestation())
    ws = wb[ATTESTATION_SHEET_NAME]
    blob = "\n".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    for cid in CLAIM_IDS:
        assert cid in blob
    assert "HOLDS" in blob and "VIOLATED" not in blob
    # the _unavailable sentinel renders as UNVERIFIED — never as a silent pass
    wb2 = Workbook()
    write_attestation_sheet(wb2, {"_unavailable": True})
    blob2 = "\n".join(str(c.value) for row in wb2[ATTESTATION_SHEET_NAME].iter_rows()
                      for c in row if c.value)
    assert "UNVERIFIED" in blob2 and "HOLDS" not in blob2


# ------------------------------------------- W59 PR-2 (T9): the paired charter + 5th claim ---
_VOCAB_SRC = (
    '"""Synthetic vocabulary owner for the attestation falsifiers."""\n'
    'SSH_PROFILES = ("default", "legacy-sha1")\n'
    'LEGACY_SHA1_TIER_KEX = ("diffie-hellman-group14-sha1", "diffie-hellman-group-exchange-sha1")\n'
    'LEGACY_SHA1_TIER_HOST_KEYS = ("ssh-rsa", "ssh-rsa-cert-v01@openssh.com")\n'
)


def _legacy_pkg(tmp_path, monkeypatch, *, legacy_extra="", others=None, vocab=_VOCAB_SRC, legacy_replace=None):
    """A fake analysis package carrying the REAL legacy_ssh.py (plus a planted suffix, and optionally one exact
    in-place replacement ``(old, new)`` -- ``old`` must occur exactly once), a synthetic vocabulary owner and optional
    extra modules, and a resolvable fake collector entry module."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    real = open(os.path.join(ROOT, "cisco_toolkit", "legacy_ssh.py"), encoding="utf-8").read()
    if legacy_replace is not None:
        old, new = legacy_replace
        assert real.count(old) == 1, f"the planted route's anchor no longer occurs exactly once: {old!r}"
        real = real.replace(old, new)
    files = {"legacy_ssh.py": real + legacy_extra, "clean.py": "X = 1\n"}
    if vocab is not None:
        files["ssh_session.py"] = vocab
    files.update(others or {})
    pkg = _fake_pkg(tmp_path, files)
    collector_dir = tmp_path / "collector_src"
    collector_dir.mkdir()
    (collector_dir / "w59_fake_collector_entry.py").write_text("COMMANDS_IOS = ['show version']\n",
                                                               encoding="utf-8")
    monkeypatch.syspath_prepend(str(collector_dir))
    return pkg, "w59_fake_collector_entry"


def _legacy_claim(pkg, collector):
    return _by_id(compute_attestation(toolkit_dir=pkg, collector_module=collector))["legacy_ssh_confined"]


def test_every_no_egress_exclusion_is_paired_with_a_published_claim():
    """Mutation caught: an exclusion added to the walk with no published floor claim (a subtraction the
    client is told nothing about), or the texts restating the set instead of deriving from it."""
    from cisco_toolkit.attestation import NO_EGRESS_CHARTER, NO_EGRESS_EXCLUDE, NO_EGRESS_PERMITTED_IMPORTS

    # W59 PR-2 review (P1-a): legacy_ssh.py is NOT excluded whole any more; it stays in the walk with only paramiko
    # permitted, and every charter entry is exactly one of the two kinds.
    assert set(NO_EGRESS_CHARTER) == NO_EGRESS_EXCLUDE | set(NO_EGRESS_PERMITTED_IMPORTS)
    assert not NO_EGRESS_EXCLUDE & set(NO_EGRESS_PERMITTED_IMPORTS)
    assert NO_EGRESS_EXCLUDE == {"rest_collect.py"}
    assert dict(NO_EGRESS_PERMITTED_IMPORTS) == {"legacy_ssh.py": frozenset({"paramiko"})}
    assert set(NO_EGRESS_CHARTER.values()) <= set(CLAIM_IDS)
    att = _by_id(compute_attestation())
    c = att["no_egress_import_graph"]
    for rel, cid in NO_EGRESS_CHARTER.items():
        kind = "excluded whole" if rel in NO_EGRESS_EXCLUDE else "scanned with only paramiko permitted"
        assert f"{rel} {kind} (covered by its own published claim {cid})" in c["method"], c["method"]
    assert f"excluded by charter: {', '.join(sorted(NO_EGRESS_EXCLUDE))}" in c["detail"], c["detail"]
    assert "network imports permitted by charter: legacy_ssh.py -> paramiko only" in c["detail"], c["detail"]
    assert "matched nothing" not in c["detail"], c["detail"]
    assert all(rel in att["no_llm_runtime"]["method"] for rel in NO_EGRESS_CHARTER)


def test_legacy_ssh_confined_holds_on_the_real_module(tmp_path, monkeypatch):
    pkg, collector = _legacy_pkg(tmp_path, monkeypatch)
    c = _legacy_claim(pkg, collector)
    assert c["result"] == HOLDS, c["detail"]
    assert "LEGACY_SHA1_TIER_KEX" in c["detail"] and "legacy_ssh.py" in c["detail"]
    assert "closed allowlist" in c["detail"] and "of its own" in c["detail"]
    # W59 PR-2 review round 2 (P2): the closed rules each had a subject (non-vacuity is a refusal, never a pass)
    for phrase in ("allowlisted call sites", "closed attribute allowlist", "closed grammar",
                   "one binding per name per scope", "connection-capable binding(s), none called"):
        assert phrase in c["detail"], (phrase, c["detail"])
    assert "connection-capable binding(s)" in c["detail"] and "found 0 " not in c["detail"]


def test_legacy_ssh_confined_is_violated_by_a_store_into_a_paramiko_table(tmp_path, monkeypatch):
    pkg, collector = _legacy_pkg(
        tmp_path, monkeypatch,
        legacy_extra="\n\ndef _open_everyone():\n    Transport._kex_info[_KEX_GROUP14_SHA1] = None\n")
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED and "store into a paramiko table" in c["detail"], c["detail"]


def test_legacy_ssh_confined_is_violated_by_a_mutating_call_on_a_table(tmp_path, monkeypatch):
    pkg, collector = _legacy_pkg(
        tmp_path, monkeypatch, legacy_extra="\n\nRSAKey.HASHES.update({})\n")
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED and ".update()" in c["detail"], c["detail"]


def test_legacy_ssh_confined_is_violated_by_a_send_call(tmp_path, monkeypatch):
    pkg, collector = _legacy_pkg(
        tmp_path, monkeypatch,
        legacy_extra="\n\ndef _leak(conn):\n    return conn.send_command('show version')\n")
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED and "send_command" in c["detail"], c["detail"]


def test_legacy_ssh_confined_is_violated_by_a_sha1_literal_in_another_module(tmp_path, monkeypatch):
    pkg, collector = _legacy_pkg(
        tmp_path, monkeypatch, others={"default_path.py": 'HOST_KEYS = ("rsa-sha2-256", "ssh-rsa")\n'})
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED and "default_path.py" in c["detail"], c["detail"]


def test_legacy_ssh_confined_is_violated_when_another_module_reads_the_tier(tmp_path, monkeypatch):
    pkg, collector = _legacy_pkg(
        tmp_path, monkeypatch,
        others={"widen.py": "from .ssh_session import LEGACY_SHA1_TIER_KEX\nX = LEGACY_SHA1_TIER_KEX\n"})
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED and "widen.py" in c["detail"], c["detail"]


def test_legacy_ssh_confined_is_violated_by_sha1_signing_outside_the_tier(tmp_path, monkeypatch):
    pkg, collector = _legacy_pkg(
        tmp_path, monkeypatch,
        others={"sign.py": "from cryptography.hazmat.primitives import hashes\nH = hashes.SHA1\n"})
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED and "sign.py" in c["detail"], c["detail"]


def test_legacy_ssh_confined_is_violated_by_a_mutable_table_definition(tmp_path, monkeypatch):
    pkg, collector = _legacy_pkg(
        tmp_path, monkeypatch,
        legacy_extra="\n\nclass _Open(Transport):\n    _kex_info = dict(Transport._kex_info)\n")
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED and "not a tuple or a MappingProxyType" in c["detail"], c["detail"]


def test_legacy_ssh_confined_abstains_without_its_source_or_its_subjects(tmp_path, monkeypatch):
    """NOT_EVALUATED, never HOLDS, when there is nothing to judge: no module; a vocabulary owner whose
    literals the pattern cannot recognise; an unscannable collector entry; a module with no table."""
    (tmp_path / "bare").mkdir()
    bare = _fake_pkg(tmp_path / "bare", {"clean.py": "X = 1\n"})
    c = _by_id(compute_attestation(toolkit_dir=bare, collector_module="no_such_collector_module_xyz"))[
        "legacy_ssh_confined"]
    assert c["result"] == NOT_EVALUATED and "legacy_ssh.py" in c["detail"]

    pkg, collector = _legacy_pkg(tmp_path / "novocab", monkeypatch,
                                 vocab='SSH_PROFILES = ("default", "legacy-sha1")\n')
    c = _legacy_claim(pkg, collector)
    assert c["result"] == NOT_EVALUATED and "recognised no literal" in c["detail"], c["detail"]

    pkg, _collector = _legacy_pkg(tmp_path / "nocollector", monkeypatch)
    c = _legacy_claim(pkg, "no_such_collector_module_xyz")
    assert c["result"] == NOT_EVALUATED and "not scannable" in c["detail"], c["detail"]

    (tmp_path / "notables").mkdir()
    notables = _fake_pkg(tmp_path / "notables", {
        "legacy_ssh.py": "from .ssh_session import LEGACY_SHA1_TIER_KEX\n",
        "ssh_session.py": _VOCAB_SRC})
    c = _legacy_claim(notables, collector)
    assert c["result"] == NOT_EVALUATED and "no algorithm table" in c["detail"], c["detail"]


# --------------------------------------- W59 PR-2 review: the legacy module stays judged by both claims ---
@pytest.mark.parametrize("plant,lib", [
    ("\n\nimport socket\n\ndef _leak():\n    return socket.create_connection(('192.0.2.1', 22))\n", "socket"),
    ("\n\nimport urllib.request\n\ndef _leak():\n    return urllib.request.urlopen('http://192.0.2.1/')\n",
     "urllib.request"),
    ("\n\ndef _leak():\n    import requests\n    return requests.post('http://192.0.2.1/', data=b'x')\n", "requests"),
])
def test_t9_a_network_library_planted_in_the_legacy_module_violates_both_claims(tmp_path, monkeypatch, plant, lib):
    """W59 PR-2 review (P1-a). Mutation caught: the whole of legacy_ssh.py excluded from the no-egress walk with
    nothing standing in for it -- a planted ``socket.create_connection``, ``urllib.request.urlopen`` or
    ``requests.post`` left BOTH published claims at HOLDS. Now the walk keeps the file and permits only paramiko
    there, and the confinement claim holds it to a closed import allowlist."""
    pkg, collector = _legacy_pkg(tmp_path, monkeypatch, legacy_extra=plant)
    att = _by_id(compute_attestation(toolkit_dir=pkg, collector_module=collector))
    egress, confined = att["no_egress_import_graph"], att["legacy_ssh_confined"]
    assert egress["result"] == VIOLATED, egress["detail"]
    assert "legacy_ssh.py" in egress["detail"] and lib in egress["detail"]
    assert "paramiko" not in egress["detail"], "the permitted paramiko imports must not be reported"
    assert confined["result"] == VIOLATED, confined["detail"]
    assert f"imports the network library {lib}" in confined["detail"], confined["detail"]


def test_t9_the_legacy_import_allowlist_is_closed(tmp_path, monkeypatch):
    """W59 PR-2 review (P1-a). A non-network import outside the allowlist (here ``subprocess``) also violates the
    confinement claim: the allowlist is closed, not a list of network libraries."""
    pkg, collector = _legacy_pkg(tmp_path, monkeypatch, legacy_extra="\n\nimport subprocess\n")
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED and "imports subprocess (outside the closed import allowlist)" in c["detail"]


@pytest.mark.parametrize("plant", [
    "\n\n_T = Transport\n",
    "\n\ndef _x():\n    dict.update(Transport._kex_info, {})\n",
    "\n\ndef _x():\n    dict.__setitem__(Transport._kex_info, 'k', None)\n",
    "\n\nimport operator\n\ndef _x():\n    operator.setitem(Transport._kex_info, 'k', None)\n",
    "\n\ndef _x():\n    type.__setattr__(Transport, '_kex_info', {})\n",
    "\n\ndef _x():\n    kex = Transport._kex_info\n    return kex\n",
    "\n\ndef _x():\n    return RSAKey.HASHES.copy()\n",
])
def test_legacy_ssh_confined_allows_a_paramiko_table_only_as_a_copy(tmp_path, monkeypatch, plant):
    """W59 PR-2 review (P2-c). Mutations caught: an alias of a stock class, an unbound ``dict.update`` /
    ``dict.__setitem__``, ``operator.setitem``, ``type.__setattr__`` and a plain read of a stock table -- each walked
    past the old denylist of mutating-method spellings. The rule is now an allowlist of copy shapes."""
    pkg, collector = _legacy_pkg(tmp_path, monkeypatch, legacy_extra=plant)
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED, c["detail"]
    assert "other than as a class base or the operand of a copy" in c["detail"], c["detail"]


# ------------------ W59 PR-2 review round 2 (P2): the closed rules, one falsifier per planted route ---
@pytest.mark.parametrize("plant,expected", [
    # (a) a module-level Transport given (host, port) opens a TCP connection when the module is imported
    ("\n\n_PROBE = LegacySHA1Transport(('192.0.2.1', 22))\n",
     ["<module>: calls LegacySHA1Transport (a class or callable derived from a paramiko binding",
      "calls LegacySHA1Transport in <module> (outside the closed call-site allowlist)"]),
    # (b) widening paramiko's stock Transport tables for every thread at runtime, by reflection
    ("\n\ndef _widen(t, n, v):\n    setattr(type(t).mro()[-2], n, v)\n",
     ["names setattr (dynamic code", "reflective attribute mro",
      "attribute mro (outside the closed attribute allowlist)",
      "calls setattr in _widen (outside the closed call-site allowlist)"]),
    # (c) session calls the old send-method denylist did not name
    ("\n\ndef _keepalive(t):\n    return t.global_request('keepalive@openssh.com')\n",
     ["calls t.global_request in _keepalive (outside the closed call-site allowlist)",
      "attribute global_request (outside the closed attribute allowlist)"]),
    ("\n\ndef _rekey(t):\n    return t.renegotiate_keys()\n",
     ["calls t.renegotiate_keys in _rekey (outside the closed call-site allowlist)",
      "attribute renegotiate_keys (outside the closed attribute allowlist)"]),
    ("\n\ndef _pty(chan):\n    return chan.get_pty()\n",
     ["calls chan.get_pty in _pty (outside the closed call-site allowlist)",
      "attribute get_pty (outside the closed attribute allowlist)"]),
    # (d) a module the vocabulary owner itself imports, reached through the old `cisco_toolkit.ssh_session.` prefix
    ("\n\nfrom cisco_toolkit.ssh_session import os\n\ndef _run():\n    return os.system('true')\n",
     ["imports cisco_toolkit.ssh_session.os (outside the closed import allowlist)",
      "calls os.system in _run (outside the closed call-site allowlist)"]),
])
def test_t9_round2_each_planted_route_violates_the_confinement_claim(tmp_path, monkeypatch, plant, expected):
    """W59 PR-2 review round 2 (P2). Mutation caught: the four shapes (a) to (d) the review planted into a copy of the
    real legacy_ssh.py, each of which left `legacy_ssh_confined` at HOLDS, because the send, reflection and import
    rules were named subsets. Each now violates the claim through the CLOSED rules (call sites, attributes, imports)
    and, where it applies, the reused T8 taint fixpoint.

    `no_egress_import_graph` stays HOLDS for these four, and rightly: it is an import-graph claim, none of them adds
    a network-library import, and its charter pairs legacy_ssh.py with this claim, which is what catches them."""
    pkg, collector = _legacy_pkg(tmp_path, monkeypatch, legacy_extra=plant)
    att = _by_id(compute_attestation(toolkit_dir=pkg, collector_module=collector))
    c = att["legacy_ssh_confined"]
    assert c["result"] == VIOLATED, c["detail"]
    for phrase in expected:
        assert phrase in c["detail"], (phrase, c["detail"])
    assert att["no_egress_import_graph"]["result"] == HOLDS, att["no_egress_import_graph"]["detail"]


@pytest.mark.parametrize("plant,expected", [
    # the reused T8 taint alone: an allowlisted spelling rebound to a class derived from paramiko
    ("\n\ntuple = LegacySHA1Transport\n_PROBE = tuple(('192.0.2.1', 22))\n",
     ["<module>: calls tuple (a class or callable derived from a paramiko binding",
      "binds the builtin name tuple in <module>"]),
    # a decorator is a call
    ("\n\n@LegacySHA1Transport\ndef _decorated():\n    return 1\n",
     ["calls @LegacySHA1Transport in <module> (outside the closed call-site allowlist)",
      "<module>: calls @LegacySHA1Transport (a class or callable derived from a paramiko binding"]),
    # a connection-capable value handed to anything but a copy
    ("\n\n_N = len(LegacySHA1Transport._preferred_kex)\n",
     ["<module>: hands a connection-capable value to len() (only a copy may take one"]),
    # an attribute of a runtime-reached object, and a parameter rebound before an allowlisted spelling uses it
    ("\n\nclass _Rebound(LegacyKexGexSHA1):\n    def _parse_kexdh_gex_group(self, m):\n        m = self\n"
     "        return self.transport\n",
     ["attribute transport (outside the closed attribute allowlist)",
      "rebinds m in _parse_kexdh_gex_group"]),
    # an implicit-call statement outside the closed grammar
    ("\n\ndef _entered(x):\n    with x:\n        return 1\n",
     ["With construct (outside the closed grammar)"]),
    # an import alias, and a module paramiko re-exports (the old `paramiko.` prefix admitted it)
    ("\n\nfrom hashlib import sha256 as digest\n",
     ["imports hashlib.sha256 as digest (an import alias", "imports hashlib.sha256 (outside the closed import"]),
    ("\n\nfrom paramiko.transport import socket\n",
     ["imports paramiko.transport.socket (outside the closed import allowlist)"]),
])
def test_t9_round2_each_closed_rule_falsifies_on_its_own_route(tmp_path, monkeypatch, plant, expected):
    """W59 PR-2 review round 2 (P2). Non-vacuity of each new closed rule: the reused T8 taint fixpoint (a callee
    rebound to a paramiko-derived class, which the call-site allowlist alone admits by spelling; a decorator; a
    hand-over to a non-copy), the attribute allowlist, the one-binding rule, the closed grammar, and the exact
    import allowlist with no alias."""
    pkg, collector = _legacy_pkg(tmp_path, monkeypatch, legacy_extra=plant)
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED, c["detail"]
    for phrase in expected:
        assert phrase in c["detail"], (phrase, c["detail"])


def test_t9_round2_a_name_the_vocabulary_owner_only_imports_is_refused(tmp_path, monkeypatch):
    """W59 PR-2 review round 2 (P2, item 4). The tier tuples are admitted by the owner's naming convention, so the
    rule also refuses any vocabulary name the OWNER binds through an import statement -- here a module the owner
    imports under a tier-shaped name, which the naming convention alone would admit."""
    pkg, collector = _legacy_pkg(
        tmp_path, monkeypatch, vocab=_VOCAB_SRC + "import os as LEGACY_SHA1_TIER_OS\n",
        legacy_extra="\n\nfrom cisco_toolkit.ssh_session import LEGACY_SHA1_TIER_OS\n")
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED, c["detail"]
    assert ("imports cisco_toolkit.ssh_session.LEGACY_SHA1_TIER_OS, which the vocabulary owner binds through an "
            "import statement") in c["detail"], c["detail"]


def test_t9_round2_the_closed_allowlists_are_exact_for_the_real_module():
    """W59 PR-2 review round 2 (P2). The allowlists are a census of the real module, not a loose superset: every
    listed call site, attribute and import is one the module really makes, so no stale entry silently pre-admits a
    future call. The grammar adds only its declared harmless siblings. A deliberate change to the tier changes the
    allowlist in the same commit."""
    import ast as _ast

    from cisco_toolkit import attestation as A

    tree = _ast.parse(open(os.path.join(ROOT, "cisco_toolkit", "legacy_ssh.py"), encoding="utf-8").read())
    owners = A.qualified_owners(tree)
    calls = {}
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            calls.setdefault(owners.get(id(node), "<module>"), set()).add(A.call_signature(node))
    # W59 PR-2 review round 3 (P2): each site is its FULL signature -- spelling, positional count, keyword names
    assert calls == {k: set(v) for k, v in A._LEGACY_SSH_CALL_SITES.items()}, calls
    assert not [n for n in _ast.walk(tree) if isinstance(n, (_ast.FunctionDef, _ast.ClassDef)) and n.decorator_list]
    assert not [n for n in _ast.walk(tree) if isinstance(n, _ast.ClassDef) and n.keywords]
    # ... and every copy or projection a connection-capable value may be handed to is one the module really uses
    _found, passes, _tainted, _factories = A.connection_constructor_calls(tree, signatures=True)
    assert {s for sigs in passes.values() for s in sigs} == A._COPY_CALLS | A._NAME_LIST_CALLS, passes
    assert {n.attr for n in _ast.walk(tree) if isinstance(n, _ast.Attribute)} == A._LEGACY_SSH_ATTRIBUTES
    used = {type(n).__name__ for n in _ast.walk(tree)}
    assert used <= A._LEGACY_SSH_GRAMMAR, used - A._LEGACY_SSH_GRAMMAR
    assert A._LEGACY_SSH_GRAMMAR - used == {"Pass", "And", "USub", "LtE", "GtE", "In", "Is", "IsNot"}, \
        A._LEGACY_SSH_GRAMMAR - used
    imported = {name for node in _ast.walk(tree) if isinstance(node, (_ast.Import, _ast.ImportFrom))
                for name, _alias in A._legacy_import_names(node)}
    vocab = {n for n in imported if n.startswith("cisco_toolkit.ssh_session.")}
    assert imported - vocab == A._LEGACY_SSH_IMPORTS_EXACT, imported - vocab
    leaves = {n.rsplit(".", 1)[1] for n in vocab}
    assert leaves - A._LEGACY_SSH_IMPORTS_VOCABULARY == {n for n in leaves if A._LEGACY_TIER_NAME.match(n)}
    assert A._LEGACY_SSH_IMPORTS_VOCABULARY <= leaves
    assert A.legacy_closure_violations(tree)[0] == [] and A._binding_violations(tree) == []


def test_t9_round2_the_taint_rule_abstains_without_a_connection_capable_binding(tmp_path, monkeypatch):
    """Non-vacuity of the reused T8 fixpoint inside the claim: a legacy module with a frozen table and a tier import
    but no paramiko class gives the taint rule no subject, so the claim abstains rather than HOLDS."""
    (tmp_path / "notaint").mkdir()
    pkg = _fake_pkg(tmp_path / "notaint", {
        "legacy_ssh.py": "from .ssh_session import LEGACY_SHA1_TIER_KEX\n"
                         "_preferred_kex = tuple(LEGACY_SHA1_TIER_KEX)\n",
        "ssh_session.py": _VOCAB_SRC})
    _pkg, collector = _legacy_pkg(tmp_path / "collector", monkeypatch)
    c = _legacy_claim(pkg, collector)
    assert c["result"] == NOT_EVALUATED, c["detail"]
    assert "the taint fixpoint found 0 connection-capable binding(s)" in c["detail"], c["detail"]


# ---------- W59 PR-2 review round 3 (P2): implicit calls through an allowlisted spelling, or a laundering copy ---
_RETURN = "    return _TRANSPORT_BY_PROFILE[profile]\n"
_IMPLICIT_CALL_ROUTES = [
    # sorted() is allowlisted in transport_for, so only its pinned SIGNATURE refuses a key= that calls the class
    ((_RETURN, "    return sorted(((profile, 22),), key=LegacySHA1Transport)\n"), "",
     ["calls sorted in transport_for (outside the closed call-site allowlist): sorted(_, key=_)",
      "transport_for: hands a connection-capable value to sorted() (only a copy may take one"]),
    (("{sorted(_TRANSPORT_BY_PROFILE)}", "{sorted(_TRANSPORT_BY_PROFILE, key=LegacySHA1Transport)}"), "",
     ["calls sorted in transport_for (outside the closed call-site allowlist): sorted(_, key=_)",
      "transport_for: hands a connection-capable value to sorted() (only a copy may take one"]),
    # ... and the class reached through the frozen mapping that holds it: the copy must not launder its member
    ((_RETURN, "    return sorted(((profile, 22),), key=_TRANSPORT_BY_PROFILE[profile])\n"), "",
     ["calls sorted in transport_for (outside the closed call-site allowlist): sorted(_, key=_)",
      "transport_for: hands a connection-capable value to sorted() (only a copy may take one"]),
    # a mapping lookup, then a call
    ((_RETURN, "    return _TRANSPORT_BY_PROFILE[profile]((profile, 22))\n"), "",
     ["transport_for: calls _TRANSPORT_BY_PROFILE[profile] (a class or callable derived from a paramiko binding"]),
    # getattr on the mapping
    ((_RETURN, "    return getattr(_TRANSPORT_BY_PROFILE, 'get')(profile)((profile, 22))\n"), "",
     ["transport_for: calls getattr(_TRANSPORT_BY_PROFILE, 'get')(profile) (a class or callable derived from a "
      "paramiko binding", "names getattr (dynamic code"]),
    # map() and filter() call what they are handed
    ((_RETURN, "    return tuple(map(_TRANSPORT_BY_PROFILE[profile], ((profile, 22),)))\n"), "",
     ["transport_for: hands a connection-capable value to map() (only a copy may take one"]),
    ((_RETURN, "    return tuple(filter(_TRANSPORT_BY_PROFILE[profile], ((profile, 22),)))\n"), "",
     ["transport_for: hands a connection-capable value to filter() (only a copy may take one"]),
    # a dict.get lookup, then a call; and the same bound method held in a local first
    ((_RETURN, "    return _TRANSPORT_BY_PROFILE.get(profile)((profile, 22))\n"), "",
     ["transport_for: calls _TRANSPORT_BY_PROFILE.get(profile) (a class or callable derived from a paramiko binding",
      "attribute get (outside the closed attribute allowlist)"]),
    ((_RETURN, "    pick = _TRANSPORT_BY_PROFILE.get\n    return pick(profile)((profile, 22))\n"), "",
     ["transport_for: calls pick(profile) (a class or callable derived from a paramiko binding"]),
    # a `+` copy (one the table rule accepts) keeps its members too
    (None, "\n\n_EVERY = (LegacySHA1Transport,) + ()\n\n\ndef _first():\n    return _EVERY[0](('192.0.2.1', 22))\n",
     ["_first: calls _EVERY[0] (a class or callable derived from a paramiko binding"]),
]


@pytest.mark.parametrize("replace,extra,expected", _IMPLICIT_CALL_ROUTES,
                         ids=["sorted-key-class", "sorted-key-in-allowlisted-site", "sorted-key-via-mapping",
                              "mapping-lookup-call", "getattr-on-mapping", "map", "filter", "dict-get-call",
                              "bound-get-alias", "plus-copy"])
def test_t9_round3_each_implicit_call_route_violates_the_confinement_claim(tmp_path, monkeypatch, replace, extra,
                                                                          expected):
    """W59 PR-2 review round 3 (P2). Mutation caught: a one-line edit of the real legacy_ssh.py that makes a class
    derived from paramiko be called IMPLICITLY -- ``sorted(..., key=LegacySHA1Transport)`` (``Transport(str)`` opens
    a TCP connection) under the allowlisted ``sorted`` spelling, or the class reached through the frozen
    ``_TRANSPORT_BY_PROFILE`` mapping (a lookup, ``getattr``, ``map``, ``filter``, ``.get``, a held bound method) or a
    ``+`` copy. Round 2 keyed the call-site allowlist by the callee's spelling only, and its taint model treated a
    copy's result as clean, so ``sorted(..., key=_TRANSPORT_BY_PROFILE[profile])`` left the claim at HOLDS. Each route
    now violates it, and each through the TAINT rule itself (the expected phrases), whatever the call-site and
    attribute allowlists also say."""
    pkg, collector = _legacy_pkg(tmp_path, monkeypatch, legacy_extra=extra, legacy_replace=replace)
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED, c["detail"]
    for phrase in expected:
        assert phrase in c["detail"], (phrase, c["detail"])


def test_t9_round3_a_copy_keeps_its_members_taint_and_only_untainted_contents_are_clean():
    """W59 PR-2 review round 3 (P2), at the model: a copy (``MappingProxyType``, ``tuple``, ``sorted``,
    ``dict.fromkeys``, a ``+``) of a display or a mapping that holds a tainted value is tainted; a copy of untainted
    contents is clean; and the name-list rendering's result is a ``str``, clean by construction."""
    import ast as _ast

    from cisco_toolkit.attestation import connection_constructor_calls

    src = ("from types import MappingProxyType\nfrom paramiko.transport import Transport\n"
           "HELD = MappingProxyType({'p': Transport})\nPAIR = tuple((Transport,))\nBOTH = ('a',) + (Transport,)\n"
           "ORDER = sorted(HELD)\nKEYS = dict.fromkeys(PAIR)\n"
           "NAMES = MappingProxyType({'p': 'name'})\nWORDS = tuple(('a', 'b'))\nSUM = ('a',) + ('b',)\n"
           "LISTED = sorted(('b', 'a'))\nRENDERED = ','.join(Transport._preferred_kex)\n"
           "def build():\n    return HELD['p'](('192.0.2.1', 22))\n")
    found, passes, tainted, factories = connection_constructor_calls(_ast.parse(src), signatures=True)
    names = {name for scope, name in tainted if scope == "<module>"}
    assert {"HELD", "PAIR", "BOTH", "ORDER", "KEYS"} <= names, names
    assert not {"NAMES", "WORDS", "SUM", "LISTED", "RENDERED"} & names, names
    assert found == {"build": [("HELD['p']", 1, ())]}, found
    assert ("','.join", 1, ()) in passes["<module>"], passes
    assert factories == set(), factories                     # build() calls the class; it returns an instance


@pytest.mark.parametrize("text,name", [
    ("kex=diffie-hellman-group14-sha1", "diffie-hellman-group14-sha1"),
    ("host-keys/ssh-rsa", "ssh-rsa"),
    ("HostKeyAlgorithms:ssh-dss", "ssh-dss"),
])
def test_t9_round3_a_sha1_name_joined_by_any_non_name_character_is_a_literal(tmp_path, monkeypatch, text, name):
    """W59 PR-2 review round 3 (P3). Mutation caught: a SHA-1 SSH name in a default-path module joined to its
    neighbour by '=', '/' or ':' -- the round-2 tokeniser split only on a hand-kept delimiter class, so each of these
    left the confinement claim at HOLDS. A name is now matched wherever it occurs, bounded by any character that
    cannot continue it."""
    pkg, collector = _legacy_pkg(tmp_path, monkeypatch, others={"joined.py": f"OPTION = {text!r}\n"})
    c = _legacy_claim(pkg, collector)
    assert c["result"] == VIOLATED, c["detail"]
    assert f"joined.py:1: SSH SHA-1 algorithm literal {name!r} outside the vocabulary owner" in c["detail"], c["detail"]


def test_t9_round3_the_method_text_is_rendered_from_the_allowlists(tmp_path, monkeypatch):
    """W59 PR-2 review round 3 (P3). Mutation caught: the published method restating an allowlist's size or members
    ("two types names", "five paramiko classes") instead of rendering them, so a widened allowlist kept describing
    the old one. Every count and list is read from its allowlist, and moves with it."""
    from cisco_toolkit import attestation as A

    pkg, collector = _legacy_pkg(tmp_path, monkeypatch)
    method = _legacy_claim(pkg, collector)["method"]
    assert method == A._legacy_ssh_method()
    assert f"exact list of {len(A._LEGACY_SSH_IMPORTS_EXACT)} names" in method
    assert all(name in method for name in A._LEGACY_SSH_IMPORTS_EXACT | A._LEGACY_SSH_IMPORTS_VOCABULARY)
    assert f"{len(A._LEGACY_SSH_IMPORTS_VOCABULARY)} pinned names" in method
    assert f"closed list of {sum(len(v) for v in A._LEGACY_SSH_CALL_SITES.values())} call sites" in method
    assert f"closed list of {len(A._LEGACY_SSH_ATTRIBUTES)};" in method
    assert f"closed grammar of {len(A._LEGACY_SSH_GRAMMAR)} (none of " in method
    assert all(A.render_call(s) in method for s in A._COPY_CALLS | A._NAME_LIST_CALLS)
    assert "two types names" not in method and "five paramiko classes" not in method
    # widen two allowlists: the text follows them
    monkeypatch.setattr(A, "_LEGACY_SSH_IMPORTS_EXACT", A._LEGACY_SSH_IMPORTS_EXACT | {"paramiko.client.SSHClient"})
    monkeypatch.setattr(A, "_LEGACY_SSH_GRAMMAR", A._LEGACY_SSH_GRAMMAR | {"With"})
    widened = A._legacy_ssh_method()
    assert "paramiko.client.SSHClient" in widened
    assert f"exact list of {len(A._LEGACY_SSH_IMPORTS_EXACT)} names" in widened
    excluded = widened.split("(none of ", 1)[1].split(")", 1)[0].split(", ")
    assert "With" not in excluded and "For" in excluded, excluded
