"""Protocol constants in engine-authored prose are exempt PER OCCURRENCE, on every surface.

Two defects motivated this, pulling in opposite directions.

TOO NARROW on surface: the exemption additionally required the schema path to contain
``design_blueprint`` or ``design_nrfu`` -- true of the snapshot JSON, false of ``out_design.docx``,
``out_crd.docx`` and ``out_archreview.docx``, which render the SAME authored sentences. So every
``--redact`` run failed mandatory finalization on 24 "leaks" that were protocol constants in the
engine's own copy, and no redacted deliverable set could be produced at all.

TOO WIDE on containment: the test was ``phrase in text`` -- does this sentence appear ANYWHERE in
the document. Once it did, every occurrence of that constant document-wide was exempt, including a
genuinely leaked one. The ``10.0.0.0/16`` branch two lines below did containment correctly; this
one did not, so the file disagreed with itself about what the rule was.

Fixing only the first would have multiplied the second across three more artifacts. The tests below
are weighted accordingly: the containment cases are the ones that must never regress, because that
is the direction in which this check can silently stop protecting anyone.
"""
import pytest

from webapp.backend import redaction_verify as rv


_CLOUD = "Never expose an admin / database port (or all ports) to 0.0.0.0/0 in a cloud security group"
_HSRP = "the HSRP transport (multicast 224.0.0.2 / UDP 1985, or IPv6 FF02::66)"
_DAD = "a DAD failure on fe80:: silently kills OSPFv3/EIGRPv6"


def _leaks(text: str, where: str = "out_design.docx:word/document.xml") -> list[str]:
    out: list[str] = []
    rv._scan_text(text, where, out)
    return out


# --- the exemption applies, and applies regardless of surface ---------------------------------

@pytest.mark.parametrize("where", [
    "out_design.docx:word/document.xml",
    "out_crd.docx:word/document.xml",
    "out_archreview.docx:word/document.xml",
    "design_blueprint.decisions[0].evidence",
    "design_nrfu.waves[0].checks[2].detail",
    "out_report.html",
])
@pytest.mark.parametrize("sentence", [_CLOUD, _HSRP, _DAD])
def test_authored_doctrine_is_exempt_on_every_surface(sentence, where):
    assert _leaks(sentence, where) == []


def test_the_sentence_survives_ooxml_run_splitting():
    """OOXML splits sentences across runs, so the text arrives with injected whitespace."""
    assert _leaks(_HSRP.replace(" ", "\n  ")) == []
    assert _leaks(_CLOUD.replace(" ", "   ")) == []
    assert _leaks(_DAD.replace(" ", "\t")) == []


# --- containment: the direction in which this check can go quietly blind ----------------------

def test_a_second_occurrence_outside_the_sentence_is_still_reported():
    """THE regression this file exists for. Old rule: sentence present anywhere -> all exempt."""
    text = _CLOUD + ". Observed on core1: ip route 0.0.0.0/0 192.0.2.1"
    kinds = _leaks(text)
    assert any(k.startswith("non-pseudonym IPv4") for k in kinds), (
        "a constant OUTSIDE the authored sentence was exempted because the sentence appeared "
        "elsewhere in the same document — the exemption must be per occurrence"
    )


def test_a_near_miss_of_the_authored_sentence_does_not_exempt():
    """One altered word is not the engine's copy."""
    assert _leaks("Never expose an admin / database port (or all ports) to 0.0.0.0/0 "
                  "in a client security group")


def test_an_unlisted_constant_in_a_listed_sentence_is_not_exempt():
    """The sentence exempts the constants it is registered for, not everything inside it."""
    assert _leaks(_CLOUD.replace("0.0.0.0/0", "198.51.100.7"))


@pytest.mark.parametrize("token", ["0.0.0.0/0", "224.0.0.2", "FF02::66", "fe80::", "10.0.0.0/16"])
def test_every_listed_constant_bare_is_still_reported(token):
    """Non-vacuity: none of these is exempt on its own merits."""
    assert _leaks(f"observed value {token} on the wire")


def test_the_10_0_0_0_16_containment_behaviour_is_preserved():
    """This branch already did containment correctly; folding it in must not change it."""
    assert _leaks("Target address space (supernet, e.g. 10.0.0.0/16)") == []
    assert _leaks("Target address space (supernet, e.g. 10.0.0.0/16). Core VLAN is 10.0.0.0/16.")


def test_the_or_slash_zero_parenthetical_is_still_pinned_to_its_field_and_spelling():
    assert rv._documented_example("(or ::/0)", 4, 8,
                                  "design_blueprint.decisions[0].evidence.summary")
    assert not rv._documented_example("(or ::/0)", 4, 8, "interfaces.core1.ipv6")


def test_every_registered_phrase_actually_EXEMPTS_when_scanned():
    """Feed each phrase to the real scanner and require zero leaks. THE guard that matters.

    This replaces a string-containment check (`constant in phrase`) that passed over a DEAD entry.
    `"supply e.g. 10.0.0.0/16."` never exempted anything: `_IPV4_CANDIDATE_RE` ends with `(?![\\d.])`,
    so a SENTENCE-FINAL constant fails the lookahead, the match backtracks, and the token offered to
    `_documented_example` is the bare `10.0.0.0` — not the key the phrase was registered under. The
    old assertion could not see that, because it never ran the scanner; it checked that a string
    contained a substring, which was true of the broken entry too.

    The real producer string this covers is `cisco_toolkit/design_advisor.py:4240`, reachable whenever
    a requirements register supplies an unparseable `address_space`, and it was still failing
    verification while a phrase registered to cover it sat inert in the table.
    """
    assert rv._AUTHORED_CONSTANT_PHRASES, "empty table — this test would prove nothing"
    dead = []
    for constant, phrases in rv._AUTHORED_CONSTANT_PHRASES.items():
        assert phrases, f"{constant} maps to no phrase"
        for phrase in phrases:
            if _leaks(phrase):
                dead.append((constant, phrase, _leaks(phrase)))
    assert not dead, (
        "registered phrase(s) do NOT exempt their constant when actually scanned — the exemption is "
        "dead code and the producer string it covers still fails verification:\n"
        + "\n".join(f"  {c!r} in {p!r} -> {leaks}" for c, p, leaks in dead)
    )


def test_the_real_design_advisor_producer_string_verifies_clean():
    """Tie the table to the PRODUCER, not to a paraphrase of it.

    A hand-written fixture in the shape the table expects would agree with the table's bugs. This
    uses the engine's own f-string shape from cisco_toolkit/design_advisor.py:4240.
    """
    where = "design_blueprint.target_state.note"
    # `198.51.100.999` is not a valid IPv4 (999 > 255) so the scanner correctly ignores it — the
    # authored example is then the ONLY address-shaped token, and the note must verify clean.
    msg = "address_space '198.51.100.999' is not a valid network; supply e.g. 10.0.0.0/16."
    assert _leaks(msg, where) == [], (
        "the engine's own advisory message still fails verification — this is the "
        "'every --redact run fails mandatory finalization' class, not a cosmetic exemption gap"
    )
    # Non-vacuity in the same run: a REAL client address in the same note must still be reported,
    # or the exemption has widened from 'the authored example' to 'this sentence is safe'.
    dirty = "address_space '10.44.7.219' is not a valid network; supply e.g. 10.0.0.0/16."
    assert _leaks(dirty, where), (
        "an operator-supplied REAL address was exempted because the authored sentence surrounds it"
    )


# --- invisible-character evasion of the identifier patterns -----------------------------------

@pytest.mark.parametrize("label, payload", [
    ("ZWSP in a Cisco serial",        "FCW1234\u200bA001"),
    ("SOFT HYPHEN in a serial",       "FCW1234\u00adA001"),
    ("WORD JOINER in a serial",       "FCW1234\u2060A001"),
    ("ZWSP in an IPv4",               "10.44.7\u200b.219"),
    ("FULLWIDTH FULL STOP in IPv4",   "10.44.7\uff0e219"),
    ("ZWSP in a MAC",                 "00:1a:2b:3c:4d:5\u200be"),
    ("ZWSP in an email",              "bob@ac\u200bme.example"),
])
def test_one_invisible_character_cannot_hide_an_identifier(label, payload):
    """Every pattern here is ASCII, so a single format character used to blind the WHOLE verifier.

    Measured before `_fold_identifier_text`: each of these reported ZERO leaks while the
    byte-identical ASCII form reported one — five of five identifier classes, on the gate that
    decides whether a deliverable is safe to send a client. A soft hyphen comes from Word, a ZWSP
    from wrapped terminal output, fullwidth punctuation from a CJK IME; all of them reach a device
    description and from there a generated document.
    """
    assert _leaks(payload), f"{label} is invisible to the verifier: {payload!r}"


def test_folding_does_not_manufacture_leaks_or_break_exemptions():
    """The other direction, in the same run: folding must not over-report.

    A one-way fix is still a defanged check if it starts flagging the engine's own prose — that is
    how §5.3's 24 false indicators blocked every `--redact` run. So pin BOTH: clean text stays
    clean, and the authored protocol constants stay exempt after normalisation.
    """
    assert _leaks("no identifiers in this sentence at all") == []
    assert _leaks("release 17.9.4 shipped on 2026-07-31") == []
    assert _leaks(_HSRP) == [], "authored doctrine must stay exempt after folding"
    assert _leaks(_CLOUD) == [], "authored doctrine must stay exempt after folding"
    # NFKC is idempotent: folding an already-folded string must not change the verdict.
    assert _leaks(rv._fold_identifier_text(_HSRP)) == []
