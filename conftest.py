"""Pytest bootstrap: put the repo root and tests/ on sys.path so tests can
`import COLLECT_PARSE_V3_23_0` (single-file script, not a package) and
`import synthetic_fixtures`."""
import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, os.path.join(ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)


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
