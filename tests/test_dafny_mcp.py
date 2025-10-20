import json
import types
import sys
import subprocess
from pathlib import Path

import pytest

# Ensure project root is on sys.path so `import dafny_mcp` resolves when
# running tests from the `tests/` directory.
repo_root = str(Path(__file__).resolve().parents[1])
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)


def _install_fastmcp_shim():
    """Install a minimal shim for mcp.server.fastmcp.FastMCP so importing
    dafny_mcp works in test environments where the real package isn't
    available.
    """
    import types

    fastmcp_module = types.ModuleType("mcp.server.fastmcp")

    class FastMCPShim:
        def __init__(self, name):
            self.name = name

        def tool(self):
            def decorator(f):
                return f

            return decorator

    fastmcp_module.FastMCP = FastMCPShim
    sys.modules["mcp"] = types.ModuleType("mcp")
    sys.modules["mcp.server"] = types.ModuleType("mcp.server")
    sys.modules["mcp.server.fastmcp"] = fastmcp_module


@pytest.fixture(autouse=True)
def shim_fastmcp():
    _install_fastmcp_shim()
    yield


def make_proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    class P:
        def __init__(self):
            self.stdout = stdout.encode("utf-8")
            self.stderr = stderr.encode("utf-8")
            self.returncode = returncode

    return P()


def test_resolve_calls_subprocess(monkeypatch):
    import dafny_mcp

    captured = {}

    def fake_run(cmd, input, cwd, capture_output, timeout):
        captured['cmd'] = cmd
        return make_proc(stdout="Dafny program verifier did not attempt verification", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    res = dafny_mcp.dafny_resolve("method Main() { }", options={"timeout": 5})
    assert res["exit_code"] == 0
    assert "resolve" in captured['cmd']


def test_verify_parses_json(monkeypatch):
    import dafny_mcp

    json_out = json.dumps({"type": "status", "value": "finished"})

    def fake_run(cmd, input, cwd, capture_output, timeout):
        return make_proc(stdout=json_out, returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    res = dafny_mcp.dafny_verify("method Main() { }", options={"timeout": 5, "json_output": True})
    assert res["exit_code"] == 0
    assert "parsed_json" in res
    assert res["parsed_json"]["type"] == "status"


def test_run_writes_file_when_stdin_false(monkeypatch, tmp_path):
    import dafny_mcp
    recorded = {}

    def fake_run(cmd, input, cwd, capture_output, timeout):
        # the command should include a path ending with input.dfy when stdin=False
        recorded['cmd'] = cmd
        return make_proc(stdout="ok", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    res = dafny_mcp.dafny_run("method Main() { }", options={"stdin": False, "timeout": 5})
    assert res["exit_code"] == 0
    # ensure command contains a file path (not --stdin)
    assert any(isinstance(p, str) and p.endswith("input.dfy") for p in recorded['cmd'])
