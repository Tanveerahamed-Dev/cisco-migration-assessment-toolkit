"""The share-safety verifier must not report a Cisco serial for a GUID.

Background: ``_CISCO_SERIAL_RE`` is ``[A-Z]{3}\\d{4}[A-Z0-9]{2,6}``. The final group of a
GUID is 12 hex characters, so it can satisfy that shape by coincidence — and one GUID
that does is a FIXED OOXML constant python-pptx writes into ``ppt/presProps.xml`` of
every deck it produces. The verifier therefore reported a "Cisco serial" leak on every
``.pptx`` it had ever checked, in bytes the redactor does not author and cannot clean.

That is not a cosmetic complaint. A share-safety report whose findings are known-noisy is
a report people learn to skim, which is exactly how a real leak in the same list gets
waved through. The repository's own guardrail names the mirror-image failure (absence
rendered as health); this is presence rendered as noise, and it costs the same thing —
the reader's attention at the moment it matters.

The rule under test is a CONTEXT exclusion, and these tests pin it as such: a token is
exempt only when it lies inside a whole 8-4-4-4-12 GUID. The tempting alternative — make
``_CISCO_SERIAL_RE`` reject hex-only tokens — would silence the noise by also blinding the
check to real serials that happen to be hex-shaped. So the non-vacuity tests below matter
more than the false-positive test: they are what stops this exemption from widening into
"serial-shaped things near hyphens are fine".
"""
import re

import pytest

from webapp.backend import redaction_verify as rv


# The literal constant from ppt/presProps.xml. Its tail BBA856620510 is [A-Z]{3}\d{4}[A-Z0-9]{2,6}:
# BBA / 8566 / 20510.
_PPTX_GUID = "{D31A062A-798A-4329-ABDD-BBA856620510}"


def _serial_leaks(text: str) -> list[str]:
    leaks: list[str] = []
    rv._scan_text(text, "probe.xml", leaks)
    return [leak for leak in leaks if leak.startswith("Cisco serial")]


def test_the_pptx_guid_tail_really_does_match_the_serial_pattern():
    """Guard the premise. If this stops matching, the exemption below is testing nothing."""
    assert rv._CISCO_SERIAL_RE.search(_PPTX_GUID) is not None, (
        "the serial pattern no longer matches the GUID tail — the false positive this "
        "module exempts is gone, so the exemption is now dead code and should be removed "
        "rather than left to widen silently"
    )


def test_the_fixed_pptx_guid_is_not_reported_as_a_serial():
    where = 'presProps.xml uri="' + _PPTX_GUID + '"'
    assert _serial_leaks(where) == []


@pytest.mark.parametrize(
    "text",
    [
        "SerialNumber: FDO1734Q0GT",                       # bare, no GUID anywhere
        _PPTX_GUID + " FDO1734Q0GT",                       # a real serial ALONGSIDE a GUID
        "FDO1734Q0GT " + _PPTX_GUID,                       # ...on the other side
        "D31A062A-798A-4329-ABDD-FDO1734Q0GT",             # non-hex tail: not a GUID at all
        "prefix-FDO1734Q0GT-suffix",                       # hyphens alone must not exempt
        "D31A062A-798A-4329-ABD-BBA856620510",             # 3-char group: wrong GUID shape
        "798A-4329-ABDD-BBA856620510",                     # truncated: only 3 groups
    ],
)
def test_a_real_serial_is_still_reported(text):
    """Non-vacuity: the exemption must not generalize beyond a complete GUID."""
    assert _serial_leaks(text), f"serial leak went unreported in {text!r}"


def test_the_exemption_requires_the_whole_guid_not_just_the_tail():
    """The tail on its own is not a GUID, so it must still be reported."""
    assert _serial_leaks("BBA856620510")


def test_the_guid_pattern_is_anchored_against_longer_hex_runs():
    """A GUID embedded in a longer hex/hyphen run is not a GUID; refuse to match it."""
    assert rv._GUID_RE.search("aD31A062A-798A-4329-ABDD-BBA856620510") is None
    assert rv._GUID_RE.search("D31A062A-798A-4329-ABDD-BBA856620510f") is None


def test_inside_guid_only_covers_spans_it_wholly_contains():
    text = "xx " + _PPTX_GUID + " FDO1734Q0GT"
    guid = re.search(re.escape(_PPTX_GUID[1:-1]), text)
    assert rv._inside_guid(text, guid.start(), guid.end())
    tail = text.index("FDO1734Q0GT")
    assert not rv._inside_guid(text, tail, tail + len("FDO1734Q0GT"))
    # A span straddling the GUID boundary is not contained by it.
    assert not rv._inside_guid(text, guid.start() - 2, guid.end())
