"""MCP server (stdio). Run with `receipts-mcp` or `python -m receipts.server`."""
from typing import Annotated

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from . import config, core, ledger
from .files import InputError, tokens
from .llm import ModelUnavailable

mcp = FastMCP(
    "receipts",
    instructions=(
        "Receipts reads large files with a local model so their full text never enters your context, and returns a "
        "short answer plus quotes that were verified against the files, with file:line references. Use it for facts "
        "buried in logs, long source files, docs or whole directories. Read files directly when you need to edit "
        "them or need their full text."
    ),
    log_level="WARNING",
)

Paths = Annotated[
    list[str],
    Field(description="Files, directories or globs (e.g. 'logs/app.log', 'src', 'src/**/*.py'). "
          "Relative paths resolve against the project root."),
]


async def run(tool: str, fn, *args) -> str:
    try:
        result = await anyio.to_thread.run_sync(lambda: fn(*args))
    except (InputError, ModelUnavailable) as e:
        raise ToolError(str(e)) from e
    text = core.render(result)
    ledger.record(tool, result.tokens_total, tokens(text))
    return text


@mcp.tool()
async def ask_files(
    paths: Paths,
    question: Annotated[str, Field(description="A specific question, e.g. 'What timeout does the retry loop use?'")],
    max_chunks: Annotated[int, Field(ge=1, le=16, description="How many of the best-matching ~6k-token chunks "
                                     "the local model reads. Raise it if the answer is not found.")] = config.ASK_CHUNKS,
) -> str:
    """Answer a question about files without reading them into your context. A local model reads the
    best-matching parts and proposes quotes; every quote is located in the real file, and only those that are
    found are returned, with their true file:line ranges. The short answer is written from verified quotes only.
    Check the quotes before relying on the answer; 'not found' means the text that was read did not contain it."""
    return await run("ask_files", core.ask, paths, question, max_chunks)


@mcp.tool()
async def extract_from_files(
    paths: Paths,
    what: Annotated[str, Field(description="What to list, e.g. 'every ERROR line mentioning the billing service' "
                               "or 'functions that open a network connection'.")],
    max_items: Annotated[int, Field(ge=1, le=100, description="Maximum items to return.")] = 30,
) -> str:
    """List every place in the files matching a description, as verified quotes with file:line references.
    Unlike ask_files it reads all of the text (up to about 240k tokens), so use it for 'find all' requests."""
    return await run("extract_from_files", core.extract, paths, what, max_items)


@mcp.tool()
def token_savings() -> str:
    """Show how many tokens Receipts has kept out of your context, for the last 24 hours and all time."""
    return ledger.summary()


def main():
    mcp.run()


if __name__ == "__main__":
    main()
