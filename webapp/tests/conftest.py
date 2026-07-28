"""Collection guard (Plan A / Move-0.2): webapp/tests is part of the DEFAULT pytest gate
(pytest.ini testpaths), so environments that install only the ENGINE deps — the engine's
own CI matrix, a wheel-install dev box — must skip this directory cleanly instead of
erroring at `from fastapi...` import time. Where the web layer's deps are present (the
dev machine, webapp-ci), nothing is ignored and the suite runs as-is.

**The un-collection is LOUD.** `collect_ignore_glob` produces no skip report and no reason
line — unlike `pytest.skip(allow_module_level=True)`, which reports one skip per file — and
`pytest.ini` sets `addopts = -q`, so a run that silently dropped ~20 webapp test files was
visually identical to a full green one. That is the whole Atlas `--redact-folder` safety
suite, the security-hardening suite, the DNS-rebinding Host allowlist and the unplug-safety
suite leaving the gate with nothing said; and the `verify-green` Stop hook runs a bare
`python -m pytest`, so it would have reported green and allowed the turn. This file's own
guard test names that class ("an asset EXISTS but silently sits outside the gate") — so the
skip now announces itself through the terminal reporter and records WHICH dependency was
missing, and `MISSING_WEB_DEPS` is importable so a test can assert the guard's state
directly rather than grepping this source.
"""
import importlib.util

_REQUIRED = ("fastapi", "httpx")

#: The web deps that are absent, in declaration order. Empty tuple == the suite is collected.
MISSING_WEB_DEPS = tuple(m for m in _REQUIRED if importlib.util.find_spec(m) is None)

if MISSING_WEB_DEPS:
    collect_ignore_glob = ["test_*.py"]


def pytest_report_collectionfinish(config):
    """Say it out loud, at the top of the run, where -q cannot hide it."""
    if MISSING_WEB_DEPS:
        return (f"webapp/tests: NOT COLLECTED — missing {', '.join(MISSING_WEB_DEPS)}. "
                f"The web-layer safety suites (Atlas redaction, security hardening, "
                f"unplug safety) did NOT run; this run's green does not cover them.")
    return None
