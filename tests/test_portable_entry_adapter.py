"""Frozen packaging callbacks preserve shared CLI ordering and default behavior."""

from __future__ import annotations

import os

import pytest

from portable import atlas_entry, maintenance
from webapp.backend import serve


@pytest.mark.parametrize("status", [0, 29])
@pytest.mark.parametrize("live_requested", [False, True])
def test_packaging_dispatch_runs_after_freeze_support_and_live_flag_scoping(
    monkeypatch, status, live_requested,
):
    events = []
    monkeypatch.setenv("ATLAS_PORTABLE_ALLOW_LIVE_NETWORK", "prior")
    monkeypatch.setattr(serve.multiprocessing, "freeze_support", lambda: events.append("freeze"))
    monkeypatch.setattr(serve, "_frozen", lambda: True)

    def dispatch(argv):
        events.append((list(argv), os.environ.get("ATLAS_PORTABLE_ALLOW_LIVE_NETWORK")))
        return status

    monkeypatch.setattr(maintenance, "main", dispatch)
    monkeypatch.setattr(serve, "_load_engine_main", lambda: pytest.fail("engine loaded"))
    monkeypatch.setattr(serve, "_writable_failure", lambda path: pytest.fail("store write reached"))
    argv = ["--update", "candidate.zip"]
    if live_requested:
        argv.append(serve.LIVE_NETWORK_FLAG)
    original = list(argv)
    assert atlas_entry.main(argv) == status
    assert events == ["freeze", (["--update", "candidate.zip"], "1" if live_requested else None)]
    assert argv == original
    assert os.environ["ATLAS_PORTABLE_ALLOW_LIVE_NETWORK"] == "prior"


def test_packaging_dispatch_failure_restores_prior_live_network_setting(monkeypatch):
    monkeypatch.delenv("ATLAS_PORTABLE_ALLOW_LIVE_NETWORK", raising=False)
    monkeypatch.setattr(serve, "_frozen", lambda: True)

    def refused(argv):
        assert os.environ["ATLAS_PORTABLE_ALLOW_LIVE_NETWORK"] == "1"
        raise ValueError("synthetic maintenance refusal")

    monkeypatch.setattr(maintenance, "main", refused)
    with pytest.raises(ValueError, match="synthetic maintenance refusal"):
        atlas_entry.main(["--update", "candidate.zip", serve.LIVE_NETWORK_FLAG])
    assert "ATLAS_PORTABLE_ALLOW_LIVE_NETWORK" not in os.environ


def test_default_shared_main_keeps_legacy_scoped_call_signature(monkeypatch):
    seen = []

    def scoped(argv):
        seen.append(argv)
        return 31

    monkeypatch.setattr(serve, "_main_scoped", scoped)
    assert serve.main(["--version"]) == 31
    assert seen == [["--version"]]


def test_default_shared_selftest_dispatch_keeps_legacy_call_signature(monkeypatch):
    seen = []

    def selftest(*, dist_dir, db_path):
        seen.append((dist_dir, db_path))
        return 32

    monkeypatch.setattr(serve, "run_selftest", selftest)
    assert serve.main(["--selftest", "--dist", "synthetic-dist", "--db", "synthetic.db"]) == 32
    assert seen == [("synthetic-dist", "synthetic.db")]


def test_packaging_selftest_passes_explicit_db_to_admission_before_assets(monkeypatch):
    seen = []

    def refuse(*, external_db):
        seen.append(external_db)
        return True

    monkeypatch.setattr(atlas_entry, "_maintenance_write_refused", refuse)
    monkeypatch.setattr(serve, "_explorer_template_path", lambda: pytest.fail("asset reached before fence"))
    assert atlas_entry.main(["--selftest", "--db", "synthetic.db"]) == 1
    assert seen == ["synthetic.db"]


def test_duplicate_live_flag_is_rejected_before_packaging_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(atlas_entry, "_command_handler", lambda argv: pytest.fail("dispatch reached"))
    assert atlas_entry.main(["--update", "candidate.zip", serve.LIVE_NETWORK_FLAG,
                             serve.LIVE_NETWORK_FLAG]) == 2
    assert "may be supplied only once" in capsys.readouterr().err
