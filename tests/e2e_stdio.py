"""End-to-end check: spawn the server over stdio with the official MCP client, list tools, call each one, and
check the error paths (path outside the roots, Ollama down). Needs Ollama running.

Run from the repo root:  python tests/e2e_stdio.py
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
failures = []


async def session(extra_env=None):
    env = {**os.environ, "RECEIPTS_ROOTS": str(ROOT), "RECEIPTS_DATA_DIR": tempfile.mkdtemp(), **(extra_env or {})}
    params = StdioServerParameters(command=sys.executable, args=["-m", "receipts.server"], env=env, cwd=str(ROOT))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        yield s


async def call(s, tool, args, expect_error=False, must_contain=""):
    t0 = time.perf_counter()
    res = await s.call_tool(tool, args)
    text = "\n".join(getattr(c, "text", "") for c in res.content)
    label = f"{tool}({', '.join(f'{k}={v!r}' for k, v in args.items())})"
    print(f"\n=== {label} [{'ERROR' if res.isError else 'ok'}] {time.perf_counter() - t0:.1f}s ===\n{text[:1500]}")
    if res.isError != expect_error or must_contain not in text:
        failures.append(label)


async def main():
    async for s in session():
        tools = (await s.list_tools()).tools
        print("Tools:", ", ".join(f"{t.name}({', '.join(t.inputSchema['properties'])})" for t in tools))
        await call(s, "ask_files", {"paths": ["bench/corpus/app.log"],
                                    "question": "Which replica was promoted to primary during the database failover?"},
                   must_contain="replica-db-3")
        await call(s, "extract_from_files", {"paths": ["bench/corpus/stdlib/json_decoder.py"],
                                             "what": "error messages passed to JSONDecodeError"},
                   must_contain="json_decoder.py:")
        await call(s, "token_savings", {}, must_contain="tokens saved")
        await call(s, "ask_files", {"paths": ["../outside.txt"], "question": "x"}, expect_error=True,
                   must_contain="outside the allowed roots")
    async for s in session({"OLLAMA_URL": "http://localhost:1"}):
        await call(s, "ask_files", {"paths": ["bench/corpus/stdlib/textwrap.py"], "question": "default width?"},
                   expect_error=True, must_contain="not reachable")
    print("\nRESULT:", "PASS" if not failures else f"FAIL {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
