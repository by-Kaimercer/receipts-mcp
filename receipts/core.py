"""The Receipts pipeline: rank chunks, let the local model propose quotes, verify them, answer from what survived."""
import re
from dataclasses import dataclass, field

from . import config
from .files import Chunk, load, rank, tokens
from .llm import chat_json
from .verify import LineIndex, clean_quote

FIND = """You extract evidence from a file excerpt. Every line starts with a marker like "L42| ".
Rules:
- Copy each quote EXACTLY as it appears, character for character, WITHOUT the "L42| " marker. 1 to 3 consecutive lines per quote.
- Only quote text that is in the excerpt. Never paraphrase or fix text inside a quote.
- {limit}
- If nothing in the excerpt is relevant, return an empty list.
Reply with JSON only: {{"findings": [{{"quote": "...", "why": "<=15 words on what it shows"}}]}}"""

ANSWER = """Answer the question using ONLY the numbered evidence below.
- 1 to 3 sentences. Put a citation like [1] after each claim, pointing at the evidence that supports it.
- Copy exact values (numbers, timestamps, names, messages) from the evidence.
- If the evidence answers only part of the question, answer that part and say what is missing.
- If the evidence answers none of it, the answer must be exactly NOT_FOUND.
Reply with JSON only: {"answer": "..."}"""

CITE = re.compile(r"\[(\d+)\]")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(`'\"])")
MAX_LINE_CHARS = 300
MAX_EVIDENCE_LINES = 6


@dataclass
class Evidence:
    path: str
    start: int
    end: int
    text: str
    why: str = ""
    exact: bool = True

    @property
    def ref(self) -> str:
        return f"{self.path}:{self.start}" + (f"-{self.end}" if self.end != self.start else "")


@dataclass
class Result:
    answer: str | None  # None for extract; "NOT_FOUND" when the evidence doesn't answer
    evidence: list[Evidence]
    chunks_read: int
    chunks_total: int
    tokens_read: int
    tokens_total: int
    proposed: int = 0
    rejected: int = 0
    repaired: int = 0
    skipped: list[str] = field(default_factory=list)
    rejected_quotes: list[str] = field(default_factory=list)
    uncited_removed: int = 0


def _excerpt(lines: list[str], start: int, end: int) -> str:
    sel = lines[start - 1 : end][:MAX_EVIDENCE_LINES]
    text = "\n".join(line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + " ..." for line in sel)
    return text + ("\n..." if end - start + 1 > MAX_EVIDENCE_LINES else "")


def _propose(chunk: Chunk, task: str, limit: str) -> list[dict]:
    user = f"File: {chunk.path} (lines {chunk.first_line}-{chunk.last_line})\n\n{chunk.numbered()}\n\n{task}"
    found = chat_json(FIND.format(limit=limit), user).get("findings", [])
    return [f for f in found if isinstance(f, dict) and isinstance(f.get("quote"), str) and f["quote"].strip()]


def _gather(chunks, files, order, task, limit, verify=True):
    evidence, proposed, rejected, repaired, rejected_quotes = [], 0, 0, 0, []
    for i in order:
        c = chunks[i]
        index = LineIndex(c.lines, c.first_line)
        for f in _propose(c, task, limit):
            proposed += 1
            why = str(f.get("why", ""))[:160]
            if not verify:  # the "trust the model" baseline, used only by the benchmark
                evidence.append(Evidence(c.path, 0, 0, clean_quote(f["quote"]), why))
                continue
            m = index.find(f["quote"])
            if m is None:
                rejected += 1
                rejected_quotes.append(f["quote"][:200])
                continue
            repaired += not m.exact
            if any(e.path == c.path and e.start <= m.start_line and m.end_line <= e.end for e in evidence):
                continue  # already covered (chunks overlap)
            evidence.append(Evidence(c.path, m.start_line, m.end_line,
                                     _excerpt(files[c.path], m.start_line, m.end_line), why, m.exact))
    return evidence, proposed, rejected, repaired, rejected_quotes


def _synthesize(question: str, evidence: list[Evidence], strict: bool = True) -> tuple[str, int]:
    """Returns (answer, number of uncited sentences removed)."""
    body = "\n\n".join(f"[{n}] {e.ref}\n{e.text}" for n, e in enumerate(evidence, 1))
    ans = str(chat_json(ANSWER, f"Evidence:\n\n{body}\n\nQuestion: {question}").get("answer", "")).strip()
    if not ans or "NOT_FOUND" in ans:
        return "NOT_FOUND", 0
    if not strict:
        return ans, 0
    sentences = [s for s in SENTENCE.split(ans) if s.strip()]
    kept = [g for s in sentences if (g := ground(s, evidence))]
    return (" ".join(kept).strip() or "NOT_FOUND"), len(sentences) - len(kept)


# Specific details in a sentence: anything with a digit, identifiers like a_b / a.b / a-b / camelCase, quoted strings.
# Plain hyphenated words ("suspicious-login") are English, not identifiers, so a bare hyphen doesn't count.
SPECIFIC = re.compile(r"`([^`]+)`|'([^']+)'|\"([^\"]+)\"|([\w.:/\-]*\d[\w.:/\-]*|[A-Za-z]+[_.][\w.\-]+|[a-z]+[A-Z]\w*)")
CONTENT = re.compile(r"[a-z0-9]{3,}")
COMMON = set("the and was were that this with from for are has have had not but which what when into been its "
             "their there they then than also used uses use".split())


def _overlap(body: str, text: str) -> float:
    words = {w for w in CONTENT.findall(body.lower()) if w not in COMMON}
    return len(words & set(CONTENT.findall(text))) / len(words) if words else 0.0


def _flat(s: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3})", "", " ".join(s.split())).lower()


def specifics(sentence: str) -> list[str]:
    out = []
    for m in SPECIFIC.finditer(CITE.sub("", sentence)):
        tok = next(g for g in m.groups() if g).strip().rstrip(".:,;")
        if tok:
            out.append(_flat(tok))
    return out


def ground(sentence: str, evidence: list[Evidence]) -> str | None:
    """Keep a sentence only if every specific detail in it (numbers, identifiers, quoted strings) appears in the
    verified evidence; add citations to the evidence that contains them. A sentence with no checkable detail is kept
    when most of its words appear in one quote, or when the model cited real evidence."""
    cited = {int(n) for n in CITE.findall(sentence) if 1 <= int(n) <= len(evidence)}
    body = re.sub(r"\s+([.!?,;])", r"\1", CITE.sub("", sentence)).strip()
    toks = specifics(body)
    texts = [_flat(e.text) for e in evidence]
    if not toks:
        support = {i + 1 for i, tx in enumerate(texts) if _overlap(body, tx) >= 0.6}
        refs = sorted(cited | support)
        if not refs:
            return None
    else:
        if not all(any(t in tx for tx in texts) for t in toks):
            return None
        support = {i + 1 for i, tx in enumerate(texts) if any(t in tx for t in toks)}
        refs = sorted(cited & support) or sorted(support)
    end = body[-1] if body[-1] in ".!?" else ""
    return (body[:-1] if end else body) + " " + "".join(f"[{n}]" for n in refs) + end


def ask(paths: list[str], question: str, max_chunks: int = config.ASK_CHUNKS, verify: bool = True) -> Result:
    chunks, files, total, skipped = load(paths)
    order = rank(chunks, question)[:max_chunks]
    evidence, proposed, rejected, repaired, rq = _gather(
        chunks, files, order, f"Question: {question}", "At most 5 quotes, most useful first.", verify
    )
    evidence = evidence[: config.MAX_EVIDENCE]
    answer, uncited = _synthesize(question, evidence, strict=verify) if evidence else ("NOT_FOUND", 0)
    return Result(answer, evidence, len(order), len(chunks), sum(tokens("\n".join(chunks[i].lines)) for i in order),
                  total, proposed, rejected, repaired, skipped, rq, uncited)


def extract(paths: list[str], what: str, max_items: int = 30) -> Result:
    chunks, files, total, skipped = load(paths)
    if len(chunks) > config.EXTRACT_CHUNKS:
        from .files import InputError

        raise InputError(f"extract reads every chunk, and these paths make {len(chunks)} (limit "
                         f"{config.EXTRACT_CHUNKS}). Narrow the paths, or use ask_files, which reads the best-matching chunks.")
    evidence, proposed, rejected, repaired, rq = _gather(
        chunks, files, range(len(chunks)), f"Find every occurrence of: {what}", "List every match, up to 15.", True
    )
    return Result(None, evidence[:max_items], len(chunks), len(chunks), total, total,
                  proposed, rejected, repaired, skipped, rq)


def render(r: Result) -> str:
    """Compact plain-text output for the calling model."""
    out = []
    if r.answer is not None:
        if r.answer == "NOT_FOUND":
            out.append("Answer: not found in the text that was read." + (" Closest evidence below." if r.evidence else ""))
        else:
            out.append(f"Answer ({config.MODEL}, written from the verified evidence only): {r.answer}")
        out.append("")
    if r.evidence:
        out.append("Evidence (each quote was located in the file; text and line numbers are the file's own):")
        for n, e in enumerate(r.evidence, 1):
            tag = "" if e.exact else " (model's quote was near-exact; file text shown)"
            out.append(f"[{n}] {e.ref}{tag}" + (f": {e.why}" if e.why else ""))
            out.extend("    " + line for line in e.text.splitlines())
    elif r.answer is None:
        out.append("No matches found in the text that was read.")
    cov = "all" if r.chunks_read == r.chunks_total else f"{r.chunks_read} of {r.chunks_total}"
    out.append(
        f"\nRead {cov} chunks (~{r.tokens_read:,} of ~{r.tokens_total:,} tokens). "
        f"Model proposed {r.proposed} quotes: {r.proposed - r.rejected} verified, {r.rejected} rejected as not in the file."
        + (f" Removed {r.uncited_removed} answer sentence(s) with details not found in the verified quotes."
           if r.uncited_removed else "")
        + (f" Skipped binary files: {', '.join(r.skipped)}." if r.skipped else "")
    )
    if r.chunks_read < r.chunks_total and (r.answer == "NOT_FOUND" or not r.evidence):
        out.append("Unread chunks may still contain the answer: retry with a larger max_chunks or narrower paths.")
    return "\n".join(out)
