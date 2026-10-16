"""Repository-local executable closure for the named-form computation ratchet.

Entries are discovered by class: browser documents/projects, API modules and
registered/library-backed report writers. Imports are followed through helpers,
including helpers outside an entry's directory. Third-party modules are terminals;
discovery is not a claim about code outside the repository.
"""
import ast
from pathlib import PurePosixPath


SCRIPT_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")


def role_required(path):
    return path.endswith(".py") and (path.startswith(("cisco_toolkit/", "webapp/backend/")) or path == "COLLECT_PARSE_V3_23_0.py")


def module_roles(names, read):
    """Every owned module declares one literal role; missing/ambiguous roles refuse.

    Roles are reviewed source, not a filename exemption list. Mixed modules remain
    interface until a reviewed owner extraction removes their interface computation.
    """
    roles = {}
    for path in sorted(name for name in names if role_required(name)):
        tree = ast.parse(read(path), filename=path)
        writes = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
                  and node.id == "__atlas_role__" and isinstance(node.ctx, (ast.Store, ast.Del))]
        declarations = [node for node in tree.body if isinstance(node, ast.Assign) and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "__atlas_role__"]
        if len(writes) != 1 or len(declarations) != 1 or not isinstance(declarations[0].value, ast.Constant) or declarations[0].value.value not in {"engine", "interface"}:
            raise ValueError("Module requires exactly one literal __atlas_role__: " + path)
        roles[path] = declarations[0].value.value
    return roles


def python_closure(names, read, role_read=None):
    files = {path for path in names if path.endswith(".py")}
    cache = {}
    roles = module_roles(names, role_read or read)

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
    seeds = {path for path, role in roles.items() if role == "interface"}
    writers = set()
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
                writers.update(path for path in owners if not path.endswith("/__init__.py"))

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
                writers.add(path)
            if any(name.split(".")[0] in {"fastapi", "starlette", "docx", "pptx", "openpyxl", "xlsxwriter"} for name in imports):
                seeds.add(path)
                writers.add(path)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("write_") and node.name.endswith(("_html", "_docx", "_pptx", "_xlsx")):
                seeds.add(path)
                writers.add(path)

    for path in writers:
        if roles.get(path) == "engine":
            raise ValueError("An API/report writer cannot declare engine role: " + path)

    dependency_cache = {}

    def dependencies_of(path):
        if path in dependency_cache:
            return dependency_cache[path]
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
        dependency_cache[path] = dependencies
        return dependencies

    # Assert the direction even for engine modules never reached by an interface.
    # Follow unclassified helpers as well, preventing an intermediate helper from
    # laundering an engine -> interface computation dependency.
    for owner, role in roles.items():
        if role != "engine":
            continue
        visited, pending = set(), [owner]
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            if path != owner and roles.get(path) == "interface":
                raise ValueError("Engine imports interface computation: " + owner + " -> " + path)
            pending.extend(dependencies_of(path) - visited)

    selected, visited, pending = set(), set(), list(seeds)
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        if roles.get(path) == "engine":
            continue  # Calling an owner is the intended interface direction.
        selected.add(path)
        pending.extend(dependencies_of(path) - visited)
    return selected


COMPILED_ROOT = "webapp/frontend/dist/"
DIST_WORKFLOW = ".github/workflows/webapp-ci.yml"
DIST_GATE = "Verify checked-in SPA equals the source-bound build"
DIST_COMMAND = 'python .github/scripts/frontend_build_handoff.py verify-committed --output "${{ runner.temp }}/frontend-dist-handoff"'


def compiled_coverage(names, read):
    """Refuse uncovered generated code; entry documents themselves stay scanned.

    The named hosted gate compares the entire checked-in distribution inventory
    and every byte with the source-bound build; minified identities are not debt.
    """
    generated = {path for path in names if any(part in {"dist", "dist-hub", "build", ".next"}
                 for part in PurePosixPath(path).parts[:-1])
                 and path.lower().endswith((*SCRIPT_SUFFIXES, ".html"))}
    if not generated:
        return set()
    uncovered = sorted(path for path in generated if not path.startswith(COMPILED_ROOT))
    if uncovered:
        raise ValueError("Compiled source has no source-to-dist gate: " + uncovered[0])
    import yaml
    workflow = yaml.safe_load(read(DIST_WORKFLOW))
    job = workflow["jobs"]["frontend"]
    steps = job["steps"]
    gates = [(index, step) for index, step in enumerate(steps) if step.get("name") == DIST_GATE]
    if len(gates) != 1:
        raise ValueError("Compiled source-to-dist gate is absent or ambiguous")
    index, gate = gates[0]
    if (gate.get("run") != DIST_COMMAND or gate.get("working-directory") != "."
            or "if" in gate or gate.get("continue-on-error") or job.get("continue-on-error")
            or not any(step.get("run") == "npm run build" and "if" not in step
                       and not step.get("continue-on-error") for step in steps[:index])
            or not any("frontend_build_handoff.py after" in step.get("run", "")
                       and "if" not in step and not step.get("continue-on-error") for step in steps[:index])):
        raise ValueError("Compiled source-to-dist gate is not enforced after the bound build")
    helper = ast.parse(read(".github/scripts/frontend_build_handoff.py"))
    if not any(isinstance(node, ast.FunctionDef) and node.name == "verify_committed_dist" for node in helper.body):
        raise ValueError("Compiled byte-comparison implementation is absent")
    return {path for path in names if path.startswith(COMPILED_ROOT)}
