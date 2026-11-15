# Corpus discovery — 2026-11-12

Phase 0 completed before implementing the document loader. All 44 files were read
as bytes, hashed, decoded as UTF-8 and, where applicable, parsed as JSON. No source
was changed. The directory contains 825,067 bytes, not 825 KB of unique prose.

| Group | Files | Verified role | Selection |
| --- | ---: | --- | --- |
| `imports/*.md` | 11 | Imported AWS Markdown, 10 distinct byte hashes | Exclude duplicate representations |
| `raw/*/*.md` | 10 | Archived copies; hashes match normalized `raw_sha256` in all 10 cases | Exclude duplicate representations |
| `raw/*/metadata.json` | 10 | Provenance, URL, retrieval time and raw hash | Exclude; no documentary body |
| `normalized/*.json` | 10 | English normalized documents, schema `1.0` | Select after structural validation |
| `chunks/chunks.json` | 1 | Earlier `aws-structure-parent-child-v1`, 83 parents, 112 children | Exclude derived chunks; preserve untouched |
| `state.json` | 1 | Historical raw/normalized hashes | Exclude processing state |
| `import_report.json` | 1 | Import statuses and source hashes | Exclude processing report |

All files are UTF-8; JSON files have object roots, not arrays or JSONL. No empty,
binary or corrupt files were observed. `cloud-practitioner-02-domain4 (1).md`
duplicates `cloud-practitioner-02-domain4.md` byte for byte. Ten raw Markdown
files duplicate the ten unique imports. No extra documentary material was found
outside the normalized representation.

## Observed schema and units

Every normalized file has `schema_version`, `document_id`, `title`, `language`,
`document_type`, `source`, `retrieved_at`, `raw_sha256`, `normalized_sha256`,
`exam_domains`, `aws_services`, `sections`, `warnings`. `source` contains
`canonical_url`, `retrieval_url`, `source_format`, `license`, `attribution`.
Sections have existing `section_id`, `heading_path`, `anchor_url`, `blocks`.
Blocks have `type`, `text`, `links`, sometimes `attributes`.

| Document ID | Sections | Blocks | Characters in block text |
| --- | ---: | ---: | ---: |
| aws-cloud-definition | 1 | 2 | 1,176 |
| aws-iam-overview | 1 | 17 | 4,208 |
| aws-s3-overview | 30 | 97 | 33,964 |
| aws-s3-storage-classes | 8 | 43 | 15,079 |
| clf-d1 | 5 | 19 | 1,864 |
| clf-d2 | 5 | 19 | 3,045 |
| clf-d3 | 9 | 35 | 5,004 |
| clf-d4 | 4 | 15 | 2,819 |
| clf-in-scope | 20 | 22 | 3,095 |
| clf-technologies | 1 | 2 | 1,036 |

There are 84 sections (83 nonempty), 271 blocks: 168 paragraphs, 85 lists,
14 admonitions, 3 image references and 1 table. Text totals 71,290 characters,
roughly 18k tokens using a character/4 heuristic, excluding structured table rows
and heading repetition. Actual model token counts are measured during ingest.
Median block length is 198 characters, maximum 2,277. There are no code blocks.

The table's `text` contains only column headers. Its substantive cells live in
`attributes.columns` and `attributes.rows`: these must be extracted explicitly.
Image references contain captions and remote URLs, not local image content;
captions may be indexed but images are never downloaded or interpreted.

Examples inspected include all section and block schemas across all ten JSON
files, full raw/normalized provenance, IAM's identity paragraphs, S3 versioning,
consistency, storage tiers, the complete storage-class table, and the four exam
domain outlines. Exam outlines describe topics, not complete operational guides.

## Extraction and chunking decision

Use only structurally verified schema-1.0 English documents under `normalized/`.
Unknown files remain visible in the inventory and are excluded conservatively.
Malformed candidate documents fail ingestion rather than silently removing an
old indexed source. New documents using the same schema are supported.

One section is the retrieval unit until it needs subdivision. Keep headings from
the real `heading_path`. Pack whole blocks within each section, with no overlap
between whole blocks: most blocks are short and repeated evidence wastes the
small context window. Use an initial 440-token ceiling (including heading) with
the embedding model tokenizer, below BGE's 512-token limit. Split oversized
paragraphs/lists at sentence/newline/word boundaries with 40-token overlap;
record character offsets in the original text. Preserve table rows as atomic
units with their real column labels repeated; oversized atomic rows fail clearly
rather than silently truncating. Never cross document/section boundaries.

Example citations:

- `data/normalized/aws-s3-overview.json#/sections/14/blocks/0/text` is the actual
  S3 Versioning paragraph; its section ID ends in `#s3-versioning-1`.
- `data/normalized/aws-s3-storage-classes.json#/sections/7/blocks/1/attributes/rows/0`
  is the first table row (S3 Standard), discovered from the actual structure.
- IAM uses `data/normalized/aws-iam-overview.json#/sections/0/blocks/0/text`.

Chunk metadata includes real JSON Pointers, source text offsets, section ID,
document ID, source file SHA-256 and a deterministic chunk ID. File bytes are
hashed independently; the preexisting `normalized_sha256` is not assumed to be
a hash of the current JSON serialization. Configuration/model/parser/chunking
signatures control invalidation. Artifacts go under `.rag_state/` only.

## Limits and unresolved points

All normalized documents carry warnings about a limited Markdown parser and a
Draft-7 fallback validator. This implementation validates the observed structure
and preserves those warnings; it does not claim the original normalization is
perfect. Original URLs are provenance strings only; no remote AWS content is
fetched. Copyright/license metadata is retained as supplied, not independently
verified. Dates and contents are a local snapshot, not current AWS guidance.

The execution environment has Python 3.10.12 and about 7.6 GiB RAM, but no uv,
Ollama, Chroma, LangChain or embedding weights. DNS from the shell currently
fails. Real embedding/generation measurements require installing dependencies
and local models; test doubles must never be reported as a model baseline.
