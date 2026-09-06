from __future__ import annotations

import importlib.util
from pathlib import Path


_MIN_LONGEST_RUNTIME_MEMBER_CHARS = 101


def _longest_lxml_runtime_member() -> Path:
    spec = importlib.util.find_spec("lxml")
    assert spec is not None and spec.submodule_search_locations
    package_root = Path(next(iter(spec.submodule_search_locations)))
    candidates = [
        Path("_internal") / "lxml" / path.relative_to(package_root)
        for path in package_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    assert candidates
    member = max(candidates, key=lambda path: (len(path.as_posix()), path.as_posix()))
    assert len(member.as_posix()) >= _MIN_LONGEST_RUNTIME_MEMBER_CHARS
    return member


LONGEST_RUNTIME_MEMBER = _longest_lxml_runtime_member()
