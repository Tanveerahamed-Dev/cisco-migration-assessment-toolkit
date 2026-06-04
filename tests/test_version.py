"""PHASE 2 loose ends (M2): the version is single-sourced via __version__."""


def test_version_is_single_sourced(cp):
    assert isinstance(cp.__version__, str)
    assert cp.__version__ == "3.23.0"
    # the snapshot's script_version is derived from it (kept as 'V<version>')
    snap = cp.snapshot_state({}, [])
    assert snap["script_version"] == f"V{cp.__version__}" == "V3.23.0"
