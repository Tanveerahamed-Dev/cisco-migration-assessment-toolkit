"""Zero-parse yield telemetry (Plan A / Tier-1 #3) — the #1 recurring bug class made
visible at its chokepoint.

The class: an unseen platform variant parses to []/{}, which is byte-identical to
"feature absent" everywhere downstream (the real NX-OS ubest/mbest RIB once zeroed this
way and survived four audit waves). The fix is telemetry at the SINGLE chokepoint every
builder already goes through (cmdio._load_cmd_output / cmdio._safe_parse): when a command
RETURNED CONTENT but its parser produced 0 entities, that is recorded as a
collected-but-unparsed event — a possible format-fidelity gap, NEVER a device verdict.
Absent / error captures stay the Collection Completeness axis's domain and must NOT be
counted here (that would be cry-wolf)."""
import threading

import pytest

from cisco_toolkit import cmdio


# --- named probe parsers (the ledger records fn.__name__) ---
def probe_zero(text):
    return {}


def probe_entities(text):
    return {"a": 1, "b": 2}


def probe_raises(text):
    raise ValueError("malformed block")


CONTENT = "\n".join(f"route {i} via 10.0.0.{i}" for i in range(8)) + "\n"


@pytest.fixture()
def ledger():
    cmdio.reset_parse_ledger()
    yield
    cmdio.reset_parse_ledger()


def _write_capture(tmp_path, device="SW-CORE-01", cmd="show ip route", content=CONTENT):
    dev_dir = tmp_path / device
    dev_dir.mkdir(parents=True, exist_ok=True)
    p = dev_dir / (cmd.replace(" ", "_") + ".txt")
    p.write_text(content, encoding="utf-8")
    return {cmd: str(p)}


def test_content_in_zero_out_is_recorded_with_attribution(tmp_path, ledger):
    """The marquee case: real content in, zero entities out -> ONE suspect event carrying
    (device, cmd, parser, lines_in) — the row the NX-OS-RIB class becomes on first run."""
    c2f = _write_capture(tmp_path)
    out = cmdio._load_cmd_output(c2f, "show ip route")
    assert out                                            # precondition: content present
    assert cmdio._safe_parse(probe_zero, out) == {}
    rep = cmdio.parse_yield_report()
    assert rep["summary"]["zero_yield_suspect"] == 1
    (ev,) = rep["events"]
    assert ev["parser"] == "probe_zero"
    assert ev["device"] == "SW-CORE-01"                   # from the capture file's parent dir
    assert ev["cmd"] == "show ip route"
    assert ev["lines_in"] >= 3
    pp = rep["per_parser"]["probe_zero"]
    assert pp["calls"] == 1 and pp["with_content"] == 1 and pp["zero_yield"] == 1


def test_absent_capture_is_not_a_yield_event(ledger):
    """Absent command (loader returns '') must NOT count — absence is Collection
    Completeness's domain; counting it here would be the cry-wolf failure mode."""
    assert cmdio._safe_parse(probe_zero, "") == {}
    rep = cmdio.parse_yield_report()
    assert rep["summary"]["zero_yield_suspect"] == 0
    assert rep["events"] == []
    assert rep["per_parser"]["probe_zero"]["with_content"] == 0


def test_tiny_content_below_threshold_is_not_flagged(tmp_path, ledger):
    """A 1-2 line output (banner/prompt echo) is not 'content'; header-only outputs must
    not spam events."""
    c2f = _write_capture(tmp_path, content="Codes: C - connected\n")
    out = cmdio._load_cmd_output(c2f, "show ip route")
    cmdio._safe_parse(probe_zero, out)
    assert cmdio.parse_yield_report()["summary"]["zero_yield_suspect"] == 0


def test_single_line_json_blob_is_content(tmp_path, ledger):
    """Controller-REST captures are often ONE long JSON line — chars, not lines, make
    them content; a zero-entity parse of a fat JSON blob is exactly the REST-channel
    format-fidelity case."""
    blob = '{"imdata": [' + ",".join('{"x": %d}' % i for i in range(60)) + ']}'
    assert len(blob) >= cmdio.MIN_CONTENT_CHARS and blob.count("\n") == 0
    c2f = _write_capture(tmp_path, cmd="aci class fvTenant", content=blob)
    out = cmdio._load_cmd_output(c2f, "aci class fvTenant")
    cmdio._safe_parse(probe_zero, out)
    assert cmdio.parse_yield_report()["summary"]["zero_yield_suspect"] == 1


def test_entities_out_is_not_an_event(tmp_path, ledger):
    c2f = _write_capture(tmp_path)
    out = cmdio._load_cmd_output(c2f, "show ip route")
    cmdio._safe_parse(probe_entities, out)
    rep = cmdio.parse_yield_report()
    assert rep["summary"]["zero_yield_suspect"] == 0
    pp = rep["per_parser"]["probe_entities"]
    assert pp["calls"] == 1 and pp["with_content"] == 1 and pp["zero_yield"] == 0


def test_parser_exception_on_content_is_recorded_as_error_event(tmp_path, ledger):
    """A parser RAISING on real content is the same fidelity class (fail-soft already
    returns {} — the ledger must remember it happened)."""
    c2f = _write_capture(tmp_path)
    out = cmdio._load_cmd_output(c2f, "show ip route")
    assert cmdio._safe_parse(probe_raises, out) == {}     # fail-soft contract unchanged
    rep = cmdio.parse_yield_report()
    assert rep["summary"]["parse_errors"] == 1
    (ev,) = rep["events"]
    assert ev["error"] is True and ev["parser"] == "probe_raises"


def test_may_be_empty_parser_is_listed_but_not_suspect(tmp_path, ledger, monkeypatch):
    """The cry-wolf guard: parsers whose zero-on-content is a NORMAL healthy state
    (no blocked ports, no drops) stay visible in the ledger but out of the red count."""
    monkeypatch.setattr(cmdio, "MAY_BE_EMPTY_PARSERS", frozenset({"probe_zero"}))
    c2f = _write_capture(tmp_path)
    out = cmdio._load_cmd_output(c2f, "show ip route")
    cmdio._safe_parse(probe_zero, out)
    rep = cmdio.parse_yield_report()
    assert rep["summary"]["zero_yield_suspect"] == 0
    assert rep["summary"]["zero_yield_expected"] == 1
    assert rep["per_parser"]["probe_zero"]["may_be_empty"] is True
    assert len(rep["events"]) == 1                        # still visible, honestly labeled


def test_unpaired_content_degrades_to_unattributed(tmp_path, ledger):
    """When the parsed text is not the loader's last capture (sliced/derived content),
    attribution must degrade HONESTLY to [unattributed] — never guess a device."""
    c2f = _write_capture(tmp_path)
    cmdio._load_cmd_output(c2f, "show ip route")
    derived = CONTENT + "extra line that changes the length\n" * 3
    cmdio._safe_parse(probe_zero, derived)
    (ev,) = cmdio.parse_yield_report()["events"]
    assert ev["device"] == "[unattributed]" and ev["cmd"] == "[unattributed]"


def test_load_once_parse_twice_keeps_attribution(tmp_path, ledger):
    """build_acls-style reuse: one load feeds several parsers — the stash must survive
    (not consumed-on-use) so the second parse still attributes."""
    c2f = _write_capture(tmp_path)
    out = cmdio._load_cmd_output(c2f, "show ip route")
    cmdio._safe_parse(probe_zero, out)
    cmdio._safe_parse(probe_zero, out)
    evs = cmdio.parse_yield_report()["events"]
    assert len(evs) == 2 and all(e["device"] == "SW-CORE-01" for e in evs)


def test_thread_isolation_no_cross_attribution(tmp_path, ledger):
    """Phase-3 parses devices in a ThreadPoolExecutor — the load↔parse pairing is
    thread-local, so concurrent devices must never steal each other's attribution."""
    n = 40
    devices = {
        "SW-A": _write_capture(tmp_path, device="SW-A", content=CONTENT),
        "SW-B": _write_capture(tmp_path, device="SW-B", content=CONTENT + "pad line B\n" * 7),
    }

    def work(dev):
        c2f = devices[dev]
        for _ in range(n):
            out = cmdio._load_cmd_output(c2f, "show ip route")
            cmdio._safe_parse(probe_zero, out)

    threads = [threading.Thread(target=work, args=(d,)) for d in devices]
    for t in threads: t.start()
    for t in threads: t.join()
    rep = cmdio.parse_yield_report()
    assert rep["per_parser"]["probe_zero"]["calls"] == 2 * n
    for ev in rep["events"]:
        assert ev["device"] in ("SW-A", "SW-B")
        assert ev["device"] != "[unattributed]", "thread-local pairing lost under concurrency"
    # every event attributed to the RIGHT device: lengths differ, so a cross would have
    # been len-rejected into [unattributed] — asserted above — or mis-paired, impossible
    # with a thread-local stash.
    assert rep["summary"]["zero_yield_suspect"] == min(2 * n, cmdio._YIELD_EVENT_CAP) or \
        rep["summary"]["zero_yield_suspect"] == 2 * n


def test_event_cap_truncates_honestly(tmp_path, ledger, monkeypatch):
    monkeypatch.setattr(cmdio, "_YIELD_EVENT_CAP", 5)
    c2f = _write_capture(tmp_path)
    out = cmdio._load_cmd_output(c2f, "show ip route")
    for _ in range(9):
        cmdio._safe_parse(probe_zero, out)
    rep = cmdio.parse_yield_report()
    assert len(rep["events"]) == 5
    assert rep["events_truncated"] is True
    assert rep["per_parser"]["probe_zero"]["zero_yield"] == 9   # counters keep full truth


def test_report_wording_is_coverage_honest(ledger):
    """The published note must say collected-but-unparsed / possible format gap and must
    NOT read as a device health verdict (the false-health wording class)."""
    note = cmdio.parse_yield_report()["summary"]["note"].lower()
    assert "never a device" in note or "not a device" in note
    assert "format" in note
    assert "healthy" not in note


def test_unknown_rib_format_is_a_suspect_event(tmp_path, ledger):
    """THE marquee regression (the class that motivated this whole axis): a real RIB in a
    format the parser cannot read must surface as a SUSPECT event on its first run —
    never survive as a silent []. Uses the REAL parse_ip_routes against a route table
    shaped like nothing it knows."""
    from cisco_toolkit.parse import parse_ip_routes
    alien_rib = "\n".join(
        f"10.{i}.0.0/16    *[OSPF/10] 3d 04:12:{i:02d}, metric {i}\n"
        f"                    >  to 192.168.1.{i} via ge-0/0/{i}" for i in range(6))
    c2f = _write_capture(tmp_path, device="NX-CORE-7", cmd="show ip route", content=alien_rib)
    out = cmdio._load_cmd_output(c2f, "show ip route")
    result = cmdio._safe_parse(parse_ip_routes, out)
    assert not result, "precondition: the alien RIB must parse to zero routes"
    rep = cmdio.parse_yield_report()
    assert rep["summary"]["zero_yield_suspect"] >= 1
    assert any(e["parser"] == "parse_ip_routes" and e["device"] == "NX-CORE-7"
               for e in rep["events"])
    assert "parse_ip_routes" not in cmdio.MAY_BE_EMPTY_PARSERS, \
        "the RIB parser must NEVER be flagged expected-empty (that re-opens the NX-OS hole)"


def test_run_config_family_is_seeded_expected_empty():
    """The cry-wolf class found on the fixture run: run-config-fed parsers zero out
    legitimately on feature-less devices — they must be seeded may_be_empty (and the
    interface-block parser must NOT be, since every real config has interfaces)."""
    for p in ("parse_acls", "parse_object_groups", "parse_nat", "parse_security",
              "parse_config_hygiene", "parse_redistribution"):
        assert p in cmdio.MAY_BE_EMPTY_PARSERS, f"{p} must be seeded expected-empty"
    assert "parse_run_config_interfaces" not in cmdio.MAY_BE_EMPTY_PARSERS


def test_reset_clears_everything(tmp_path, ledger):
    c2f = _write_capture(tmp_path)
    out = cmdio._load_cmd_output(c2f, "show ip route")
    cmdio._safe_parse(probe_zero, out)
    cmdio.reset_parse_ledger()
    rep = cmdio.parse_yield_report()
    assert rep["events"] == [] and rep["per_parser"] == {}
    assert rep["summary"]["zero_yield_suspect"] == 0
