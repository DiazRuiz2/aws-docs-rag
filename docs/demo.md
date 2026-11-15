# Recorded local demo

This example was executed against the real persisted index and local Ollama.
It is an observed run, not a fabricated expected response.

Recorded: 2026-11-15T17:32:33.538936+00:00 (UTC).

## Reproduce

Follow the README quick start to install dependencies, download models and ingest.
Start `ollama serve` in another terminal, then run:

```bash
uv run python -m aws_rag retrieve "What version ID do existing objects have when bucket versioning is first enabled?" --top-k 4
uv run python scripts/demo.py "What version ID do existing objects have when bucket versioning is first enabled?" --output demo.json
```

The demo writes raw top-k chunks, exact filtered context, selected evidence,
answer, citations, model output and timing to JSON. It does not download models
implicitly. For an already provisioned external runtime, the equivalent is
`python3 scripts/local.py demo "<question>" --output demo.json`.

## Retrieved chunks

| Rank | Cosine distance | Source section |
| --- | ---: | --- |
| 1 | 0.158767 | `data/normalized/aws-s3-overview.json#/sections/15` |
| 2 | 0.237696 | `data/normalized/aws-s3-overview.json#/sections/14` |
| 3 | 0.292544 | `data/normalized/aws-s3-overview.json#/sections/20` |
| 4 | 0.306203 | `data/normalized/aws-s3-overview.json#/sections/13` |

Lower distance means closer. The first chunk contains:

```text
What is Amazon S3? > How Amazon S3 works > Version ID

When you enable S3 Versioning in a bucket, Amazon S3 generates a unique version ID for each object added to the bucket. Objects that already existed in the bucket at the time that you enable versioning have a version ID of null. If you modify these (or any other) objects with other operations, such as CopyObject and PutObject, the new objects get a unique version ID.

For more information, see Retaining multiple versions of objects with S3 Versioning.
```

4 chunks survived deduplication and the context budget in this run.

## Generated answer

> When bucket versioning is first enabled, existing objects have a version ID of null.

Validated supporting quote:

> Objects that already existed in the bucket at the time that you enable versioning have a version ID of null.

Source: `data/normalized/aws-s3-overview.json#/sections/15/blocks/0/text`.

Retrieval: 0.575 s. Generation: 19.16 s.
Model/index initialization is outside these timings. Values depend on hardware
and warm-up state; model builds may change future output.

[Complete recorded demo JSON](demo.json) includes all chunks and source spans.

## A real failure: retrieval succeeds, quote validation rejects the draft

The full evaluation also asked:

> How can S3 Versioning help recover objects?

Its first retrieved evidence contains `in the same bucket`. The model instead
quoted `in your buckets`, so the validator rejected the draft and returned:

> This is not stated in the supplied documentation.

The intended answer was present in the context. This failure is generation /
literal-quote compliance, not a missing retrieved reference.

A separate concurrent-write example (q10) passed quote validation but added an
unsupported conclusion. Literal citations therefore do not guarantee semantic
grounding. Both cases are retained in the [full evaluation](../reports/evaluation_baseline.md)
and [all raw outputs](../reports/generation_evaluation.json).
