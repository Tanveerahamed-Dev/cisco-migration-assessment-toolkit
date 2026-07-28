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
    """NON-VACUITY (mutation-proved, 2026-07-28): this used to scan the raw source for the literals
    "import cisco_toolkit" / "from cisco_toolkit", which miss the idiomatic in-package spelling.
    Adding `from .analyze import compute_findings` — a genuine cycle straight back into the engine,
    and the form anyone editing this module would actually write — left the test GREEN. Parse the
    import statements instead of grepping for one spelling of them."""
    import ast

    import cisco_toolkit.context as ctxmod
    assert dataclasses.is_dataclass(AnalysisContext)
    tree = ast.parse(open(ctxmod.__file__, encoding="utf-8").read())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [a.name for a in node.names if a.name.split(".")[0] == "cisco_toolkit"]
        elif isinstance(node, ast.ImportFrom):
            if node.level:                       # ANY relative import is an in-package import
                offenders.append("." * node.level + (node.module or ""))
            elif (node.module or "").split(".")[0] == "cisco_toolkit":
                offenders.append(node.module)
    assert not offenders, (
        f"cisco_toolkit.context is no longer a stdlib-only leaf — it imports {offenders}, "
        f"re-opening the import cycle the carrier exists to avoid")
