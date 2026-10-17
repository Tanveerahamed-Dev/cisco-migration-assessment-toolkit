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


# Exact-site proposals for independent review, never whole-function exemptions.
# Targets are dependencies, not permission to omit their computation or direction.
# Strings normalize through the AST so comments/quote/spacing edits stay harmless.
WRITER_TARGETS = (
    "cisco_toolkit.engagement", "cisco_toolkit.crd", "cisco_toolkit.runbook",
    "cisco_toolkit.design", "cisco_toolkit.archreview", "cisco_toolkit.mop",
    "webapp.backend.cutover_docx", "webapp.backend.nrfu_docx", "cisco_toolkit.ops",
    "cisco_toolkit.deck", "webapp.backend.pir_docx",
)
DYNAMIC_IMPORT_ALLOWANCES = (
    ("cisco_toolkit/attestation.py", "_claim_read_only", "importlib.import_module(collector_module)", ("COLLECT_PARSE_V3_23_0",)),
    ("cisco_toolkit/attestation.py", "_claim_no_llm", "importlib.util.find_spec(collector_module)", ("COLLECT_PARSE_V3_23_0",)),
    ("webapp/backend/deliverables.py", "resolve_writer", "importlib.import_module(module_name)", WRITER_TARGETS),
    ("webapp/backend/deliverables.py", "_have", "importlib.util.find_spec(_LIB_MODULE[lib])", ("docx", "pptx")),
    ("cisco_toolkit/transition_runtime_inventory.py", "_find_distribution_import_root", "importlib.util.find_spec(package)", ("cryptography",)),
    ("tools/graphify_guarded.py", "_prepare_overlay", "import_module(EXTRACTOR_MODULE)", ("graphify.extractors.json_config",)),
    ("tools/graphify_guarded.py", "_prepare_overlay", "import_module(REPORT_MODULE)", ("graphify.report",)),
    ("tools/graphify_guarded.py", "_prepare_overlay", "import_module(WATCH_MODULE)", ("graphify.watch",)),
    ("tools/graphify_guarded.py", "_prepare_overlay", "importlib.util.spec_from_loader(EXTRACTOR_MODULE, loader=None, origin=str(source_path))", ("graphify.extractors.json_config",)),
    ("tools/graphify_guarded.py", "_prepare_overlay", "importlib.util.spec_from_loader(REPORT_MODULE, loader=None, origin=str(report_source_path))", ("graphify.report",)),
    ("tools/bind_atlas_r2_authority_decision.py", "_load_module", "importlib.util.spec_from_file_location(name, path)", ("tools.build_atlas_r2_authority_candidate", "cisco_toolkit.transition_contract")),
    ("tools/bind_atlas_r2_authority_decision.py", "_load_module", "importlib.util.module_from_spec(spec)", ("tools.build_atlas_r2_authority_candidate", "cisco_toolkit.transition_contract")),
    ("tools/bind_atlas_r2_authority_decision.py", "_load_module", "spec.loader.exec_module(module)", ("tools.build_atlas_r2_authority_candidate", "cisco_toolkit.transition_contract")),
    ("tools/generate_prior_database_fixture.py", "build_fixture", "importlib.util.spec_from_file_location('atlas_prior_storage_fixture', storage_path)", ("webapp.backend.storage",)),
    ("tools/generate_prior_database_fixture.py", "build_fixture", "importlib.util.module_from_spec(spec)", ("webapp.backend.storage",)),
    ("tools/generate_prior_database_fixture.py", "build_fixture", "spec.loader.exec_module(module)", ("webapp.backend.storage",)),
    ("webapp/frontend/e2e-real/serve_real_backend.py", "load_fixtures", "importlib.util.spec_from_file_location('_real_backend_e2e_synthetic_fixtures', path)", ("tests.synthetic_fixtures",)),
    ("webapp/frontend/e2e-real/serve_real_backend.py", "load_fixtures", "importlib.util.module_from_spec(spec)", ("tests.synthetic_fixtures",)),
    ("webapp/frontend/e2e-real/serve_real_backend.py", "load_fixtures", "spec.loader.exec_module(module)", ("tests.synthetic_fixtures",)),
)


def dynamic_imports(path, tree, allowances=DYNAMIC_IMPORT_ALLOWANCES):
    """Resolve named import forms, refusing opaque loads rather than dropping edges.

    This is a closed syntactic guard, not proof of absence of Python reflection.
    An allowance binds one path, enclosing symbol, normalized call and occurrence;
    its exact target modules still enter closure and engine direction validation.
    """
    bindings, scopes, assignments = {}, {}, []

    def visit(node, scope="<module>"):
        scopes[node] = scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = node.name if scope == "<module>" else scope + "." + node.name
        if isinstance(node, ast.Import):
            for alias in node.names:
                bindings.setdefault(alias.asname or alias.name.split(".")[0], []).append(alias.name if alias.asname else alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bindings.setdefault(alias.asname or alias.name, []).append((node.module or "") + "." + alias.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and node.value is not None:
                    assignments.append((target.id, node.value))
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree)
    # Break the recursive function-cell cycle: otherwise its scopes/assignments
    # retain the complete input AST until cyclic GC, after discovery returns.
    visit = None

    def qualified(node):
        if isinstance(node, ast.Name):
            return set(bindings.get(node.id, (node.id,)))
        if isinstance(node, ast.Attribute):
            # A factory/subscript receiver may be opaque while the import or
            # loader method is explicit. Never erase that known operation.
            return {base + "." + node.attr for base in qualified(node.value)} or {node.attr}
        if isinstance(node, ast.BoolOp):
            return {name for value in node.values for name in qualified(value)}
        if isinstance(node, ast.Subscript):
            return {base + ".<dynamic>" for base in qualified(node.value)}
        if isinstance(node, ast.Call) and qualified(node.func) & {"getattr", "builtins.getattr"} and node.args:
            attribute = node.args[1].value if len(node.args) == 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str) else "<dynamic>"
            return {base + "." + attribute for base in qualified(node.args[0])} or {attribute}
        if isinstance(node, ast.Call) and qualified(node.func) & {"vars", "builtins.vars"} and len(node.args) == 1:
            return {base + ".<dynamic>" for base in qualified(node.args[0])}
        return set()

    def kind(name):
        leaf = name.rsplit(".", 1)[-1]
        if leaf in {"import_module", "find_spec"}:
            return leaf
        if (leaf in {"__import__", "module_from_spec", "exec_module", "load_module"}
                or leaf.startswith("spec_from_") or leaf in {"SourceFileLoader", "SourcelessFileLoader", "ExtensionFileLoader", "zipimporter"}
                or name.startswith(("importlib.", "builtins.")) and "<dynamic>" in name):
            return "opaque"
        return None

    # Only importer/namespace aliases enter this finite fixed point. Ordinary
    # data bindings never recursively expand across a large engine's AST.
    canonical = {"import_module": "importlib.import_module", "find_spec": "importlib.util.find_spec", "opaque": "importlib.<dynamic>"}
    namespaces = {"importlib", "importlib.util", "importlib.machinery", "builtins", "getattr", "vars", "builtins.getattr", "builtins.vars"}
    changed = True
    while changed:
        changed = False
        for name, value in assignments:
            resolved = {canonical[kind(item)] if kind(item) else item for item in qualified(value) if kind(item) or item in namespaces}
            previous = set(bindings.get(name, ()))
            if resolved - previous:
                bindings[name] = sorted(previous | resolved)
                changed = True

    allowed = {}
    for owner, symbol, expression, targets in allowances:
        if owner == path:
            key = (symbol, ast.dump(ast.parse(expression, mode="eval").body))
            if key in allowed or not targets or any(not target or not all(part.isidentifier() for part in target.split(".")) for target in targets):
                raise ValueError("Invalid exact dynamic import allowance: " + path)
            allowed[key] = tuple(targets)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    occurrences = {}
    for node in calls:
        key = (scopes[node], ast.dump(node))
        occurrences[key] = occurrences.get(key, 0) + 1

    def static_target(node):
        # Expansions, duplicate/unknown arguments and computed names/packages are
        # never interpreted as no dependency, even for absolute module names.
        if len(node.args) > 2 or any(isinstance(arg, ast.Starred) for arg in node.args):
            return None
        arguments = dict(zip(("name", "package"), node.args))
        for keyword in node.keywords:
            if keyword.arg not in {"name", "package"} or keyword.arg in arguments:
                return None
            arguments[keyword.arg] = keyword.value
        if "name" not in arguments:
            return None
        name = arguments["name"]
        package = arguments.get("package", ast.Constant(None))
        if not isinstance(name, ast.Constant) or not isinstance(name.value, str) or not isinstance(package, ast.Constant):
            return None
        name, package = name.value, package.value
        if package is not None and (not isinstance(package, str) or not package or not all(part.isidentifier() for part in package.split("."))):
            return None
        if name.startswith("."):
            if not package:
                return None
            level = len(name) - len(name.lstrip("."))
            parts = package.split(".")
            if level > len(parts):
                return None
            name = ".".join([*parts[:len(parts) - level + 1], *([name[level:]] if name[level:] else [])])
        return name if name and all(part.isidentifier() for part in name.split(".")) else None

    result = set()
    for node in calls:
        kinds = {kind(name) for name in qualified(node.func)} - {None}
        if not kinds:
            continue
        target = static_target(node) if kinds <= {"import_module", "find_spec"} else None
        if target is not None:
            result.add(target)
            continue
        key = (scopes[node], ast.dump(node))
        if key not in allowed or occurrences[key] != 1:
            raise ValueError("Unresolved dynamic import: " + path + ":" + str(node.lineno) + " (" + scopes[node] + ")")
        result.update(allowed[key])
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)) and not isinstance(node.ctx, ast.Load):
            continue
        if not isinstance(node, (ast.Name, ast.Attribute, ast.Subscript, ast.Call)) or not any(kind(name) for name in qualified(node)):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Call) and parent.func is node:
            continue  # Already resolved or refused above.
        while isinstance(parent, (ast.Attribute, ast.BoolOp)):
            node, parent = parent, parents.get(parent)
        if isinstance(parent, (ast.Assign, ast.AnnAssign)) and parent.value is node:
            targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
            if all(isinstance(target, ast.Name) for target in targets):
                continue  # Named aliases are resolved at every use, not dropped.
        # An importer escaping as a value (map/callback/return/container) has no
        # statically bound invocation. Its enclosing call must be reviewed too.
        if isinstance(parent, ast.Call):
            key = (scopes[parent], ast.dump(parent))
            if key in allowed and occurrences[key] == 1:
                result.update(allowed[key])
                continue
        raise ValueError("Unresolved dynamic import reference: " + path + ":" + str(node.lineno))
    qualified = None  # Its recursive binding must not retain alias dictionaries.
    return result


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
        for module in dynamic_imports(path, tree(path)):
            dependencies.update(module_paths(module))
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
