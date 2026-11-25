"""Records how many tokens each call kept out of the calling model's context."""
import sqlite3
import time

from . import config


def _db():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(config.DATA_DIR / "ledger.sqlite")
    db.execute("CREATE TABLE IF NOT EXISTS calls (ts REAL, tool TEXT, input_tokens INT, output_tokens INT)")
    return db


def record(tool: str, input_tokens: int, output_tokens: int) -> None:
    with _db() as db:
        db.execute("INSERT INTO calls VALUES (?, ?, ?, ?)", (time.time(), tool, input_tokens, output_tokens))


def summary() -> str:
    with _db() as db:
        rows = {
            label: db.execute(
                "SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0) FROM calls WHERE ts >= ?",
                (since,),
            ).fetchone()
            for label, since in (("Last 24 hours", time.time() - 86400), ("All time", 0))
        }
    lines = []
    for label, (n, inp, out) in rows.items():
        saved = max(inp - out, 0)
        pct = f" ({saved / inp:.0%})" if inp else ""
        lines.append(f"{label}: {n} calls; ~{inp:,} tokens of files handled locally, ~{out:,} returned; "
                     f"~{saved:,} tokens saved{pct}.")
    lines.append("Saved = estimated tokens of the input files minus tokens returned, i.e. assuming you would otherwise "
                 "have read those files in full. Token counts are estimates (about 4 characters per token).")
    return "\n".join(lines)
