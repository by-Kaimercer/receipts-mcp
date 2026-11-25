# Receipts

**An MCP server that lets Claude hand big files to a local model, and only accepts answers that come with receipts.**

Reading a 130k-token log or a 3,000-line source file to find one fact burns Claude's context. Offloading the
reading to a small local model saves those tokens, but a 7B model will happily invent a quote, a line number or a
value. Receipts makes that offload trustworthy:

1. A local model (Ollama, `qwen2.5:7b` by default) reads the relevant parts of the files and proposes **verbatim quotes**.
2. Receipts **locates every quote in the real file**. Quotes that are not there are thrown away. Line numbers are
   computed by Receipts, never taken from the model, and the text returned is always the file's own text.
3. The short answer is written from the surviving quotes only, then **every sentence is checked**: each specific
   detail in it (numbers, identifiers, versions, quoted strings) must appear in the verified quotes, or the sentence
   is removed.

Claude gets a few hundred tokens back: an answer, `file:line` evidence it can trust, and a coverage line saying how much
of the input was read and how many quotes were rejected.

## Results

`bench/` holds 40 questions with known answers over a 6,000-line service log (~131k tokens, generated with planted
events) and five CPython source files: 15 log questions, 17 code questions and 8 plausible questions whose answer is
not in the files. Scoring is deterministic, with no LLM judge: an answer is correct if it contains every gold value.
The baseline, **trust**, is the same model reading the same chunks with the same prompts, with no verification and no
grounding, i.e. what you get from an offload server that passes the local model's answer straight through.

| | Receipts | Trust the model |
|---|---:|---:|
| Correct answers (40 questions) | 65% | 65% |
| **Confident wrong answers** (answered, but wrong) | **7.5%** | 12.5% |
| Unanswerable questions refused | 100% | 100% |
| Quotes the model invented (not in the file) | **all 7 caught** | 7 of 60 passed on to Claude |
| Tokens returned vs. file text handled | ~5.6k vs ~2.9M | same |

What the numbers say:

- **Verification doesn't make a 7B model smarter; it makes its mistakes visible.** Accuracy is unchanged, but
  confident wrong answers drop by 40%, and 11.7% of the quotes the model proposed did not exist in the files. Without
  verification those fabrications reach Claude looking like evidence.
- **The remaining wrong answers come from real but wrong evidence.** For "how long did the slow ledger query take?",
  the model quoted a genuine slow-query line, just the wrong one. Every quote Claude sees is real, so this kind of
  error can be spotted by reading the quote, which is the point of returning receipts.
- **The bottleneck is the small model's extraction, not verification.** The gold lines were among the returned
  evidence for 66% of answerable questions. Most misses are the 7B model not proposing the right line from a chunk it
  did read, plus some paraphrased questions where keyword ranking picked other chunks of the 26-chunk log. A larger
  local model or embedding-based chunk ranking are the obvious next steps, and `bench/run.py` measures both.
- Uncached, a question takes about 16 s median on an RTX 5050 laptop GPU (8 GB) with four ~6k-token chunks.

Getting here took two rounds of fixing the measurement, not the model. The first grounding rule dropped any sentence
without a citation, which threw away correct answers like `Extra data` that the model simply forgot to cite; the
current rule checks the sentence's content against the quotes instead of trusting or demanding citations.

## Tools

| Tool | What it does |
|---|---|
| `ask_files(paths, question, max_chunks=4)` | Answers a question about files, directories or globs. BM25 picks the best-matching ~6k-token chunks; the local model reads them; verified quotes and a grounded answer come back. |
| `extract_from_files(paths, what, max_items=30)` | "Find every X": reads all chunks (up to ~240k tokens) and returns every verified match with `file:line`. |
| `token_savings()` | Tokens of file text handled locally versus tokens returned, for the last 24 hours and all time. |

Example output of `ask_files(["bench/corpus/app.log"], "Which replica was promoted to primary during the database failover?")`:

```text
Answer (qwen2.5:7b, written from the verified evidence only): replica-db-3 [1]

Evidence (each quote was located in the file; text and line numbers are the file's own):
[1] bench/corpus/app.log:905: Identifies the new primary after a database failover
    2026-03-14T03:42:29.877Z WARN  db      failover complete: promoted replica-db-3 to primary, old primary db-primary-1 fenced

Read 4 of 26 chunks (~20,944 of ~130,845 tokens). Model proposed 1 quotes: 1 verified, 0 rejected as not in the file.
```

## How verification works

- **Quote matching** (`receipts/verify.py`): whitespace-normalised exact match, then case-insensitive, then quotes
  with `...` matched segment by segment in order within a few lines. Quotes of 24+ characters may match fuzzily
  (RapidFuzz partial ratio ≥ 92), but the evidence shown is then the file's lines, labelled as a near-exact match.
  Copied `L123|` line markers are stripped. Short quotes must match exactly, because fuzzy matching on short strings
  finds false positives.
- **Answer grounding** (`receipts/core.py`, `ground`): the model's citations are not trusted on their own. A sentence
  survives only if all its specific details appear in the verified quotes (numbers are compared with thousands
  separators removed); citations are then attached to the quotes that contain them. Sentences with no checkable
  detail survive only with a valid citation.
- **What it can't catch**: a sentence that uses only true details but draws the wrong conclusion from them. The
  quotes are there so Claude can check that itself.

## Setup

```bash
ollama pull qwen2.5:7b          # any Ollama chat model works; set RECEIPTS_MODEL to change it
pip install git+https://github.com/by-Kaimercer/receipts-mcp
```

**Claude Code** (run in your project; the server may read files under the directory it starts in):

```bash
claude mcp add receipts -- receipts-mcp
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "receipts": {
      "command": "receipts-mcp",
      "env": { "RECEIPTS_ROOTS": "/path/to/project" }
    }
  }
}
```

| Variable | Default | Meaning |
|---|---|---|
| `RECEIPTS_ROOTS` | working directory | Directories the server may read (`os.pathsep`-separated). Anything outside is refused. |
| `RECEIPTS_MODEL` | `qwen2.5:7b` | Ollama model. |
| `RECEIPTS_NUM_CTX` | `16384` | Model context window. |
| `RECEIPTS_CHUNK_TOKENS` | `6000` | Chunk size; keep it well under `NUM_CTX`. |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server. |

If Ollama is down or the model isn't pulled, tools return an error saying exactly what to run.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest tests            # verification and grounding unit tests
python tests/e2e_stdio.py         # spawns the server over stdio with the MCP client and calls every tool
python bench/check_questions.py   # validates the benchmark's gold answers and quotes
python bench/run.py               # runs the benchmark -> results/bench.json, results/REPORT.md
```

Model calls are cached in `~/.receipts/cache.sqlite` (temperature 0), so benchmark reruns are fast and repeatable.

## License

MIT. The CPython files in `bench/corpus/stdlib/` are under the PSF License.
