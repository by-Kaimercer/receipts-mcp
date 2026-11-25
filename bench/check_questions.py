"""Validate bench/questions.jsonl against the corpus. Exit non-zero on any failure."""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # receipts-mcp folder; question paths are relative to it
TYPES = {"log", "code", "unanswerable"}


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def main():
    errors = []
    questions = []
    with open(os.path.join(HERE, "questions.jsonl"), encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                try:
                    questions.append(json.loads(line))
                except json.JSONDecodeError as e:
                    errors.append(f"line {n}: invalid JSON: {e}")

    texts = {}

    def file_text(p):
        if p not in texts:
            with open(os.path.join(ROOT, p), encoding="utf-8") as fh:
                texts[p] = norm(" ".join(fh.read().split("\n")))
        return texts[p]

    seen = set()
    counts = {t: 0 for t in TYPES}
    for q in questions:
        qid = q.get("id", "?")
        for k in ("id", "type", "paths", "question", "answers", "evidence"):
            if k not in q:
                errors.append(f"{qid}: missing field {k}")
        if qid in seen:
            errors.append(f"{qid}: duplicate id")
        seen.add(qid)
        t = q.get("type")
        if t not in TYPES:
            errors.append(f"{qid}: bad type {t!r}")
        else:
            counts[t] += 1
        paths = q.get("paths", [])
        if not paths:
            errors.append(f"{qid}: no paths")
        for p in paths:
            if not os.path.isfile(os.path.join(ROOT, p)):
                errors.append(f"{qid}: path does not exist: {p}")
        quotes = []
        for e in q.get("evidence", []):
            p, quote = e.get("path"), e.get("quote", "")
            if p not in paths:
                errors.append(f"{qid}: evidence path {p} not in paths")
            if not os.path.isfile(os.path.join(ROOT, p or "")):
                errors.append(f"{qid}: evidence file missing: {p}")
                continue
            if not norm(quote) or norm(quote) not in file_text(p):
                errors.append(f"{qid}: quote not found verbatim in {p}: {quote[:80]!r}")
            quotes.append(norm(quote).lower())
        if t == "unanswerable":
            if q.get("answers") or q.get("evidence"):
                errors.append(f"{qid}: unanswerable must have empty answers/evidence")
        else:
            if not q.get("answers"):
                errors.append(f"{qid}: no gold answers")
            if not q.get("evidence"):
                errors.append(f"{qid}: no evidence")
            for a in q.get("answers", []):
                if not any(a.lower() in qt for qt in quotes):
                    errors.append(f"{qid}: answer {a!r} not in any evidence quote")

    print("Unanswerable questions (eyeball these):")
    for q in questions:
        if q.get("type") == "unanswerable":
            print(f"  {q['id']}: {q['question']}")
            print(f"      files: {', '.join(q['paths'])}")

    print(f"\nTotal: {len(questions)}  " + "  ".join(f"{t}={counts[t]}" for t in sorted(TYPES)))
    if errors:
        print(f"\nFAILED with {len(errors)} error(s):")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
