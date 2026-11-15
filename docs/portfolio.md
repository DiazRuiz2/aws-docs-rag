# Portfolio notes

## CV (Spanish)

Desarrollo de un RAG local sobre documentación AWS con Python, LangChain, BGE,
Chroma y Ollama; ingesta incremental, chunking con trazabilidad y validación de
citas. Evaluación de recuperación con Recall@4 por sección del 100 % y MRR@4 de
0,925 sobre 20 preguntas con respuesta en un corpus de diez documentos.

## CV (English)

Built a local RAG pipeline over AWS documentation using Python, LangChain, BGE,
Chroma and Ollama, with incremental ingestion, source-traceable chunks and
citation validation. Measured section-level Recall@4 of 100% and MRR@4 of 0.925
on 20 answerable questions across a ten-document corpus.

## Technical discussion

- The input is a documentation snapshot, not a deployed AWS application.
- Chunk boundaries preserve sections and structured table rows. Every chunk
  retains exact source locations to make retrieval inspectable.
- Updates reuse unchanged vectors and publish a new collection atomically;
  queries reject stale sources rather than returning outdated citations.
- Retrieval and generation are measured independently. Real source quotes do
  not establish that all generated prose follows from the evidence.
- A small model and conservative validation can produce false abstentions.
  The recorded evaluation includes unsuccessful examples rather than hiding them.
- Dense search retrieved reference sections on this small set. There is no
  measured comparison demonstrating superiority to lexical/hybrid search.
- Tests cover lifecycle and failures; real Chroma integration uses deterministic
  vectors. Model evaluation is separate from those tests.

## Claims to avoid

Do not describe this as production-ready, cloud-deployed, hybrid retrieval,
zero-hallucination generation, or 100% answer accuracy. Retrieval metrics apply
only to the documented benchmark. Agent-assisted implementation and review are
identified in the reports; no independent human audit is claimed.

See [the measured results and generation review](../reports/evaluation_baseline.md)
and [the demo](demo.md) for evidence and limitations.
