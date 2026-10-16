"""Repository-local executable closure for the named-form computation ratchet.

Entries are discovered by class: browser documents/projects, API modules and
registered/library-backed report writers. Imports are followed through helpers,
including helpers outside an entry's directory. Third-party modules are terminals;
discovery is not a claim about code outside the repository.
"""
import ast
from pathlib import PurePosixPath


SCRIPT_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")


def python_closure(names, read):
    files = {path for path in names if path.endswith(".py")}
    cache = {}

    def tree(path):
        if path not in cache:
            cache[path] = ast.parse(read(path), filename=path)
        return cache[path]

    def module_paths(module):
        parts = module.split(".") if module else []
        result = {"/".join(parts[:n]) + "/__init__.py" for n in range(1, len(parts) + 1)} & files
        stem = "/".join(parts)
        if stem + ".py" in files:
            result.add(stem + ".py")
        return result

    registry = tree("cisco_toolkit/docmeta.py")
    seeds = set()
    for node in ast.walk(registry):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "writer_module":
                continue
            if not isinstance(keyword.value, ast.Constant) or not isinstance(keyword.value.value, (str, type(None))):
                raise ValueError("Registered writer module requires a static source owner")
            if keyword.value.value:
                owners = module_paths(keyword.value.value)
                if not owners:
                    raise ValueError("Registered report writer source is absent: " + keyword.value.value)
                seeds.update(owners)

    def authored(path):
        parts = PurePosixPath(path).parts
        return not any(part in {"tests", "test", "__tests__", "fixtures", ".venv", "node_modules"} for part in parts)

    production = {path for path in files if authored(path)}
    for path in production:
        for node in ast.walk(tree(path)):
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            imports = [name.name for name in node.names] if isinstance(node, ast.Import) else []
            # API entry classes and report-writing libraries cover unregistered
            # API modules/workbook/HTML writers without a hand-maintained file list.
            if module and module.split(".")[0] in {"fastapi", "starlette", "docx", "pptx", "openpyxl", "xlsxwriter"}:
                seeds.add(path)
            if any(name.split(".")[0] in {"fastapi", "starlette", "docx", "pptx", "openpyxl", "xlsxwriter"} for name in imports):
                seeds.add(path)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("write_") and node.name.endswith(("_html", "_docx", "_pptx", "_xlsx")):
                seeds.add(path)

    selected, pending = set(), list(seeds)
    while pending:
        path = pending.pop()
        if path in selected:
            continue
        selected.add(path)
        dependencies = set()
        package = str(PurePosixPath(path).parent).replace("/", ".")
        import_names = {"import_module", "__import__"}
        for node in ast.walk(tree(path)):
            if isinstance(node, ast.ImportFrom) and node.module in {"importlib", "builtins"}:
                import_names.update(alias.asname or alias.name for alias in node.names if alias.name in import_names)
        for node in ast.walk(tree(path)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    dependencies.update(module_paths(alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    components = package.split(".") if package != "." else []
                    base = components[:len(components) - node.level + 1]
                    module = ".".join([*base, *([node.module] if node.module else [])])
                else:
                    module = node.module or ""
                dependencies.update(module_paths(module))
                for alias in node.names:
                    if alias.name != "*":
                        dependencies.update(module_paths(".".join(filter(None, (module, alias.name)))))
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if name in import_names:
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        dependencies.update(module_paths(node.args[0].value))
                    else:
                        # A dynamic selector may select any repository production
                        # module. Conservatively close that class, not just today's
                        # literal registry targets; never execute the selector.
                        dependencies.update(production)
        pending.extend(dependencies - selected)
    return selected
