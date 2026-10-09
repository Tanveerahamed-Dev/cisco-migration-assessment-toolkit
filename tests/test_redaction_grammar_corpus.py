"""W60: shareable redaction -- the credential GRAMMAR plus the fail-safe RESIDUAL SWEEP of the raw-capture
scrub, and the independent verifier that restates both -- pinned against one adversarial corpus
(``tests/fixtures/redaction_grammar_corpus.json``).

The defect was a CLASS, not a list of lines: a deny-list of value slots leaks every slot it models
wrongly, and its verifier, written as the same kind of list, certified each leak. Round 1 keeps the
grammar but adds a sweep whose failure direction is inverted -- after the first credential keyword on
a line every token is replaced unless a CLOSED structural allowlist names it -- so an unknown word is
over-redacted, never leaked. Every corpus line runs through the REAL producer (`redact_collection_dir`)
and the REAL verifier (`verify_collection_secret_scrub`) in both directions.

The corpus carries every line both reviews (W60, W58r2) reported, each with obviously fake secrets, and
``main_6390b66c``: origin/main's own output for the line, captured by running git-archived main (not a
frozen copy of its code). `test_never_weaker_than_main_on_any_line` asserts every secret main removed
stays removed. docs/w60-redaction-grammar-2026-10-09.md records the rules, the measured over-redaction
and the residual limits.
"""
import json
import os
import re

import pytest

from cisco_toolkit import html
from webapp.backend import redaction_verify as rv

_CORPUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures",
                            "redaction_grammar_corpus.json")
with open(_CORPUS_PATH, encoding="utf-8") as _f:
    CORPUS = json.load(_f)
MUST_REDACT = CORPUS["must_redact"]
MUST_KEEP = CORPUS["must_keep"]
OVER_REDACTED = CORPUS["over_redacted"]
EVERY_ROW = MUST_REDACT + MUST_KEEP + OVER_REDACTED

#: The leaking lines reported against the pre-W60 scrub, verbatim. Each must stay in the corpus.
W58_LEAKS = (
    "enable password level 15 Plain99pw",
    "enable password level 15 0 Plain99pw",
    "enable secret level 15 0 Plain99pw",
    " ip nhrp authentication Dmvpn99",
    " ip nhrp authentication 7 0822455D0A16",
    "snmp-server host 192.0.2.10 public",
    "snmp-server host 10.1.1.1 traps Comm99v1",
    " path scp://admin:Passw0rd99@10.1.1.1/cfg",
    "  enrollment url http://ca:Ca99pw@10.1.1.1/",
    " key-octet-string 0123456789ABCDEF0123456789ABCDEF cryptographic-algorithm AES_128_CMAC",
    " key-octet-string 7 075E731F1A5C4F524D cryptographic-algorithm AES_128_CMAC",
    "config wlan security wpa akm psk set-key ascii Wlc99psk 1",
    " local-user admin password cipher Hw99pw",
    " super password level 15 cipher Hw99pw",
    " snmp-agent community read Huawei99",
    " ospf authentication-mode md5 1 cipher Hw99ospf",
    " ospf authentication-mode md5 1 plain Hw99ospf",
)
#: Round-1 review lines: the numeric-key regressions against main and the tokenizer divergences.
ROUND1_LEAKS = (
    " ip ospf message-digest-key 1 md5 12345678\n",
    " ip ospf authentication-key 12345678\n",
    "ntp authentication-key 1 md5 12345678\n",
    "enable secret\x0bFake99vt\n",
    "enable secret\u2028Fake99ls\n",
    "enable secret\xa0Fake99nbsp\n",
    "snmp-server user fakeuser fakegroup v3 auth sha Fake99wrapA priv aes 1\n28 Fake99wrapP\n",
)
_TAIL_PROBE = " Leak99tail"


def _ids(rows):
    return [f"{row['platform']}:{row['line'].strip()[:48]!r}" for row in rows]


def _write_capture(root, body):
    """One device capture holding ``body`` byte-for-byte: non-UTF-8 bytes (surrogate-escaped in the
    corpus) and CR-only / CRLF line ends included -- `newline=""` stops text mode rewriting them."""
    device = root / "core1"
    device.mkdir(parents=True)
    capture = device / "show_running-config.txt"
    capture.write_text("hostname core1\n" + body + "\n", encoding="utf-8", errors="surrogateescape",
                       newline="")
    return capture


def _read(capture):
    with open(capture, encoding="utf-8", errors="surrogateescape", newline="") as handle:
        return handle.read()


def _certified(root):
    try:
        rv.verify_collection_secret_scrub(root)
    except rv.RedactionVerificationError:
        return False
    return True


def test_the_corpus_is_well_formed_and_carries_every_reported_leak():
    lines = [row["line"] for row in EVERY_ROW]
    assert len(lines) == len(set(lines)), "a corpus line is listed twice"
    redact = {row["line"] for row in MUST_REDACT}
    missing = [line for line in W58_LEAKS if line not in redact]
    assert missing == [], f"reported leaks fell out of the corpus: {missing}"
    missing = [line for line in ROUND1_LEAKS if line.rstrip("\n") not in redact and line not in redact]
    assert missing == [], f"round-1 review leaks fell out of the corpus: {missing}"
    sources = {row["source"].split(":")[0].split()[0] for row in MUST_REDACT}
    assert {"w60-builder", "w60-review", "w58r2-review"} <= sources, sources
    platforms = {row["platform"] for row in MUST_REDACT}
    for platform in ("ios", "nxos", "asa", "aireos", "iosxr", "eos", "junos", "fortigate", "huawei", "panos"):
        assert platform in platforms, f"no {platform} credential form in the corpus"
    for row in MUST_REDACT:
        assert row["secrets"], row
        assert html._REDACT_PLACEHOLDER in row["expect"], row
        assert set(row["flags"]) <= {"notail"}, row
        for secret in row["secrets"]:
            assert secret in row["line"], (secret, row["line"])   # the sentinel really is in the input
    for row in OVER_REDACTED:
        assert row["note"] and row["expect"] != row["line"], row
    for row in EVERY_ROW:
        assert isinstance(row["main_6390b66c"], str), row


@pytest.mark.parametrize("row", MUST_REDACT, ids=_ids(MUST_REDACT))
def test_the_producer_redacts_every_secret(row):
    out = html._redact_config_values(row["line"])
    assert out == row["expect"]
    for secret in row["secrets"]:
        assert secret not in out
    assert html._redact_config_values(out) == out, "the scrub is not idempotent on its own output"


@pytest.mark.parametrize("row", MUST_KEEP, ids=_ids(MUST_KEEP))
def test_structural_lines_are_left_byte_identical(row):
    assert html._redact_config_values(row["line"]) == row["line"]


@pytest.mark.parametrize("row", OVER_REDACTED, ids=_ids(OVER_REDACTED))
def test_over_redaction_is_the_documented_result(row):
    """Fail-safe: a line with no credential may lose words after a credential keyword. Each such line is
    pinned to its documented result so the over-redaction is a decision, not drift."""
    out = html._redact_config_values(row["line"])
    assert out == row["expect"]
    assert html._redact_config_values(out) == out


def test_never_weaker_than_main_on_any_line():
    """THE parity differential. ``main_6390b66c`` is main's own output, captured by running git-archived
    origin/main 6390b66c over every corpus line. Every secret main removed must stay removed -- on every
    row, including the over-redacted and must-keep ones."""
    main_redacted = 0
    for row in EVERY_ROW:
        out = html._redact_config_values(row["line"])
        for secret in row.get("secrets", ()):
            if secret in row["line"] and secret not in row["main_6390b66c"]:
                main_redacted += 1
                assert secret not in out, (row["source"], secret, out)
    assert main_redacted >= 100, f"the differential is vacuous: main redacted only {main_redacted} secrets"
    # ...and the counterfactual: main LEFT secrets that this scrub removes, so the corpus can tell the two apart.
    main_leaked = [row for row in MUST_REDACT
                   if any(secret in row["main_6390b66c"] for secret in row["secrets"])]
    assert main_leaked, "no corpus line distinguishes this scrub from main"


@pytest.mark.parametrize("row", MUST_REDACT, ids=_ids(MUST_REDACT))
def test_the_real_scrub_and_verifier_agree_in_both_directions(row, tmp_path):
    raw_root = tmp_path / "raw"
    _write_capture(raw_root, row["line"])
    assert not _certified(raw_root), "the verifier certified a cleartext credential"

    root = tmp_path / "scrubbed"
    capture = _write_capture(root, row["line"])
    scanned, changed = html.redact_collection_dir(str(root))
    assert (scanned, changed) == (1, 1)
    body = _read(capture)
    assert body == "hostname core1\n" + row["expect"] + "\n"
    assert _certified(root), "the verifier refused the producer's own output"

    if "notail" in row["flags"]:
        return
    index = body.index(html._REDACT_PLACEHOLDER) + len(html._REDACT_PLACEHOLDER)
    capture.write_text(body[:index] + _TAIL_PROBE + body[index:], encoding="utf-8",
                       errors="surrogateescape", newline="")
    assert not _certified(root), (
        "a token after the placeholder was certified: the verifier did not read this credential context")


@pytest.mark.parametrize("row", MUST_KEEP + OVER_REDACTED, ids=_ids(MUST_KEEP + OVER_REDACTED))
def test_structural_lines_are_certified(row, tmp_path):
    capture = _write_capture(tmp_path, row["line"])
    before = _read(capture)
    scanned, changed = html.redact_collection_dir(str(tmp_path))
    if row in MUST_KEEP:
        assert (scanned, changed) == (1, 0)
        assert _read(capture) == before
    else:
        assert _read(capture) == "hostname core1\n" + row["expect"] + "\n"
    assert _certified(tmp_path), "a structural line was refused (false positive)"


@pytest.mark.parametrize("line", [
    # The pre-W60 producer's own outputs: a placeholder standing where a QUALIFIER was. A capture
    # scrubbed by an older build must be refused, not re-certified.
    "enable password <redacted> 15 Plain99pw",
    "enable secret <redacted> 15 0 Plain99pw",
    "config wlan security wpa akm psk set-key <redacted> Wlc99psk 1",
    " super password <redacted> 15 cipher Hw99pw",
    " snmp-agent community <redacted> Huawei99",
    "SNMP community <redacted> : Hunter99pw",
    "Enable password <redacted> Hunter99pw",
    "username admin secret <redacted> $6$Fake99abc$hash",
    "  action 2.0 cli command <redacted> Fake99",
    # free text is swept like any other line: a syslog record of a configuration command, a comment
    "*Oct  9 10:00:00: %PARSER-5-CFGLOG_LOGGEDCMD: User:fakeadmin logged command:enable password <redacted> 15 Fake99",
    "! snmp-server community <redacted> Fake99cmt RO",
    " description password <redacted> Fake99desc",
])
def test_residue_beside_a_placeholder_is_refused(line, tmp_path):
    _write_capture(tmp_path, line)
    assert not _certified(tmp_path)


def test_free_text_is_swept_like_any_other_line(tmp_path):
    """A banner body, a description, a comment and a syslog record carry no exemption: a credential
    pasted into prose is still a credential (round-1 review: the W60 free-text exemption certified
    'logged command:snmp-server community clear X RO')."""
    text = ("banner motd ^C\nGuest WiFi key: Fake99banner\n^C\n"
            " description password Fake99desc for the lab switch\n"
            "%PARSER-5-CFGLOG_LOGGEDCMD: User:fakeadmin  logged command:snmp-server community clear Fake99log RO\n"
            "! enable secret 0 Fake99comment\n")
    (tmp_path / "core1").mkdir()
    capture = tmp_path / "core1" / "show_running-config.txt"
    capture.write_text(text, encoding="utf-8", newline="")
    assert not _certified(tmp_path)
    html.redact_collection_dir(str(tmp_path))
    body = _read(capture)
    for secret in ("Fake99banner", "Fake99desc", "Fake99log", "Fake99comment"):
        assert secret not in body
    assert _certified(tmp_path), body


def test_one_lexical_model_for_scrub_sweep_and_verifier(tmp_path):
    """(7) Lines end ONLY at CR/LF; VT, FF, NBSP, U+2028/2029, a BOM and a non-UTF-8 byte separate tokens
    -- the same reading in the producer and the verifier, so no gap between two readings can carry a
    credential through."""
    separators = ("\x0b", "\x0c", "\xa0", "\u2028", "\u2029", "\u3000", "\udca0")
    for sep in separators:
        line = f"enable secret{sep}Fake99sep"
        assert "Fake99sep" not in html._redact_config_values(line), repr(sep)
        assert rv._raw_capture_credential_findings(line), repr(sep)
        assert not rv._raw_capture_credential_findings(html._redact_config_values(line)), repr(sep)
    # a BOM before a line-start form
    assert "Fake99bom" not in html._redact_config_values("\ufeffsnmp-server host 192.0.2.1 Fake99bom")
    # CR-only line ends: the line-start families fire on every line, and the bytes round-trip exactly
    text = "hostname R1\r    community Fake99cr {\r  authentication text Fake99crt\r"
    out = html._redact_config_values(text)
    assert "Fake99cr" not in out and out.count("\r") == 3
    assert rv._cred_lines(out) == html._REDACT_LINE_BREAK_RE.split(out)[0::2]
    # The line split is byte-exact, CR and non-UTF-8 bytes included.
    text = "a\r\nsnmp-server community Fake99 RO\r\n\udc96 b\n"
    assert html._redact_config_values(text) == "a\r\nsnmp-server community <redacted> RO\r\n\udc96 b\n"
    # a credential written in a legacy code page keeps none of its bytes
    assert html._redact_config_values("username u password 0 P\udce4ssw\udcf6rd") == \
        "username u password 0 <redacted>"


def test_the_verifier_restates_the_producers_closed_lists():
    """The verifier may not import the producer, so every closed list is stated twice; the two
    statements must be EQUAL, or the verifier checks something the sweep does not guarantee."""
    pairs = {
        "_REDACT_WS": "_CRED_WS", "_REDACT_SWEEP_KEYWORDS": "_SWEEP_KEYWORDS",
        "_REDACT_SWEEP_VOID_NEXT": "_SWEEP_VOID_NEXT", "_REDACT_SWEEP_VOID_PREV": "_SWEEP_VOID_PREV",
        "_REDACT_SWEEP_EDGE": "_SWEEP_EDGE", "_REDACT_SWEEP_ALLOW": "_SWEEP_ALLOW",
        "_REDACT_SWEEP_SLOTS": "_SWEEP_SLOTS", "_REDACT_SWEEP_NAME_SLOTS": "_SWEEP_NAME_SLOTS",
        "_REDACT_SWEEP_ESCAPES": "_SWEEP_ESCAPES", "_REDACT_SWEEP_QUERY_NAMES": "_SWEEP_QUERY_NAMES",
        "_REDACT_SWEEP_DANGLING": "_SWEEP_DANGLING", "_REDACT_SWEEP_SIZE_WORDS": "_SWEEP_SIZE_WORDS",
        "_REDACT_GRAMMAR_MAX_LINE": "_CRED_GRAMMAR_MAX_LINE",
    }
    for producer, verifier in pairs.items():
        assert getattr(html, producer) == getattr(rv, verifier), (producer, verifier)
    patterns = {
        "_REDACT_SWEEP_KW_RE": "_SWEEP_KW_RE", "_REDACT_SWEEP_IFACE_RE": "_SWEEP_IFACE_RE",
        "_REDACT_SWEEP_IPV4_RE": "_SWEEP_IPV4_RE", "_REDACT_SWEEP_IPV6_RE": "_SWEEP_IPV6_RE",
        "_REDACT_SWEEP_SYNTH_RE": "_SWEEP_SYNTH_RE", "_REDACT_SWEEP_MASK_RE": "_SWEEP_MASK_RE",
        "_REDACT_SWEEP_TOKEN_RE": "_SWEEP_TOKEN_RE", "_REDACT_SWEEP_ROW_TOKEN_RE": "_SWEEP_ROW_TOKEN_RE",
        "_REDACT_SWEEP_XML_RE": "_SWEEP_XML_RE", "_REDACT_SWEEP_URL_RE": "_SWEEP_URL_RE",
        "_REDACT_SWEEP_QUERY_RE": "_SWEEP_QUERY_RE", "_REDACT_SWEEP_SECRET_DATA_RE": "_SWEEP_SECRET_DATA_RE",
        "_REDACT_SWEEP_FIRST_TOKEN_RE": "_SWEEP_FIRST_TOKEN_RE", "_REDACT_SWEEP_B64_RE": "_SWEEP_B64_RE",
        "_REDACT_SWEEP_HEX_RE": "_SWEEP_HEX_RE", "_REDACT_SWEEP_TOKEN_FORMAT_RE": "_SWEEP_TOKEN_FORMAT_RE",
        "_REDACT_SWEEP_DIGEST_LABEL_RE": "_SWEEP_DIGEST_LABEL_RE",
        "_REDACT_SWEEP_PUBKEY_LABEL_RE": "_SWEEP_PUBKEY_LABEL_RE", "_REDACT_PEM_BEGIN_RE": "_PEM_BEGIN_RE",
        "_REDACT_PEM_END_RE": "_PEM_END_RE", "_REDACT_TABLE_END_RE": "_TABLE_END_RE",
        "_REDACT_FORTI_CONFIG_RE": "_FORTI_CONFIG_RE", "_REDACT_FORTI_END_RE": "_FORTI_END_RE",
        "_REDACT_FORTI_SET_NAME_RE": "_FORTI_SET_NAME_RE", "_REDACT_CSV_FIELD_RE": "_CSV_FIELD_RE",
        "_REDACT_SWEEP_SLOT_OPERAND_RE": "_SWEEP_SLOT_OPERAND_RE",
        "_REDACT_SWEEP_NAME_OPERAND_RE": "_SWEEP_NAME_OPERAND_RE",
    }
    for producer, verifier in patterns.items():
        p, v = getattr(html, producer), getattr(rv, verifier)
        assert (p.pattern, p.flags) == (v.pattern, v.flags), (producer, verifier)
    assert [(p.pattern, n) for p, n in html._REDACT_TABLE_HEADERS] == \
        [(p.pattern, n) for p, n in rv._TABLE_HEADERS]


def test_every_verifier_family_has_a_needle_and_every_needle_is_its_own():
    names = [family.name for family in rv._CRED_FAMILIES]
    assert len(names) == len(set(names))
    assert set(rv._CRED_FAMILY_NEEDLES) == set(names)
    assert len(html._REDACT_SECRET_NEEDLES) == len(html._REDACT_SECRET_RES)
    # Non-vacuity of the speed filter: each family still recognises a corpus line WITH the filter on.
    recognised = set()
    for row in MUST_REDACT:
        for line in rv._cred_lines(row["expect"]):
            for family, _start, _value, _end in rv._cred_clauses(line, artifact=False):
                recognised.add(family.name)
    assert recognised == set(names), f"families no corpus line exercises: {sorted(set(names) - recognised)}"


def test_private_key_blocks_and_their_json_escaped_form():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEFake99Body\nFake99Line2==\n-----END RSA PRIVATE KEY-----\nnext"
    out = html._redact_config_values(pem)
    assert out == "-----BEGIN RSA PRIVATE KEY-----\n<redacted>\n<redacted>\n-----END RSA PRIVATE KEY-----\nnext"
    assert rv._raw_capture_credential_findings(pem)
    assert not rv._raw_capture_credential_findings(out)
    # an unterminated block runs to the end of the text: fail-safe
    assert "Fake99tail" not in html._redact_config_values("-----BEGIN PRIVATE KEY-----\nAAAA\nFake99tail")
    escaped = '"key": "-----BEGIN PRIVATE KEY-----\\nMIIEFake99json\\n-----END PRIVATE KEY-----\\n",'
    assert "Fake99json" not in html._redact_config_values(escaped)
    assert rv._raw_capture_credential_findings(escaped)


def test_high_entropy_tokens_and_their_documented_exemptions():
    redact = html._redact_config_values
    # random-looking base64 / long hex / a known credential token format anywhere on a line
    assert "Zm9vYmFy" not in redact("notes Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFy0x9Q")
    assert "0123456789abcdef" not in redact("token-less 0123456789abcdef0123456789abcdef")
    assert "ghp_" not in redact("clone with ghp_Fake99Fake99Fake99Fake99Fake99")
    # ...but a digest or fingerprint LABELLED as such, an SSH public key, an interface name, a JSON
    # pointer and a camelCase identifier (an ACI class in a DN) are structure
    for keep in ("sha256: " + "ab" * 32, "SHA256 hash " + "cd" * 32,
                 "ip ssh pubkey-chain ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQFake99Key",
                 "TwentyFiveGigabitEthernet1/0/1 is up", "/interfaces/core1/Vlan30",
                 '"dn": "topology/HDfabricOverallHealth5min-0"'):
        assert redact(keep) == keep, keep
    # In a --redact snapshot the JSON key is the label: engine digests and join keys survive.
    snap = html.redact_snapshot({"config_sha256": "ef" * 32, "subject_id": "local:" + "12" * 32,
                                 "notes": "ef" * 32})
    assert snap["config_sha256"] == "ef" * 32 and snap["subject_id"] == "local:" + "12" * 32
    assert snap["notes"] == "<redacted>"


def test_url_userinfo_headers_and_query_secrets():
    redact = html._redact_config_values
    assert redact("copy ftp://admin@corp.example:Fa/ke99@192.0.2.1/f flash:") == \
        "copy ftp://admin@corp.example:<redacted>@192.0.2.1/f flash:"
    assert redact("copy ftp://:Fake99anon@192.0.2.1/f flash:") == "copy ftp://:<redacted>@192.0.2.1/f flash:"
    assert redact("Authorization: Bearer Fake99tok") == "Authorization: Bearer <redacted>"
    assert redact("X-Cisco-Meraki-API-Key: Fake99meraki") == "X-Cisco-Meraki-API-Key: <redacted>"
    assert redact("https://h.example/f?sv=1&sig=Fake99sig") == "https://h.example/f?sv=1&sig=<redacted>"
    for line in ("copy ftp://u:Fake99@192.0.2.1/f flash:", "Authorization: Basic Fake99b64",
                 "https://h.example/f?token=Fake99"):
        assert rv._raw_capture_credential_findings(line), line
        assert not rv._raw_capture_credential_findings(redact(line)), line


def test_credential_columns_of_tables_and_csv_files():
    nxos = ("Community            Group / Access      context    acl_filter\n"
            "---------            --------------      -------    ----------\n"
            "Fake99nxcomm         network-operator\n")
    out = html._redact_config_values(nxos)
    assert "Fake99nxcomm" not in out and "network-operator" in out
    assert html._redact_config_values(out) == out              # the column keeps its width
    assert rv._raw_capture_credential_findings(nxos) and not rv._raw_capture_credential_findings(out)
    csv = "host,username,password,enable_secret\ncore1,admin,Fake99csv,Fake99en\n"
    out = html._redact_config_values(csv)
    assert "Fake99csv" not in out and "Fake99en" not in out and out.startswith("host,username,password,")
    assert rv._raw_capture_credential_findings(csv) and not rv._raw_capture_credential_findings(out)


def test_a_terminal_wrap_inside_a_credential_sweeps_the_next_line():
    text = "snmp-server user u g v3 auth sha Fake99A priv aes 1\n28 Fake99P\nhostname next\n"
    out = html._redact_config_values(text)
    assert "Fake99P" not in out and out.endswith("\nhostname next\n")
    assert rv._raw_capture_credential_findings(text)
    assert not rv._raw_capture_credential_findings(out)


def test_shareable_artifacts_read_the_same_grammar_for_values():
    """`_scan_text` (snapshot, OOXML, HTML) checks the VALUE of line-start config forms with the same
    qualifier grammar: the producer's new output passes, the cleartext form does not."""
    def kinds(text):
        leaks = []
        rv._scan_text(text, "probe", leaks)
        return [kind for kind in leaks if "credential" in kind or "private-key" in kind]

    assert kinds("enable password level 15 <redacted>") == []
    assert kinds("enable password level 15 Plain99pw")
    assert kinds("username fakeuser privilege 15 secret 9 <redacted>") == []
    assert kinds("username fakeuser privilege 15 secret 9 $9$Fake99")
    assert kinds("Password encryption service") == []           # a CIS control title
    assert kinds("password <redacted> portal") == []             # a description beginning 'password'
    assert kinds("set private-key \"-----BEGIN ENCRYPTED PRIVATE KEY-----\nMIIFake99\n-----END "
                 "ENCRYPTED PRIVATE KEY-----\"")
    assert kinds("set private-key \"-----BEGIN ENCRYPTED PRIVATE KEY-----\n<redacted>\n-----END "
                 "ENCRYPTED PRIVATE KEY-----\"") == []


def test_the_producer_prefilters_admit_every_corpus_line():
    """The prefilters are speed only: every must-redact row has a line one of them admits (or a
    stateful rule -- a table column, a CSV column -- owns it)."""
    for row in MUST_REDACT:
        lines = html._REDACT_LINE_BREAK_RE.split(row["line"])[0::2]
        assert any(html._REDACT_LINE_PREFILTER.search(line.casefold())
                   or html._REDACT_SWEEP_PREFILTER.search(line.casefold())
                   or html._REDACT_SWEEP_RUN_RE.search(line) for line in lines), row["line"]


def test_verifier_grammar_fingerprint_stays_importable():
    """The D10 evidence-retention branch digests ``_INLINE_SECRET_RES`` at import time; it must stay a
    tuple of compiled patterns that names the verifier's grammar."""
    assert rv._INLINE_SECRET_RES and all(isinstance(p, re.Pattern) for p in rv._INLINE_SECRET_RES)
    assert rv._SWEEP_KW_RE in rv._INLINE_SECRET_RES
