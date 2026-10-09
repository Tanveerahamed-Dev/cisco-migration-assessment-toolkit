"""W60: the credential grammar of the raw-capture scrub and its independent verifier, pinned against
one adversarial corpus (``tests/fixtures/redaction_grammar_corpus.json``).

The defect this closes was a CLASS, not a list of lines. The scrub replaced the token right after a
credential keyword even when that token was a qualifier ('level 15', a type digit, cipher/plain,
ascii/hex, read/write, traps, ...), so the credential survived one token further on
('enable password <redacted> 15 Plain99pw'); and the verifier accepted any line whose first token
after the keyword was the placeholder. Every line of the corpus therefore runs through the REAL
producer (`redact_collection_dir`) and the REAL verifier (`verify_collection_secret_scrub`) in both
directions, and the verifier must also refuse the scrubbed line with one token appended after the
placeholder -- which proves it parsed the line's family rather than passing it by default.

Every credential in the corpus is an obviously fake synthetic value. See
docs/w60-redaction-grammar-2026-10-09.md for the grammar, its residual limits and the corpus rules.
"""
import json
import os

import pytest

from cisco_toolkit import html
from webapp.backend import redaction_verify as rv

_CORPUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures",
                            "redaction_grammar_corpus.json")
with open(_CORPUS_PATH, encoding="utf-8") as _f:
    CORPUS = json.load(_f)
MUST_REDACT = CORPUS["must_redact"]
MUST_KEEP = CORPUS["must_keep"]

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
_TAIL_PROBE = " Leak99tail"


def _ids(rows, key):
    return [f"{row['platform']}:{row[key].strip()[:48]}" for row in rows]


def _write_capture(root, body):
    device = root / "core1"
    device.mkdir(parents=True)
    capture = device / "show_running-config.txt"
    capture.write_text("hostname core1\n" + body + "\n", encoding="utf-8")
    return capture


def _certified(root):
    try:
        rv.verify_collection_secret_scrub(root)
    except rv.RedactionVerificationError:
        return False
    return True


def test_the_corpus_is_well_formed_and_carries_every_reported_leak():
    lines = [row["line"] for row in MUST_REDACT]
    assert len(lines) == len(set(lines)), "a must-redact line is listed twice"
    keep = [row["line"] for row in MUST_KEEP]
    assert len(keep) == len(set(keep)), "a must-keep line is listed twice"
    assert not set(lines) & set(keep)
    missing = [line for line in W58_LEAKS if line not in lines]
    assert missing == [], f"reported leaks fell out of the corpus: {missing}"
    platforms = {row["platform"] for row in MUST_REDACT}
    for platform in ("ios", "nxos", "asa", "aireos", "iosxr", "eos", "junos", "fortigate", "huawei"):
        assert platform in platforms, f"no {platform} credential form in the corpus"
    for row in MUST_REDACT:
        assert row["secrets"], row
        assert html._REDACT_PLACEHOLDER in row["expect"], row
        assert set(row["flags"]) <= {"url"}, row
        for secret in row["secrets"]:
            assert secret in row["line"], (secret, row["line"])   # the sentinel really is in the input


@pytest.mark.parametrize("row", MUST_REDACT, ids=_ids(MUST_REDACT, "line"))
def test_the_producer_consumes_the_whole_qualifier_sequence(row):
    out = html._redact_config_values(row["line"])
    assert out == row["expect"]
    for secret in row["secrets"]:
        assert secret not in out
    assert html._redact_config_values(out) == out, "the scrub is not idempotent on its own output"


@pytest.mark.parametrize("row", MUST_KEEP, ids=_ids(MUST_KEEP, "line"))
def test_structural_lines_are_left_byte_identical(row):
    assert html._redact_config_values(row["line"]) == row["line"]


@pytest.mark.parametrize("row", MUST_REDACT, ids=_ids(MUST_REDACT, "line"))
def test_the_real_scrub_and_verifier_agree_in_both_directions(row, tmp_path):
    raw_root = tmp_path / "raw"
    _write_capture(raw_root, row["line"])
    assert not _certified(raw_root), "the verifier certified a cleartext credential"

    root = tmp_path / "scrubbed"
    capture = _write_capture(root, row["line"])
    scanned, changed = html.redact_collection_dir(str(root))
    assert (scanned, changed) == (1, 1)
    body = capture.read_text(encoding="utf-8")
    assert body == "hostname core1\n" + row["expect"] + "\n"
    assert _certified(root), "the verifier refused the producer's own output"

    if "url" in row["flags"]:
        return
    index = body.index(html._REDACT_PLACEHOLDER) + len(html._REDACT_PLACEHOLDER)
    capture.write_text(body[:index] + _TAIL_PROBE + body[index:], encoding="utf-8")
    assert not _certified(root), (
        "a token after the placeholder was certified: the verifier did not parse this family")


@pytest.mark.parametrize("row", MUST_KEEP, ids=_ids(MUST_KEEP, "line"))
def test_structural_lines_are_certified_and_not_rewritten(row, tmp_path):
    capture = _write_capture(tmp_path, row["line"])
    before = capture.read_bytes()
    scanned, changed = html.redact_collection_dir(str(tmp_path))
    assert (scanned, changed) == (1, 0)
    assert capture.read_bytes() == before
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
    # A placeholder that no clause of the grammar explains.
    "  action 2.0 cli command <redacted> Fake99",
])
def test_residue_beside_a_placeholder_is_refused(line, tmp_path):
    _write_capture(tmp_path, line)
    assert not _certified(tmp_path)


def test_free_text_is_value_checked_but_not_tail_checked(tmp_path):
    """Prose follows a credential word in English. In a banner body, a description and a syslog
    record the tail allowlist is not applied -- but a cleartext value there is still refused."""
    text = ("banner motd ^C\nYour secret token is checked by the RADIUS server\n"
            "This secret Fake99banner must never be shared\n^C\n"
            " description password Fake99desc for the lab switch\n"
            "%SYS-5-CONFIG_I: secret Fake99log rotated by admin\n")
    (tmp_path / "core1").mkdir()
    capture = tmp_path / "core1" / "show_running-config.txt"
    capture.write_text(text, encoding="utf-8")
    assert not _certified(tmp_path), "cleartext inside free text must still be refused"
    html.redact_collection_dir(str(tmp_path))
    body = capture.read_text(encoding="utf-8")
    for secret in ("Fake99banner", "Fake99desc", "Fake99log"):
        assert secret not in body
    assert _certified(tmp_path), body


def test_a_banner_without_a_closing_delimiter_does_not_exempt_the_rest_of_the_file(tmp_path):
    filler = "\n".join(f"line {n}" for n in range(rv._CRED_BANNER_MAX_LINES + 5))
    text = f"banner motd ^C\n{filler}\nenable password <redacted> 15 Plain99pw\n"
    (tmp_path / "core1").mkdir()
    (tmp_path / "core1" / "show_running-config.txt").write_text(text, encoding="utf-8")
    assert not _certified(tmp_path)


def test_shareable_artifacts_read_the_same_grammar_for_values():
    """`_scan_text` (snapshot, OOXML, HTML) checks the VALUE of line-start config forms with the
    same qualifier grammar: the producer's new output passes, the cleartext form does not."""
    def kinds(text):
        leaks = []
        rv._scan_text(text, "probe", leaks)
        return [kind for kind in leaks if "credential" in kind]

    assert kinds("enable password level 15 <redacted>") == []
    assert kinds("enable password level 15 Plain99pw")
    assert kinds("username fakeuser privilege 15 secret 9 <redacted>") == []
    assert kinds("username fakeuser privilege 15 secret 9 $9$Fake99")
    assert kinds("Password encryption service") == []           # a CIS control title
    assert kinds("password <redacted> portal") == []             # a description beginning 'password'


def test_every_verifier_family_has_a_needle_and_every_needle_is_its_own():
    names = [family.name for family in rv._CRED_FAMILIES]
    assert len(names) == len(set(names))
    assert set(rv._CRED_FAMILY_NEEDLES) == set(names)
    # Non-vacuity of the speed filter: each family still recognises a corpus line WITH the filter on.
    recognised = set()
    for row in MUST_REDACT:
        for family, _start, _value, _end in rv._cred_clauses(row["expect"], artifact=False):
            recognised.add(family.name)
    assert recognised == set(names), f"families no corpus line exercises: {sorted(set(names) - recognised)}"


def test_the_producer_prefilter_admits_every_family():
    for row in MUST_REDACT:
        assert html._REDACT_LINE_PREFILTER.search(row["line"]), row["line"]
    # The line split is byte-exact, CR and non-UTF-8 bytes included.
    text = "a\r\nsnmp-server community Fake99 RO\r\n\udc96 b\n"
    assert html._redact_config_values(text) == "a\r\nsnmp-server community <redacted> RO\r\n\udc96 b\n"
