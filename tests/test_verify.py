from receipts.files import chunk_lines
from receipts.verify import LineIndex

LINES = [
    "def connect(host, timeout=30):",
    "    \"\"\"Open a connection.\"\"\"",
    "    if timeout <= 0:",
    "        raise ValueError('timeout must be positive')",
    "    return Socket(host, timeout)",
]
IDX = LineIndex(LINES, first_line=100)


def test_exact_quote_gets_file_line_numbers():
    m = IDX.find("raise ValueError('timeout must be positive')")
    assert (m.start_line, m.end_line, m.exact) == (103, 103, True)


def test_multiline_quote_with_different_whitespace():
    m = IDX.find("if timeout <= 0:\n raise   ValueError('timeout must be positive')")
    assert (m.start_line, m.end_line) == (102, 103)


def test_copied_line_markers_are_stripped():
    m = IDX.find("L104| return Socket(host, timeout)")
    assert (m.start_line, m.exact) == (104, True)


def test_fabricated_quote_is_rejected():
    assert IDX.find("raise TimeoutError('connection timed out after 30 seconds')") is None


def test_short_inexact_quote_is_rejected():
    assert IDX.find("timeout=60") is None


def test_near_exact_long_quote_is_repaired_to_file_lines():
    m = IDX.find("raise ValueError(\"timeout must be positive\")")
    assert m is not None and not m.exact and m.start_line == 103


def test_ellipsis_segments_must_all_match_in_order():
    assert IDX.find("def connect(host, timeout=30): ... raise ValueError").start_line == 100
    assert IDX.find("raise ValueError ... def connect(host") is None


def test_chunks_overlap_and_cover_every_line():
    lines = [f"line {i} " + "x" * 40 for i in range(1000)]
    chunks = chunk_lines("f", lines, budget=500, overlap=10)
    assert chunks[0].first_line == 1 and chunks[-1].last_line == 1000
    for a, b in zip(chunks, chunks[1:]):
        assert b.first_line <= a.last_line  # overlap, no gaps
