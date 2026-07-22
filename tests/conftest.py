"""Suite-wide fixtures.

`COLLECT_PARSE_V3_23_0.setup_logging()` sets ``propagate = False`` on the ``cisco_toolkit`` logger
tree (see ``_attach_package_logging`` — it stops a stray ``basicConfig()`` duplicating the engine's
records). That runs at MODULE IMPORT, so merely importing the engine anywhere in the suite flips the
flag process-wide for every test that follows.

pytest's ``caplog`` captures by attaching a handler to the ROOT logger, which a non-propagating logger
never reaches. Current pytest also force-attaches to non-propagating loggers, so the existing
``cisco_toolkit.gate_state`` caplog tests pass today — but that is an implementation detail, it is
documented to miss loggers that become non-propagating *after* capture starts, and
``requirements-dev.txt`` allows ``pytest>=8,<10``. Rather than let the suite's correctness ride on
which pytest CI happens to resolve, restore propagation for the duration of each test.

Tests that assert the non-propagating behaviour itself just call ``setup_logging()`` inside the test
(``tests/test_gate_audit_trail.py``), which re-applies it after this fixture has run.
"""
import logging

import pytest


@pytest.fixture(autouse=True)
def _restore_cisco_toolkit_log_propagation():
    pkg = logging.getLogger("cisco_toolkit")
    saved = pkg.propagate
    pkg.propagate = True
    try:
        yield
    finally:
        pkg.propagate = saved
