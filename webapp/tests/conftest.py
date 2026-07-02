"""Collection guard (Plan A / Move-0.2): webapp/tests is part of the DEFAULT pytest gate
(pytest.ini testpaths), so environments that install only the ENGINE deps — the engine's
own CI matrix, a wheel-install dev box — must skip this directory cleanly instead of
erroring at `from fastapi...` import time. Where the web layer's deps are present (the
dev machine, webapp-ci), nothing is ignored and the suite runs as-is."""
import importlib.util

if any(importlib.util.find_spec(m) is None for m in ("fastapi", "httpx")):
    collect_ignore_glob = ["test_*.py"]
