import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Dafny")

def _safe_ctx_log(ctx: Any, level: str, message: str) -> None:
    """Try several common logging methods on the context if present.
    This helper is defensive because different FastMCP contexts may expose
    different logging APIs.
    """
    if ctx is None:
        return
    try:
        if hasattr(ctx, "log"):
            ctx.log(level, message)
            return
        if hasattr(ctx, "log_info") and level.lower() == "info":
            ctx.log_info(message)
            return
        if hasattr(ctx, "info"):
            ctx.info(message)
            return
    except Exception:
        # Best-effort logging; do not fail the tool because logging failed.
        pass


def _run_dafny(subcmd: str, code: str, options: Optional[Dict[str, Any]] = None, ctx: Any = None) -> Dict[str, Any]:
    """Run a Dafny subcommand safely and return a structured result.

    Options (supported):
      - stdin: bool (default True) -- try to pass code via stdin rather than a file
      - timeout: process timeout in seconds (default 60)
      - verification_time_limit: passed to `dafny verify` as --verification-time-limit
      - resource_limit: passed to `dafny verify` as --resource-limit
      - cores: passed as --cores
      - json_output: bool (ask dafny for --json-output)
      - cleanup: bool (remove tempdir) default True
      - extra_args: list of additional CLI args
    """
    opts = options.copy() if options else {}
    stdin_mode = opts.get("stdin", True)
    timeout = opts.get("timeout", 60)
    json_output = opts.get("json_output", False)
    cleanup = opts.get("cleanup", True)
    extra_args: List[str] = list(opts.get("extra_args", []))

    run_id = f"dafny-run-{int(time.time()*1000)}"
    tempdir = tempfile.mkdtemp(prefix="dafny-mcp-")
    _safe_ctx_log(ctx, "info", f"[{run_id}] workspace: {tempdir}")

    try:
        # Prepare base command
        cmd: List[str] = ["dafny", subcmd]

        # Map common options
        if "cores" in opts and opts["cores"] is not None:
            cmd += ["--cores", str(opts["cores"])]
        if "verification_time_limit" in opts and opts["verification_time_limit"] is not None:
            cmd += ["--verification-time-limit", str(opts["verification_time_limit"])]
        if "resource_limit" in opts and opts["resource_limit"] is not None:
            cmd += ["--resource-limit", str(opts["resource_limit"])]
        if json_output:
            cmd.append("--json-output")

        # Append any extra CLI args
        if extra_args:
            cmd += extra_args

        # Decide whether to use stdin or a temporary file
        use_stdin_flag = False
        if stdin_mode:
            # many Dafny subcommands accept --stdin
            cmd.append("--stdin")
            use_stdin_flag = True

        # If not using stdin, write code to a file and pass it
        file_written = None
        if not use_stdin_flag:
            fn = os.path.join(tempdir, "input.dfy")
            with open(fn, "w", encoding="utf-8") as f:
                f.write(code)
            file_written = fn
            cmd.append(fn)

        # Run the process
        _safe_ctx_log(ctx, "info", f"[{run_id}] running: {' '.join(cmd)}")
        try:
            proc = subprocess.run(
                cmd,
                input=code.encode("utf-8") if use_stdin_flag else None,
                cwd=tempdir,
                capture_output=True,
                timeout=timeout,
            )
            stdout = proc.stdout.decode("utf-8", errors="replace") if isinstance(proc.stdout, (bytes, bytearray)) else proc.stdout or ""
            stderr = proc.stderr.decode("utf-8", errors="replace") if isinstance(proc.stderr, (bytes, bytearray)) else proc.stderr or ""
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as e:
            _safe_ctx_log(ctx, "info", f"[{run_id}] process timeout after {timeout}s")
            return {
                "run_id": run_id,
                "exit_code": None,
                "timeout": True,
                "timeout_seconds": timeout,
                "stdout": e.stdout.decode("utf-8", errors="replace") if e.stdout else "",
                "stderr": e.stderr.decode("utf-8", errors="replace") if e.stderr else "",
                "cmd": cmd,
                "tempdir": tempdir if not cleanup else None,
            }
        except FileNotFoundError as e:
            # Dafny executable not found; return structured error instead of raising
            msg = str(e)
            _safe_ctx_log(ctx, "info", f"[{run_id}] executable not found: {msg}")
            return {
                "run_id": run_id,
                "exit_code": None,
                "error": "executable_not_found",
                "error_message": msg,
                "cmd": cmd,
                "tempdir": tempdir if not cleanup else None,
            }

        result: Dict[str, Any] = {
            "run_id": run_id,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "cmd": cmd,
            "tempdir": tempdir if not cleanup else None,
        }

        # Try to parse JSON output if requested
        if json_output:
            try:
                parsed = json.loads(stdout)
                result["parsed_json"] = parsed
            except Exception:
                # If parsing fails, include parse error note but keep raw stdout
                result["parsed_json_error"] = "failed to parse dafny JSON output"

        return result
    finally:
        if cleanup:
            try:
                shutil.rmtree(tempdir)
                _safe_ctx_log(ctx, "info", f"[{run_id}] cleaned workspace")
            except Exception:
                # best-effort cleanup
                pass


@mcp.tool()
def dafny_resolve(code: str, options: Optional[Dict[str, Any]] = None, ctx: Any = None) -> Dict[str, Any]:
    """Parse and type-check Dafny source. Returns structured result.

    Example options: {"stdin": True, "timeout": 10, "json_output": False}
    """
    opts = options or {}
    return _run_dafny("resolve", code, opts, ctx)


@mcp.tool()
def dafny_verify(code: str, options: Optional[Dict[str, Any]] = None, ctx: Any = None) -> Dict[str, Any]:
    """Verify Dafny source. Options can include verification_time_limit, resource_limit, json_output, etc."""
    opts = options or {}
    # sensible default: ask Dafny to produce JSON when asked by client
    if "json_output" not in opts:
        opts["json_output"] = True
    return _run_dafny("verify", code, opts, ctx)


@mcp.tool()
def dafny_run(code: str, program_args: Optional[List[str]] = None, options: Optional[Dict[str, Any]] = None, ctx: Any = None) -> Dict[str, Any]:
    """Run a Dafny program. program_args become arguments to the Dafny runtime program.

    Options may include target, no_verify, timeout, json_output=false (usually), stdin.
    """
    opts = options.copy() if options else {}
    # Translate program_args into Dafny CLI form by appending '--' followed by args per Dafny help
    extra = opts.get("extra_args", [])
    if program_args:
        # Dafny CLI uses: dafny run <file> [<program-arguments>...] [options]
        # We'll pass program args after a '--' separator to be safe
        extra = list(extra) + ["--"] + list(program_args)
        opts["extra_args"] = extra
    # default: do not request --json-output for run
    if "json_output" not in opts:
        opts["json_output"] = False
    return _run_dafny("run", code, opts, ctx)

