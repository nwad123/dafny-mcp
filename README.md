# dafny-mcp
Dafny Verifier Tool for the Model Context Protocol, which can be used with Claude

## Dependencies

- Implemented using [FastMCP](https://github.com/jlowin/fastmcp)
- Accesses [https://dafny.livecode.ch]()

## Setup

- `uv pip install fastmcp`
- `uv pip install requests`
- `fastmcp install mcp.py`
- `fastmcp dev mcp.py --with requests`
