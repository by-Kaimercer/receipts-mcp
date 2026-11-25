"""Quote verification: the guarantee that makes Receipts trustworthy.

A local model proposes quotes; this module finds each one in the real file and returns the file's own lines.
Nothing the model writes is passed through as evidence, and line numbers are always computed here, never taken
from the model.
"""
import bisect
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

LINE_PREFIX = re.compile(r"^\s*L?\d+\s*[|:]\s?", re.MULTILINE)  # "L123| " prefixes the model may copy
ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…)\s*")
FUZZY_MIN_LEN = 24  # shorter quotes must match exactly; fuzzy matching on short strings finds false positives
FUZZY_THRESHOLD = 92


@dataclass
class Match:
    start_line: int  # 1-based, inclusive, in file coordinates
    end_line: int
    exact: bool


def norm(s: str) -> str:
    return " ".join(s.split())


class LineIndex:
    """Whitespace-normalised view of a block of lines that maps character offsets back to line numbers."""

    def __init__(self, lines: list[str], first_line: int = 1):
        self.first_line = first_line
        self.starts, parts, pos = [], [], 0
        for line in lines:
            n = norm(line)
            self.starts.append(pos)
            parts.append(n)
            pos += len(n) + 1
        self.text = " ".join(parts)
        self.lower = self.text.lower()

    def line_at(self, offset: int) -> int:
        return self.first_line + bisect.bisect_right(self.starts, offset) - 1

    def span(self, start: int, end: int) -> tuple[int, int]:
        return self.line_at(start), self.line_at(max(start, end - 1))

    def find(self, quote: str) -> Match | None:
        q = clean_quote(quote)
        if not q:
            return None
        segments = [s for s in ELLIPSIS.split(q) if s]
        if len(segments) > 1:
            return self._find_segments(segments)
        i = self.text.find(q)
        if i < 0:
            i = self.lower.find(q.lower())
        if i >= 0:
            return Match(*self.span(i, i + len(q)), exact=True)
        if len(q) < FUZZY_MIN_LEN:
            return None
        al = fuzz.partial_ratio_alignment(q, self.text, score_cutoff=FUZZY_THRESHOLD)
        if al is None:
            return None
        return Match(*self.span(al.dest_start, al.dest_end), exact=False)

    def _find_segments(self, segments: list[str]) -> Match | None:
        """A quote with '...' must match every segment, in order, within a few lines."""
        pos, first, last = 0, None, None
        for seg in segments:
            i = self.lower.find(seg.lower(), pos)
            if i < 0:
                return None
            first = i if first is None else first
            last, pos = i + len(seg), i + len(seg)
        a, b = self.span(first, last)
        return Match(a, b, exact=True) if b - a <= 8 else None


def clean_quote(quote: str) -> str:
    q = LINE_PREFIX.sub("", quote.strip())
    q = norm(q).strip("\"'`")
    return q.strip()
