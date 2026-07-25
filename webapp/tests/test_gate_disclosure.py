"""AssessHub's on-demand design/MOP download vs the PPDIOO document gates (decision 2026-07-22).

The recorded decision is DISCLOSE-not-block: this surface consults `cisco_toolkit.gate_state` and
reports an unsatisfied document gate on the response, but always delivers the file. The reasoning
(an AssessHub campaign is a DB row with no filesystem engagement root, so a server-root ledger
would wrongly refuse OTHER campaigns; and there is no --override-gate here) lives in
`backend.deliverables.generate`'s docstring; the source-level half of the pin is
`tests/test_gate_state.py::test_assesshub_deliverable_download_discloses_gates`.

Both halves matter and they fail in opposite directions: a regression to silence loses the
disclosure, a regression to refusal loses the deliverable. Every test here asserts BOTH.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend import deliverables  # noqa: E402
from backend.app import create_app  # noqa: E402

from cisco_toolkit import gate_state  # noqa: E402  (backend import bootstraps sys.path)

_GATED = ("design", "mop")


def _seed(client) -> int:
    r = client.post("/api/demo/seed")
    assert r.status_code == 200, r.text
    return r.json()["snapshot"]["id"]


@pytest.fixture()
def engagement(tmp_path, monkeypatch):
    """Run the server with its cwd AT an engagement root, which is how gate_state resolves the
    ledger (root='.'). Yields the root so a test can record decisions into it."""
    root = tmp_path / "engagement"
    root.mkdir()
    monkeypatch.chdir(root)
    return root


def _client(tmp_path):
    app = create_app(db_path=str(tmp_path / "gate.db"))
    # base_url=localhost so the default Host passes the no-token DNS-rebinding guard (#384).
    return TestClient(app, base_url="http://localhost")


def _download(client, sid, kind):
    r = client.get(f"/api/snapshots/{sid}/deliverable/{kind}",
                   headers={"sec-fetch-site": "same-origin"})
    return r


@pytest.mark.parametrize("kind", _GATED)
def test_unapproved_gate_discloses_but_still_delivers(tmp_path, engagement, kind):
    """The load-bearing case: upstream approval REVOKED (a peer review that actively said no).

    A revoked ledger must produce a disclosure header AND a real document — that pairing IS the
    decision. Asserting only the header would pass if the route had started refusing.

    The token is `pending`, the one `gate_state.enforce`/`pending_approvals` report for a LOCATED
    ledger with missing approvals. It read `ungated` until 2026-07-25 — a token `UNEVALUATED`
    reserves for approvals that were never evaluated at all, so the header told an operator whose
    LLD had been REVOKED that no gates were tracked. See
    tests/test_gate_state.py::test_gate_disclosure_token_matches_the_owner_of_the_posture_fact."""
    # Revoke design's upstream and both of the MOP's, so either kind has an unsatisfied gate.
    for g in ("assessment_approved", "lld_approved", "baseline_captured"):
        gate_state.record_decision(g, "revoked", root=str(engagement), by="reviewer")

    with _client(tmp_path) as c:
        sid = _seed(c)
        if not deliverables.availability().get(kind):
            pytest.skip("python-docx not installed — the availability 503 pre-empts the gate path")
        r = _download(c, sid, kind)

    assert r.status_code == 200, f"the gate BLOCKED the download (decision is disclose): {r.text[:200]}"
    gate_hdr = r.headers.get("X-Gate-Status", "")
    assert gate_hdr.startswith("pending:"), \
        f"an unapproved gate was not disclosed as pending: {gate_hdr!r}"
    assert not gate_hdr.startswith("ungated:"), \
        f"a REVOKED approval was disclosed as 'ungated', which reads as 'no gates here': {gate_hdr!r}"
    # DOCX is a zip — 'PK' proves a real document was streamed, not an empty/stub refusal body.
    assert r.content[:2] == b"PK" and len(r.content) > 5000, \
        f"disclosed but delivered nothing usable ({len(r.content)} bytes)"


@pytest.mark.parametrize("kind", _GATED)
def test_approved_and_brownfield_engagements_are_silent(tmp_path, engagement, kind):
    """Non-vacuity for the test above: the header must be ABSENT when there is nothing to say.

    Two silent cases, and they are silent for different reasons — approvals recorded and present,
    and the brownfield engagement that never opted in (no store at all). If either emitted a
    header, the assertion above would be reporting a constant rather than the ledger."""
    with _client(tmp_path) as c:
        sid = _seed(c)
        if not deliverables.availability().get(kind):
            pytest.skip("python-docx not installed — the availability 503 pre-empts the gate path")

        # (a) brownfield: no docs/engagement-state.json exists yet.
        assert not (engagement / "docs" / "engagement-state.json").exists()
        r = _download(c, sid, kind)
        assert r.status_code == 200 and "X-Gate-Status" not in r.headers, \
            "a brownfield engagement must stay silent (unchanged behaviour), got " \
            f"{r.headers.get('X-Gate-Status')!r}"

        # (b) every upstream approved.
        for g in ("assessment_approved", "lld_approved", "baseline_captured"):
            gate_state.record_decision(g, "approved", root=str(engagement), by="lead")
        r = _download(c, sid, kind)
        assert r.status_code == 200 and "X-Gate-Status" not in r.headers, \
            f"an approved engagement was flagged: {r.headers.get('X-Gate-Status')!r}"


def test_ungated_deliverable_never_carries_the_header(tmp_path, engagement):
    """Only design and mop are gated (gate_state.GENERATOR_REQUIRES). A revoked ledger must not
    leak a disclosure onto the runbook, which no document gate governs."""
    gate_state.record_decision("assessment_approved", "revoked", root=str(engagement), by="reviewer")
    with _client(tmp_path) as c:
        sid = _seed(c)
        if not deliverables.availability().get("runbook"):
            pytest.skip("python-docx not installed")
        r = _download(c, sid, "runbook")
    assert r.status_code == 200 and "X-Gate-Status" not in r.headers, \
        f"an ungated deliverable was gate-flagged: {r.headers.get('X-Gate-Status')!r}"


def test_corrupt_ledger_discloses_and_still_delivers(tmp_path, engagement):
    """The asymmetry this surface deliberately inverts: the CLI fails CLOSED on an unreadable
    store, AssessHub cannot (a broken ledger must never withhold a deliverable) — so it must fail
    OPEN AND SAY SO. Silence here would be the worst outcome: an operator whose ledger is corrupt
    would read it as 'gates fine'."""
    docs = engagement / "docs"
    docs.mkdir(parents=True)
    (docs / "engagement-state.json").write_text("{ this is not json", encoding="utf-8")

    with _client(tmp_path) as c:
        sid = _seed(c)
        if not deliverables.availability().get("design"):
            pytest.skip("python-docx not installed")
        r = _download(c, sid, "design")

    assert r.status_code == 200, f"a corrupt ledger blocked the download: {r.text[:200]}"
    assert r.headers.get("X-Gate-Status", "").startswith("unreadable:"), \
        f"a corrupt ledger was not disclosed: {r.headers.get('X-Gate-Status')!r}"
    assert r.content[:2] == b"PK"
