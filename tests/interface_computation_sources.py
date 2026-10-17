"""Repository-local executable closure for the named-form computation ratchet.

Entries are discovered by class: browser documents/projects, API modules and
registered/library-backed report writers. Imports are followed through helpers,
including helpers outside an entry's directory. Third-party modules are terminals;
discovery is not a claim about code outside the repository.
"""
import ast
import json
from pathlib import PurePosixPath


SCRIPT_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
BROWSER_DOCUMENT_SUFFIXES = (".html", ".htm", ".xhtml", ".svg")


def python_module(path):
    return path.lower().endswith(".py")


def role_required(path):
    folded = path.casefold()
    return python_module(path) and (folded.startswith(("cisco_toolkit/", "webapp/backend/")) or folded == "collect_parse_v3_23_0.py")


def module_roles(names, read, declaration_names=None):
    """Require one explicit role per owned module, never an exemption filename list.

    A literal module constant or its module-owned ``.atlas-role`` companion is a
    declaration. Companions preserve frozen executable source bytes. Both forms
    together, missing/ambiguous roles, duplicate JSON keys and orphan companions
    refuse. All modules come from the source class, not the declaration inventory.
    """
    available = set(names if declaration_names is None else declaration_names)
    owned = {path for path in names if role_required(path)}
    for path in available:
        if path.endswith(".atlas-role") and path.removesuffix(".atlas-role") not in owned:
            raise ValueError("Orphan or unowned module role declaration: " + path)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate module role declaration key")
            result[key] = value
        return result

    roles = {}
    for path in sorted(owned):
        tree = ast.parse(read(path), filename=path)
        writes = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
                  and node.id == "__atlas_role__" and isinstance(node.ctx, (ast.Store, ast.Del))]
        declarations = [node for node in tree.body if isinstance(node, ast.Assign) and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "__atlas_role__"]
        values = []
        if writes or declarations:
            if len(writes) != 1 or len(declarations) != 1 or not isinstance(declarations[0].value, ast.Constant):
                raise ValueError("Module requires exactly one literal role declaration: " + path)
            values.append(declarations[0].value.value)
        companion = path + ".atlas-role"
        if companion in available:
            data = json.loads(read(companion), object_pairs_hook=unique)
            if type(data) is not dict or set(data) != {"role"}:
                raise ValueError("Module role companion has unknown or missing fields: " + companion)
            values.append(data["role"])
        if len(values) != 1 or type(values[0]) is not str or values[0] not in {"engine", "interface"}:
            raise ValueError("Module requires exactly one literal role declaration: " + path)
        roles[path] = values[0]
    return roles


def python_closure(names, read, role_read=None, role_names=None):
    files = {path for path in names if python_module(path)}
    folded_files = {}
    for path in sorted(files):
        folded = path.casefold()
        if folded in folded_files:
            raise ValueError("Ambiguous Windows Python module identity: " + path)
        folded_files[folded] = path
    cache = {}
    roles = module_roles(names, role_read or read, role_names)

    def tree(path):
        if path not in cache:
            cache[path] = ast.parse(read(path), filename=path)
        return cache[path]

    def module_file(path):
        actual = folded_files.get(path.casefold())
        return {actual} if actual else set()

    def module_paths(module):
        parts = module.split(".") if module else []
        result = set()
        for n in range(1, len(parts) + 1):
            result.update(module_file("/".join(parts[:n]) + "/__init__.py"))
        stem = "/".join(parts)
        result.update(module_file(stem + ".py"))
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
                stem = keyword.value.value.replace(".", "/")
                leaves = module_file(stem + ".py") | module_file(stem + "/__init__.py")
                if not leaves:
                    raise ValueError("Registered report writer source is absent: " + keyword.value.value)
                seeds.update(owners)
                writers.update(leaves)  # A package initializer can itself be the registered writer.

    def authored(path):
        parts = PurePosixPath(path).parts
        return not any(part in {"tests", "test", "__tests__", "fixtures", ".venv", "node_modules"} for part in parts)

    def readonly_workbook_reader(nodes):
        """Closed read-only form, not a module-name exception or general purity proof.

        A report-library import alone remains conservative writer discovery unless
        all library bindings are direct load_workbook calls with literal read_only=True.
        Constructors, save operations, escapes and ambiguous bindings refuse that form.
        """
        bindings = set()
        for node in nodes:
            if isinstance(node, ast.Import) and any(alias.name.split(".")[0] in {"docx", "pptx", "openpyxl", "xlsxwriter"} for alias in node.names):
                return False
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in {"docx", "pptx", "openpyxl", "xlsxwriter"}:
                if node.module != "openpyxl" or any(alias.name != "load_workbook" for alias in node.names):
                    return False
                bindings.update(alias.asname or alias.name for alias in node.names)
        if not bindings:
            return False
        parents = {child: node for node in nodes for child in ast.iter_child_nodes(node)}
        called = set()
        for node in nodes:
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"save", "save_virtual_workbook", "Workbook", "Document", "Presentation"}:
                return False
            if isinstance(node, ast.Name) and node.id in bindings:
                parent = parents.get(node)
                if not (isinstance(node.ctx, ast.Load) and isinstance(parent, ast.Call) and parent.func is node
                        and not any(keyword.arg is None for keyword in parent.keywords)
                        and any(keyword.arg == "read_only" and isinstance(keyword.value, ast.Constant)
                                and keyword.value.value is True for keyword in parent.keywords)):
                    return False
                called.add(node.id)
            if isinstance(node, ast.arg) and node.arg in bindings:
                return False
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in bindings:
                return False
        return called == bindings

    production = {path for path in files if authored(path)}
    for path in production:
        nodes = list(ast.walk(tree(path)))
        report_library = False
        for node in nodes:
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            imports = [name.name for name in node.names] if isinstance(node, ast.Import) else []
            # API entries and report libraries are class-derived seeds. A closed
            # positive read-only workbook form is an engine input reader, not a writer.
            if ((module and module.split(".")[0] in {"fastapi", "starlette"})
                    or any(name.split(".")[0] in {"fastapi", "starlette"} for name in imports)):
                seeds.add(path)
                writers.add(path)
            if ((module and module.split(".")[0] in {"docx", "pptx", "openpyxl", "xlsxwriter"})
                    or any(name.split(".")[0] in {"docx", "pptx", "openpyxl", "xlsxwriter"} for name in imports)):
                report_library = True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("write_") and node.name.endswith(("_html", "_docx", "_pptx", "_xlsx")):
                seeds.add(path)
                writers.add(path)
        if report_library and not readonly_workbook_reader(nodes):
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
DIST_WORKFLOW = ".github/workflows/ci.yml"
DIST_GATE = "Prove the SPA build reproduced the immutable source"
DIST_COMMAND = ('python .github/scripts/verify_checkout_immutable.py '
                '--expected-commit "${{ steps.source.outputs.commit }}" '
                '--expected-tree "${{ steps.source.outputs.tree }}" '
                '--allow-untracked-prefix webapp/frontend/node_modules')


def compiled_coverage(names, read, generated=None):
    """Require the existing whole-checkout build proof before excluding imports.

    Every compiled entry stays inspected. The required Distribution contract
    compares all tracked bytes and refuses every unapproved output (ignored too).
    It therefore closes minified imports without ratcheting generated identities.
    """
    if generated is None:
        generated = {path for path in names if any(part in {"dist", "dist-hub", ".next"}
                     for part in PurePosixPath(path).parts[:-1])
                     and path.lower().endswith((*SCRIPT_SUFFIXES, *BROWSER_DOCUMENT_SUFFIXES))}
    if not generated:
        return set()
    uncovered = sorted(path for path in generated if not path.startswith(COMPILED_ROOT))
    if uncovered:
        raise ValueError("Compiled source has no source-to-dist gate: " + uncovered[0])
    import yaml
    workflow = yaml.safe_load(read(DIST_WORKFLOW))
    job = workflow["jobs"]["package"]
    steps = job["steps"]
    gates = [(index, step) for index, step in enumerate(steps) if step.get("name") == DIST_GATE]
    if len(gates) != 1:
        raise ValueError("Compiled source-to-dist gate is absent or ambiguous")
    index, gate = gates[0]
    builds = [(i, step) for i, step in enumerate(steps[:index])
              if step.get("name") == "Rebuild the bundled AssessHub SPA"]
    captures = [(i, step) for i, step in enumerate(steps[:index])
                if step.get("name") == "Capture the immutable source identity"]
    if (job.get("name") != "Distribution contract" or "if" in job or job.get("continue-on-error")
            or "if" in gate or gate.get("continue-on-error") or gate.get("run") != DIST_COMMAND
            or len(builds) != 1 or len(captures) != 1):
        raise ValueError("Compiled source-to-dist gate is not required after the bound build")
    build_index, build = builds[0]
    capture_index, capture = captures[0]
    if (build.get("working-directory") != "webapp/frontend" or "if" in build or build.get("continue-on-error")
            or build.get("run", "").split() != "npm run verify:node npm ci npm test npm run build".split()
            or capture_index >= build_index or capture.get("id") != "source" or "if" in capture
            or capture.get("continue-on-error")
            or "git rev-parse 'HEAD^{commit}'" not in capture.get("run", "")
            or "git rev-parse 'HEAD^{tree}'" not in capture.get("run", "")):
        raise ValueError("Compiled source-to-dist gate lost its immutable source/build binding")
    helper = ast.parse(read(".github/scripts/verify_checkout_immutable.py"))
    required = {"_verify_tracked_bytes", "_untracked_paths", "_checkout_observation", "verify_checkout"}
    if not required <= {node.name for node in helper.body if isinstance(node, ast.FunctionDef)}:
        raise ValueError("Compiled source-to-dist gate byte/inventory implementation is absent")
    return {path for path in names if path.startswith(COMPILED_ROOT)}
