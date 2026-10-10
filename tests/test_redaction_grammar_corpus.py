"""W60: shareable redaction -- the credential GRAMMAR plus the fail-safe RESIDUAL SWEEP of the raw-capture
scrub, and the independent verifier that restates both -- pinned against one adversarial corpus
(``tests/fixtures/redaction_grammar_corpus.json``).

The defect was a CLASS, not a list of lines: a deny-list of value slots leaks every slot it models
wrongly, and its verifier, written as the same kind of list, certified each leak. The sweep inverts the
failure direction AFTER A LISTED KEYWORD OR CREDENTIAL FIELD NAME -- every following token is replaced
unless a CLOSED structural allowlist names it -- and round 2 closes what the round-1 review found outside
that: unlisted keyword forms, credential field names, shell arguments, multi-line credential blocks,
show/CSV/chap columns, private-key armor families and TERMINAL WRAPS, which origin/main 6390b66c's
cross-line '\\s+' patterns used to catch. Every corpus line runs through the REAL producer
(`redact_collection_dir`) and the REAL verifier (`verify_collection_secret_scrub`) in both directions.

The corpus carries every line all four reviews reported (W60 rounds 0, 1 and 2, W58r2), each with obviously
fake secrets, and ``main_6390b66c``: origin/main's own output for the line, captured by running
git-archived main (not a frozen copy of its code). `test_never_weaker_than_main_on_any_line` asserts
every secret main removed stays removed. Round 3 adds every case the round-2 review reported (its R1
class: a credential keyword INSIDE a wrapped value read as a clause start; its R3 class: a clause ending
in a qualifier-shaped value) and the R1 pin matrix -- each dangling clause x {neutral, camelCase-keyword,
numbered-keyword, keyword+punctuation} value. Round 4 adds the final review's three residual classes: net-snmp
argument vectors read by STRUCTURE (snmpd.conf(5) 'trapsess'/'proxy', snmpcmd(1) options), the persistent
'usmUser' keys and 'smuxpeer' password by position, and an authorization scheme that ends its line.
docs/w60-redaction-grammar-2026-10-09.md records the rules, the measured over-redaction and the residual limits.
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
#: Round 3: a secret spelled like a word its line also uses as structure ('snmp-server host X version 2c
#: host', 'username adm secret 0 secret'): checked by its whole-word count, which must drop.
QUALIFIER_SHAPED = CORPUS["qualifier_shaped"]
EVERY_ROW = MUST_REDACT + MUST_KEEP + OVER_REDACTED + QUALIFIER_SHAPED

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
#: Round-2: the review rows (ids of the 232-row review corpus, all of which are must-redact rows here)
#: that the round-1 build leaked and certified, or regressed against main, or refused after its own scrub.
ROUND2_REPORTED = (
    "ios26", "ios27", "ios28", "ios29", "ios30", "eos05", "jn01", "jn02", "jn11", "hw01", "lx01", "lx02",
    "lx03", "lx04", "lx05", "lx08", "lx09", "lx11", "lx12", "lx13", "lx14", "rs01", "rs02", "rs03", "rs04",
    "rs05", "rs06", "rs07", "rs11", "rs12", "rs13", "rs14", "rs16", "rs19", "rs20", "ym01", "ym03", "ym04",
    "pem01", "pem02", "ws09", "sl04", "cm03", "cm05", "cm07", "r2-01", "r2-02", "r2-03", "r2-05", "r2-07",
    "r2-09", "r2-10", "r2-11", "r2-13", "r2-14", "r2-15", "r2-16", "r2-17", "r2-18", "r2-19", "r2-20",
    "r2-21", "r2-22", "r2-23", "r2-25", "r2-26", "r2-27", "r2-31", "r2-32", "r2-34", "r2-35", "r2-36",
    "r2-39", "r3-01", "r3-02", "r3-03", "r3-04", "r3-05", "r3-06", "r3-07", "r3-08",
)
#: Round 3: the round-2 review's report lines (its R1, R2 and R3 examples), each in the corpus by line.
ROUND3_REPORTED = (
    "enable secret 0\nSecret99Qz", "snmp-server community\nSecret99Qz RO", " neighbor 192.0.2.1 password\nBgpSecret!77",
    " ip ospf authentication-key 7\nXyZ_md5KeyQ", "set snmp community\nSecret99Qz authorization read-only",
    "%PARSER-5-CFGLOG_LOGGEDCMD: User:admin, logged command:username x password 0\nProseWrapQ1",
    "enable secret 0 none", "crypto isakmp key enc address 203.0.113.9", "username ops password md5 privilege 15",
    "password: >-\n    FoldedYamlPwQ", "pass: YamlPassAloneQ", "device;user;pass\nr1;admin;CsvSemiPassQ",
    "<snmp-server><community-config><name>XeYangCommQ</name><permission>ro</permission></community-config>"
    "</snmp-server>",
    "echo 'root:LinuxRootPwQ' | chpasswd", "Authorization: Bearer ro",
)
#: Round 4: the final review's residual classes (net-snmp SNMPCMD_ARGS directives, a wrapped authorization
#: credential, short positional USM keys), each in the corpus by line.
ROUND4_REPORTED = (
    "trapsess -v 3 -u trapops -l authPriv -a SHA -A Ns9tsAaQ -x AES -X Ns9tsXxQ 192.0.2.10:162",
    "informsess -v 2c -c Ns9isCommQ 192.0.2.12", "Authorization: Bearer\nNs9wrapTokQ",
    "usmUser 1 3 0x80001f8880aa01 0x6f7073 0x6f7073 NULL .1.3.6.1.6.3.10.1.1.2 0x0a1b2c3d .1.3.6.1.6.3.10.1.2.2 "
    "0x4e5f6071 \"\"",
)
_TAIL_PROBE = " Leak99tail"
#: A listed secret that is a credential-shaped token (letters and a digit, no blank): the context probes
#: ('community read ', 'password 7') are about ONE row and can recur in another row's legitimate text.
_STRONG_SECRET_RE = re.compile(r"(?=\S*[A-Za-z])(?=\S*\d)\S{5,}")


def _ids(rows):
    return [f"{row['platform']}:{row['line'].strip()[:48]!r}" for row in rows]


def _sources(rows, prefix):
    return {source.split(":", 1)[1] for row in rows for source in row["source"].split()
            if source.startswith(prefix + ":")}


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


def _words(secret, text):
    """Whole-word occurrences of ``secret`` in ``text`` (a qualifier-shaped secret's survival measure)."""
    return len(re.findall(r"(?<![\w-])" + re.escape(secret) + r"(?![\w-])", text))


def _certified(root):
    try:
        rv.verify_collection_secret_scrub(root)
    except rv.RedactionVerificationError:
        return False
    return True


def _refused(text):
    return bool(rv._raw_capture_credential_findings(text))


def test_the_corpus_is_well_formed_and_carries_every_reported_leak():
    lines = [row["line"] for row in EVERY_ROW]
    assert len(lines) == len(set(lines)), "a corpus line is listed twice"
    redact = {row["line"] for row in MUST_REDACT}
    missing = [line for line in W58_LEAKS if line not in redact]
    assert missing == [], f"reported leaks fell out of the corpus: {missing}"
    missing = [line for line in ROUND1_LEAKS if line.rstrip("\n") not in redact and line not in redact]
    assert missing == [], f"round-1 review leaks fell out of the corpus: {missing}"
    review2 = _sources(MUST_REDACT, "w60-review-r2")
    assert len(review2) == 232, "every row of the round-1 review corpus is a must-redact row"
    assert set(ROUND2_REPORTED) <= review2, sorted(set(ROUND2_REPORTED) - review2)
    # round 3: every case the round-2 review reported (381: leaked, regressed against main, raw-certified or
    # changed verdict) is a must-redact or qualifier-shaped row, and so is every line its report quotes
    review3 = _sources(MUST_REDACT + QUALIFIER_SHAPED, "w60-review-r3")
    assert len(review3) == 381, len(review3)
    every_line = {row["line"] for row in EVERY_ROW}
    missing = [line for line in ROUND3_REPORTED + ROUND4_REPORTED if line not in every_line]
    assert missing == [], missing
    assert len(_sources(MUST_REDACT, "w60-r3-matrix")) >= 190, "the R1 pin matrix fell out of the corpus"
    sources = {source.split(":")[0] for row in MUST_REDACT for source in row["source"].split()}
    assert {"w60-builder", "w60-review", "w58r2-review", "w60-review-r2", "w60-r2-wrap", "w60-review-r3",
            "w60-r3-matrix", "w60-review-r4"} <= sources, sources
    # round 4: the negative controls (look-alike lines the new rules must leave byte-identical) are kept rows
    assert len(_sources(MUST_KEEP, "w60-review-r4")) >= 15, "the round-4 negative controls fell out"
    platforms = {row["platform"] for row in MUST_REDACT}
    for platform in ("ios", "nxos", "asa", "aireos", "iosxr", "eos", "junos", "fortigate", "huawei", "panos",
                     "net-snmp", "rest", "yaml", "pem", "csv", "shell", "wrap"):
        assert platform in platforms, f"no {platform} credential form in the corpus"
    for row in MUST_REDACT:
        assert row["secrets"], row
        assert html._REDACT_PLACEHOLDER in row["expect"], row
        assert set(row["flags"]) <= {"notail"}, row
        for secret in row["secrets"]:
            assert secret in row["line"], (secret, row["line"])   # the sentinel really is in the input
    for row in OVER_REDACTED:
        assert row["note"] and row["expect"] != row["line"], row
    for row in QUALIFIER_SHAPED:
        assert row["secrets"] and row["note"] and html._REDACT_PLACEHOLDER in row["expect"], row
        for secret in row["secrets"]:
            assert _words(secret, row["line"]) >= 1, row
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
    row, including the over-redacted and must-keep ones; a qualifier-shaped secret by its whole-word
    count (main removed an occurrence, so must this scrub)."""
    main_redacted = 0
    for row in MUST_REDACT + MUST_KEEP + OVER_REDACTED:
        out = html._redact_config_values(row["line"])
        for secret in row.get("secrets", ()):
            if secret in row["line"] and secret not in row["main_6390b66c"]:
                main_redacted += 1
                assert secret not in out, (row["source"], secret, out)
    for row in QUALIFIER_SHAPED:
        out = html._redact_config_values(row["line"])
        for secret in row["secrets"]:
            if _words(secret, row["main_6390b66c"]) < _words(secret, row["line"]):
                main_redacted += 1
                assert _words(secret, out) < _words(secret, row["line"]), (row["source"], secret, out)
    assert main_redacted >= 800, f"the differential is vacuous: main redacted only {main_redacted} secrets"
    # ...and the counterfactual: main LEFT secrets that this scrub removes, so the corpus can tell the two apart.
    main_leaked = [row for row in MUST_REDACT
                   if any(secret in row["main_6390b66c"] for secret in row["secrets"])]
    assert len(main_leaked) >= 300, "no corpus line distinguishes this scrub from main"


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


@pytest.mark.parametrize("row", QUALIFIER_SHAPED, ids=_ids(QUALIFIER_SHAPED))
def test_qualifier_shaped_secrets_lose_their_value_slot(row, tmp_path):
    """Round 3 (the round-2 review's R3 class): a clause that ends in a qualifier- or keyword-shaped word
    ends in its VALUE. The word survives where the line also uses it as structure, so the measure is its
    whole-word count, which must drop; the verifier refuses the raw line and certifies the output."""
    out = html._redact_config_values(row["line"])
    assert out == row["expect"]
    for secret in row["secrets"]:
        assert _words(secret, out) < _words(secret, row["line"]), (secret, out)
    assert html._redact_config_values(out) == out
    assert _refused(row["line"]) and not _refused(out)


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


def test_the_whole_corpus_as_one_capture_is_a_certified_fixpoint():
    """Every row, in corpus order, in ONE capture: the multi-line states (wraps, blocks, banners, tables,
    CSV and chap-secrets columns) interact across row boundaries, and the scrub must still be a fixpoint
    the verifier certifies, with no listed secret surviving that the benign rows do not themselves spell."""
    text = "\n".join(row["line"] for row in EVERY_ROW) + "\n"
    out = html._redact_config_values(text)
    assert html._redact_config_values(out) == out
    assert rv._raw_capture_credential_findings(out) == []
    benign = "\n".join(row["line"] for row in MUST_KEEP + OVER_REDACTED + QUALIFIER_SHAPED)
    survivors = sorted({secret for row in MUST_REDACT for secret in row["secrets"]
                        if _STRONG_SECRET_RE.fullmatch(secret) and secret not in benign and secret in out})
    assert survivors == []


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
    # round 2: a residue beside a placeholder in each new rule family
    '{"pwd":"<redacted>", "pass": "Fake99json"}',
    "set system root-authentication plain-text-password-value <redacted> Fake99jn",
    "curl -k -u admin:Fake99curl https://192.0.2.1/x",
    " description pw <redacted> Fake99pw",
    # round 3: a partial value after a dangling clause, a credential table cell, a block-scalar indicator
    # replaced while its value stays, an authorization scheme's credential spelled like structure
    " neighbor 192.0.2.1 password\nBgpSecret<redacted>",
    "Community            Group / Access      context    acl_filter\n<redacted> Fake99cell   network-operator",
    "password: <redacted>\n    Fake99folded",
    "Authorization: Bearer ro",
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


def test_prose_context_anchors_banners_and_descriptions():
    """In a banner body (until its delimiter), a description, a remark or a comment, the informal words
    'pw', 'pwd', 'pass', 'creds' and 'account' anchor the sweep too; elsewhere 'pass' is a pass/fail word."""
    redact = html._redact_config_values
    banner = "banner exec ^C\nRemember: break-glass account fakeops / Fake99brk\n^C\nhostname next"
    out = redact(banner)
    assert "Fake99brk" not in out and out.endswith("^C\nhostname next")
    assert "Fake99lab" not in redact("banner motd #Lab creds fakeadmin/Fake99lab#")
    assert redact("banner motd #Lab creds fakeadmin/Fake99lab#").endswith("#")   # the delimiter survives
    for line in (" description Guest wifi pass Fake99pass", " description pwd: Fake99pwd",
                 " description ISP PPPoE login cpe@isp.example pw Fake99pw"):
        assert "Fake99" not in redact(line), line
        assert _refused(line) and not _refused(redact(line)), line
    assert redact("  Tests run: 12, pass 12, fail 0") == "  Tests run: 12, pass 12, fail 0"


def test_one_lexical_model_for_scrub_sweep_and_verifier(tmp_path):
    """(7) Lines end ONLY at CR/LF; VT, FF, NBSP, U+2028/2029, a BOM and a non-UTF-8 byte separate tokens
    -- the same reading in the producer and the verifier, so no gap between two readings can carry a
    credential through. Invisible format characters inside a keyword do not hide it."""
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
    # soft hyphen / zero-width characters inside a keyword
    for line in ("username fakeops pass\xadword 0 Fake99shy", "username fakeops pass\u200bword 0 Fake99zw"):
        assert "Fake99" not in html._redact_config_values(line), repr(line)
        assert _refused(line) and not _refused(html._redact_config_values(line)), repr(line)


def test_the_verifier_restates_the_producers_closed_lists():
    """The verifier may not import the producer, so every closed list is stated twice; the two
    statements must be EQUAL, or the verifier checks something the sweep does not guarantee."""
    pairs = {
        "_REDACT_WS": "_CRED_WS", "_REDACT_WS_CHARS": "_CRED_WS_CHARS",
        "_REDACT_SWEEP_KEYWORDS": "_SWEEP_KEYWORDS",
        "_REDACT_SWEEP_VOID_NEXT": "_SWEEP_VOID_NEXT", "_REDACT_SWEEP_VOID_PREV": "_SWEEP_VOID_PREV",
        "_REDACT_SWEEP_EDGE": "_SWEEP_EDGE", "_REDACT_SWEEP_KEEP": "_SWEEP_KEEP",
        "_REDACT_SWEEP_ALLOW": "_SWEEP_ALLOW", "_REDACT_SWEEP_SLOTS": "_SWEEP_SLOTS",
        "_REDACT_SWEEP_NAME_SLOTS": "_SWEEP_NAME_SLOTS", "_REDACT_SWEEP_ESCAPES": "_SWEEP_ESCAPES",
        "_REDACT_SWEEP_QUERY_NAMES": "_SWEEP_QUERY_NAMES", "_REDACT_SWEEP_SIZE_WORDS": "_SWEEP_SIZE_WORDS",
        "_REDACT_DANGLE_KWS": "_SWEEP_DANGLE_KWS", "_REDACT_DANGLE_QUALIFIERS": "_SWEEP_DANGLE_QUALIFIERS",
        "_REDACT_SNMP_HOST_WORDS": "_SWEEP_SNMP_HOST_WORDS", "_REDACT_CONT_EXEMPT": "_SWEEP_CONT_EXEMPT",
        "_REDACT_WORD_CHARS": "_SWEEP_WORD_CHARS", "_REDACT_RAW_TOKEN_EXTRAS": "_SWEEP_RAW_TOKEN_EXTRAS",
        "_REDACT_RAW_QUOTED_EXACT": "_SWEEP_RAW_QUOTED_EXACT", "_REDACT_ARGV_OPTIONS": "_SWEEP_ARGV_OPTIONS",
        "_REDACT_CSV_DELIMS": "_CSV_DELIMS", "_REDACT_JOIN_TAIL": "_CRED_JOIN_TAIL",
        "_REDACT_GRAMMAR_MAX_LINE": "_CRED_GRAMMAR_MAX_LINE",
        # round 3
        "_REDACT_COMMAND_WORDS": "_SWEEP_COMMAND_WORDS", "_REDACT_CONT_TRAILERS": "_SWEEP_CONT_TRAILERS",
        "_REDACT_RAW_UNQUOTED_EXACT": "_SWEEP_RAW_UNQUOTED_EXACT", "_REDACT_PROSE_PREV": "_SWEEP_PROSE_PREV",
        "_REDACT_SWEEP_SCHEMES": "_SWEEP_SCHEMES", "_REDACT_XML_STRUCT_CHILD": "_SWEEP_XML_STRUCT_CHILD",
        "_REDACT_TABLE_CRED_COLUMNS": "_TABLE_CRED_COLUMNS", "_REDACT_TABLE_ALSO_COLUMNS": "_TABLE_ALSO_COLUMNS",
        "_REDACT_WRAP_ENC": "_CRED_WRAP_ENC", "_REDACT_CLAUSE_END": "_CRED_CLAUSE_END",
        "_REDACT_KEY_ENDS": "_CRED_KEY_ENDS", "_REDACT_CLAUSE_LEAD": "_CRED_CLAUSE_LEAD",
        # round 4
        "_REDACT_SNMP_PROTOCOLS": "_SWEEP_SNMP_PROTOCOLS", "_REDACT_SNMP_POSITIONAL": "_SWEEP_SNMP_POSITIONAL",
        # the credential field-name vocabulary's OWNER (docs/ssot.md) and its restatement
        "_REDACT_SECRET_KEYS": "_SECRET_KEYS",
    }
    for producer, verifier in pairs.items():
        assert getattr(html, producer) == getattr(rv, verifier), (producer, verifier)
    assert tuple(html._REDACT_SECRET_TOKENS) == tuple(rv._SECRET_KEY_TOKENS)
    patterns = {
        "_REDACT_SWEEP_KW_RE": "_SWEEP_KW_RE", "_REDACT_SWEEP_IFACE_RE": "_SWEEP_IFACE_RE",
        "_REDACT_SWEEP_IPV4_RE": "_SWEEP_IPV4_RE", "_REDACT_SWEEP_IPV6_RE": "_SWEEP_IPV6_RE",
        "_REDACT_SWEEP_SYNTH_RE": "_SWEEP_SYNTH_RE", "_REDACT_SWEEP_MASK_RE": "_SWEEP_MASK_RE",
        "_REDACT_IGNORABLE_RE": "_SWEEP_IGNORABLE_RE",
        "_REDACT_SWEEP_TOKEN_RE": "_SWEEP_TOKEN_RE", "_REDACT_SWEEP_ROW_TOKEN_RE": "_SWEEP_ROW_TOKEN_RE",
        "_REDACT_LEAD_RE": "_SWEEP_LEAD_RE",
        "_REDACT_SWEEP_XML_RE": "_SWEEP_XML_RE", "_REDACT_SWEEP_XML_TAG_RE": "_SWEEP_XML_TAG_RE",
        "_REDACT_SWEEP_XML_ATTR_RE": "_SWEEP_XML_ATTR_RE", "_REDACT_SWEEP_URL_RE": "_SWEEP_URL_RE",
        "_REDACT_SWEEP_QUERY_RE": "_SWEEP_QUERY_RE", "_REDACT_PCT_RE": "_SWEEP_PCT_RE",
        "_REDACT_SWEEP_SECRET_DATA_RE": "_SWEEP_SECRET_DATA_RE",
        "_REDACT_SWEEP_FIRST_TOKEN_RE": "_SWEEP_FIRST_TOKEN_RE", "_REDACT_NAME_STRIP_RE": "_SWEEP_NAME_STRIP_RE",
        "_REDACT_SWEEP_QKEY_RE": "_SWEEP_QKEY_RE", "_REDACT_SWEEP_UKEY_RE": "_SWEEP_UKEY_RE",
        "_REDACT_NAME_HINT_RE": "_SWEEP_NAME_HINT_RE", "_REDACT_PROSE_KW_RE": "_SWEEP_PROSE_KW_RE",
        "_REDACT_PROSE_LINE_RE": "_SWEEP_PROSE_LINE_RE", "_REDACT_BANNER_RE": "_SWEEP_BANNER_RE",
        "_REDACT_ARGV_CMD_RE": "_SWEEP_ARGV_CMD_RE", "_REDACT_CRYPT_RE": "_SWEEP_CRYPT_RE",
        "_REDACT_SWEEP_B64_RE": "_SWEEP_B64_RE", "_REDACT_SWEEP_HEX_RE": "_SWEEP_HEX_RE",
        "_REDACT_SWEEP_TOKEN_FORMAT_RE": "_SWEEP_TOKEN_FORMAT_RE",
        "_REDACT_SWEEP_DIGEST_LABEL_RE": "_SWEEP_DIGEST_LABEL_RE",
        "_REDACT_SWEEP_PUBKEY_LABEL_RE": "_SWEEP_PUBKEY_LABEL_RE",
        "_REDACT_DANGLE_HINT_RE": "_SWEEP_DANGLE_HINT_RE", "_REDACT_SNMP_USER_RE": "_SWEEP_SNMP_USER_RE",
        "_REDACT_SNMP_AUTHPRIV_RE": "_SWEEP_SNMP_AUTHPRIV_RE",
        "_REDACT_SNMP_HOST_OPEN_RE": "_SWEEP_SNMP_HOST_OPEN_RE", "_REDACT_NAME_OPEN_RE": "_SWEEP_NAME_OPEN_RE",
        "_REDACT_DANGLE_VOID_LINE_RE": "_SWEEP_DANGLE_VOID_LINE_RE", "_REDACT_PROSE_COMMA_RE": "_SWEEP_PROSE_COMMA_RE",
        "_REDACT_KEY_ID_RE": "_SWEEP_KEY_ID_RE", "_REDACT_KEY_SECRET_LINE_RE": "_SWEEP_KEY_SECRET_LINE_RE",
        "_REDACT_CHPASSWD_RE": "_SWEEP_CHPASSWD_RE", "_REDACT_PGPASS_RE": "_SWEEP_PGPASS_RE",
        "_REDACT_EXPECT_PROMPT_RE": "_SWEEP_EXPECT_PROMPT_RE", "_REDACT_EXPECT_SEND_RE": "_SWEEP_EXPECT_SEND_RE",
        "_REDACT_XML_ANY_TAG_RE": "_SWEEP_XML_ANY_TAG_RE", "_REDACT_TABLE_GROUP_RE": "_TABLE_GROUP_RE",
        "_REDACT_TABLE_WORD_RE": "_TABLE_WORD_RE", "_REDACT_YAML_VALUE_RE": "_YAML_VALUE_RE",
        "_REDACT_B64_LINE_RE": "_B64_LINE_RE", "_REDACT_CREDENTIAL_SHAPE_RE": "_CREDENTIAL_SHAPE_RE",
        "_REDACT_PEM_BEGIN_RE": "_PEM_BEGIN_RE", "_REDACT_PEM_END_RE": "_PEM_END_RE",
        "_REDACT_PUTTY_PRIVATE_RE": "_PUTTY_PRIVATE_RE",
        "_REDACT_TABLE_END_RE": "_TABLE_END_RE", "_REDACT_FORTI_CONFIG_RE": "_FORTI_CONFIG_RE",
        "_REDACT_FORTI_END_RE": "_FORTI_END_RE", "_REDACT_FORTI_SET_NAME_RE": "_FORTI_SET_NAME_RE",
        "_REDACT_CHAP_HEADER_RE": "_CHAP_HEADER_RE", "_REDACT_JSON_OPEN_RE": "_JSON_OPEN_RE",
        "_REDACT_JSON_STRING_RE": "_JSON_STRING_RE", "_REDACT_XML_OPEN_RE": "_XML_OPEN_RE",
        "_REDACT_YAML_OPEN_RE": "_YAML_OPEN_RE", "_REDACT_CSV_FIELD_RE": "_CSV_FIELD_RE",
        "_REDACT_CSV_HEADER_CHARS_RE": "_CSV_HEADER_CHARS_RE",
        "_REDACT_SWEEP_SLOT_OPERAND_RE": "_SWEEP_SLOT_OPERAND_RE",
        "_REDACT_SWEEP_NAME_OPERAND_RE": "_SWEEP_NAME_OPERAND_RE",
        "_REDACT_SWEEP_PREFILTER": "_SWEEP_PREFILTER", "_REDACT_SWEEP_RUN_RE": "_SWEEP_RUN_RE",
        "_REDACT_LINE_PREFILTER": "_CRED_PREFILTER_RE", "_REDACT_TYPE_DIGIT_RE": "_CRED_TYPE_DIGIT_RE",
        # round 4
        "_REDACT_SNMP_ARGV_SHAPE_RE": "_SWEEP_SNMP_ARGV_SHAPE_RE",
        "_REDACT_SNMP_DIRECTIVE_RE": "_SWEEP_SNMP_DIRECTIVE_RE",
        "_REDACT_SNMP_FIELD_RE": "_SWEEP_SNMP_FIELD_RE", "_REDACT_SCHEME_OPEN_RE": "_SWEEP_SCHEME_OPEN_RE",
    }
    for producer, verifier in patterns.items():
        p, v = getattr(html, producer), getattr(rv, verifier)
        assert (p.pattern, p.flags) == (v.pattern, v.flags), (producer, verifier)
    assert [(p.pattern, n, kind) for p, n, kind in html._REDACT_TABLE_HEADERS] == \
        [(p.pattern, n, kind) for p, n, kind in rv._TABLE_HEADERS]


def test_every_verifier_family_has_a_needle_and_every_needle_is_its_own():
    names = [family.name for family in rv._CRED_FAMILIES]
    assert len(names) == len(set(names))
    assert set(rv._CRED_FAMILY_NEEDLES) == set(names)
    assert len(html._REDACT_SECRET_NEEDLES) == len(html._REDACT_SECRET_RES) == len(html._REDACT_SECRET_ANCHORS)
    assert len(html._REDACT_SECRET_CROSS) == len(html._REDACT_SECRET_RES) == len(rv._CRED_FAMILIES)
    # Each family's anchor is the producer's, in the producer's order (the AireOS RADIUS/TACACS+ anchor
    # alone also reads a port the sweep already replaced), and the families a wrap is followed across agree.
    for anchor, family in zip(html._REDACT_SECRET_ANCHORS, rv._CRED_FAMILIES):
        if family.name != "aireos radius/tacacs":
            assert (anchor.pattern, anchor.flags) == (family.anchor.pattern, family.anchor.flags), family.name
    assert [f.name for f, cross in zip(rv._CRED_FAMILIES, html._REDACT_SECRET_CROSS) if cross] == \
        [f.name for f in rv._CRED_FAMILIES if f.cross]
    # Non-vacuity of the speed filter: each family still recognises a corpus line WITH the filter on.
    recognised = set()
    for row in MUST_REDACT:
        for line in rv._cred_lines(row["expect"]):
            for family, _start, _value, _end in rv._cred_clauses(line, artifact=False):
                recognised.add(family.name)
    assert recognised == set(names), f"families no corpus line exercises: {sorted(set(names) - recognised)}"


def test_credential_field_names_derive_from_the_snapshot_owner():
    """The raw-text credential FIELD-NAME vocabulary is `_REDACT_SECRET_KEYS` / `_REDACT_SECRET_TOKENS`
    (the snapshot's own credential-key rule, registered in docs/ssot.md) plus the raw-text extras."""
    for key in html._REDACT_SECRET_KEYS:
        assert html._redact_credential_name(key, False) and rv._sweep_credential_name(key, False), key
    for name in ("apicPwd", "md5Key", "passwordHash", "Cisco-IOS-XE-snmp:community-config", "ro_communities",
                 "snmpV2Community", "secretValue", "passcode", "authkey"):
        assert html._redact_credential_name(name, True), name
    for name in ("key", "auth", "authentication"):
        assert html._redact_credential_name(name, True) and not html._redact_credential_name(name, False), name
    for name in ("pass", "pw", "pin"):       # round 3: an unquoted 'pass: X' / 'pass=X' key names a password too
        assert html._redact_credential_name(name, True) and html._redact_credential_name(name, False), name
        assert rv._sweep_credential_name(name, True) and rv._sweep_credential_name(name, False), name
    for name in ("name", "username", "permission", "keyId", "passive"):
        assert not html._redact_credential_name(name, True), name


@pytest.mark.parametrize("line, secret", [
    ("set system login user fakeops authentication plain-text-password-value Fake99ptpv", "Fake99ptpv"),
    ("    set password2 ENC Fake99pw2", "Fake99pw2"),
    (" radius-common-pw Fake99rcpw", "Fake99rcpw"),
    ("  ip pim hello-authentication ah-md5 3 Fake99pim", "Fake99pim"),
    (" ldap-server authentication manager cn=Manager,dc=example,dc=com Fake99ldap", "Fake99ldap"),
    ("cellular 0/2/0 lte profile create 1 internet.apn chap fakelte Fake99lte ipv4", "Fake99lte"),
    ("request authkey set Fake99authkey", "Fake99authkey"),
    ('{"md5Key": "Fake99md5", "v3Password": "Fake99v3"}', "Fake99v3"),
    ('{"name":"fakeops","pwd":"Fake99pwd"}', "Fake99pwd"),
    ('<credential user="fakeops" pwd="Fake99xmlattr"/>', "Fake99xmlattr"),
    ("body=username%3Dfakeops%26password%3DFake99form", "Fake99form"),
    ("trap2sink 192.0.2.100 Fake99t2s 162", "Fake99t2s"),
    ("    login = cleartext \"Fake99tacp\"", "Fake99tacp"),
    ("1 MD5 Fake99ntpkey", "Fake99ntpkey"),
    ("fakesvc:$1$Fake99s$Fake99md5HashNotRandom:19700:0:99999:7:::", "Fake99md5HashNotRandom"),
    ("ephone 1\n pin 48269", "48269"),
])
def test_round_two_keyword_name_and_shape_rules(line, secret):
    out = html._redact_config_values(line)
    assert secret not in out, out
    assert _refused(line) and not _refused(out), out
    assert html._redact_config_values(out) == out


def test_shell_argument_credentials():
    redact = html._redact_config_values
    assert redact("curl -k -u fakeadmin:Fake99curl https://192.0.2.1/api") == \
        "curl -k -u fakeadmin:<redacted> https://192.0.2.1/api"
    assert redact("sshpass -p 'Fake99sshp' scp r1.cfg bkp@192.0.2.2:/srv/") == \
        "sshpass -p '<redacted>' scp r1.cfg bkp@192.0.2.2:/srv/"
    assert redact("mysql -u root -pFake99mysql inventory") == "mysql -u root -p<redacted> inventory"
    assert redact("/usr/bin/snmpwalk -v2c -c Fake99walk 192.0.2.3") == "/usr/bin/snmpwalk -v2c -c <redacted> 192.0.2.3"
    out = redact("snmpget -v3 -l authPriv -u fakemon -a SHA -A Fake99snA -x AES -X Fake99snX 192.0.2.4 sysName.0")
    assert "Fake99snA" not in out and "Fake99snX" not in out and "-a SHA" in out and "-x AES" in out
    for line in ("curl -u fakeadmin:Fake99curl https://192.0.2.1/x", "sshpass -pFake99sshp ssh r1"):
        assert _refused(line) and not _refused(redact(line)), line


def test_credential_blocks_in_json_xml_and_yaml():
    """A value on a later line than its credential-named key: RESTCONF JSON, NETCONF XML, vManage
    templates, YAML block scalars and lists, and a JSON value placed on the next line."""
    redact = html._redact_config_values
    cases = (
        '{\n  "Cisco-IOS-XE-snmp:community": [\n    {\n      "name": "Fake99rc",\n      "RO": [null]\n    }\n  ]\n}',
        '<community-config xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-snmp">\n  <name>Fake99nc</name>\n'
        '  <permission>ro</permission>\n</community-config>',
        '"pre-shared-secret": {\n  "vipObjectType": "object",\n  "vipValue": "Fake99vm"\n}',
        "enable_secret: >-\n  Fake99folded\nhostname: core1",
        "snmp:\n  ro_communities:\n    - Fake99list\n    - Fake99list2\n  location: lab",
        '{"password":\n  "Fake99next"}',
    )
    for text in cases:
        out = redact(text)
        assert "Fake99" not in out, out
        assert _refused(text) and not _refused(out), out
        assert redact(out) == out
    # the block ENDS: what follows it is the capture's own text again
    assert redact("password: |\n  Fake99blk\nhostname: core1").endswith("\nhostname: core1")


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
    # SSH2 (RFC 4716) armor and a PuTTY .ppk 'Private-Lines: N' body, short last lines included
    ssh2 = ("---- BEGIN SSH2 ENCRYPTED PRIVATE KEY ----\nComment: \"fake\"\nFake99Ssh2Body\nFk9==\n"
            "---- END SSH2 ENCRYPTED PRIVATE KEY ----")
    ppk = "PuTTY-User-Key-File-3: ssh-ed25519\nPrivate-Lines: 2\nFake99PpkLine\nFk9ppk\nPrivate-MAC: 00"
    for text in (ssh2, ppk):
        out = html._redact_config_values(text)
        assert "Fake99" not in out and "Fk9" not in out, out
        assert _refused(text) and not _refused(out), out


def test_high_entropy_tokens_and_their_documented_exemptions():
    redact = html._redact_config_values
    # random-looking base64 / long hex / a known credential token format / a crypt(3) hash anywhere
    assert "Zm9vYmFy" not in redact("notes Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFy0x9Q")
    assert "0123456789abcdef" not in redact("token-less 0123456789abcdef0123456789abcdef")
    assert "ghp_" not in redact("clone with ghp_Fake99Fake99Fake99Fake99Fake99")
    assert redact("fakesvc:$6$Fake99s$Fake99hash:19700:0:99999:7:::") == "fakesvc:<redacted>:19700:0:99999:7:::"
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
    # a percent-encoded body that names a credential, in a URL query or bare
    assert "Fake99q" not in redact("https://h.example/login?payload=%7B%22password%22%3A%22Fake99q%22%7D")
    assert "Fake99p" not in redact("GET /api/login?payload=%7B%22password%22%3A%22Fake99p%22%7D")
    for line in ("copy ftp://u:Fake99@192.0.2.1/f flash:", "Authorization: Basic Fake99b64",
                 "https://h.example/f?token=Fake99"):
        assert rv._raw_capture_credential_findings(line), line
        assert not rv._raw_capture_credential_findings(redact(line)), line


def test_credential_columns_of_tables_csv_files_and_chap_secrets():
    nxos = ("Community            Group / Access      context    acl_filter\n"
            "---------            --------------      -------    ----------\n"
            "Fake99nxcomm         network-operator\n")
    out = html._redact_config_values(nxos)
    assert "Fake99nxcomm" not in out and "network-operator" in out
    assert html._redact_config_values(out) == out              # the column keeps its width
    assert rv._raw_capture_credential_findings(nxos) and not rv._raw_capture_credential_findings(out)
    # a table ENDS at a line that is not a row (here a banner): the column must not eat the delimiter
    tail = nxos + "banner exec ^C\nbreak-glass account fakeops / Fake99brk\n^C\n"
    out = html._redact_config_values(tail)
    assert "banner exec ^C" in out and "Fake99brk" not in out
    for csv in ("host,username,password,enable_secret\ncore1,admin,Fake99csv,Fake99en\n",
                "host\tusername\tpassword\ncore1\tadmin\tFake99tsv\n",
                "hostname;ip;username;password\ncore1;192.0.2.5;admin;Fake99semi\n",
                "host,username,password\ncore1,admin,Fake99a\n\ncore2,admin,Fake99b\n",
                'host,username,password\ncore1,admin,Fake99r1,Fake99extra\ncore2,admin,"Fake99,q"\n'):
        out = html._redact_config_values(csv)
        assert "Fake99" not in out, out
        assert rv._raw_capture_credential_findings(csv) and not rv._raw_capture_credential_findings(out), out
    chap = "# Secrets for authentication using CHAP\n# client\tserver\tsecret\t\tIP addresses\nfakecpe\t*\tFake99chap\t*\n"
    out = html._redact_config_values(chap)
    assert "Fake99chap" not in out and "fakecpe" in out
    assert _refused(chap) and not _refused(out)


@pytest.mark.parametrize("text, secret", [
    # the keyword ends the line and the value wraps onto the next (origin/main's '\s+' crossed it)
    ("snmp-server community\nFake99wrc RO", "Fake99wrc"),
    ("username fakewrap privilege 15 secret\n5 $1$Fk9s$Fake99wrh", "Fake99wrh"),
    ("tacacs-server host 192.0.2.1 key\nFake99wrt", "Fake99wrt"),
    ("crypto isakmp key\nFake99wri address 192.0.2.170", "Fake99wri"),
    ("enable secret 0\nFake99wre", "Fake99wre"),
    ("snmp-server user fakeops network-admin auth sha Fake99wa priv\nFake99wrp", "Fake99wrp"),
    ("snmp-server user fakeuser fakegroup v3 auth sha Fake99A priv aes 1\n28 Fake99wsz", "Fake99wsz"),
    # a qualifier wraps too ('Enable password' / 'is X', a split trap-host clause)
    ("Enable password\nis Fake99wpi", "Fake99wpi"),
    ("snmp-server\nhost 192.0.2.1 traps version 2c Fake99wsh udp-port 162", "Fake99wsh"),
    ("snmp-server host 192.0.2.1 vrf MGMT\ntraps version 2c Fake99wsv", "Fake99wsv"),
    # the value itself wraps, or the keyword is split
    ("username fakewrap privilege 15 algorithm-type scrypt secret Fake99Wrap\nTail99wq", "Tail99wq"),
    ("tacacs-server host 192.0.2.1 ke\ny Fake99wky", "Fake99wky"),
    ("    set password ENC\n Fake99wfg", "Fake99wfg"),
])
def test_terminal_wraps_follow_the_clause_onto_the_next_line(text, secret):
    out = html._redact_config_values(text + "\nhostname next\n")
    assert secret not in out, out
    assert out.endswith("\nhostname next\n"), "the wrap took more than the clause's value"
    assert _refused(text) and not _refused(out), out


def test_wraps_take_one_value_and_never_a_line_of_its_own():
    """A wrap continuation takes ONE value token, as origin/main's '\\s+' took one, and never a token that
    starts a clause of its own; a complete clause ('vrrp 10 authentication md5'), a key ID ('key 1') or a
    keychain key-string does not cost the next configuration line its words."""
    redact = html._redact_config_values
    for text in ("interface Vlan10\n vrrp 10 authentication md5\n vrrp 10 ip 10.10.10.254\n",
                 "interface Gi0/1\n ip authentication mode eigrp 100 md5\n ip address 10.20.30.1 255.255.255.0\n",
                 "router isis CORE\n authentication mode md5\n net 49.0001.1921.6800.1001.00\n",
                 "ntp server 192.0.2.1 key 1\nntp server 192.0.2.2 key 2\n",
                 "key chain KC\n key 1\n  key-string 7 <redacted>\n  accept-lifetime 00:00:00 Jan 1 2026 infinite\n",
                 "config system snmp community\n    edit 1\n        set name \"<redacted>\"\n    next\nend\n"):
        assert redact(text) == text, text
    out = redact("tacacs-server key 7\nsnmp-server host 192.0.2.9 traps version 2c Fake99own udp-port 162\n")
    assert "Fake99own" not in out and "snmp-server host 192.0.2.9" in out


def test_a_wrap_survives_the_scrub_of_its_own_line():
    """A credential block sweeps its lines whole, so a wrapped value inside one can look structural
    ('Tunnel99' is an interface name) and the scrub can replace the very keyword a wrap hangs on
    ('snmp-server' inside a YAML 'credentials:' block). The clause still continues: into a block line
    (producer and verifier alike: the verifier refuses the unscrubbed form), and -- fail safe, beyond
    what the verifier can read on scrubbed text -- from the previous line as it was read."""
    redact = html._redact_config_values
    into_block = '"snmp_community": {\n  "fake_row": 1,\nusername fakeops password 0\nTunnel99\n'
    out = redact(into_block)
    assert out.endswith("password 0\n<redacted>\n"), out
    assert _refused(into_block) and not _refused(out) and redact(out) == out
    assert _refused(out.replace("<redacted>\n", "Tunnel99\n")), "the verifier must demand the in-block wrap"
    lost = "credentials:\n  password: |\n    Fake99blk\n snmp-server host\n10.1.1.1 version 1 Fake99lost\n"
    out = redact(lost)
    assert out.endswith(" <redacted> host\n10.1.1.1 version 1 <redacted>\n"), out
    assert _refused(lost) and not _refused(out) and redact(out) == out


def test_the_verifier_has_checks_no_producer_list_restates():
    """The verifier is not only the producer's lists restated: it PARSES every embedded JSON document and
    checks each credential-named field's value with the snapshot rule (`rv._is_secret_key`). A layout the
    line rules cannot follow -- key, colon and value on three lines -- is therefore refused (fail closed),
    although the producer's own restated rules see nothing on it."""
    text = '{"password"\n:\n"Fake99three"}'
    out = html._redact_config_values(text)
    assert "Fake99three" in out                                  # a documented producer residual ...
    assert rv._independent_credential_findings(out, rv._cred_lines(out))
    assert rv._raw_capture_credential_findings(out)              # ... that the verifier refuses
    # the field rule: a credential-named field anywhere must carry the placeholder
    assert rv._independent_credential_findings("snmpcommunity: Fake99f", ["snmpcommunity: Fake99f"])
    assert not rv._independent_credential_findings("snmpcommunity: <redacted>", ["snmpcommunity: <redacted>"])


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
    """The prefilters are speed only: every must-redact row has a line one of them admits, or a prose
    context line (description, remark, comment), which the sweep reads without the prefilter."""
    for row in MUST_REDACT:
        lines = html._REDACT_LINE_BREAK_RE.split(row["line"])[0::2]
        assert any(html._REDACT_LINE_PREFILTER.search(line.casefold())
                   or html._REDACT_SWEEP_PREFILTER.search(line.casefold())
                   or html._REDACT_SWEEP_RUN_RE.search(line) or html._REDACT_PROSE_LINE_RE.match(line)
                   for line in lines), row["line"]


def test_verifier_grammar_fingerprint_stays_importable():
    """The D10 evidence-retention branch digests ``_INLINE_SECRET_RES`` at import time; it must stay a
    tuple of compiled patterns that names the verifier's grammar."""
    assert rv._INLINE_SECRET_RES and all(isinstance(p, re.Pattern) for p in rv._INLINE_SECRET_RES)
    assert rv._SWEEP_KW_RE in rv._INLINE_SECRET_RES


# ---- round 3: the round-2 review ----
def test_a_keyword_inside_a_wrapped_value_is_no_clause_start():
    """R1 (the round-2 review's P1): a wrapped value whose own text holds a keyword ('Secret99Qz',
    'Password2026x', 'md5KeyQ', 'BgpSecret!77') was read as a clause start, so the producer left it and
    the verifier, restating the same rule, certified it -- a regression against main on 138 cases. A
    token starts a clause only when an anchor or keyword begins at its core and covers ALL of it."""
    for token in ("Secret99Qz", "Password2026x", "Community7Q", "authKeyQ9", "tokenQAbc", "md5KeyQ", "psk4Q",
                  "apikeyQ", "XyZ_md5KeyQ", "BgpSecret!77", "pw=Q9x"):
        line = token + " next"
        masked = html._redact_sweep_masked(line)
        assert not html._redact_starts_clause(line, masked, 0, len(token)), token
        assert not rv._sweep_starts_clause(line, rv._sweep_masked(line), 0, len(token)), token
    for token in ("password", "secret", "key-string", "snmp-server community", "Password:", '"password"'):
        line = token + " next"
        assert html._redact_starts_clause(line, html._redact_sweep_masked(line), 0, len(token)), token
    redact = html._redact_config_values
    for text in ("enable secret 0\nSecret99Qz", "snmp-server community\nCommunity7Q",
                 " ip ospf authentication-key 7\nXyZ_md5KeyQ", " neighbor 192.0.2.1 password\nBgpSecret!77",
                 "        set password ENC\nPassword2026x", "enable secret 0\npw=Q9x"):
        out = redact(text + "\nhostname next\n")
        assert out.endswith("\n<redacted>\nhostname next\n"), out
        assert _refused(text) and not _refused(out), out
    # the pin matrix in the corpus: every dangling clause x the four value shapes, all must-redact rows
    shapes = {source.split(":")[1] for row in MUST_REDACT for source in row["source"].split()
              if source.startswith("w60-r3-matrix:")}
    assert shapes == {"neutral", "camel", "numbered", "punct"}


def test_a_clause_never_ends_in_a_qualifier():
    """R3: a qualifier (a type digit aside) or a soft stop word that ends the clause -- the line end, or
    'privilege'/'role'/'authorization' (and, for 'key', 'address'/'hostname') with its operand -- IS the
    value, as origin/main redacted it; and the clause word is never replaced in its place."""
    redact = html._redact_config_values
    for line, expect in (
            ("enable secret 0 none", "enable secret 0 <redacted>"),
            ("username adm secret 0 md5", "username adm secret 0 <redacted>"),
            ("  key-string enc", "  key-string <redacted>"),
            (" ikev1 pre-shared-key local", " ikev1 pre-shared-key <redacted>"),
            ("set protocols bgp group G authentication-key version",
             "set protocols bgp group G authentication-key <redacted>"),
            ("crypto isakmp key enc address 203.0.113.9", "crypto isakmp key <redacted> address 203.0.113.9"),
            ("username ops password md5 privilege 15", "username ops password <redacted> privilege 15"),
            ("username admin password 0 enc role network-admin", "username admin password 0 <redacted> role network-admin"),
            ("set snmp community none authorization read-only", "set snmp community <redacted> authorization read-only"),
            ("        set password ENC", "        set password <redacted>")):
        assert redact(line) == expect, line
        assert _refused(line) and not _refused(expect), line
    # ... but a structural word that may END a complete line is not a value, and a wrap still dangles
    for line in ("ntp server 192.0.2.1 key 1 prefer", " authentication-mode aaa", "mpls ldp password required",
                 "key config-key ascii", "key config-key password-encrypt",
                 "interface Vlan10\n vrrp 10 authentication md5\n vrrp 10 ip 10.10.10.254"):
        assert redact(line) == line, line
    assert redact("        set password ENC\nFake99fgw\n    next") == "        set password ENC\n<redacted>\n    next"


def test_credential_cells_are_values_by_position():
    """A credential table, chap-secrets or CSV cell is a value by POSITION: a keyword inside it does not end
    the table (round 2 did, and certified the value), and a row is recognised by its shape, so a later
    configuration line is never eaten as a row."""
    redact = html._redact_config_values
    cases = (
        ("Keyring      Hostname/Address                            Preshared Key\n\n"
         "default      203.0.113.9                                 ShowIkeKeyQ1\nKR-1 10.0.0.1 ShowIkeKeyQ2\n"
         "KR-2 10.0.0.0 255.0.0.0 ShowIkeKeyQ3", ("ShowIkeKeyQ1", "ShowIkeKeyQ2", "ShowIkeKeyQ3")),
        ("Community            Group / Access      context    acl_filter\n"
         "---------            --------------      -------    ----------\nSecret99Qz           network-operator",
         ("Secret99Qz",)),
        ("SNMP Community Name     Client IP Address    Client IP Mask     Access Mode  Status\n"
         "MyKey123Q               0.0.0.0              0.0.0.0            Read Only    Enable", ("MyKey123Q",)),
        ("# client server secret IP\nvpnusr * Cisco_Key1Q *", ("Cisco_Key1Q",)),
        ("device;user;pass\nr1;admin;CsvSemiPassQ", ("CsvSemiPassQ",)),
        ("Device    Username   Password       Enable\nr1        admin      TblPwQ1        TblEnQ1",
         ("TblPwQ1", "TblEnQ1")),
    )
    for text, secrets in cases:
        out = redact(text)
        assert not any(secret in out for secret in secrets), out
        assert _refused(text) and not _refused(out) and redact(out) == out, out
    # a configuration line after a table is not a row: its keyword ends the table and keeps its own clause
    out = redact("Keyring      Hostname/Address                            Preshared Key\n"
                 "default      203.0.113.9                                 Fake99psk\n"
                 "crypto isakmp key\nFake99wrap address 203.0.113.9")
    assert out.endswith("\ncrypto isakmp key\n<redacted> address 203.0.113.9"), out


def test_yaml_blocks_fields_and_wrap_continuations():
    """A YAML block-scalar indicator is never a value (round 2 replaced it and kept the block); an unquoted
    'pass' key names a password; a plain scalar continues on more-indented lines; a wrapped value's
    continuation takes its first token before a clause-trailing word, never chains through a lone
    placeholder line and never takes a 'key=value' field."""
    redact = html._redact_config_values
    for text, secret in (("password: >-\n    Fake99fold", "Fake99fold"), ("password: |\n  Fake99lit", "Fake99lit"),
                         ("pass: Fake99pass", "Fake99pass"), ("password: abc\n  Fake99plain", "Fake99plain"),
                         ("snmp-server community " + "C" * 58 + "\nFake99tail RO 99", "Fake99tail"),
                         ("crypto isakmp key " + "k" * 62 + "\nFake99ike address 203.0.113.9", "Fake99ike")):
        out = redact(text)
        assert secret not in out, out
        assert _refused(text) and not _refused(out), out
    assert redact("password: >-\n    Fake99fold") == "password: >-\n    <redacted>"
    text = "DB_PASSWORD=Fake99db\nDB_HOST=10.0.0.5\nDB_USER=fakeadmin\n"
    assert redact(text) == "DB_PASSWORD=<redacted>\nDB_HOST=10.0.0.5\nDB_USER=fakeadmin\n"


def test_round_three_credential_families():
    """Families neither main nor round 2 covered (the round-2 review's P3 list)."""
    redact = html._redact_config_values
    for text, secret in (
            ("router hsrp\n interface Gi0/0/0/1\n  address-family ipv4\n   hsrp 1\n    authentication Fake99xr",
             "Fake99xr"),
            ("    text-authentication Fake99xrv", "Fake99xrv"), (" standby 1 authentication text\nFake99sbt", "Fake99sbt"),
            (" vrrp 1 authentication text\nFake99vrt", "Fake99vrt"), (" ip nhrp authentication\nFake99nhrp", "Fake99nhrp"),
            ("<snmp-server><community-config><name>Fake99yang</name><permission>ro</permission>"
             "</community-config></snmp-server>", "Fake99yang"),
            ("echo 'root:Fake99chp' | chpasswd", "Fake99chp"),
            ("ipmitool -I lanplus -H 10.0.0.9 -U admin -P Fake99ipmi chassis status", "Fake99ipmi"),
            ("net use \\\\srv\\share /user:dom\\ops Fake99netuse", "Fake99netuse"),
            ("smbclient //srv/share -U ops%Fake99smb", "Fake99smb"),
            ('expect "assword:"\nsend "Fake99exp\\r"', "Fake99exp"), ("rootpw {SSHA}Fake99sshaHash=", "Fake99sshaHash"),
            ("bindpw Fake99bind", "Fake99bind"), ("ldap_default_authtok = Fake99tok", "Fake99tok"),
            ("10.0.0.6:5432:db:dbu:Fake99pg", "Fake99pg"), ("! snmp ro string is Fake99cmt", "Fake99cmt"),
            (" description ISP circuit; login admin / Fake99desc", "Fake99desc"),
            ("snmp-server user v3w grpW v3 auth sha Fake99a\n priv aes 256 Fake99p", "Fake99p"),
            ("Authorization: Bearer ro", None), ("web2:{SHA}Fake99ShaB64abcd=", "Fake99ShaB64abcd")):
        out = redact(text)
        assert (secret not in out) if secret else out == "Authorization: Bearer <redacted>", out
        assert _refused(text) and not _refused(out), out


def test_round_three_over_redaction_fixes():
    """Ordinary show output and configuration the round-2 review measured as newly over-redacted stay
    byte-identical (the NX-OS rmon default lines keep everything but their trap community)."""
    redact = html._redact_config_values
    for line in ("*Oct  9 10:00:02.000: %SSH-5-SSH2_USERAUTH: User 'ops' authentication for SSH2 Session from "
                 "198.51.100.150 (tty = 0) using crypto cipher 'aes256-gcm', hmac 'hmac-sha2-256' Succeeded",
                 "      Auth sign: PSK, Auth verify: PSK", "User                          Auth  Priv(enforce) Groups",
                 "Credentials Caching.............................. Disabled",
                 "%OSPF-4-NOVALIDKEY: No valid authentication send key is available on interface Vlan10",
                 " description Uplink (auth via dot1x)", " description Branch VPN (psk tunnel)",
                 " description Badge reader - password reset kiosk", " authentication open", "Authentication Servers",
                 "Authentication methods:publickey,keyboard-interactive,password",
                 "config radius auth add 1 10.1.1.1 1812 ascii <redacted>"):
        assert redact(line) == line, line
        assert not _refused(line), line
    assert redact("rmon event 1 log trap public description FATAL(1) owner PMON@FATAL") == \
        "rmon event 1 log trap <redacted> description FATAL(1) owner PMON@FATAL"
    # a syslog line that ends in 'and password' is prose: it does not take the next record's first word
    text = ("Oct 10 09:00:03: %ASA-3-713167: Remote peer has failed user authentication - check configured "
            "username and password\nOct 10 09:00:04: %ASA-5-713041: IKE Initiator: New Phase 1")
    assert redact(text) == text


def test_fail_closed_disagreements_now_agree():
    """Round 2's verifier refused these producer outputs (safe, but it blocked whole runs): the producer now
    removes the value and the verifier certifies the result."""
    redact = html._redact_config_values
    for text, secret in (('{\n  "password":\n    "Secret99Qz"\n}', "Secret99Qz"),
                         ('password = """Fake99triple"""', "Fake99triple"), ("        set password enc", " enc"),
                         ("        set password ENC\nXyZ_md5KeyQ", "XyZ_md5KeyQ")):
        out = redact(text)
        assert secret not in out, out
        assert _refused(text) and not _refused(out), out


# ---- round 4: the final review's residual classes ----
def test_net_snmp_argument_vectors_are_read_by_structure():
    """(P2) snmpd.conf(5) 'trapsess [SNMPCMD_ARGS] HOST' and 'proxy ... [SNMPCMD_ARGS] HOST OID' carried
    '-c'/'-A'/'-X' that the closed tool list never reached, and the verifier certified them. A line holding one of
    net-snmp's own option+operand pairs ('-v 1|2c|3', '-l <level>', '-a|-x <USM protocol>', '-3m|-3M|-3k|-3K')
    is an SNMP argument vector from its first token, whatever directive, wrapper or log record carries it; the
    SNMPCMD_ARGS directives at the line start cover a vector that names no version. '-3?' key operands are
    values, and an '-a'/'-x' operand is a protocol name or -- fail safe -- a value."""
    redact = html._redact_config_values
    for line, secrets in (
            ("trapsess -v 2c -c Fake99tsc 192.0.2.10", ("Fake99tsc",)),
            ("trapsess -v 3 -u ops -l authPriv -a SHA -A Fake99tsA -x AES -X Fake99tsX 192.0.2.10:162",
             ("Fake99tsA", "Fake99tsX")),
            ("trapsess -c Fake99nov 192.0.2.11", ("Fake99nov",)),                # the directive, no version
            ("informsess -v 2c -c Fake99isc 192.0.2.12", ("Fake99isc",)),
            ("proxy -Cn ctx1 -v 3 -u pxu -l authPriv -a SHA-256 -A Fake99pxA -x AES-256 -X Fake99pxX 192.0.2.13 "
             ".1.3.6.1.2.1.2", ("Fake99pxA", "Fake99pxX")),
            ("trapsess -v3 -u ops -lauthPriv -aSHA -AFake99atA -xAES -XFake99atX 192.0.2.14",
             ("Fake99atA", "Fake99atX")),
            ("trapsess -v 3 -u ops -l authPriv -3m 0xFake99m -3K 0xFake99k 192.0.2.15", ("0xFake99m", "0xFake99k")),
            ("trapsess -v 3 -u ops -l authNoPriv -a Fake99misA 192.0.2.16", ("Fake99misA",)),
            ("net-snmp-create-v3-user -ro -a Fake99cuA -x Fake99cuX -X DES opsuser", ("Fake99cuA", "Fake99cuX")),
            ("encode_keychange -t sha1 -O Fake99old -N Fake99new", ("Fake99old", "Fake99new")),
            ("check_wrapper.sh -H 192.0.2.17 -v 2c -c Fake99wrp", ("Fake99wrp",))):
        out = redact(line)
        assert not any(secret in out for secret in secrets), out
        assert _refused(line) and not _refused(out) and redact(out) == out, out
    assert redact("trapsess -v 3 -u ops -l authPriv -a SHA -A Fake99a -x AES -X Fake99x 192.0.2.10") == \
        "trapsess -v 3 -u ops -l authPriv -a SHA -A <redacted> -x AES -X <redacted> 192.0.2.10"
    # look-alike lines: another tool's '-A'/'-X'/'-c', a '-v' without an SNMP version, a daemon's config file
    for line in ("curl -v -X POST https://192.0.2.1/api/v1/status", "ssh -v -A -X ops@192.0.2.1",
                 "iptables -A INPUT -p udp --dport 161 -j ACCEPT", "ping -c 5 -v 192.0.2.1",
                 "/usr/sbin/snmpd -f -Lo -c /etc/snmp/snmpd.conf", " ip proxy-arp",
                 "trapsess -v 3 -u trapops -l noAuthNoPriv 192.0.2.10", "net-snmp-config --version"):
        assert redact(line) == line, line
        assert not _refused(line), line


def test_net_snmp_positional_credentials():
    """(P3) The persistent 'usmUser' line stores localized keys as lowercase hex, which the entropy rule never
    reads (no upper case), so a key survived at any length; snmpd.conf(5) 'smuxpeer OID PASS' had no rule. Both
    are values BY POSITION (snmplib/snmpusm.c usm_save_user: status, storage type, engine ID, name, security name,
    clone-from, auth protocol, AUTH KEY, priv protocol, PRIV KEY, public string)."""
    redact = html._redact_config_values
    usm = ("usmUser 1 3 0x80001f88804a3f5a2b6c7d8e9f 0x6e736f7073 0x6e736f7073 NULL .1.3.6.1.6.3.10.1.1.3 "
           "0x9f8e7d6c5b4a39281706f5e4d3c2b1a0 .1.3.6.1.6.3.10.1.2.4 0x00112233445566778899aabbccddeeff \"\"")
    assert html._redact_high_entropy_spans(usm, False) == []       # the entropy rule alone misses both keys
    assert redact(usm) == ("usmUser 1 3 0x80001f88804a3f5a2b6c7d8e9f 0x6e736f7073 0x6e736f7073 NULL "
                           ".1.3.6.1.6.3.10.1.1.3 <redacted> .1.3.6.1.6.3.10.1.2.4 <redacted> \"\"")
    quoted = ("usmUser 1 3 0x80001f8880aa02 \"ns ops\" \"ns ops\" NULL .1.3.6.1.6.3.10.1.1.2 \"Fake 99 q\" "
              ".1.3.6.1.6.3.10.1.2.2 \"Fake99qx\" \"\"")
    assert redact(quoted).endswith(".1.3.6.1.6.3.10.1.1.2 \"<redacted>\" .1.3.6.1.6.3.10.1.2.2 \"<redacted>\" \"\"")
    for line in (usm, quoted, "smuxpeer .1.3.6.1.4.1.674.10892.1 Fake99smux"):
        out = redact(line)
        assert _refused(line) and not _refused(out) and redact(out) == out, out
    for line in ("usmUser 1 3 0x80001f8880aa03 0x6f7073 0x6f7073 NULL .1.3.6.1.6.3.10.1.1.1 \"\" "
                 ".1.3.6.1.6.3.10.1.2.1 \"\" \"\"", "smuxpeer .1.3.6.1.4.1.674.10892.1",
                 "usmUserStatus.\"ops\" = INTEGER: active(1)"):
        assert redact(line) == line and not _refused(line), line


def test_a_dangling_authorization_scheme_owns_the_next_lines_first_token():
    """(P3) The scheme rule was same-line only, so 'Authorization: Bearer' / '<token>' (a terminal or paste
    wrap) kept the token. A credential header whose scheme ends its line DANGLES: the next non-blank line's
    first blank-delimited token is the credential, whatever it spells; the verifier demands the placeholder there."""
    redact = html._redact_config_values
    for text, secret in (("Authorization: Bearer\nFake99wtok\nhostname next", "Fake99wtok"),
                         ("Authorization: Bearer\n\n  Fake99wind rest\nhostname next", "Fake99wind"),
                         ('"Authorization": "Bearer\nFake99wjs",\nhostname next', "Fake99wjs"),
                         ("Proxy-Authorization: Basic\r\nFake99wb==\r\nhostname next", "Fake99wb"),
                         ("X-Auth-Token: Bearer\rFake99wx\rhostname next", "Fake99wx"),
                         ("Authorization: Bearer\nro\nhostname next", None)):
        out = redact(text)
        assert (secret is None or secret not in out) and out.endswith("hostname next"), out
        assert out.splitlines()[-2].strip().startswith("<redacted>"), out
        assert _refused(text) and not _refused(out) and redact(out) == out, out
    assert _refused("Authorization: Bearer\nFake99later"), "the verifier must demand the wrapped credential"
    for text in ("WWW-Authenticate: Basic\nContent-Length: 0", '"token_type": "Bearer",\n"expires_in": 3600',
                 "Authorization scheme in use: Bearer\nhostname next",
                 "Authorization: Bearer <redacted>\nhostname next"):
        assert redact(text) == text and not _refused(text), text
