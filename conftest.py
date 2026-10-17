"""Pytest bootstrap: put the repo root and tests/ on sys.path so tests can
`import COLLECT_PARSE_V3_23_0` (single-file script, not a package) and
`import synthetic_fixtures`; and own the full gate's shard options (`--atlas-shard`,
`--atlas-shard-manifest`, tests/atlas_shard_partition.py)."""
import importlib
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, os.path.join(ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)


# -- the full gate's shards (.github/workflows/portable-release.yml `gate_shard` / `gate`) ---------
# One required job ran the whole Windows suite plus the frontend gate under one 120-minute limit and
# was cancelled under runner contention, so the suite is split by TEST FILE across parallel jobs and
# the required job proves the shards' union is exactly one full collection
# (.github/scripts/verify_shard_union.py). The partition itself is tests/atlas_shard_partition.py.
#
# Without either option every hook below returns before touching anything: no item is moved or
# deselected, no file is written and the helper module is not even imported -- this conftest is a
# plugin for every run (tests + webapp/tests, webapp-ci's backend leg, the 3.10-3.14 matrix,
# coverage, the Stop hook's `-n auto`). The shard is read ONLY from the command line: an
# environment variable would leak into every subprocess a test starts.
def pytest_addoption(parser):
    group = parser.getgroup("atlas-shard", "full-gate sharding (tests/atlas_shard_partition.py)")
    group.addoption("--atlas-shard", action="store", default=None, dest="atlas_shard", metavar="I/N",
                    help="keep only the test files that hash to shard I of N (integers, 0 <= I < N); "
                         "the other items are deselected")
    group.addoption("--atlas-shard-manifest", action="store", default=None, dest="atlas_shard_manifest",
                    metavar="PATH",
                    help="write the final selected node ids to the NEW file PATH: sorted, one per line, "
                         "UTF-8, LF")


def _atlas_shard_options(config):
    return (config.getoption("atlas_shard", default=None),
            config.getoption("atlas_shard_manifest", default=None))


def pytest_configure(config):
    """Refuse a malformed spec, a stale or unplaceable manifest, and any pytest-xdist run, before
    collection starts: a pytest usage error (exit 4), never a quietly unsharded or partial run."""
    spec, manifest = _atlas_shard_options(config)
    if spec is None and manifest is None:
        return
    # xdist workers each collect and would race on one manifest, and the controller holds no items.
    if hasattr(config, "workerinput") or getattr(config.option, "dist", "no") != "no":
        raise pytest.UsageError("--atlas-shard / --atlas-shard-manifest cannot be combined with "
                                "pytest-xdist distribution (-n / --dist)")
    import atlas_shard_partition as shard

    try:
        if spec is not None:
            shard.parse_spec(spec)
        if manifest is not None:
            shard.check_manifest_target(manifest)
    except shard.ShardOptionError as error:
        raise pytest.UsageError(str(error)) from None


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items):
    """Last, so it sees the final item set every other plugin produced: keep this shard's files,
    deselect the rest, then record exactly what remains."""
    spec, manifest = _atlas_shard_options(config)
    if spec is None and manifest is None:
        return
    import atlas_shard_partition as shard

    try:
        if spec is not None:
            index, total = shard.parse_spec(spec)
            kept, dropped = shard.select(items, index, total)
            if dropped:
                config.hook.pytest_deselected(items=dropped)
            items[:] = kept
        if manifest is not None:
            shard.write_manifest(manifest, (item.nodeid for item in items))
    except (shard.ShardOptionError, OSError) as error:
        raise pytest.UsageError(f"atlas shard: {error}") from None


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
