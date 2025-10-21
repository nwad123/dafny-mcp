from typing import Any, Dict, List, Literal, Optional, Annotated
from pydantic import Field

from fastmcp import FastMCP, Context
import dafny

mcp = FastMCP(name="DafnyServer")

@mcp.tool()
def dafny_resolve(
    code: Annotated[str, "Dafny source code to parse and type-check"],
    stdin: Annotated[bool, "Read code from stdin rather than creating a temp file"] = True,
    timeout: Annotated[int, Field(description="Process timeout in seconds", ge=0)] = 60,
    cores: Annotated[int, Field(description="Number of cores to use for verification", ge=1)] = 6,
    allow_warnings: Annotated[bool, "Allow warnings without failing"] = False,
    verify_included_files: Annotated[bool, "Also verify included files"] = False,
    json_output: Annotated[bool, "Return output in JSON format"] = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """Parse and type-check Dafny source code.
    
    Validates the syntax and performs type checking, but does not verify the code.
    This is faster than full verification when you just want to check for basic errors.
    """
    opts = {
        "stdin": stdin,
        "timeout": timeout,
        "cores": cores,
        "json_output": json_output
    }
    if allow_warnings:
        opts["extra_args"] = ["--allow-warnings"]
    if verify_included_files:
        opts["extra_args"] = opts.get("extra_args", []) + ["--verify-included-files"]
    
    return dafny.run("resolve", code, opts)


@mcp.tool()
def dafny_verify(
    code: Annotated[str, "Dafny source code to verify"],
    stdin: Annotated[bool, "Read code from stdin rather than creating a temp file"] = True,
    timeout: Annotated[int, Field(description="Process timeout in seconds", ge=0)] = 60,
    cores: Annotated[int, Field(description="Number of cores to use for verification", ge=1)] = 6,
    verification_time_limit: Annotated[int, Field(description="Time limit in seconds for verifying each assertion batch (0 for no limit)", ge=0)] = 30,
    resource_limit: Annotated[int, Field(description="Resource limit for Z3 solver (deterministic alternative to time limit)", ge=0)] = 0,
    json_output: Annotated[bool, "Return output in JSON format"] = True,
    allow_warnings: Annotated[bool, "Allow warnings without failing"] = False,
    verify_included_files: Annotated[bool, "Also verify included files"] = False,
    extract_counterexample: Annotated[bool, "Extract counterexample for first failing assertion"] = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """Verify Dafny source code.
    
    Performs full verification including parsing, type checking, and proving all assertions.
    Use verification_time_limit or resource_limit to control how long the prover spends on each assertion.
    """
    opts = {
        "stdin": stdin,
        "timeout": timeout,
        "cores": cores,
        "json_output": json_output,
        "verification_time_limit": verification_time_limit,
        "resource_limit": resource_limit
    }
    
    extra_args = []
    if allow_warnings:
        extra_args.append("--allow-warnings")
    if verify_included_files:
        extra_args.append("--verify-included-files")
    if extract_counterexample:
        extra_args.append("--extract-counterexample")
    if extra_args:
        opts["extra_args"] = extra_args
    
    return dafny.run("verify", code, opts)

if __name__ == "__main__":
    mcp.run()