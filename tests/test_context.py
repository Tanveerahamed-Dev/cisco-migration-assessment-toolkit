"""Plan-A #15: the typed pipeline carrier. Pins that AnalysisContext defaults are safe (empty
containers, not shared mutable state), that it is mutable (stages populate it incrementally), and
that it is a stdlib-only leaf (no project import cycle)."""
import dataclasses

from cisco_toolkit.context import AnalysisContext


def test_defaults_are_empty_and_not_shared():
    a, b = AnalysisContext(), AnalysisContext()
    assert a.out_xlsx == "" and a.workers == 1 and a.args is None
    assert a.all_cmd_to_files == {} and a.all_devices_meta == [] and a.snap_dict == {}
    a.all_devices_meta.append("x")
    a.snap_dict["k"] = 1
    assert b.all_devices_meta == [] and b.snap_dict == {}          # default_factory -> no shared mutables


def test_is_mutable_carrier_stages_fill_in_place():
    ctx = AnalysisContext(args=object(), out_xlsx="out.xlsx", root_dir="/r", workers=4)
    ctx.all_cmd_to_files["h"] = {"show version": "v.txt"}
    ctx.snap_dict["devices"] = {}
    ctx.snap_path = "out.snapshot.json"
    assert ctx.out_xlsx == "out.xlsx" and ctx.workers == 4
    assert ctx.snap_path.endswith(".snapshot.json") and "h" in ctx.all_cmd_to_files


def test_is_a_dataclass_leaf():
    assert dataclasses.is_dataclass(AnalysisContext)
    # stdlib-only leaf: its module imports must not pull the engine (no import cycle)
    import cisco_toolkit.context as ctxmod
    src = open(ctxmod.__file__, encoding="utf-8").read()
    assert "import cisco_toolkit" not in src and "from cisco_toolkit" not in src
