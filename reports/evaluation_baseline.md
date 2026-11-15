# Local RAG evaluation: retrieval and generation

Run: 2026-11-15T17:19:15.412734+00:00 to 2026-11-15T17:30:08.765400+00:00 (UTC).

Real BGE embeddings, persisted Chroma, and local Ollama `qwen3:1.7b` were used.
The index contains 96 chunks from 10 documents. All 23 questions were executed
sequentially with the existing prompt and configuration. No parameters were
tuned after inspecting development or holdout outputs.

## Automatic measurements

| Metric | Development | Holdout | All |
| --- | ---: | ---: | ---: |
| Questions | 17 | 6 | 23 |
| Section Recall@4 | 1.0000 | 1.0000 | 1.0000 |
| Section MRR@4 | 0.9667 | 0.8000 | 0.9250 |
| Correct abstention rate (out of coverage) | 1.0000 | 1.0000 | 1.0000 |
| False abstention rate (answerable) | 0.4667 | 0.6000 | 0.5000 |
| Mean retrieval latency (s) | 0.0789 | 0.0569 | 0.0732 |
| Mean generation latency (s) | 28.63 | 27.36 | 28.30 |

Denominators: development has 15 answerable and 2 out-of-coverage questions;
holdout has 5 answerable and 1 out-of-coverage question. Recall/MRR match the
section containing the reference, not every claim or individual chunk.

These per-query latencies exclude BGE/index initialization. Generation includes
the first Ollama model load. They are local CPU measurements, not a serving SLA.
The earlier retrieval-only run separately measured 123.24 s initialization and
0.0556 s average retrieval. Do not confuse retrieval time with end-to-end latency.

## Answer and grounding review

The implementation agent reviewed all emitted answers against reference excerpts
and the exact context sent to the generator. This is **not independent human
review**. The rubric allows faithful paraphrases and direct implications; a
correct core with unsupported material or contradictory wording is partial.
An abstention on an answerable question is a failure.

| Outcome on 20 answerable questions | Count |
| --- | ---: |
| Correct and fully supported | 7 |
| Partial / unsupported or ambiguous addition | 2 |
| Incorrect / contradictory conclusion | 1 |
| False abstention | 10 |

**Strict agent-reviewed answer accuracy: 7/20 (35%).** Of the ten non-abstained
answers, seven were fully supported under this rubric. All three out-of-coverage
questions produced correct abstentions. The sample is too small to establish
general performance, and its questions were authored by an implementation agent.

All ten positive abstentions were validation rejections: nine drafts contained
a non-verbatim quote, and one omitted the required support array. The model
itself returned `answerable=true` in those ten cases. Recovery is therefore
limited by generation/format compliance even when retrieval provides evidence.

## Per-question review

| ID | Split | Final outcome | Grounding | Review notes |
| --- | --- | --- | --- | --- |
| q01 | development | false_abstention | not_applicable | False abstention: the S1 definition is present, but the S3 cost-tools quote is rewritten and fails literal matching. |
| q02 | development | partial | partially_supported | Core IAM purpose is correct, but saying IAM creates identities like the root user is unsupported. The context says the root identity originates when creating the AWS account. |
| q03 | development | correct | fully_supported | Correct recommendation and full-access description. IAM alternatives appear in S1; the misuse-risk wording is treated as a direct implication of unrestricted access. |
| q04 | holdout | correct | fully_supported | Correct: IAM is eventually consistent. The answer and quoted passage agree. |
| q05 | development | partial | partially_supported | The no-additional-charge statement is correct, but the leading Yes conflicts with the question asking whether there is an additional charge. Marked partial for contradictory polarity. |
| q06 | development | correct | fully_supported | Correct and fully supported: S3 is object storage. |
| q07 | development | false_abstention | not_applicable | False abstention: the answer is in S1, but the quote changes in the same bucket to in your buckets. |
| q08 | holdout | correct | fully_supported | Correct and fully supported: objects already present receive the null version ID. |
| q09 | development | correct | fully_supported | Correct and fully supported: single-key updates are atomic. S2 contains the literal supporting passage. |
| q10 | development | incorrect | contradicted | Incorrect added conclusion: the response first says latest timestamp wins, then says the second PUT is ignored and the first is retained. The latter is neither supported nor implied by atomicity. |
| q11 | development | false_abstention | not_applicable | False abstention: S3 Standard is present, but at least one submitted quote invents or rewrites text. |
| q12 | development | false_abstention | not_applicable | False abstention: cost optimization is present, but the quoted sentence removes wording from the source and is not verbatim. |
| q13 | holdout | false_abstention | not_applicable | False abstention: the size/duration reference is retrieved, but the long quote joins list and paragraph text using different whitespace. |
| q14 | development | false_abstention | not_applicable | False abstention: the rendered row has Availability Zones: 1, but the quote concatenates nonadjacent fields into a new string. |
| q15 | development | correct | fully_supported | Correct and fully supported: Domain 1 is 24% in the snapshot. |
| q16 | development | correct | fully_supported | Correct and fully supported: Domain 2 is 30% in the snapshot. |
| q17 | development | false_abstention | not_applicable | False abstention: 34% is present, but the model combines heading and body into a sentence not present verbatim. |
| q18 | holdout | false_abstention | not_applicable | False abstention: 12% is present, but the quote changes the domain-description sentence. |
| q19 | development | false_abstention | not_applicable | False abstention: the concepts list is present, but the model omits the required support array. |
| q20 | holdout | false_abstention | not_applicable | False abstention: compute services are present, but the quote changes heading/list whitespace and references an additional source. |
| q21 | development | correct_abstention | not_applicable | Correct abstention: no workload specification or exact monthly bill is provided. |
| q22 | holdout | correct_abstention | not_applicable | Correct abstention: no PostgreSQL streaming-replication setup procedure is provided. |
| q23 | development | correct_abstention | not_applicable | Correct abstention: the corpus contains no live weather data. |

## Failure examples

- **q07, S3 Versioning:** the source says `in the same bucket`; the model quoted
  `in your buckets`. Literal quote validation rejected the otherwise relevant draft.
- **q10, concurrent writes:** citations are real, but the answer adds that the
  second PUT is ignored and the first retained. That conclusion contradicts
  the latest-timestamp rule and is not entailed by atomicity.
- **q19, exam concepts:** relevant concepts are retrieved, but the response omits
  `support`, so the final answer becomes an abstention.

The pipeline is suitable as an inspectable portfolio prototype. This generator
baseline does **not** meet a reliable answer-quality acceptance criterion.
A next experiment should improve structured-output and literal-quote compliance
on development examples, followed by a newly authored independent test set.
No retrieval failure in this small benchmark justifies adding hybrid search
or reranking without a separate comparison.

## Artifacts and reproducibility

- [Full generation artifact](generation_evaluation.json): all 23 questions,
  raw model drafts, final answers, exact contexts, evidence, citations, model
  response metadata, timings, manifest and explicit review labels.
- [Earlier retrieval-only artifact](retrieval_evaluation.json): raw retrieved
  chunks, context and reference checks, with no LLM calls.
- [Recorded demo](../docs/demo.md): a successful answer and an observed rejection.

Absolute checkout/runtime prefixes are replaced with `<project>` and
`<state_dir>` in published copies. The original runtime artifacts and live
index are preserved. Published manifests are archival, not reusable live state.
The generation prompt hash and configuration are included. Model tags/revisions
are mutable, so this documents an observed run rather than guaranteeing bitwise
reproduction on future downloads.

```bash
uv run python -m aws_rag evaluate --validate-only
uv run python scripts/evaluate_retrieval.py
# Start ollama serve in another terminal before this command:
uv run python -m aws_rag evaluate
```

`evaluate` records fresh results and overwrites this report with an unreviewed
automatic summary; it does not reproduce the qualitative judgments automatically.
The recorded agent review remains in `generation_evaluation.json`. The command
now also exports a portable `evaluation_baseline.json` beside its fresh report.
Evaluation checkpoints each completed question in the configured runtime.

See [CI](../.github/workflows/ci.yml) for model-free checks. Hosted CI has not
been run in this workspace; it starts after pushing the repository to GitHub.
