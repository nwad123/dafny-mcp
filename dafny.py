import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Annotated
from fastmcp import Context
from pydantic import BaseModel, Field
from dataclasses import dataclass
from enum import Enum, auto


class DafnyError(Enum):
    """Types of errors that can occur when running Dafny."""

    TIMEOUT = auto()
    EXECUTABLE_NOT_FOUND = auto()
    JSON_PARSE_ERROR = auto()


@dataclass
class DafnyResult:
    """Structured result from running a Dafny command."""

    run_id: str
    exit_code: Optional[int]
    stdout: str
    stderr: str
    cmd: List[str]
    tempdir: Optional[str]
    error_type: Optional[DafnyError] = None
    error_message: Optional[str] = None
    parsed_json: Optional[Dict[str, Any]] = None
    timeout_seconds: Optional[int] = None

    @classmethod
    def from_timeout(
        cls,
        run_id: str,
        cmd: List[str],
        timeout: int,
        stdout: str,
        stderr: str,
        tempdir: Optional[str],
    ) -> "DafnyResult":
        """Create a result for a timeout error."""
        return cls(
            run_id=run_id,
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            cmd=cmd,
            tempdir=tempdir,
            error_type=DafnyError.TIMEOUT,
            timeout_seconds=timeout,
        )

    @classmethod
    def from_executable_error(
        cls, run_id: str, cmd: List[str], error_message: str, tempdir: Optional[str]
    ) -> "DafnyResult":
        """Create a result for when the Dafny executable is not found."""
        return cls(
            run_id=run_id,
            exit_code=None,
            stdout="",
            stderr="",
            cmd=cmd,
            tempdir=tempdir,
            error_type=DafnyError.EXECUTABLE_NOT_FOUND,
            error_message=error_message,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert the result to a dictionary format."""
        result = {
            "run_id": self.run_id,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "cmd": self.cmd,
            "tempdir": self.tempdir,
        }

        if self.error_type:
            result["error"] = self.error_type.name.lower()
        if self.error_message:
            result["error_message"] = self.error_message
        if self.parsed_json is not None:
            result["parsed_json"] = self.parsed_json
        if self.timeout_seconds is not None:
            result["timeout_seconds"] = self.timeout_seconds
            result["timeout"] = True

        return result


def _decode_output(output: Optional[bytes | str]) -> str:
    """Safely decode subprocess output to a string."""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output or ""


# Mapping of option names to their command line argument forms
DAFNY_ARG_MAPPING = {
    "cores": "--cores",
    "verification_time_limit": "--verification-time-limit",
    "resource_limit": "--resource-limit",
    "json_output": "--json-output",
}


class DafnyOptions(BaseModel):
    """Options for running Dafny commands.

    These options control how Dafny is executed and what features are enabled.
    Most options map directly to Dafny command-line arguments.
    """

    stdin: Annotated[
        bool,
        Field(
            description="Try to pass code via stdin rather than a file", default=True
        ),
    ]
    timeout: Annotated[
        int, Field(description="Process timeout in seconds", default=60, ge=0)
    ]
    verification_time_limit: Annotated[
        Optional[int],
        Field(
            description="Time limit for verifying each assertion batch (seconds)",
            default=None,
            ge=0,
        ),
    ]
    resource_limit: Annotated[
        Optional[int],
        Field(description="Resource limit for Z3 solver", default=None, ge=0),
    ]
    cores: Annotated[
        Optional[int],
        Field(
            description="Number of cores to use for verification", default=None, ge=1
        ),
    ]
    json_output: Annotated[
        bool, Field(description="Ask Dafny to produce JSON output", default=False)
    ]
    cleanup: Annotated[
        bool,
        Field(description="Remove temporary directory after execution", default=True),
    ]
    extra_args: Annotated[
        List[str],
        Field(
            description="Additional command-line arguments to pass to Dafny",
            default_factory=list,
        ),
    ]

    def build_command(self, subcmd: str) -> List[str]:
        """Build the Dafny command line arguments.

        Args:
            subcmd: The Dafny subcommand (resolve, verify, run, etc.)

        Returns:
            List of command line arguments for Dafny.
        """
        cmd = ["dafny", subcmd]

        # Add mapped arguments with values
        for opt_name, flag in DAFNY_ARG_MAPPING.items():
            value = getattr(self, opt_name)
            if isinstance(value, bool):
                if value:
                    cmd.append(flag)
            elif value is not None:
                cmd.extend([flag, str(value)])

        # Add stdin flag if requested
        if self.stdin:
            cmd.append("--stdin")

        # Add any extra arguments
        if self.extra_args:
            cmd.extend(self.extra_args)

        return cmd


def run(
    subcmd: str, code: str, options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Run a Dafny subcommand safely and return a structured result.

    Args:
        subcmd: The Dafny subcommand to run (resolve, verify, run, etc.)
        code: The Dafny source code to process
        options: Options for running Dafny (converted to DafnyOptions)

    Returns:
        A dictionary containing the execution results including stdout, stderr,
        exit code, and any parsed JSON output if requested.
    """
    # Convert dict options to DafnyOptions model
    opts = DafnyOptions(**(options or {}))
    run_id = f"dafny-run-{int(time.time()*1000)}"
    tempdir = tempfile.mkdtemp(prefix="dafny-mcp-")

    try:
        # Build the command line
        cmd = opts.build_command(subcmd)
        use_stdin_flag = opts.stdin
        timeout = opts.timeout
        cleanup = opts.cleanup
        json_output = opts.json_output

        # If not using stdin, write code to a file and pass it
        if not use_stdin_flag:
            fn = os.path.join(tempdir, "input.dfy")
            with open(fn, "w", encoding="utf-8") as f:
                f.write(code)
            file_written = fn
            cmd.append(fn)

        # Run the process
        try:
            proc = subprocess.run(
                cmd,
                input=code.encode("utf-8") if use_stdin_flag else None,
                cwd=tempdir,
                capture_output=True,
                timeout=timeout,
            )
            result = DafnyResult(
                run_id=run_id,
                exit_code=proc.returncode,
                stdout=_decode_output(proc.stdout),
                stderr=_decode_output(proc.stderr),
                cmd=cmd,
                tempdir=tempdir if not cleanup else None,
            )

        except subprocess.TimeoutExpired as e:
            result = DafnyResult.from_timeout(
                run_id=run_id,
                cmd=cmd,
                timeout=timeout,
                stdout=_decode_output(e.stdout),
                stderr=_decode_output(e.stderr),
                tempdir=tempdir if not cleanup else None,
            )

        except FileNotFoundError as e:
            result = DafnyResult.from_executable_error(
                run_id=run_id,
                cmd=cmd,
                error_message=str(e),
                tempdir=tempdir if not cleanup else None,
            )

        # Try to parse JSON output if requested
        if json_output and result.stdout:
            try:
                result.parsed_json = json.loads(result.stdout)
            except Exception:
                result.error_type = DafnyError.JSON_PARSE_ERROR
                result.error_message = "Failed to parse Dafny JSON output"

        return result.to_dict()
    finally:
        if cleanup:
            try:
                shutil.rmtree(tempdir)
            except Exception:
                pass
