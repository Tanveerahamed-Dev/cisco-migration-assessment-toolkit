"""Windows-hosted raw six-case timing, followed by a separate fixture proof.

No product module is imported by this parent. Raw pytest has no injected plugin.
Synthetic Git dates are disclosed controls shared by both variants, not a replay
of historical ambient state. Results do not qualify whole-suite timing or Atlas.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

MODULE = "tests/test_portable_source_view.py"
DATES = "2026-10-18T00:00:00+00:00"
ENV_FIELDS = ("GITHUB_ACTIONS", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTEST_ADDOPTS", "PYTHONOPTIMIZE")


class _WinRefusal(RuntimeError):
    def __init__(self, reason):
        self.reason = reason  # call sites are fixed public labels, never exception text
        self.error = ctypes.get_last_error()


def _git_environment():
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="NUL", GIT_NO_REPLACE_OBJECTS="1",
                       GIT_ATTR_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    return environment


def _git(root, *arguments):
    result = subprocess.run(["git", "--no-replace-objects", "-c", "core.hooksPath=NUL", "-c",
                             "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-C", str(root),
                             *arguments], env=_git_environment(), capture_output=True, timeout=60, check=True)
    return result.stdout.decode("utf-8").strip()


def _host(subject, output):
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows"
            or os.name != "nt" or sys.version_info[:3] != (3, 12, 10)
            or sys.maxsize != 2**63 - 1
            or not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.flags.optimize):
        raise ValueError("host refused")
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    expected = workspace / "subject"
    if subject.absolute() != expected or subject.resolve(strict=True) != expected or subject.is_symlink():
        raise ValueError("fresh subject required")
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    if (output.exists() or output.is_symlink() or not output.resolve().is_relative_to(temporary)
            or output.resolve().is_relative_to(expected)):
        raise ValueError("fresh external output required")
    return expected, output.resolve()


def _source(root, source, tree, digest):
    git = root / ".git"
    if git.is_symlink() or not git.is_dir() or git.resolve() != git:
        raise ValueError("ordinary Git directory required")
    if (Path(_git(root, "rev-parse", "--show-toplevel")).resolve() != root
            or Path(_git(root, "rev-parse", "--absolute-git-dir")).resolve() != git
            or Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve() != git
            or _git(root, "rev-parse", "HEAD") != source or _git(root, "rev-parse", "HEAD^{tree}") != tree
            or _git(root, "status", "--porcelain", "--untracked-files=all")):
        raise ValueError("source custody refused")
    path = root / MODULE
    if path.is_symlink() or path.resolve() != path or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("test source refused")


class _Process:
    def __init__(self, kernel, handle, command):
        self.kernel, self.handle, self.command, self.code = kernel, handle, command, None

    def wait(self, timeout):
        result = self.kernel.WaitForSingleObject(self.handle, max(0, int(timeout * 1000)))
        if result == 258:  # WAIT_TIMEOUT
            raise subprocess.TimeoutExpired(self.command, timeout)
        if result != 0:
            raise _WinRefusal("child_wait")
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise _WinRefusal("child_result")
        self.code = code.value
        return self.code

    def poll(self):
        if self.code is not None:
            return self.code
        if self.kernel.WaitForSingleObject(self.handle, 0) == 258:
            return None
        return self.wait(0)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class _Job:
    """Own only this child tree; closing the handle reaps descendants on parent loss."""
    def __init__(self):
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", wintypes.DWORD), ("min_working", ctypes.c_size_t),
                        ("max_working", ctypes.c_size_t), ("active", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_ulonglong * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.TerminateJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.GetExitCodeProcess.restype = wintypes.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise _WinRefusal("job_create")
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            refusal = _WinRefusal("job_policy")
            self.close()
            raise refusal

    def launch(self, command, root, environment, stream):
        """Atomically associate the new process with this job before user code.

        PROC_THREAD_ATTRIBUTE_JOB_LIST avoids the runnable-Popen/late-assignment
        race. The explicit HANDLE_LIST admits only our log and NUL input handles.
        https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute
        """
        import msvcrt

        class Startup(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR),
                        ("desktop", wintypes.LPWSTR), ("title", wintypes.LPWSTR),
                        ("x", wintypes.DWORD), ("y", wintypes.DWORD),
                        ("x_size", wintypes.DWORD), ("y_size", wintypes.DWORD),
                        ("x_chars", wintypes.DWORD), ("y_chars", wintypes.DWORD),
                        ("fill", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("show", wintypes.WORD), ("reserved_bytes", wintypes.WORD),
                        ("reserved_pointer", ctypes.c_void_p), ("stdin", wintypes.HANDLE),
                        ("stdout", wintypes.HANDLE), ("stderr", wintypes.HANDLE)]

        class StartupEx(ctypes.Structure):
            _fields_ = [("startup", Startup), ("attributes", ctypes.c_void_p)]

        class Information(ctypes.Structure):
            _fields_ = [("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
                        ("pid", wintypes.DWORD), ("tid", wintypes.DWORD)]

        kernel = self.kernel
        kernel.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                                            ctypes.POINTER(ctypes.c_size_t)]
        kernel.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        kernel.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t,
            ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
        kernel.UpdateProcThreadAttribute.restype = wintypes.BOOL
        kernel.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
        kernel.DeleteProcThreadAttributeList.restype = None
        kernel.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(StartupEx),
            ctypes.POINTER(Information)]
        kernel.CreateProcessW.restype = wintypes.BOOL
        size = ctypes.c_size_t()
        ctypes.set_last_error(0)
        if (kernel.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
                or ctypes.get_last_error() != 122 or not 0 < size.value <= 65536):
            raise _WinRefusal("attribute_size")
        storage = ctypes.create_string_buffer(size.value)
        if not kernel.InitializeProcThreadAttributeList(storage, 2, 0, ctypes.byref(size)):
            raise _WinRefusal("attribute_initialize")
        try:
            jobs = (wintypes.HANDLE * 1)(self.handle)
            if not kernel.UpdateProcThreadAttribute(storage, 0, 0x2000D, jobs, ctypes.sizeof(jobs), None, None):
                raise _WinRefusal("atomic_job_attribute")
            with open(os.devnull, "rb") as null:
                handles = (msvcrt.get_osfhandle(stream.fileno()), msvcrt.get_osfhandle(null.fileno()))
                inherited = tuple(os.get_handle_inheritable(handle) for handle in handles)
                try:
                    for handle in handles:
                        os.set_handle_inheritable(handle, True)
                    admitted_handles = (wintypes.HANDLE * 2)(*handles)
                    if not kernel.UpdateProcThreadAttribute(storage, 0, 0x20002, admitted_handles,
                                                           ctypes.sizeof(admitted_handles), None, None):
                        raise _WinRefusal("handle_attribute")
                    startup = StartupEx()
                    startup.startup.cb = ctypes.sizeof(startup)
                    startup.startup.flags = 0x101  # USESTDHANDLES | USESHOWWINDOW; SW_HIDE=0
                    startup.startup.stdin = handles[1]
                    startup.startup.stdout = startup.startup.stderr = handles[0]
                    startup.attributes = ctypes.cast(storage, ctypes.c_void_p)
                    information = Information()
                    arguments = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
                    block = ctypes.create_unicode_buffer("\0".join(key + "=" + value for key, value in
                        sorted(environment.items(), key=lambda row: row[0].upper())) + "\0")
                    flags = 0x80000 | 0x400 | 0x8000000  # extended startup, Unicode environment, no window
                    if not kernel.CreateProcessW(command[0], arguments, None, None, True, flags, block,
                                                  str(root), ctypes.byref(startup), ctypes.byref(information)):
                        raise _WinRefusal("atomic_child_create")
                    kernel.CloseHandle(information.thread)
                    return _Process(kernel, information.process, command)
                finally:
                    for handle, prior in zip(handles, inherited):
                        os.set_handle_inheritable(handle, prior)
        finally:
            kernel.DeleteProcThreadAttributeList(storage)

    def terminate(self):
        if not self.kernel.TerminateJobObject(self.handle, 124):
            raise _WinRefusal("child_tree_terminate")

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _run(root, output, command, environment, deadline):
    output.mkdir()
    started = time.monotonic()
    job, child, timed_out, reaped = _Job(), None, False, False
    try:
        with (output / "pytest.log").open("wb") as stream:
            child = job.launch(command, root, environment, stream)
            try:
                code = child.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                job.terminate()
                child.wait(timeout=5)
                code = 124
            reaped = child.poll() is not None
    finally:
        job.close()
        if child is not None:
            child.close()
    text = (output / "pytest.log").read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)  # parsing only; original log remains unchanged
    nodes = re.findall(r"(?m)^(tests/test_portable_source_view\.py::\S+) PASSED\b", text)
    summary = re.findall(r"(?m)^.*\b6 passed\b[^\r\n]*$", text)
    result = {"command": command, "exit_code": code, "wall_seconds": round(time.monotonic() - started, 6),
              "timed_out": timed_out, "child_reaped": reaped, "atomic_job_association": True,
              "nodeids_passed": nodes, "terminal_summary": summary[-1] if summary else None,
              "six_cases_passed": code == 0 and len(nodes) == len(set(nodes)) == 6 and bool(summary),
              "environment": {key: environment.get(key) for key in ENV_FIELDS}}
    (output / "child-exit.json").write_text(json.dumps({"exit_code": code}), encoding="utf-8")
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("subject", "output", "recipe", "candidate-json"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--case", choices=("original", "candidate"), required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--tree", required=True)
    arguments = parser.parse_args()
    stage, output = "host", None
    try:
        root, output = _host(arguments.subject, arguments.output)
        output.mkdir()
        recipe_raw, data_raw = arguments.recipe.read_bytes(), arguments.candidate_json.read_bytes()
        recipe, data = json.loads(recipe_raw), json.loads(data_raw)
        stage = "recipe"
        if hashlib.sha256(data_raw).hexdigest() != recipe["candidate_data_sha256"]:
            raise ValueError("candidate data refused")
        expected_source = recipe["base_source"] if arguments.case == "original" else recipe["candidate_source"]
        expected_tree = recipe["base_tree"] if arguments.case == "original" else recipe["candidate_tree"]
        digest = data["source_sha256"] if arguments.case == "original" else data["candidate_sha256"]
        if (arguments.source != expected_source or arguments.tree != expected_tree
                or re.fullmatch(r"[0-9a-f]{40}", expected_source) is None
                or re.fullmatch(r"[0-9a-f]{40}", expected_tree) is None):
            raise ValueError("source recipe refused")
        stage = "initial_source_guard"
        _source(root, expected_source, expected_tree, digest)
        environment = _git_environment()
        if environment.get("PYTEST_ADDOPTS"):
            raise ValueError("undeclared pytest options")
        for key in tuple(environment):
            if key.upper() in ("PYTHONPATH", "PYTHONOPTIMIZE") or key.startswith(("ATLAS_ORDER", "ATLAS_HEAP", "ATLAS_TARGET_", "ATLAS_SOURCEVIEW_")):
                del environment[key]
        environment.update(GIT_AUTHOR_DATE=DATES, GIT_COMMITTER_DATE=DATES)
        stage = "environment_inventory"
        if importlib.metadata.version("pip") != "26.2.1":
            raise ValueError("bootstrap version refused")
        freeze = subprocess.run([sys.executable, "-I", "-B", "-m", "pip", "freeze"], cwd=root,
                                env=_git_environment(), capture_output=True, check=True, timeout=60).stdout.decode("utf-8").splitlines()
        editable = "-e git+https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit@" + expected_source + "#egg=cisco_migration_assessment_toolkit"
        if freeze.count(editable) != 1 or any(row != editable and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}==[A-Za-z0-9_.+!-]{1,128}", row) is None for row in freeze):
            raise ValueError("public version inventory refused")
        git_version = _git(root, "--version")
        if re.fullmatch(r"git version [0-9A-Za-z.+-]{1,80}", git_version) is None:
            raise ValueError("Git version refused")
        (output / "environment.json").write_text(json.dumps({"source": expected_source, "tree": expected_tree,
            "test_sha256": digest, "recipe_sha256": hashlib.sha256(recipe_raw).hexdigest(),
            "candidate_data_sha256": hashlib.sha256(data_raw).hexdigest(), "python": sys.version,
            "pip_version": importlib.metadata.version("pip"), "git_version": git_version,
            "pip_freeze": freeze, "synthetic_git_dates": DATES, "synthetic_git_config_global": "NUL",
            "synthetic_git_config_nosystem": "1", "environment": {key: environment.get(key) for key in ENV_FIELDS},
            "limits": "Version inventory is not wheel/installed-byte identity. Parallel-host raw durations are finite observations, not whole-suite savings or Linux polluter proof. Proof is a separate later process."}, indent=2), encoding="utf-8")
        remaining = float(os.environ["ATLAS_DIAGNOSTIC_DEADLINE"]) - time.time() - 15
        if remaining <= 0:
            raise ValueError("diagnostic deadline exhausted")
        deadline = time.monotonic() + remaining  # 10s for reaping/report before outer 5s reserve
        command = [sys.executable, "-m", "pytest", "-vv", "--durations=40", MODULE]
        stage = "raw_six_cases"
        raw = _run(root, output / "raw", command, environment, deadline)
        stage = "between_process_source_guard"
        _source(root, expected_source, expected_tree, digest)
        proof_environment = dict(environment)
        proof_environment.update(PYTHONPATH=str(Path(__file__).resolve().parent),
            ATLAS_SOURCEVIEW_PROOF_REPORT=str(output / "fixture-proof.json"),
            ATLAS_SOURCEVIEW_PROOF_SOURCE_ROOT=str(root), ATLAS_SOURCEVIEW_PROOF_SOURCE=expected_source,
            ATLAS_SOURCEVIEW_PROOF_TREE=expected_tree, ATLAS_SOURCEVIEW_PROOF_CASE=arguments.case)
        stage = "proof_six_cases"
        proof = _run(root, output / "proof", command[:3] + ["-p", "rc8_sourceview_proof"] + command[3:], proof_environment, deadline)
        stage = "fixture_proof_admission"
        proof_path = output / "fixture-proof.json"
        fixture = json.loads(proof_path.read_text(encoding="utf-8")) if proof_path.is_file() else {}
        fixture_admitted = (
            fixture.get("status") == "proved"
            and fixture.get("selected_count") == fixture.get("executed_count") == 6
            and fixture.get("builder_calls") == (6 if arguments.case == "original" else 1)
            and sorted(fixture.get("selected_nodeids", [])) == sorted(raw["nodeids_passed"])
            and sorted(fixture.get("executed_nodeids", [])) == sorted(proof["nodeids_passed"])
            and sorted(raw["nodeids_passed"]) == sorted(proof["nodeids_passed"])
        )
        stage = "final_source_guard"
        _source(root, expected_source, expected_tree, digest)
        result = {"status": "complete", "source": expected_source, "tree": expected_tree,
                  "raw": raw, "proof": proof, "source_guard_after": "pass",
                  "fixture_proof_present": proof_path.is_file(), "fixture_proof_admitted": fixture_admitted}
        (output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0 if raw["six_cases_passed"] and proof["six_cases_passed"] and fixture_admitted else 1
    except Exception as error:
        refusal = {"status": "refused_or_failed", "stage": stage}
        if type(error) is _WinRefusal:
            refusal.update(native_stage=error.reason, win32_error=error.error)
        if output is not None:
            try:
                (output / "refusal.json").write_text(json.dumps(refusal), encoding="utf-8")
            except OSError:
                pass
        print(json.dumps(refusal))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
