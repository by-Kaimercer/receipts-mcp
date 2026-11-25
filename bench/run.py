"""Benchmark: Receipts (verified) against the same local model trusted as-is, on 40 questions with known answers.

Scoring is deterministic (no LLM judge): an answer is correct if every gold string appears in it (whole-word,
case-insensitive, citations stripped); evidence is a hit if a returned span overlaps the gold lines.

Usage (from the repo root):  python bench/run.py            -> results/bench.json and results/REPORT.md
"""
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("RECEIPTS_ROOTS", str(ROOT))
sys.path.insert(0, str(ROOT))

from receipts import config, core  # noqa: E402
from receipts.files import tokens  # noqa: E402
from receipts.verify import LineIndex  # noqa: E402

RESULTS = ROOT / "results"
VARIANTS = {"receipts": True, "trust": False}  # verify quotes or not; same model, same chunks, same prompts


def gold_spans(q):
    spans = []
    for ev in q["evidence"]:
        lines = (ROOT / ev["path"]).read_text(encoding="utf-8").splitlines()
        m = LineIndex(lines).find(ev["quote"])
        spans.append((Path(ev["path"]).name, m.start_line, m.end_line))
    return spans


def contains(text, ans):
    pat = re.escape(ans.lower())
    pat = (r"\b" if ans[0].isalnum() else "") + pat + (r"\b" if ans[-1].isalnum() else "")
    return re.search(pat, text.lower()) is not None


def score(q, r, verified):
    text = core.CITE.sub("", r.answer or "")
    answered = r.answer not in (None, "NOT_FOUND")
    if q["type"] == "unanswerable":
        correct = not answered
    else:
        correct = answered and all(contains(text, a) for a in q["answers"])
    hit = None
    if verified and q["type"] != "unanswerable":
        gold = gold_spans(q)
        hit = any(Path(e.path).name == g[0] and e.start <= g[2] and g[1] <= e.end for e in r.evidence for g in gold)
    return {"answered": answered, "correct": correct, "evidence_hit": hit}


def summarize(rows):
    ans = [r for r in rows if r["type"] != "unanswerable"]
    una = [r for r in rows if r["type"] == "unanswerable"]
    mean = lambda xs: round(statistics.mean(xs), 3) if xs else None  # noqa: E731
    hits = [r["evidence_hit"] for r in ans if r["evidence_hit"] is not None]
    return {
        "accuracy": mean([r["correct"] for r in rows]),
        "accuracy[answerable]": mean([r["correct"] for r in ans]),
        "accuracy[log]": mean([r["correct"] for r in ans if r["type"] == "log"]),
        "accuracy[code]": mean([r["correct"] for r in ans if r["type"] == "code"]),
        "refused_unanswerable": mean([not r["answered"] for r in una]),
        # wrong answers stated with confidence: answered, but incorrect (includes answering the unanswerable)
        "confident_wrong_rate": mean([r["answered"] and not r["correct"] for r in rows]),
        "evidence_hit": mean(hits) if hits else None,
        "quotes_proposed": sum(r["proposed"] for r in rows),
        "quotes_not_in_file": sum(r["rejected"] for r in rows),
        "fabricated_quote_rate": round(sum(r["rejected"] for r in rows) / max(1, sum(r["proposed"] for r in rows)), 3),
        "uncited_sentences_removed": sum(r["uncited_removed"] for r in rows),
        "input_tokens_total": sum(r["input_tokens"] for r in rows),
        "output_tokens_total": sum(r["output_tokens"] for r in rows),
        "latency_p50_s": round(statistics.median(r["secs"] for r in rows), 1),
    }


def main():
    qs = [json.loads(line) for line in open(ROOT / "bench/questions.jsonl", encoding="utf-8") if line.strip()]
    RESULTS.mkdir(exist_ok=True)
    out = {"model": config.MODEL, "max_chunks": config.ASK_CHUNKS, "variants": {}}
    for name, verify in VARIANTS.items():
        rows = []
        for n, q in enumerate(qs, 1):
            t0 = time.perf_counter()
            r = core.ask(q["paths"], q["question"], verify=verify)
            secs = time.perf_counter() - t0
            text = core.render(r)
            row = {"id": q["id"], "type": q["type"], "question": q["question"], "gold": q["answers"],
                   "answer": r.answer, **score(q, r, verify), "proposed": r.proposed, "rejected": r.rejected,
                   "uncited_removed": r.uncited_removed, "rejected_quotes": r.rejected_quotes,
                   "input_tokens": r.tokens_total, "output_tokens": tokens(text), "secs": round(secs, 1)}
            rows.append(row)
            print(f"[{name}] {n}/{len(qs)} {q['id']:9s} correct={row['correct']!s:5} hit={row['evidence_hit']} "
                  f"rejected={r.rejected}/{r.proposed} {secs:.0f}s", flush=True)
        out["variants"][name] = {"summary": summarize(rows), "rows": rows}
        print(name, json.dumps(out["variants"][name]["summary"]), flush=True)
    # "trust" reuses the cached proposals, so its fabrication counts are computed from the receipts run
    s_t, s_r = out["variants"]["trust"]["summary"], out["variants"]["receipts"]["summary"]
    s_t["quotes_not_in_file"], s_t["fabricated_quote_rate"] = s_r["quotes_not_in_file"], s_r["fabricated_quote_rate"]
    (RESULTS / "bench.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    report(out)


def report(out):
    cols = ["accuracy", "accuracy[log]", "accuracy[code]", "refused_unanswerable", "confident_wrong_rate",
            "evidence_hit"]  # latency is in bench.json; it is meaningless once the model calls are cached
    lines = [f"# Receipts benchmark ({out['model']}, {out['max_chunks']} chunks per question)\n",
             "| Variant | " + " | ".join(cols) + " |", "|---|" + "---:|" * len(cols)]
    for name, v in out["variants"].items():
        s = v["summary"]
        lines.append(f"| {name} | " + " | ".join("–" if s[c] is None else str(s[c]) for c in cols) + " |")
    s = out["variants"]["receipts"]["summary"]
    lines += ["", f"Quotes proposed by the model: {s['quotes_proposed']}; not found in the file: "
              f"{s['quotes_not_in_file']} ({s['fabricated_quote_rate']:.1%}). Answer sentences removed because a detail "
              f"was not in the verified quotes: "
              f"{s['uncited_sentences_removed']}.",
              f"Tokens: ~{s['input_tokens_total']:,} of file text handled locally, ~{s['output_tokens_total']:,} "
              f"returned ({1 - s['output_tokens_total'] / s['input_tokens_total']:.1%} fewer)."]
    (RESULTS / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
