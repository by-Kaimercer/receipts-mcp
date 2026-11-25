# Receipts benchmark (qwen2.5:7b, 4 chunks per question)

| Variant | accuracy | accuracy[log] | accuracy[code] | refused_unanswerable | confident_wrong_rate | evidence_hit |
|---|---:|---:|---:|---:|---:|---:|
| receipts | 0.65 | 0.667 | 0.471 | 1 | 0.075 | 0.656 |
| trust | 0.65 | 0.667 | 0.471 | 1 | 0.125 | – |

Quotes proposed by the model: 60; not found in the file: 7 (11.7%). Answer sentences removed because a detail was not in the verified quotes: 2.
Tokens: ~2,919,665 of file text handled locally, ~5,583 returned (99.8% fewer).
