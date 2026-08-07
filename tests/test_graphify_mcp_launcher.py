"""Contract tests for the cross-platform Graphify MCP launcher."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tools" / "graphify_mcp_launcher.mjs"
NODE_TEST = ROOT / "tests" / "graphify_mcp_launcher.test.mjs"


def test_mcp_config_uses_the_portable_graphify_launcher() -> None:
    config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    graphify = config["mcpServers"]["graphify"]

    assert graphify == {
        "command": "node",
        "args": ["tools/graphify_mcp_launcher.mjs"],
    }
    assert LAUNCHER.is_file()


def test_graphify_mcp_launcher_javascript_contract() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed on this test host")

    for args in (["--check", str(LAUNCHER)], ["--test", str(NODE_TEST)]):
        result = subprocess.run(
            [node, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
