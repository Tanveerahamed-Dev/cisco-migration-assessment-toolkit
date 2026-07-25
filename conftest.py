"""Pytest bootstrap: put the repo root and tests/ on sys.path so tests can
`import COLLECT_PARSE_V3_23_0` (single-file script, not a package) and
`import synthetic_fixtures`."""
import importlib
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, os.path.join(ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _engine_global_logging_and_gate_state():
    """Undo, per test, the two PROCESS-GLOBAL side effects of importing the engine.

    `COLLECT_PARSE_V3_23_0.setup_logging()` runs at module import, so merely importing the engine
    anywhere in the suite (`tests/`, and `webapp/tests/test_section_registry.py`) flips two globals
    for every test that follows. This conftest is at the repo root because `pytest.ini` sets
    `testpaths = tests webapp/tests` — a `tests/conftest.py` would cover only half the default gate.

    1. `propagate = False` on the `cisco_toolkit` tree (see `_attach_package_logging`). pytest's
       `caplog` captures by attaching a handler to the ROOT logger, which a non-propagating logger
       never reaches. Current pytest also force-attaches to non-propagating loggers — so the existing
       `cisco_toolkit.gate_state` caplog tests pass either way — but that is an implementation detail
       documented to miss loggers that go non-propagating *after* capture starts, and
       `requirements-dev.txt` allows `pytest>=8,<10`. Belt-and-braces, not load-bearing.
    2. `gate_state._VERDICTS`, the per-run gate ledger that gets SEALED into the run manifest. Tests
       that call `enforce()` would otherwise leave rows visible to every later test in the session.

    Tests that assert the non-propagating behaviour itself call `setup_logging()` inside the test
    (`tests/test_gate_audit_trail.py`), which re-applies it after this fixture has run.
    """
    pkg = logging.getLogger("cisco_toolkit")
    saved = pkg.propagate
    pkg.propagate = True
    try:
        yield
    finally:
        pkg.propagate = saved
        try:
            importlib.import_module("cisco_toolkit.gate_state").reset_verdicts()
        except Exception:      # the package need not be importable for every test
            pass


@pytest.fixture(scope="session")
def cp():
    """The script under test, imported as a module (does not run main())."""
    return importlib.import_module("COLLECT_PARSE_V3_23_0")


@pytest.fixture(scope="session")
def collection_root(tmp_path_factory):
    """A written-out synthetic offline collection directory."""
    import synthetic_fixtures as fx
    root = tmp_path_factory.mktemp("collection")
    return fx.write_collection(str(root))


@pytest.fixture(scope="session")
def built(cp, collection_root):
    """(all_interfaces, all_cmd_to_files) parsed from the synthetic fixtures,
    mirroring the script's --no-collect loader."""
    import synthetic_fixtures as fx
    all_cmd_to_files = {}
    all_interfaces = {}
    cmds = list(dict.fromkeys(cp.COMMANDS_NXOS + cp.COMMANDS_IOS))
    for host, (plat, _out) in fx.COLLECTIONS.items():
        dev_dir = os.path.join(collection_root, host)
        c2f = {c: os.path.join(dev_dir, fx.cmd_filename(c))
               for c in cmds if os.path.isfile(os.path.join(dev_dir, fx.cmd_filename(c)))}
        all_cmd_to_files[host] = c2f
        ident = cp.build_switch_identity(host, plat, c2f)
        all_interfaces[host] = cp.build_interfaces(host, plat, c2f, switch_identity=ident)
    return all_interfaces, all_cmd_to_files
