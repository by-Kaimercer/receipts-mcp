"""Resolve paths inside the allowed roots, read text files and cut them into line-numbered chunks."""
import glob
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import config

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", "dist", "build"}


class InputError(ValueError):
    """A problem with the caller's paths; the message is shown to the model so it can fix the call."""


def tokens(text: str) -> int:
    """Rough token estimate (about 4 characters per token for English and code)."""
    return math.ceil(len(text) / 4)


@dataclass
class Chunk:
    path: str  # as displayed to the caller (relative to its root when possible)
    first_line: int  # 1-based
    lines: list[str]

    @property
    def last_line(self) -> int:
        return self.first_line + len(self.lines) - 1

    def numbered(self) -> str:
        return "\n".join(f"L{self.first_line + i}| {line}" for i, line in enumerate(self.lines))


def display(p: Path) -> str:
    for root in config.roots():
        try:
            return p.relative_to(root).as_posix()
        except ValueError:
            continue
    return str(p)


def resolve(patterns: list[str]) -> list[Path]:
    """Expand paths and globs (relative to the first root), refusing anything outside the allowed roots."""
    roots = config.roots()
    out: list[Path] = []
    for pat in patterns:
        base = Path(pat) if Path(pat).is_absolute() else roots[0] / pat
        hits = [Path(h) for h in glob.glob(str(base), recursive=True)] if glob.has_magic(pat) else [base]
        if not hits:
            raise InputError(f"No files match '{pat}' (relative paths resolve against {roots[0]}).")
        for h in hits:
            h = h.resolve()
            if not any(h == r or r in h.parents for r in roots):
                raise InputError(f"'{pat}' is outside the allowed roots: {', '.join(map(str, roots))}.")
            if h.is_dir():
                hits_in = [f for f in h.rglob("*") if f.is_file() and not SKIP_DIRS & set(f.relative_to(h).parts)]
                out.extend(sorted(hits_in))
            elif h.is_file():
                out.append(h)
            else:
                raise InputError(f"'{pat}' does not exist.")
    out = list(dict.fromkeys(out))
    if len(out) > config.MAX_FILES:
        raise InputError(f"{len(out)} files matched; the limit is {config.MAX_FILES}. Narrow the paths or glob.")
    return out


def read_text(p: Path) -> str | None:
    """Return text, or None for binary files."""
    data = p.read_bytes()
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def chunk_lines(path: str, lines: list[str], budget: int, overlap: int) -> list[Chunk]:
    chunks, start = [], 0
    while start < len(lines):
        size, end = 0, start
        while end < len(lines) and (size + tokens(lines[end]) + 3 <= budget or end == start):
            size += tokens(lines[end]) + 3  # +3 for the "L123| " prefix
            end += 1
        chunks.append(Chunk(path, start + 1, lines[start:end]))
        if end >= len(lines):
            break
        start = max(end - overlap, start + 1)
    return chunks


def load(patterns: list[str]) -> tuple[list[Chunk], dict[str, list[str]], int, list[str]]:
    """Returns (chunks, lines per file, total file tokens, skipped files)."""
    chunks, files, total, skipped = [], {}, 0, []
    for p in resolve(patterns):
        text = read_text(p)
        name = display(p)
        if text is None:
            skipped.append(name)
            continue
        lines = text.splitlines()
        files[name] = lines
        total += tokens(text)
        chunks.extend(chunk_lines(name, lines, config.CHUNK_TOKENS, config.CHUNK_OVERLAP))
    if total > config.MAX_INPUT_TOKENS:
        raise InputError(f"Inputs total ~{total:,} tokens; the limit is {config.MAX_INPUT_TOKENS:,}. Narrow the paths.")
    if not chunks:
        raise InputError("No readable text in the given paths" + (f" (skipped binary: {', '.join(skipped)})." if skipped else "."))
    return chunks, files, total, skipped


# --- ranking: pick which chunks to read when a question doesn't need everything --------------------------------
WORD = re.compile(r"[A-Za-z0-9]+")


def terms(text: str) -> list[str]:
    out = []
    for w in WORD.findall(text):
        lw = w.lower()
        out.append(lw)
        out.extend(p.lower() for p in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", w) if p.lower() != lw)
    return [t for t in out if len(t) > 1 and t not in STOP]


STOP = set("the a an and or of to in on for is are was were be by with what which who when where how does do did "
           "this that it its as at from if than then there their any all can should would could about into".split())


def rank(chunks: list[Chunk], question: str) -> list[int]:
    """BM25 over chunks; returns chunk indices, best first."""
    docs = [Counter(terms(" ".join(c.lines))) for c in chunks]
    n = len(docs)
    avg = sum(sum(d.values()) for d in docs) / max(n, 1)
    df = Counter(t for d in docs for t in d)
    q = set(terms(question))
    scores = []
    for d in docs:
        dl = sum(d.values())
        s = 0.0
        for t in q:
            if t in d:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * d[t] * 2.2 / (d[t] + 1.2 * (0.25 + 0.75 * dl / max(avg, 1)))
        scores.append(s)
    return sorted(range(n), key=lambda i: -scores[i])
