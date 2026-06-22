"""Read-only REST collector tests (Cisco ACI/APIC + Catalyst SD-WAN/vManage).

The HTTP transport is MOCKED (monkeypatched _post / _get_json / _get_text) — a network client is verified by
mocking its transport, not by hitting a live controller. The key property: the collector writes JSON exports
under the SAME offline command-filenames the engine's offline (`--no-collect`) parsers read, so the loop
collector -> offline parser -> detector closes. Also locks the safety contract (login-only POST; the password
is used once and never persisted to any written file)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cisco_toolkit import rest_collect, parse   # noqa: E402


class _FakeResp:
    def __init__(self, body=""):
        self._b = body.encode("utf-8") if isinstance(body, str) else body

    def read(self):
        return self._b


def test_collect_apic_writes_offline_files_then_parsers_read_them(tmp_path, monkeypatch):
    """ACI collector: aaaLogin (POST) then GET each MO class, writing JSON under the offline command-filenames
    build_aci/parse_aci_* read — closing the loop without a live APIC (mocked HTTP)."""
    posted = []

    def fake_post(opener, url, data, headers=None, timeout=30):
        posted.append((url, data))
        return _FakeResp("{}")

    APIC = {
        "faultInst": {"totalCount": "1", "imdata": [{"faultInst": {"attributes": {
            "code": "F1394", "severity": "critical", "lc": "raised", "ack": "no", "dn": "d", "descr": "port down"}}}]},
        "fabricNode": {"imdata": [{"fabricNode": {"attributes": {
            "id": "102", "name": "leaf-102-OLD", "fabricSt": "decommissioned", "adSt": "off"}}}]},
        "fabricHealthTotal": {"imdata": [{"fabricHealthTotal": {"attributes": {"cur": "82", "maxSev": "critical"}}}]},
    }

    def fake_get_json(opener, url, headers=None, timeout=30):
        for cls, obj in APIC.items():
            if f"/{cls}.json" in url:
                return obj
        return None

    monkeypatch.setattr(rest_collect, "_post", fake_post)
    monkeypatch.setattr(rest_collect, "_get_json", fake_get_json)

    out = str(tmp_path / "apic1")
    files = rest_collect.collect_apic("https://apic.example/", "ro-user", "s3cret", out)

    # login happened, and the password was sent ONCE (login body) ...
    assert posted and "aaaLogin" in posted[0][0]
    assert posted[0][1]["aaaUser"]["attributes"]["pwd"] == "s3cret"
    assert len(posted) == 1, "only the login is a POST — every fabric query is a GET (read-only)"
    # ... the 3 exports were written under the offline filenames ...
    assert len(files) == 3
    fn = lambda c: os.path.join(out, rest_collect._cmd_filename(c))   # noqa: E731
    assert os.path.isfile(fn("moquery -c faultInst"))
    # ... and the password is NOT persisted in any written file.
    blob = "".join(open(p, encoding="utf-8").read() for p in files)
    assert "s3cret" not in blob
    # CLOSE THE LOOP: the offline parsers read the collector's output verbatim.
    faults = parse.parse_aci_faults(open(fn("moquery -c faultInst"), encoding="utf-8").read())
    assert faults and faults[0]["code"] == "F1394" and faults[0]["severity"] == "critical"
    nodes = parse.parse_aci_fabric_nodes(open(fn("moquery -c fabricNode"), encoding="utf-8").read())
    assert nodes[0]["fabric_st"] == "decommissioned"
    health = parse.parse_aci_health(open(fn("moquery -c fabricHealthTotal"), encoding="utf-8").read())
    assert health["cur"] == 82


def test_collect_vmanage_writes_offline_files_then_parsers_read_them(tmp_path, monkeypatch):
    """vManage collector: j_security_check (POST) -> JSESSIONID, fetch the XSRF token, then GET each
    /dataservice endpoint (carrying the X-XSRF-TOKEN header), writing JSON parse_sdwan_* read — mocked HTTP."""
    posted = []

    def fake_post(opener, url, data, headers=None, timeout=30):
        posted.append(url)
        return _FakeResp("OK")   # not the HTML login page -> auth accepted

    def fake_get_text(opener, url, headers=None, timeout=30):
        return "XSRFTOKEN123" if "client/token" in url else None

    DS = {
        "/dataservice/device": {"data": [{"system-ip": "10.10.1.99", "host-name": "BR99", "reachability": "unreachable"}]},
        "/dataservice/device/control/connections": {"data": [{"system-ip": "10.10.1.13", "host-name": "BR13", "peer-type": "vsmart", "state": "down", "expected-connections": 2, "actual-connections": 0}]},
        "/dataservice/device/counters": {"data": [{"system-ip": "10.10.1.13", "host-name": "BR13", "ompPeersUp": 1, "ompPeersDown": 1}]},
    }

    def fake_get_json(opener, url, headers=None, timeout=30):
        assert headers and headers.get("X-XSRF-TOKEN") == "XSRFTOKEN123", "dataservice GETs must carry the XSRF token"
        for ep, obj in DS.items():
            if url.endswith(ep):
                return obj
        return None

    monkeypatch.setattr(rest_collect, "_post", fake_post)
    monkeypatch.setattr(rest_collect, "_get_text", fake_get_text)
    monkeypatch.setattr(rest_collect, "_get_json", fake_get_json)

    out = str(tmp_path / "vmanage1")
    files = rest_collect.collect_vmanage("https://vmanage.example:8443", "ro", "pw", out)

    assert posted and posted[0].endswith("/j_security_check") and len(posted) == 1
    assert len(files) == 3
    fn = lambda c: os.path.join(out, rest_collect._cmd_filename(c))   # noqa: E731
    devs = parse.parse_sdwan_devices(open(fn("dataservice/device"), encoding="utf-8").read())
    assert devs[0]["reachability"] == "unreachable"
    conns = parse.parse_sdwan_control_connections(open(fn("dataservice/device/control/connections"), encoding="utf-8").read())
    assert conns[0]["state"] == "down"
    omp = parse.parse_sdwan_omp_counters(open(fn("dataservice/device/counters"), encoding="utf-8").read())
    assert omp[0]["omp_down"] == 1


def test_collect_login_failure_is_fail_soft(tmp_path, monkeypatch):
    """A failed login writes nothing and returns [] (fail-soft; never raises). vManage HTML login page is
    treated as auth-rejected."""
    monkeypatch.setattr(rest_collect, "_post", lambda *a, **k: None)
    assert rest_collect.collect_apic("https://x", "u", "p", str(tmp_path / "a")) == []
    monkeypatch.setattr(rest_collect, "_post", lambda *a, **k: _FakeResp("<html><body>login</body></html>"))
    assert rest_collect.collect_vmanage("https://x", "u", "p", str(tmp_path / "v")) == []


def test_collect_refuses_non_https(monkeypatch, tmp_path):
    """Security: the collectors refuse a non-HTTPS controller URL (the login would leak the password in
    cleartext) -- they return [] WITHOUT ever issuing the login POST."""
    posted = []
    monkeypatch.setattr(rest_collect, "_post", lambda *a, **k: (posted.append(a), _FakeResp("{}"))[1])
    assert rest_collect.collect_apic("http://apic.example", "u", "secret", str(tmp_path / "a")) == []
    assert rest_collect.collect_vmanage("http://vmanage.example:8443", "u", "secret", str(tmp_path / "v")) == []
    assert posted == [], "no login POST may be sent to a non-HTTPS URL (the password would be cleartext)"
