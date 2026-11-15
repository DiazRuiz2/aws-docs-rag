"""Evaluate the installed dense retriever offline, using a disposable index copy."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from time import perf_counter
import json
import os
import shutil
import tempfile

# This evaluation uses already installed local weights and never downloads.
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['ANONYMIZED_TELEMETRY'] = 'False'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('MKL_NUM_THREADS', '2')

from aws_rag.config import Config
from aws_rag.artifacts import public_artifact
from aws_rag.corpus import digest
from aws_rag.evaluation import load_questions, rank_of_reference
from aws_rag.indexing import open_index, index_lock
from aws_rag.retrieval import pack_context, retrieve

original = Config.load()
questions = load_questions(original.questions, original.source_dir)
rows = []
with tempfile.TemporaryDirectory(prefix='aws-rag-evaluation-') as directory:
    state = Path(directory)
    with index_lock(original):
        shutil.copytree(original.state_dir / 'chroma', state / 'chroma')
        shutil.copyfile(original.state_dir / 'index_manifest.json', state / 'index_manifest.json')
    # Reuse the installed Hugging Face cache when the model is configured by ID.
    # Changing the temporary state path must not trigger another model download.
    if (original.state_dir / 'models').is_dir():
        (state / 'models').symlink_to((original.state_dir / 'models').resolve(), target_is_directory=True)
    config = replace(original, state_dir=state)
    started = perf_counter()
    store, manifest = open_index(config)
    initialization_seconds = perf_counter() - started
    print(f'Loaded real BGE/Chroma: {len(manifest["chunk_ids"])} chunks', flush=True)
    for q in questions:
        hits, seconds = retrieve(store, q['question'], config.top_k)
        context, evidence = pack_context(hits, config.context_tokens)
        retrieved = [dict(source_path=d.metadata['source_path'],
                          source_locator=d.metadata['source_locator'], distance=float(score),
                          text=d.page_content) for d, score in hits]
        rank = rank_of_reference(q, retrieved)
        context_rank = rank_of_reference(q, [e.metadata for e in evidence])
        excerpt = q.get('reference_excerpt', '')
        rows.append(dict(question=q, rank=rank, context_rank=context_rank,
                         reference_excerpt_in_hits=any(excerpt in d.page_content for d, _ in hits) if q['answerable'] else None,
                         reference_excerpt_in_context=excerpt in context if q['answerable'] else None,
                         retrieval_seconds=seconds, retrieved=retrieved,
                         context=context, context_bytes=len(context.encode()),
                         evidence_count=len(evidence)))
        print(f'{q["id"]}: rank={rank}, context_rank={context_rank}, {seconds:.3f}s', flush=True)

summaries = {}
for split in ('development', 'holdout', 'all'):
    selected = [r for r in rows if split == 'all' or r['question']['split'] == split]
    positives = [r for r in selected if r['question']['answerable']]
    summaries[split] = dict(
        questions=len(selected), answerable=len(positives),
        **{f'recall_at_{config.top_k}': mean(bool(r['rank']) for r in positives),
           f'mrr_at_{config.top_k}': mean(1/r['rank'] if r['rank'] else 0 for r in positives)},
        reference_section_in_context=mean(bool(r['context_rank']) for r in positives),
        reference_excerpt_in_hits=mean(r['reference_excerpt_in_hits'] for r in positives),
        reference_excerpt_in_context=mean(r['reference_excerpt_in_context'] for r in positives),
        mean_retrieval_seconds=mean(r['retrieval_seconds'] for r in selected),
        mean_evidence_count=mean(r['evidence_count'] for r in selected))
payload = dict(evaluated_at=datetime.now(timezone.utc).isoformat(),
               mode='retrieval_only_real_embeddings_and_chroma',
               generation_status='Not run: this script measures retrieval only',
               initialization_seconds=initialization_seconds,
               configuration={k:str(v) for k,v in vars(original).items()},
               manifest=manifest, questions_sha256=digest(original.questions.read_bytes()),
               summaries=summaries, rows=rows)
Path('reports/retrieval_evaluation.json').write_text(
    json.dumps(public_artifact(payload, original), indent=2, ensure_ascii=False)+'\n')
print(json.dumps(summaries, indent=2), flush=True)
