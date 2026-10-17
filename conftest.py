"""Pytest bootstrap: put the repo root and tests/ on sys.path so tests can
`import COLLECT_PARSE_V3_23_0` (single-file script, not a package) and
`import synthetic_fixtures`; and own the full gate's shard options (`--atlas-shard`,
`--atlas-shard-manifest`, `--atlas-shard-executed`, `--atlas-shard-environment`;
tests/atlas_shard_partition.py)."""
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
# was cancelled under runner contention, so the suite is split by TEST FILE across parallel jobs. Each
# shard records what it selected, which of those tests completed without failure, and the environment
# it ran in, and the required job proves from that evidence (.github/scripts/verify_shard_union.py)
# that the shards selected exactly one full collection, that each ran its whole selection without
# failure, and that all of them ran in the environment of that collection. The partition and the
# evidence are tests/atlas_shard_partition.py.
#
# Without any of the options every hook below returns before touching anything: no item is moved or
# deselected, no plugin is registered, no file is written and the helper module is not even imported
# -- this conftest is a plugin for every run (tests + webapp/tests, webapp-ci's backend leg, the
# 3.10-3.14 matrix, coverage, the Stop hook's `-n auto`). Each option is read ONLY from the command
# line: an environment variable would leak into every subprocess a test starts.
def pytest_addoption(parser):
    group = parser.getgroup("atlas-shard", "full-gate sharding (tests/atlas_shard_partition.py)")
    group.addoption("--atlas-shard", action="store", default=None, dest="atlas_shard", metavar="I/N",
                    help="keep only the test files that hash to shard I of N (integers, 0 <= I < N); "
                         "the other items are deselected")
    group.addoption("--atlas-shard-manifest", action="store", default=None, dest="atlas_shard_manifest",
                    metavar="PATH",
                    help="write the final selected node ids to the NEW file PATH: sorted, one per line, "
                         "UTF-8, LF")
    group.addoption("--atlas-shard-executed", action="store", default=None, dest="atlas_shard_executed",
                    metavar="PATH",
                    help="when the session finishes, write the node ids that completed without failure "
                         "to the NEW file PATH (the same format)")
    group.addoption("--atlas-shard-environment", action="store", default=None,
                    dest="atlas_shard_environment", metavar="PATH",
                    help="before any test runs, write the interpreter and every installed distribution "
                         "to the NEW file PATH (the same format)")


#: Each shard option's flag and the pytest option name its value is stored under.
_ATLAS_SHARD_DESTS = (
    ("--atlas-shard", "atlas_shard"),
    ("--atlas-shard-manifest", "atlas_shard_manifest"),
    ("--atlas-shard-executed", "atlas_shard_executed"),
    ("--atlas-shard-environment", "atlas_shard_environment"),
)


def _atlas_shard_options(config):
    """Every shard option's value (None when it was not given), by flag."""
    return {flag: config.getoption(dest, default=None) for flag, dest in _ATLAS_SHARD_DESTS}


class _AtlasShardExecutedRecorder:
    """The ``--atlas-shard-executed`` evidence. Records the (node id, phase, outcome) of every test
    report pytest logs and, when the session finishes, writes the node ids that completed without
    failure (tests/atlas_shard_partition.py :: completed_without_failure) -- read from the reports
    themselves, so what a step does with pytest's exit status cannot change it. Registered only when
    the option is given."""

    def __init__(self, path):
        self.path = path
        self.facts = []

    # trylast: after every normally ordered implementation has seen, and possibly amended, the report.
    @pytest.hookimpl(trylast=True)
    def pytest_runtest_logreport(self, report):
        self.facts.append((report.nodeid, report.when, report.outcome))

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session):
        import atlas_shard_partition as shard

        try:
            shard.write_manifest(self.path, shard.completed_without_failure(self.facts))
        except (shard.ShardOptionError, OSError) as error:
            # Never a quiet pass: the run fails, and the gate finds no executed manifest to accept.
            sys.stderr.write(f"atlas shard: the executed manifest was not written: {error}\n")
            session.exitstatus = pytest.ExitCode.INTERNAL_ERROR


def pytest_configure(config):
    """Refuse a malformed spec, a stale or unplaceable evidence file, and any pytest-xdist run, before
    collection starts: a pytest usage error (exit 4), never a quietly unsharded, partial or unevidenced
    run. Then, before any test can install or change a distribution, write the environment evidence,
    and register the recorder that writes the executed evidence."""
    options = _atlas_shard_options(config)
    if all(value is None for value in options.values()):
        return
    # xdist workers each collect and run a part and would race on one file, while the controller
    # holds no items and only relays its workers' reports.
    if hasattr(config, "workerinput") or getattr(config.option, "dist", "no") != "no":
        raise pytest.UsageError(" / ".join(options) + " cannot be combined with pytest-xdist "
                                "distribution (-n / --dist)")
    import atlas_shard_partition as shard

    targets = [(flag, options[flag]) for flag in
               ("--atlas-shard-manifest", "--atlas-shard-executed", "--atlas-shard-environment")
               if options[flag] is not None]
    try:
        if options["--atlas-shard"] is not None:
            shard.parse_spec(options["--atlas-shard"])
        for flag, path in targets:
            shard.check_manifest_target(path, flag)
        if options["--atlas-shard-environment"] is not None:
            shard.write_manifest(options["--atlas-shard-environment"], shard.environment_rows())
    except (shard.ShardOptionError, OSError) as error:
        raise pytest.UsageError(f"atlas shard: {error}") from None
    if options["--atlas-shard-executed"] is not None:
        config.pluginmanager.register(_AtlasShardExecutedRecorder(options["--atlas-shard-executed"]),
                                      "atlas-shard-executed-recorder")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items):
    """Keep this shard's files, deselect the rest, then record exactly what remains. trylast runs it
    after every normally ordered implementation (-k/-m deselection, fixture reordering); anything that
    changes the items later is still caught because each shard's executed manifest must equal its
    selected one."""
    options = _atlas_shard_options(config)
    spec, manifest = options["--atlas-shard"], options["--atlas-shard-manifest"]
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
