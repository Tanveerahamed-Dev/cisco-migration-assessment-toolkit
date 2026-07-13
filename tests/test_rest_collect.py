"""Read-only REST collector tests (Cisco ACI/APIC + Catalyst SD-WAN/vManage).

The HTTP transport is MOCKED (monkeypatched _post / _get_json / _get_text) — a network client is verified by
mocking its transport, not by hitting a live controller. The key property: the collector writes JSON exports
under the SAME offline command-filenames the engine's offline (`--no-collect`) parsers read, so the loop
collector -> offline parser -> detector closes. Also locks the safety contract (login-only POST; the password
is used once and never persisted to any written file)."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cisco_toolkit import rest_collect, parse   # noqa: E402


class _FakeResp:
    def __init__(self, body=""):
        self._b = body.encode("utf-8") if isinstance(body, str) else body

    def read(self):
        return self._b

    def close(self):                       # collectors close the login response (no fd left dangling)
        pass


def test_safe_url_preserves_ipv6_brackets_when_stripping_creds():
    """[audit-5 sec LOW] _safe_url strips embedded userinfo before logging, but urlsplit().hostname returns an
    IPv6 literal WITHOUT its brackets, so rebuilding host:port yielded an ambiguous / RFC-3986-invalid authority
    in the [rest] log line. The credential must still be removed (the security-critical property) AND the IPv6
    literal must keep its brackets so the host:port stays unambiguous."""
    out = rest_collect._safe_url("https://rouser:S3cret@[2001:db8::1]:9060/ers/config/node")
    assert "S3cret" not in out and "rouser" not in out      # userinfo stripped
    assert "[2001:db8::1]:9060" in out                       # brackets restored -> unambiguous host:port
    assert rest_collect._safe_url("https://u:p@10.0.0.1:443/x") == "https://10.0.0.1:443/x"   # IPv4 unaffected


def test_collect_refuses_redirect_downgrade_and_cross_host():
    """Security: a redirect that would leak the credential is REFUSED on TWO vectors. _require_https only guards
    the FIRST hop, but urllib's stock HTTPRedirectHandler follows a 30x and re-sends the session cookie /
    Basic-auth Authorization header to the new location. (1) An https->http DOWNGRADE would put the credential
    on the wire in cleartext. (2) A same-scheme CROSS-HOST redirect (a controller / MITM / poisoned DNS that
    answers with a 302 to https://attacker/) would deliver the still-encrypted credential straight to an attacker
    host. A read-only collector pointed at ONE controller has no reason to follow an auth redirect to a different
    host, so the handler must refuse both -- only a SAME-HOST https->https redirect (a different path/port on the
    same controller) is delegated to urllib."""
    import urllib.request
    import urllib.error
    opener = rest_collect._http_session()
    assert any(isinstance(h, rest_collect._NoDowngradeRedirectHandler) for h in opener.handlers), \
        "the opener must install the no-downgrade redirect handler"
    h = rest_collect._NoDowngradeRedirectHandler()
    req = urllib.request.Request("https://controller.example/api/x")
    with pytest.raises(urllib.error.HTTPError):        # https -> http downgrade is refused (raises -> fail-soft None)
        h.redirect_request(req, None, 302, "Found", {}, "http://evil.example/login")
    # a same-HOST https -> https redirect (a different path on the same controller) must still be allowed
    same_host = h.redirect_request(req, None, 302, "Found", {}, "https://controller.example/api/y")
    assert same_host is not None, "a same-host https->https redirect must be allowed, not refused"
    # but a CROSS-HOST same-scheme redirect is REFUSED -- urllib's stock handler would re-send the credential
    # to the foreign host (the same-scheme cross-host credential-exfiltration vector)
    cred_req = urllib.request.Request("https://controller.example/api/x",
                                      headers={"Authorization": "Basic dXNlcjpwYXNz"})
    with pytest.raises(urllib.error.HTTPError):
        h.redirect_request(cred_req, None, 302, "Found", {}, "https://attacker.example/collect")


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


def test_collect_apic_skips_rbac_denied_error_envelope(tmp_path, monkeypatch):
    """[audit-5 #17 false-health] An APIC response whose imdata carries an {'error':...} MO is a fault /
    RBAC-denied envelope, not class data. collect_apic wrote it to disk anyway, so the offline parser read a
    denied class as collected-but-empty. Such envelopes must NOT be written."""
    monkeypatch.setattr(rest_collect, "_post", lambda *a, **k: _FakeResp("{}"))
    monkeypatch.setattr(rest_collect, "_safe_close", lambda *a, **k: None)
    err = {"totalCount": "1", "imdata": [{"error": {"attributes": {"code": "403", "text": "RBAC denied"}}}]}
    monkeypatch.setattr(rest_collect, "_get_json", lambda *a, **k: err)
    assert rest_collect.collect_apic("https://apic.example", "u", "p", str(tmp_path)) == []


def test_collect_ise_ers_paginates_and_keeps_node_on_detail_failure(tmp_path, monkeypatch):
    """[audit-5 #16 false-health] The ISE ERS collector read only page 1 of the node list and silently DROPPED
    any node whose per-id detail GET failed -> an under-reported node census. It must follow nextPage AND keep
    the list summary when a detail GET fails."""
    import json as _json

    def fake_get(opener, url, headers=None, timeout=30):
        if url.endswith("/ers/config/node"):                       # ERS list page 1
            return {"SearchResult": {"resources": [{"id": "n1", "name": "A"}, {"id": "n2", "name": "B"}],
                                     "nextPage": {"href": "https://ise:9060/ers/config/node?page=2"}}}
        if "page=2" in url:                                        # ERS list page 2
            return {"SearchResult": {"resources": [{"id": "n3", "name": "C"}]}}
        if url.endswith("/node/n2"):                               # n2 detail GET FAILS
            return None
        if "/ers/config/node/" in url:                             # n1 / n3 detail GET ok
            rid = url.rsplit("/", 1)[-1]
            return {"ers-node-data": {"id": rid, "name": rid.upper()}}
        return {}                                                  # other (Open-API) endpoints
    monkeypatch.setattr(rest_collect, "_get_json", fake_get)
    written = rest_collect.collect_ise("https://ise.example", "u", "p", str(tmp_path))
    found = None
    for f in written:
        try:
            data = _json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("resources"), list):
            ids = {n.get("id") for n in data["resources"] if isinstance(n, dict)}
            if {"n1", "n2", "n3"} <= ids:
                found = ids
    assert found == {"n1", "n2", "n3"}        # p2 followed + n2 kept despite its detail GET failing


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


def test_get_json_is_fail_soft_on_non_json_and_none(monkeypatch):
    """The parse-fidelity floor for every controller: a non-JSON body or a failed GET → None, never a raise
    (rest_collect.py:145-152) — one bad query never aborts the whole collection."""
    from cisco_toolkit import rest_collect as RC
    monkeypatch.setattr(RC, "_get_text", lambda *a, **k: "this is not json")
    assert RC._get_json(None, "https://apic/api/x") is None
    monkeypatch.setattr(RC, "_get_text", lambda *a, **k: None)
    assert RC._get_json(None, "https://apic/api/x") is None


def test_post_and_get_text_fail_soft_on_transport_error():
    from cisco_toolkit import rest_collect as RC

    class _Opener:
        def open(self, *a, **k):
            raise OSError("connection refused")

    op = _Opener()
    assert RC._post(op, "https://ctrl/login", {"a": 1}) is None      # login POST fail-soft
    assert RC._get_text(op, "https://ctrl/api") is None              # GET fail-soft


def test_http_session_disables_tls_verification_when_asked():
    import urllib.request
    from cisco_toolkit import rest_collect as RC
    opener = RC._http_session(verify_tls=False)
    assert any(isinstance(h, urllib.request.HTTPSHandler) for h in opener.handlers)  # CERT_NONE handler added


class _FakeFMCLogin:
    """A fake FMC generatetoken response: the access token + DOMAINS list arrive in the response HEADERS."""
    def __init__(self, domains):
        import json as _json
        self.headers = {"X-auth-access-token": "TOK123", "DOMAINS": _json.dumps(domains)}

    def close(self):        # collect_fmc _safe_close()s the login response (no dangling fd)
        pass


def test_collect_fmc_paginates_devicerecords_across_pages(tmp_path, monkeypatch):
    """[coverage-honest] FMC list endpoints default to limit=25 rows/page; a single GET reads only the first
    page, silently truncating the FTD inventory on a fleet of >25 -- the same page-1-only census bug fixed for
    ISE ERS (audit-5 #16). collect_fmc must follow paging.next across ALL pages and write the FULL census."""
    DOM = "dom-uuid-1"
    base = "https://fmc.example"
    p1_next = f"{base}/api/fmc_config/v1/domain/{DOM}/devices/devicerecords?offset=2&limit=2&expanded=true"
    monkeypatch.setattr(rest_collect, "_post", lambda *a, **k: _FakeFMCLogin([{"name": "Global", "uuid": DOM}]))

    def fake_get_json(opener, url, headers=None, timeout=30):
        assert headers and headers.get("X-auth-access-token") == "TOK123", "every config GET carries the token"
        if "devices/devicerecords" in url and "offset=" not in url:            # devicerecords PAGE 1 of 2
            return {"items": [{"name": "FTD-01"}, {"name": "FTD-02"}],
                    "paging": {"offset": 0, "limit": 2, "count": 3, "pages": 2, "next": [p1_next]}}
        if "devices/devicerecords" in url and "offset=2" in url:               # devicerecords PAGE 2 of 2
            return {"items": [{"name": "FTD-03"}], "paging": {"offset": 2, "limit": 2, "count": 3, "pages": 2}}
        if "serverversion" in url:
            return {"serverVersion": "7.4.0"}
        return {"items": []}                                                   # other list endpoints: empty
    monkeypatch.setattr(rest_collect, "_get_json", fake_get_json)

    rest_collect.collect_fmc(base, "ro", "pw", str(tmp_path))
    fn = os.path.join(str(tmp_path), rest_collect._cmd_filename("api/fmc_config/v1/devices/devicerecords"))
    assert os.path.isfile(fn)
    devs = parse.parse_fmc_devices(open(fn, encoding="utf-8").read())
    # ALL 3 devices across BOTH pages -- pre-fix (single GET) collected only FTD-01/FTD-02 (page 1).
    assert {d["name"] for d in devs} == {"FTD-01", "FTD-02", "FTD-03"}


def test_collect_fmc_refuses_off_host_pagination_link(tmp_path, monkeypatch):
    """[security] paging.next comes from the controller response body -- a rogue/MITM'd FMC could point it at
    an attacker host to exfiltrate the X-auth-access-token (or an internal host = SSRF, or http:// = cleartext
    downgrade). collect_fmc must only follow a same-origin (https, same host:port) link and NEVER GET the
    off-host URL -- mirrors the ISE ERS nextPage guard (#368)."""
    DOM = "dom-uuid-1"
    base = "https://fmc.example"
    got = []
    monkeypatch.setattr(rest_collect, "_post", lambda *a, **k: _FakeFMCLogin([{"name": "Global", "uuid": DOM}]))

    def fake_get_json(opener, url, headers=None, timeout=30):
        got.append(url)
        if "devices/devicerecords" in url and "offset=" not in url:            # page 1 -> off-host next
            return {"items": [{"name": "FTD-01"}],
                    "paging": {"next": ["https://attacker.evil/api/fmc_config/v1/domain/x/devices/"
                                        "devicerecords?offset=1&limit=1&expanded=true"]}}
        return {"items": []}
    monkeypatch.setattr(rest_collect, "_get_json", fake_get_json)

    rest_collect.collect_fmc(base, "ro", "pw", str(tmp_path))
    # the off-host pagination link was REFUSED -- never fetched, so the token was never sent to attacker.evil
    assert not any("attacker.evil" in u for u in got), "must not GET the body-supplied off-host pagination URL"
    fn = os.path.join(str(tmp_path), rest_collect._cmd_filename("api/fmc_config/v1/devices/devicerecords"))
    devs = parse.parse_fmc_devices(open(fn, encoding="utf-8").read())
    assert {d["name"] for d in devs} == {"FTD-01"}      # only the same-origin page 1 (refusal is logged/honest)
