import json
import requests
from fastmcp import FastMCP

mcp = FastMCP("Dafny", dependencies=["requests"])

@mcp.tool()
def dafny_verifier(code: str) -> str:
    """Verify a Dafny code."""
    v = code
    r = requests.post("https://dafny.livecode.ch/check", data = { 'v': v })
    text = r.json()["out"]
    return text
