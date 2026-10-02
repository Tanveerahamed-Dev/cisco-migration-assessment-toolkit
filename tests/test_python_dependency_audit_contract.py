"""The required Dependency audit covers every tracked Python requirements file, lock and pyproject declaration it
can reach, and every one of its audits can fail.

The npm half of the job is pinned by test_frontend_platform_contract.py, which derives every tracked lockfile from
`git ls-files`. Until 2026-10-02 the Python half audited only the installed `.[dev]` environment, so the Master
Reference release toolchain, the hash-locked set that ships inside Atlas.exe, the transition runtime pins, the
`mcp`/`eval` extras and `wheel` from `[build-system].requires` were never audited by a required check. Seven high
pypdf advisories in master-reference/requirements-release.txt were found by Dependabot, not by this gate.

Two properties are enforced, both fail-closed:
- COVERAGE. The denominator is every tracked file a Python installer or locker can read: classified by name, plus
  every tracked file a workflow or a requirements file passes to `-r`/`-c`. A file or pyproject table with no audit
  form here is a gap, never a skip. A declaration whose environment marker is false on the audit runner must be
  pinned by an audited lock or be a reviewed entry in NAMED_MARKER_GATED_LIMITS. What is still uncovered is named in
  NAMED_COVERAGE_LIMITS, so no surface claims more.
- BLOCKING. The workflow is read with a YAML loader that rejects duplicate keys, so the grammar applies to what the
  runner executes. Each audit step runs exactly one allowlisted command under `if: ${{ !cancelled() }}` (so one
  failing manifest does not hide the other Python verdicts); the environment audit directly follows the install it
  audits; and no other step may write the runner environment or name an audited manifest in its run text.

Threat model: this guards against an editor accidentally losing coverage or blocking. It is not a sandbox against a
malicious committer, who could edit this test as easily as the workflow; branch protection and review own that.
"""

from __future__ import annotations

import functools
import posixpath
import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml
from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI lane
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
CI_PATH = ".github/workflows/ci.yml"
AUDIT_JOB = "dependency-audit"
AUDIT_JOB_NAME = "Dependency audit"
PROJECT_DISTRIBUTION = "cisco-migration-assessment-toolkit"
PIP_AUDIT_REQUIREMENT = "pip-audit>=2.9,<3"
ENVIRONMENT = "<installed environment>"
RUN_UNLESS_CANCELLED = "!cancelled()"
UNINSTALL_PROJECT = f"python -m pip uninstall --yes {PROJECT_DISTRIBUTION}"
BUILD_TRIO = ("pip", "setuptools", "wheel")

# The audit job's interpreter: actions/setup-python 3.12 on ubuntu-latest. Markers are evaluated against it.
AUDIT_MARKER_ENVIRONMENT = {
    **default_environment(),
    "implementation_name": "cpython", "platform_python_implementation": "CPython", "os_name": "posix",
    "sys_platform": "linux", "platform_system": "Linux", "platform_machine": "x86_64",
    "python_version": "3.12", "python_full_version": "3.12.0", "implementation_version": "3.12.0",
}

# A vulnerability id may be ignored only on the one audit target named here (a manifest path, or ENVIRONMENT).
# A new suppression is a reviewed edit to this registry, with its reason, never a flag added to the workflow alone.
NAMED_PIP_AUDIT_SUPPRESSIONS = {
    # The shipped Atlas lock still pins paramiko 4.0.0 under netmiko 4.7.0. netmiko 4.8.0 (2026-09-21) lifted its
    # paramiko<5 cap, so the fix is a re-lock, which re-qualifies the portable release contract. The floating
    # environment already resolves paramiko 5.0.0 and is audited with no suppression.
    "PYSEC-2026-2858": "portable/windows-x64-requirements.lock",
}

# Declarations whose marker is false on the audit runner and that no audited lock pins. Each entry is reviewed; a
# new marker-gated declaration fails until it is covered or listed here, and a stale entry fails too.
NAMED_MARKER_GATED_LIMITS = {
    "tomli": "python_version < '3.11': installed only on the Python 3.10 test lane; no audited set resolves for 3.10",
}

# What this contract does not cover, stated so that no surface claims more.
NAMED_COVERAGE_LIMITS = (
    "inline `pip install` pins in .github/workflows/*.yml (graph, build and publish tooling)",
    "a requirements file named outside the classifier and passed to pip only by a script, not by a tracked workflow"
    " or another requirements file",
    "a non-audit step's effect through a helper script or a working directory: only its inline run text is read",
    "marker-gated declarations listed in NAMED_MARKER_GATED_LIMITS",
    "Windows-only transitive dependencies of the floating environment and the ranged requirements files (for example"
    " colorama, pywin32): every resolving audit runs on the Linux runner, and the shipped Windows lock does not pin them",
)

# Lockfile names owned by other ecosystems. Any other `*.lock` must be a pip-compile or uv lock audited here.
NON_PYTHON_LOCK_NAMES = frozenset(name.lower() for name in (
    "yarn.lock", "bun.lock", "Cargo.lock", "Gemfile.lock", "composer.lock", "flake.lock", "mix.lock",
    "pubspec.lock", "Podfile.lock",
))
# pyproject tool tables through which uv, Poetry, PDM or Hatch install dependencies this audit never reads.
DEPENDENCY_TOOL_TABLES = ("uv", "poetry", "pdm", "hatch")
# Workflow- or job-level variables that change what pip resolves or what pip-audit reads.
_RESOLUTION_ENV = re.compile(
    r"(?i)(?:PIP_(?:INDEX_URL|EXTRA_INDEX_URL|FIND_LINKS|NO_INDEX|CONSTRAINT|REQUIREMENT|NO_DEPS|TARGET|PREFIX|ROOT"
    r"|USER|CONFIG_FILE|ONLY_BINARY|NO_BINARY|REQUIRE_HASHES|IGNORE_INSTALLED|UPGRADE)|PIP_AUDIT_.*|PYTHONHOME"
    r"|PYTHONSTARTUP|PYTHONUSERBASE|PYTHONNOUSERSITE|PYTHONSAFEPATH|VIRTUAL_ENV|UV_.*|.*PATH)")
_DECLARATION_SUFFIXES = (".lock", ".txt", ".in", ".pip")
_REQUIREMENTS_NAME = re.compile(r"(?i)[^/]*(?:requirement|constraint|reqs|deps)[^/]*\.(?:txt|in|pip)")
_REQUIREMENTS_DIR = re.compile(r"(?i)(?:^|/)(?:requirements?|constraints?|reqs|deps)/[^/]+\.(?:txt|in|pip)$")
_UNSUPPORTED_NAME = re.compile(r"(?i)(?:Pipfile|Pipfile\.lock|pylock(?:\.[^/]*)?\.toml)")
_LOCK_HEADER = re.compile(r"(?i)autogenerated by (?:pip-compile|uv)")
_SETUP_DECLARATIONS = re.compile(r"\b(?:install_requires|setup_requires|extras_require|tests_require)\b")
_EDITABLE_PROJECT = re.compile(r"-e\s+\.(?:\[([A-Za-z0-9_,\-\s]*)\])?")
# Writes that change what later steps' pip or pip-audit see: the runner's environment files and pip's configuration.
_RUNNER_ENVIRONMENT_FILES = re.compile(r"GITHUB_ENV|GITHUB_PATH|PIP_CONFIG_FILE|pip\.conf|pip\.ini|\bpip\d*(?:\.\d+)?\s+config\b")
_FILE_OPTION = re.compile(r"""(?:^|\s)(?:-r|--requirement|-c|--constraint)(?:\s+|=)["']?([^\s"']+)""")


class _StrictLoader(yaml.SafeLoader):
    """A SafeLoader that refuses duplicate mapping keys, which plain YAML loaders resolve silently (last one wins)."""


def _mapping_without_duplicates(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", key_node.start_mark)
        seen.add(key)
    return loader.construct_mapping(node, deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_without_duplicates)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _extras(group: str | None) -> set[str]:
    return {_norm(extra.strip()) for extra in (group or "").split(",") if extra.strip()}


def _requirement_lines(text: str) -> list[str]:
    return [line for line in (raw.split(" #", 1)[0].strip() for raw in text.splitlines())
            if line and not line.startswith("#")]


def _canonical(spec: str) -> str:
    try:
        return str(Requirement(spec))
    except InvalidRequirement:
        return spec


def _condition(value) -> str:
    text = str(value).strip()
    match = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", text)
    return re.sub(r"\s+", "", match.group(1) if match else text)


def _path(target: str) -> str:
    return posixpath.normpath(target.replace("\\", "/"))


def _classify(path: str, text: str) -> str | None:
    """The kind of Python dependency declaration a tracked file is, or None when it is not one."""
    name = path.rsplit("/", 1)[-1]
    if name == "pyproject.toml":
        return "pyproject"
    if name in ("setup.py", "setup.cfg"):
        return "setup"
    if _UNSUPPORTED_NAME.fullmatch(name):
        return "unsupported"
    if name.lower().endswith(".lock"):
        if name.lower() in NON_PYTHON_LOCK_NAMES:
            return None
        return "requirements" if _LOCK_HEADER.search(text[:4096]) else "unsupported"
    if _REQUIREMENTS_NAME.fullmatch(name) or _REQUIREMENTS_DIR.search(path):
        return "requirements"
    return None


def _tracked(root: Path) -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True, timeout=120)
    return [path for path in listed.stdout.decode("utf-8").split("\0") if path]


def _tracked_declarations(root: Path, tracked: list[str]) -> dict[str, str]:
    """Every tracked file the classifier recognises, with its text; the denominator comes from git."""
    files = {}
    for path in tracked:
        name = path.rsplit("/", 1)[-1]
        if (name in ("pyproject.toml", "setup.py", "setup.cfg") or name.lower().endswith(_DECLARATION_SUFFIXES)
                or _UNSUPPORTED_NAME.fullmatch(name)):
            text = (root / path).read_text(encoding="utf-8", errors="replace")
            if _classify(path, text):
                files[path] = text
    return files


def _tracked_workflows(root: Path, tracked: list[str]) -> dict[str, str]:
    return {path: (root / path).read_text(encoding="utf-8") for path in tracked
            if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))}


def _commands(run: str) -> list[str]:
    joined = re.sub(r"\\\n\s*", " ", run)
    return [line.strip() for line in joined.splitlines() if line.strip()]


def _audit_options(words: list[str]) -> tuple[dict, list[str]]:
    """Read pip_audit's arguments under the allowlist; every other word is a problem."""
    options = {"strict": 0, "targets": [], "disable_pip": 0, "ignores": []}
    problems = []
    index = 3
    while index < len(words):
        word = words[index]
        if word == "--strict":
            options["strict"] += 1
        elif word == "--disable-pip":
            options["disable_pip"] += 1
        elif word == "--progress-spinner" and index + 1 < len(words) and words[index + 1] == "off":
            index += 1
        elif word in ("-f", "--format", "-o", "--output") and index + 1 < len(words):
            index += 1  # a report format or file changes what is written, never what is audited or the exit code
        elif word in ("-r", "--requirement", "--ignore-vuln") and index + 1 < len(words):
            index += 1
            if word == "--ignore-vuln":
                options["ignores"].append(words[index])
            else:
                options["targets"].append(_path(words[index]))
        else:
            problems.append(f"pip_audit carries a word outside the allowlist: {word!r}")
        index += 1
    return options, problems


def _manifest_requirements(text: str) -> list[Requirement]:
    """The requirement lines of a requirements file or lock (options, hashes and comments are not requirements)."""
    found = []
    for line in _requirement_lines(text):
        line = line.rstrip("\\").strip()
        if not line or line.startswith("-"):
            continue
        try:
            found.append(Requirement(line))
        except InvalidRequirement:
            continue
    return found


def _skipped_on_runner(requirement: Requirement) -> bool:
    """pip-audit drops a requirement whose marker is false where it runs, silently and even under --strict."""
    return requirement.marker is not None and not requirement.marker.evaluate(AUDIT_MARKER_ENVIRONMENT)


def _lock_pins(text: str) -> dict[str, str]:
    """Exact pins the audit really sees: a pin whose marker is false on the audit runner is not coverage."""
    pins = {}
    for requirement in _manifest_requirements(text):
        exact = [spec for spec in requirement.specifier if spec.operator == "=="]
        if len(exact) == 1 and not _skipped_on_runner(requirement):
            pins[_norm(requirement.name)] = exact[0].version
    return pins


def _python_audit_gaps(ci: str, files: dict[str, str], workflows: dict[str, str], tracked: set[str]) -> list[str]:
    """Every way the Python audit fails to cover the reachable declarations or fails to block; empty when sound.

    `ci` is .github/workflows/ci.yml's text, `files` the classified declarations, `workflows` every tracked workflow's
    text, and `tracked` every tracked path."""
    gaps: list[str] = []
    try:
        document = yaml.load(ci, Loader=_StrictLoader) or {}
    except yaml.YAMLError as error:
        return [f"{CI_PATH} is not a strict YAML document: {error}"]

    if "defaults" in document:
        gaps.append("the workflow sets top-level `defaults`, which can change how every audit runs")
    for key in document.get("env") or {}:
        if _RESOLUTION_ENV.fullmatch(str(key)):
            gaps.append(f"the workflow-level env sets {key}, which changes what pip resolves or pip_audit reads")
    job = (document.get("jobs") or {}).get(AUDIT_JOB)
    if not isinstance(job, dict):
        return gaps + [f"{CI_PATH} has no {AUDIT_JOB} job"]
    unexpected = set(job) - {"name", "runs-on", "steps", "timeout-minutes", "permissions"}
    if unexpected:
        gaps.append(f"the {AUDIT_JOB} job sets {sorted(unexpected)}")
    if job.get("name") != AUDIT_JOB_NAME or job.get("runs-on") != "ubuntu-latest":
        gaps.append(f"the {AUDIT_JOB} job is not named {AUDIT_JOB_NAME!r} on ubuntu-latest")
    holders, referenced = [], set()
    for path, text in {**{p: t for p, t in workflows.items() if p != CI_PATH}, CI_PATH: ci}.items():
        referenced.update(_path(target) for target in _FILE_OPTION.findall(text) if "$" not in target)
        try:
            other = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            continue
        for job_id, body in (other.get("jobs") or {}).items():
            if isinstance(body, dict) and body.get("name") == AUDIT_JOB_NAME:
                holders.append(f"{path}:{job_id}")
    if holders != [f"{CI_PATH}:{AUDIT_JOB}"]:
        gaps.append(f"the required check name {AUDIT_JOB_NAME!r} must belong to exactly this job: {holders}")
    for path, text in files.items():
        for target in _FILE_OPTION.findall(text):
            referenced.add(_path(posixpath.join(posixpath.dirname(path), target)))
    for target in sorted(referenced & tracked):
        if target not in files or _classify(target, files[target]) != "requirements":
            gaps.append(f"{target} is passed to pip as a requirements file but the classifier does not recognise it")

    pyprojects = {path: tomllib.loads(text) for path, text in files.items() if _classify(path, text) == "pyproject"}
    root_project = pyprojects.get("pyproject.toml", {})
    build_requires = sorted(_canonical(spec) for spec in root_project.get("build-system", {}).get("requires", []))
    environment_pins = {_norm(Requirement(spec).name): str(next(iter(Requirement(spec).specifier)).version)
                        for spec in build_requires if len(Requirement(spec).specifier) == 1
                        and next(iter(Requirement(spec).specifier)).operator == "=="}

    installed: set[str] | None = None
    environment_index = install_index = None
    audited: dict[str, list[dict]] = {}
    for index, step in enumerate(job.get("steps") or []):
        if not isinstance(step, dict):
            gaps.append(f"step {index} is not a mapping")
            continue
        run = step.get("run")
        run_text = run if isinstance(run, str) else ""
        if _RUNNER_ENVIRONMENT_FILES.search(run_text):
            gaps.append(f"step {index} writes the runner environment ($GITHUB_ENV/$GITHUB_PATH)")
        bearing = re.search(r"(?i)pip[_-]audit", run_text) or re.search(r"pip\s+install\b[^\n]*\s-e\b", run_text)
        if not bearing:
            named = sorted(path for path in files if path in run_text or re.search(
                rf"(?<![\w./-]){re.escape(path.rsplit('/', 1)[-1])}(?![\w.-])", run_text))
            if named:
                gaps.append(f"non-audit step {index} names audited declarations {named}")
            continue
        try:
            commands = _commands(run_text)
            first = shlex.split(commands[0]) if commands else []
        except ValueError as error:
            gaps.append(f"audit-bearing step {index} cannot be split into words: {error}")
            continue
        installing = first[:4] == ["python", "-m", "pip", "install"]
        required = {"name", "run"} if installing else {"name", "run", "if"}
        if not required <= set(step) or set(step) - required - {"id"}:
            gaps.append(f"audit-bearing step {index} must carry {sorted(required)} (and optionally id), not {sorted(step)}")
        if not installing and _condition(step.get("if", "")) != RUN_UNLESS_CANCELLED:
            gaps.append(f"audit step {index} must run under `if: ${{{{ {RUN_UNLESS_CANCELLED} }}}}`: {step.get('if')!r}")
        if installing:
            if install_index is not None:
                gaps.append("the project is installed by more than one step")
            install_index = index
            rest = first[4:]
            if len(commands) != 1 or rest.count("-e") != 1 or rest.index("-e") + 1 >= len(rest):
                gaps.append(f"the project install is not one command with one `-e`: {commands}")
                installed = set()
                continue
            at = rest.index("-e")
            match = re.fullmatch(r"\.(?:\[([A-Za-z0-9_,\-\s]*)\])?", rest[at + 1])
            installed = _extras(match.group(1)) if match else set()
            if not match:
                gaps.append(f"the editable install is not this project: {rest[at + 1]!r}")
            others = sorted(_canonical(word) for word in rest[:at] + rest[at + 2:])
            if others != sorted(build_requires + [_canonical(PIP_AUDIT_REQUIREMENT)]):
                gaps.append(f"the install's other words {others} are not [build-system].requires {build_requires} "
                            f"plus {PIP_AUDIT_REQUIREMENT}")
            continue
        try:
            if len(commands) == 2 and commands[0] == UNINSTALL_PROJECT:
                words, target = shlex.split(commands[1]), ENVIRONMENT
            elif len(commands) == 1:
                words, target = first, None
            else:
                gaps.append(f"audit-bearing step {index} is not one allowlisted command: {commands}")
                continue
        except ValueError as error:
            gaps.append(f"audit-bearing step {index} cannot be split into words: {error}")
            continue
        if words[:3] != ["python", "-m", "pip_audit"]:
            gaps.append(f"audit-bearing step {index} does not run `python -m pip_audit`: {words[:3]}")
            continue
        options, problems = _audit_options(words)
        gaps.extend(problems)
        if options["strict"] != 1:
            gaps.append(f"pip_audit must carry --strict exactly once: {' '.join(words)}")
        if target == ENVIRONMENT:
            if options["targets"] or options["disable_pip"]:
                gaps.append("the environment audit names a requirements file")
            if environment_index is not None:
                gaps.append("more than one environment audit")
            environment_index = index
        elif len(options["targets"]) != 1:
            gaps.append(f"a requirements audit must name exactly one manifest: {options['targets']}")
            continue
        else:
            target = options["targets"][0]
            audited.setdefault(target, []).append(options)
            text = files.get(target, "")
            if bool(options["disable_pip"]) != ("--hash=" in text) or options["disable_pip"] > 1:
                gaps.append(f"{target}: --disable-pip must be used exactly when the file is hash-locked")
            if not options["disable_pip"]:
                # A resolving audit pre-installs the latest pip/setuptools/wheel and reports only what would change,
                # so such a pin is covered only when the environment audit installs the same version.
                for name, version in _lock_pins(text).items():
                    if name in BUILD_TRIO and environment_pins.get(name) != version:
                        gaps.append(f"{target} pins {name}=={version}, which its resolving audit cannot see and the "
                                    f"environment does not install")
        for vuln in options["ignores"]:
            owner = NAMED_PIP_AUDIT_SUPPRESSIONS.get(vuln)
            if owner is None:
                gaps.append(f"{vuln} is ignored but is not a named suppression")
            elif owner != target:
                gaps.append(f"{vuln} is ignored on {target}, but its named target is {owner}")

    if install_index is None or installed is None:
        return gaps + ["no step installs the project for the environment audit"]
    if environment_index is None:
        return gaps + ["no installed-environment pip_audit"]
    if environment_index != install_index + 1:
        gaps.append("the environment audit must directly follow the install it audits; a step between them can "
                    "change the environment")

    compiled: dict[str, dict[str, dict[str, str]]] = {}
    audited_pins: dict[str, str] = {}
    marker_gated: set[str] = set()
    for path, text in sorted(files.items()):
        kind = _classify(path, text)
        if kind == "unsupported":
            gaps.append(f"{path} is a Python dependency declaration with no audit form here")
        elif kind == "setup" and _SETUP_DECLARATIONS.search(text):
            gaps.append(f"{path} declares dependencies outside pyproject.toml, which no audit reads")
        elif kind == "requirements":
            lines = _requirement_lines(text)
            editable = [_EDITABLE_PROJECT.fullmatch(line) for line in lines]
            if lines and all(editable):
                missing = set().union(*(_extras(m.group(1)) for m in editable)) - installed
                if missing:
                    gaps.append(f"{path} installs the project with {sorted(missing)}, which the audited environment lacks")
                continue
            if len(audited.get(path, [])) != 1:
                gaps.append(f"{path} is audited {len(audited.get(path, []))} times, not once")
                continue
            for requirement in _manifest_requirements(text):
                if _skipped_on_runner(requirement):
                    name = _norm(requirement.name)
                    marker_gated.add(name)
                    if name not in NAMED_MARKER_GATED_LIMITS:
                        gaps.append(f"{path} pins {requirement}, which its audit skips silently on the Linux runner")
            header = text[:4096]
            if _LOCK_HEADER.search(header):
                audited_pins.update(_lock_pins(text))
                for source in pyprojects:
                    if re.search(rf"(?m)^#.*(?<!\S){re.escape(source)}(?!\S)", header):
                        for extra in re.findall(r"--extra[= ]([A-Za-z0-9_\-]+)", header):
                            compiled.setdefault(source, {})[_norm(extra)] = _lock_pins(text)
    for target in audited:
        if target not in files or _classify(target, files[target]) != "requirements":
            gaps.append(f"{target} is audited but is not a tracked requirements manifest")

    for path, project in sorted(pyprojects.items()):
        if path != "pyproject.toml":
            gaps.append(f"{path} is a nested project with no audit form here")
            continue
        if project.get("dependency-groups"):
            gaps.append(f"{path} declares [dependency-groups], which no audit installs")
        for table in DEPENDENCY_TOOL_TABLES:
            if table in project.get("tool", {}):
                gaps.append(f"{path} declares [tool.{table}], whose dependencies no audit reads")
        declared = project.get("project", {})
        optional = {_norm(extra): specs for extra, specs in declared.get("optional-dependencies", {}).items()}
        environment_specs = list(declared.get("dependencies", [])) + [
            spec for extra in installed for spec in optional.get(extra, [])]
        for spec in environment_specs:
            try:
                requirement = Requirement(spec)
            except InvalidRequirement:
                gaps.append(f"{path} has an unparseable requirement {spec!r}")
                continue
            if requirement.marker is not None and not requirement.marker.evaluate(AUDIT_MARKER_ENVIRONMENT):
                name = _norm(requirement.name)
                if name in audited_pins:
                    continue
                marker_gated.add(name)
                if name not in NAMED_MARKER_GATED_LIMITS:
                    gaps.append(f"{path} declares {spec!r}, which the audit runner never installs and no audited "
                                f"lock pins")
        for extra, requirements in sorted(optional.items()):
            if not requirements or extra in installed:
                continue
            pins = compiled.get(path, {}).get(extra)
            if pins is None:
                gaps.append(f"{path} extra [{extra}] is audited neither in the environment nor through an audited lock")
                continue
            for spec in requirements:
                try:
                    requirement = Requirement(spec)
                except InvalidRequirement:
                    gaps.append(f"{path} extra [{extra}] has an unparseable requirement {spec!r}")
                    continue
                version = pins.get(_norm(requirement.name))
                if requirement.marker is not None:
                    gaps.append(f"{path} extra [{extra}] requirement {spec!r} has a marker the lock check cannot evaluate")
                elif version is None:
                    gaps.append(f"{path} extra [{extra}] names {requirement.name}, which its audited lock does not pin")
                elif not requirement.specifier.contains(version, prereleases=True):
                    gaps.append(f"{path} extra [{extra}] requires {spec!r}, but its audited lock pins {version}")
    for name in sorted(set(NAMED_MARKER_GATED_LIMITS) - marker_gated):
        gaps.append(f"NAMED_MARKER_GATED_LIMITS lists {name}, which is no longer an uncovered marker-gated declaration")
    return gaps


@functools.cache
def _repository_inputs():
    tracked = _tracked(ROOT)
    return ((ROOT / CI_PATH).read_text(encoding="utf-8"), _tracked_declarations(ROOT, tracked),
            _tracked_workflows(ROOT, tracked), set(tracked))


def test_the_denominator_is_derived_from_git_and_is_not_empty():
    _, files, workflows, tracked = _repository_inputs()
    # Positive controls, so a derivation that silently found nothing cannot pass the coverage test below.
    for expected in ("pyproject.toml", "setup.py", "requirements.txt", "master-reference/requirements-release.txt",
                     "portable/windows-x64-requirements.lock"):
        assert expected in files, sorted(files)
    assert CI_PATH in workflows and CI_PATH in tracked, sorted(workflows)


def test_dependency_audit_audits_every_reachable_python_declaration_and_every_audit_can_fail():
    assert _python_audit_gaps(*_repository_inputs()) == []


def _step_insert(ci: str, step_name: str, extra_line: str) -> str:
    anchor = f"      - name: {step_name}\n"
    assert anchor in ci, step_name
    return ci.replace(anchor, anchor + extra_line, 1)


def _replace_condition(ci: str, step_name: str, new: str) -> str:
    old = f"      - name: {step_name}\n        if: ${{{{ !cancelled() }}}}\n"
    assert old in ci, step_name
    return ci.replace(old, f"      - name: {step_name}\n        {new}\n", 1)


def _before_step(ci: str, step_name: str, block: str) -> str:
    anchor = f"      - name: {step_name}\n"
    assert anchor in ci, step_name
    return ci.replace(anchor, block + anchor, 1)


_WEBAPP_RUN = "        run: python -m pip_audit --strict -r webapp/requirements.txt\n"
_PIP_COMPILE_HEADER = ("#\n# This file is autogenerated by pip-compile with Python 3.12\n# by the following command:\n#\n"
                       "#    pip-compile --generate-hashes --output-file=x.lock pyproject.toml\n#\n")


def _ci(fn):
    return lambda ci, f, w, t: (fn(ci), f, w, t)


def _files(fn):
    return lambda ci, f, w, t: (ci, fn(dict(f)), w, t)


def _pyproject(old: str, new: str):
    def edit(f):
        assert old in f["pyproject.toml"], old
        return {**f, "pyproject.toml": f["pyproject.toml"].replace(old, new, 1)}
    return _files(edit)


_MUTATIONS = {
    # coverage: the denominator
    "drop_release_audit": _ci(lambda ci: "\n".join(line for line in ci.splitlines()
                                                   if "-r master-reference/requirements-release.txt" not in line)),
    "new_requirements_file": _files(lambda f: {**f, "tools/requirements-new.txt": "example==1.0\n"}),
    "dev_requirements_name": _files(lambda f: {**f, "dev-requirements.txt": "example==1.0\n"}),
    "singular_requirement_name": _files(lambda f: {**f, "requirementsdev.txt": "example==1.0\n"}),
    "pip_suffix": _files(lambda f: {**f, "requirements.pip": "example==1.0\n"}),
    "requirements_directory": _files(lambda f: {**f, "requirements/base.txt": "example==1.0\n"}),
    "reqs_directory": _files(lambda f: {**f, "reqs/dev.txt": "example==1.0\n"}),
    "constraints_file": _files(lambda f: {**f, "constraints.txt": "example==1.0\n"}),
    "requirements_in": _files(lambda f: {**f, "tools/x/requirements.in": "example>=1\n"}),
    "workflow_references_unclassified_file": lambda ci, f, w, t: (
        ci, f, {**w, ".github/workflows/tools.yml": "jobs:\n  t:\n    steps:\n      - run: pip install -r tools/ci-tools.txt\n"},
        t | {"tools/ci-tools.txt"}),
    "requirements_file_includes_unclassified_file": lambda ci, f, w, t: (
        ci, {**f, "webapp/requirements.txt": f["webapp/requirements.txt"] + "-r ../tools/ci-tools.txt\n"}, w,
        t | {"tools/ci-tools.txt"}),
    "pipfile_lock": _files(lambda f: {**f, "Pipfile.lock": "{}\n"}),
    "pylock": _files(lambda f: {**f, "pylock.toml": "lock-version = '1.0'\n"}),
    "unknown_lock_format": _files(lambda f: {**f, "x/requirements.lock": "# generated by hand\nexample==1.0\n"}),
    "lock_header_inside_window_unaudited": _files(lambda f: {**f, "late/header.lock": "#" * 700 + "\n" + _PIP_COMPILE_HEADER
                                                            + "example==1.0 \\\n    --hash=sha256:00\n"}),
    "lock_header_past_window": _files(lambda f: {**f, "late/far.lock": "#" * 5000 + "\n" + _PIP_COMPILE_HEADER
                                                + "example==1.0 \\\n    --hash=sha256:00\n"}),
    "nested_pyproject": _files(lambda f: {**f, "tools/sub/pyproject.toml": "[project]\nname = 'x'\ndependencies = ['example==1.0']\n"}),
    "dependency_groups": _files(lambda f: {**f, "pyproject.toml": f["pyproject.toml"] + "\n[dependency-groups]\nlint = ['example==1.0']\n"}),
    "tool_uv_dev_dependencies": _files(lambda f: {**f, "pyproject.toml": f["pyproject.toml"] + "\n[tool.uv]\ndev-dependencies = ['example==1.0']\n"}),
    "tool_poetry_group": _files(lambda f: {**f, "pyproject.toml": f["pyproject.toml"] + "\n[tool.poetry.group.dev.dependencies]\nexample = '1.0'\n"}),
    "setup_install_requires": _files(lambda f: {**f, "setup.py": "from setuptools import setup\nsetup(install_requires=['example'])\n"}),
    "stale_audit_step": _files(lambda f: {k: v for k, v in f.items() if k != "webapp/requirements.txt"}),
    # coverage: what the environment and the lock carry
    "extra_not_installed": _ci(lambda ci: ci.replace(',eval]"', ']"', 1)),
    "build_requires_dropped": _ci(lambda ci: ci.replace('"wheel==0.48.0" ', "", 1)),
    "build_requires_drift": _pyproject('requires = ["setuptools==84.0.0", "wheel==0.48.0"]',
                                       'requires = ["setuptools==84.0.0", "wheel==0.48.0", "example==1.0"]'),
    "build_extra_outgrows_lock": _pyproject('build = ["pip==26.2.1",', 'build = ["example==1.0", "pip==26.2.1",'),
    "build_extra_pin_downgraded": _pyproject('build = ["pip==26.2.1",', 'build = ["pip==20.0",'),
    "editable_extra_missing": _files(lambda f: {**f, "requirements-docs.txt": "-e .[docs]\n", "pyproject.toml": f["pyproject.toml"].replace(
        "[project.optional-dependencies]\n", '[project.optional-dependencies]\ndocs = ["example>=1,<2"]\n', 1)}),
    "marker_gated_base_dependency": _pyproject('    "netmiko>=4.1,<5",\n', '    "netmiko>=4.1,<5",\n    "exceptiongroup>=1,<2; python_version < \'3.11\'",\n'),
    "marker_gated_installed_extra": _pyproject('    "setuptools==84.0.0",\n', '    "setuptools==84.0.0",\n    "pywin32>=306; sys_platform == \'win32\'",\n'),
    "stale_marker_limit": _pyproject('    "tomli>=2,<3; python_version < \'3.11\'",\n', ""),
    "lock_pin_marker_false_on_runner": _files(lambda f: {**f, "portable/windows-x64-requirements.lock": f[
        "portable/windows-x64-requirements.lock"] + 'example==1.0 ; sys_platform == "win32" \\\n    --hash=sha256:00\n'}),
    "ranged_line_marker_false_on_runner": _files(lambda f: {**f, "webapp/requirements.txt": f["webapp/requirements.txt"]
                                                            + "pywin32>=306; sys_platform == 'win32'\n"}),
    "windows_only_dependency_relocked": _files(lambda f: {
        **f,
        "pyproject.toml": f["pyproject.toml"].replace('    "netmiko>=4.1,<5",\n',
                                                      '    "netmiko>=4.1,<5",\n    "example>=1,<2; sys_platform == \'win32\'",\n', 1),
        "portable/windows-x64-requirements.lock": f["portable/windows-x64-requirements.lock"]
        + 'example==1.0 ; sys_platform == "win32" \\\n    --hash=sha256:00\n'}),
    "resolving_audit_trio_pin": _files(lambda f: {**f, "tools/requirements-transition-runtime-test.txt": f[
        "tools/requirements-transition-runtime-test.txt"].replace("setuptools==84.0.0", "setuptools==99.0.0", 1)}),
    "combined_resolution": _ci(lambda ci: ci.replace("-r requirements.txt", "-r requirements.txt -r webapp/requirements.txt", 1)),
    # blocking: the audit command
    "unnamed_ignore": _ci(lambda ci: ci.replace("-r webapp/requirements.txt", "-r webapp/requirements.txt --ignore-vuln GHSA-0000-0000-0000", 1)),
    "named_ignore_elsewhere": _ci(lambda ci: ci.replace("-r webapp/requirements.txt", "-r webapp/requirements.txt --ignore-vuln PYSEC-2026-2858", 1)),
    "ignore_vuln_equals": _ci(lambda ci: ci.replace("-r webapp/requirements.txt", "-r webapp/requirements.txt --ignore-vuln=GHSA-0000-0000-0000", 1)),
    "no_strict": _ci(lambda ci: ci.replace("pip_audit --strict -r requirements.txt", "pip_audit -r requirements.txt", 1)),
    "lock_resolved_by_pip": _ci(lambda ci: ci.replace("--disable-pip ", "", 1)),
    "pinned_file_disables_pip": _ci(lambda ci: ci.replace("--strict -r webapp/requirements.txt", "--strict --disable-pip -r webapp/requirements.txt", 1)),
    "requirement_equals": _ci(lambda ci: ci.replace("-r webapp/requirements.txt", "--requirement=webapp/requirements.txt", 1)),
    "dry_run": _ci(lambda ci: ci.replace("-r webapp/requirements.txt", "--dry-run -r webapp/requirements.txt", 1)),
    "environment_path": _ci(lambda ci: ci.replace("python -m pip_audit --strict\n", "python -m pip_audit --strict --path /tmp/empty\n", 1)),
    "masked_exit": _ci(lambda ci: ci.replace("-r webapp/requirements.txt", "-r webapp/requirements.txt || true", 1)),
    "piped_exit": _ci(lambda ci: ci.replace("-r webapp/requirements.txt", "-r webapp/requirements.txt | tee audit.txt", 1)),
    "dollar_flags": _ci(lambda ci: ci.replace("-r webapp/requirements.txt", "-r webapp/requirements.txt $AUDIT_FLAGS", 1)),
    "echo_prefix": _ci(lambda ci: ci.replace("run: python -m pip_audit --strict -r webapp/requirements.txt",
                                             "run: echo python -m pip_audit --strict -r webapp/requirements.txt", 1)),
    "plain_continuation_ignore": _ci(lambda ci: ci.replace(_WEBAPP_RUN, _WEBAPP_RUN + "          --ignore-vuln GHSA-0000-0000-0000\n", 1)),
    "plain_continuation_or_true": _ci(lambda ci: ci.replace(_WEBAPP_RUN, _WEBAPP_RUN + "          || true\n", 1)),
    "folded_continuation": _ci(lambda ci: ci.replace("run: python -m pip_audit --strict -r webapp/requirements.txt",
                                                     "run: >-\n          python -m pip_audit --strict -r webapp/requirements.txt\n"
                                                     "          --ignore-vuln GHSA-0000-0000-0000", 1)),
    "set_plus_e": _ci(lambda ci: ci.replace("          python -m pip uninstall --yes", "          set +e\n          python -m pip uninstall --yes", 1)),
    "shell_comment": _ci(lambda ci: ci.replace("          python -m pip_audit --strict\n",
                                               "          # python -m pip_audit --strict\n          echo skipped\n", 1)),
    # blocking: step keys and order
    "step_continue_on_error": _ci(lambda ci: _step_insert(ci, "Audit the webapp requirements", "        continue-on-error: true\n")),
    "quoted_continue_on_error": _ci(lambda ci: _step_insert(ci, "Audit the webapp requirements", '        "continue-on-error": true\n')),
    "duplicate_condition": _ci(lambda ci: _step_insert(ci, "Audit the webapp requirements", "        if: github.event_name == 'push'\n")),
    "condition_changed": _ci(lambda ci: _replace_condition(ci, "Audit the webapp requirements", "if: github.event_name == 'push'")),
    "always_condition": _ci(lambda ci: _replace_condition(ci, "Audit the webapp requirements", "if: always()")),
    "spaced_key_condition": _ci(lambda ci: _replace_condition(ci, "Audit the webapp requirements", "if : false")),
    "condition_dropped": _ci(lambda ci: ci.replace("      - name: Audit the webapp requirements\n        if: ${{ !cancelled() }}\n",
                                                   "      - name: Audit the webapp requirements\n", 1)),
    "working_directory": _ci(lambda ci: _step_insert(ci, "Audit the runtime requirements", "        working-directory: webapp\n")),
    "shell_override": _ci(lambda ci: _step_insert(ci, "Audit installed Python dependencies", "        shell: bash {0}\n")),
    "step_env_injection": _ci(lambda ci: _step_insert(ci, "Audit the webapp requirements",
                                                      "        env:\n          PIP_AUDIT_VULNERABILITY_SERVICE: osv\n")),
    "install_step_if": _ci(lambda ci: _step_insert(ci, "Install audited Python environment", "        if: false\n")),
    "install_no_deps": _ci(lambda ci: ci.replace('"pip-audit>=2.9,<3"', '"pip-audit>=2.9,<3" --no-deps', 1)),
    "install_local_path": _ci(lambda ci: ci.replace('"pip-audit>=2.9,<3"', '"pip-audit>=2.9,<3" ./.github/shim-pkg', 1)),
    "upgrade_between_install_and_audit": _ci(lambda ci: _before_step(
        ci, "Audit installed Python dependencies", "      - run: python -m pip install --upgrade pip setuptools wheel\n")),
    # blocking: the job and the rest of the workflow
    "job_continue_on_error": _ci(lambda ci: ci.replace("    name: Dependency audit\n", "    name: Dependency audit\n    continue-on-error: true\n", 1)),
    "job_conditional": _ci(lambda ci: ci.replace("    name: Dependency audit\n", "    name: Dependency audit\n    if: github.event_name == 'push'\n", 1)),
    "job_env": _ci(lambda ci: ci.replace("    name: Dependency audit\n", "    name: Dependency audit\n    env:\n      PIP_AUDIT_VULNERABILITY_SERVICE: osv\n", 1)),
    "job_container": _ci(lambda ci: ci.replace("    name: Dependency audit\n", "    name: Dependency audit\n    container: ghcr.io/example/shim:1\n", 1)),
    "stub_takes_required_name": _ci(lambda ci: ci.replace("    name: Dependency audit\n", "    name: Dependency audit (full)\n", 1).replace(
        "\n  dependency-audit:\n", "\n  audit-stub:\n    name: Dependency audit\n    runs-on: ubuntu-latest\n    steps:\n      - run: \"true\"\n\n  dependency-audit:\n", 1)),
    "nonaudit_step_truncates_manifest": _ci(lambda ci: _before_step(
        ci, "Audit the Master Reference release toolchain", "      - name: Prepare\n        run: printf '' > master-reference/requirements-release.txt\n")),
    "nonaudit_step_truncates_by_basename": _ci(lambda ci: _before_step(
        ci, "Audit the Master Reference release toolchain",
        "      - name: Prepare\n        working-directory: master-reference\n        run: printf '' > requirements-release.txt\n")),
    "nonaudit_step_writes_runner_env": _ci(lambda ci: _before_step(
        ci, "Audit the Master Reference release toolchain", "      - name: Prepare\n        run: echo \"PYTHONPATH=shim\" >> \"$GITHUB_ENV\"\n")),
    "nonaudit_step_writes_pip_config": _ci(lambda ci: _before_step(
        ci, "Install audited Python environment", "      - name: Prepare\n        run: python -m pip config --user set global.no-deps true\n")),
    "workflow_defaults": _ci(lambda ci: ci.replace("\njobs:\n", "\ndefaults: {run: {shell: \"true {0}\"}}\n\njobs:\n", 1)),
    "workflow_env_pythonpath": _ci(lambda ci: ci.replace("\njobs:\n", "\nenv:\n  PYTHONPATH: shim\n\njobs:\n", 1)),
    "workflow_env_index_url": _ci(lambda ci: ci.replace("\njobs:\n", "\nenv:\n  PIP_INDEX_URL: https://example.invalid/simple\n\njobs:\n", 1)),
}


@pytest.mark.parametrize("mutation", sorted(_MUTATIONS))
def test_the_contract_rejects_each_known_way_coverage_or_blocking_can_be_lost(mutation):
    inputs = _repository_inputs()
    mutated = _MUTATIONS[mutation](*inputs)
    assert mutated != inputs, f"{mutation} changed nothing, so it proves nothing"
    assert _python_audit_gaps(*mutated), mutation


# Harmless, GitHub-valid edits must stay green: a guard that cries wolf on ordinary edits pushes editors to weaken it.
_HARMLESS = {
    "job_timeout_and_permissions": _ci(lambda ci: ci.replace(
        "    name: Dependency audit\n", "    name: Dependency audit\n    timeout-minutes: 30\n    permissions:\n      contents: read\n", 1)),
    "workflow_env_unrelated": _ci(lambda ci: ci.replace(
        "\njobs:\n", "\nenv:\n  FORCE_COLOR: \"1\"\n  PYTHONUNBUFFERED: \"1\"\n  PIP_DISABLE_PIP_VERSION_CHECK: \"1\"\n\njobs:\n", 1)),
    "quoted_condition_without_braces": _ci(lambda ci: _replace_condition(ci, "Audit the webapp requirements", "if: \"!cancelled()\"")),
    "progress_spinner_off": _ci(lambda ci: ci.replace("-r webapp/requirements.txt", "--progress-spinner off -r webapp/requirements.txt", 1)),
    "dot_slash_target": _ci(lambda ci: ci.replace("-r requirements.txt", "-r ./requirements.txt", 1)),
    "long_requirement_option": _ci(lambda ci: ci.replace("-r requirements.txt", "--requirement requirements.txt", 1)),
    "trailing_yaml_comment": _ci(lambda ci: ci.replace(_WEBAPP_RUN, _WEBAPP_RUN.rstrip("\n") + "  # webapp set\n", 1)),
    "unrelated_step_mentions_pip_audit_in_with": _ci(lambda ci: _before_step(
        ci, "Install audited Python environment",
        "      - uses: actions/cache@v4\n        with:\n          path: ~/.cache/pip-audit\n          key: pip-audit\n")),
    "build_requires_reformatted": _pyproject('requires = ["setuptools==84.0.0", "wheel==0.48.0"]',
                                             'requires = ["setuptools == 84.0.0", "wheel == 0.48.0"]'),
    "uppercase_extra_installed": _ci(lambda ci: ci.replace(',eval]"', ',EVAL]"', 1)),
    "audit_step_id": _ci(lambda ci: _step_insert(ci, "Audit the webapp requirements", "        id: audit-webapp\n")),
    "report_output": _ci(lambda ci: ci.replace("-r webapp/requirements.txt", "-f json -o webapp-audit.json -r webapp/requirements.txt", 1)),
    "uv_lock_header_source_first": _files(lambda f: {**f, "portable/windows-x64-requirements.lock": re.sub(
        r"\A(?:#[^\n]*\n)+",
        "# This file was autogenerated by uv via the following command:\n"
        "#    uv pip compile pyproject.toml --extra build --generate-hashes"
        " --output-file portable/windows-x64-requirements.lock\n",
        f["portable/windows-x64-requirements.lock"], count=1)}),
}


@pytest.mark.parametrize("edit", sorted(_HARMLESS))
def test_harmless_edits_stay_green(edit):
    inputs = _repository_inputs()
    edited = _HARMLESS[edit](*inputs)
    assert edited != inputs, f"{edit} changed nothing, so it proves nothing"
    assert _python_audit_gaps(*edited) == [], edit
