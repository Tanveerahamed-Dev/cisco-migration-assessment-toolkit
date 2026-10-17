"""Hosted prefix observer: retain collection; record only the target after timing."""
import json
import os

import pytest

TARGET = "tests/test_vlan_carriage_budget.py::test_the_first_document_and_one_full_page_stay_within_their_api_budgets"
_cut_before = os.environ.get("ATLAS_MINIMAL_CUT_BEFORE", "")
_cut_prefix = _cut_before + "::" if _cut_before else ""
_session = None
_omitting = False
_omitted = 0
_cut_seen = False
_setup_outcome = None
_call_outcome = None
_call_seconds = None
_teardown_outcome = None
_failure = None
_finishes = 0
_exit_status = None


def pytest_sessionstart(session):
    global _session
    _session = session


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    global _omitting, _omitted, _cut_seen
    # Only WHOLE FILE suffixes may be omitted. The original last admitted
    # item's nextitem already closes that file's module/class fixtures.
    # No collected item, mark, report, ordering or nextitem is rewritten.
    if _cut_prefix and item.nodeid.startswith(_cut_prefix):
        _omitting = _cut_seen = True
    if _omitting and item.nodeid != TARGET:
        _omitted += 1
        return True
    return None


def pytest_runtest_logreport(report):
    global _setup_outcome, _call_outcome, _call_seconds, _teardown_outcome, _failure
    if report.nodeid != TARGET:
        return
    if report.when == "setup":
        _setup_outcome = report.outcome  # existing scalar; no report/container retained
    elif report.when == "call":
        _call_outcome = report.outcome
        _call_seconds = report.duration
        if report.failed:
            _failure = str(report.longrepr)  # target timing has already finished
    elif report.when == "teardown":
        _teardown_outcome = report.outcome


def pytest_runtest_logfinish(nodeid, location):
    global _finishes
    if nodeid == TARGET:
        _finishes += 1
        _session.shouldstop = "ATLAS diagnostic target protocol completed"


def pytest_sessionfinish(session, exitstatus):
    global _exit_status
    _exit_status = int(exitstatus)  # never change pytest's actual interrupted exit


def pytest_unconfigure(config):
    if _session is None:
        return
    # Serialize only after target call, teardown and ordinary session cleanup.
    # This list is observed AFTER timing; all original Items stayed retained.
    result = {
        "cut_before": _cut_before, "cut_seen": _cut_seen, "omitted": _omitted,
        "setup": _setup_outcome, "call": _call_outcome, "call_seconds": _call_seconds,
        "teardown": _teardown_outcome, "target_finishes": _finishes,
        "failure": _failure, "pytest_exit": _exit_status,
        "session_testsfailed": _session.testsfailed,
        "planned_stop": _finishes == 1,
        "collection": [item.nodeid for item in _session.items],
    }
    with open(os.environ["ATLAS_MINIMAL_REPORT"], "w", encoding="utf-8") as stream:
        json.dump(result, stream)
