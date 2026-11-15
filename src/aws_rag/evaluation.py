"""Reference validation, retrieval metrics and explicit manual answer review."""
from pathlib import Path
from datetime import datetime, timezone
from statistics import mean
import json
import platform
import sys
from .config import RagError
from .corpus import digest
from .generation import ask, SYSTEM
from .artifacts import public_artifact
from .indexing import atomic_json


def resolve_pointer(document, pointer):
    value = document
    for part in pointer.lstrip('/').split('/'):
        key = part.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def load_questions(path, source_root):
    questions = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    ids = set()
    for q in questions:
        if q['id'] in ids or not isinstance(q['answerable'], bool) or q.get('split') not in ('development', 'holdout'):
            raise RagError('Invalid question IDs, answerable flag or split')
        ids.add(q['id'])
        if not q['answerable']:
            continue
        source = Path(q['reference_source_path'])
        if source_root.resolve() not in source.resolve().parents:
            raise RagError('Evaluation reference lies outside configured corpus')
        try:
            doc = json.loads(source.read_text(encoding='utf-8'))
            value = resolve_pointer(doc, q['reference_locator'])
            content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            if q['reference_excerpt'] not in content:
                raise ValueError('Reference excerpt is not present at locator')
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise RagError(f'Invalid reference for question {q["id"]}: {exc}') from exc
    return questions


def rank_of_reference(q, retrieved):
    if not q['answerable']:
        return None
    for rank, item in enumerate(retrieved, 1):
        locator = item['source_locator']
        if item['source_path'] == q['reference_source_path'] and (
                q['reference_locator'] == locator or q['reference_locator'].startswith(locator + '/')):
            return rank
    return None


def evaluate(config, store, generator, manifest, report_path):
    rows = []
    questions = load_questions(config.questions, config.source_dir)
    started = datetime.now(timezone.utc).isoformat()
    for q in questions:
        result = ask(config, store, generator, q['question'], include_evidence=True)
        rank = rank_of_reference(q, result['retrieved'])
        rows.append(dict(question=q, result=result, rank=rank,
                         raw_response=getattr(generator, 'last_response', None),
                         response_metadata=getattr(generator, 'last_metadata', None),
                         review={'accuracy': None, 'groundedness': None, 'notes': None}))
        atomic_json(config.state_dir / 'evaluation_progress.json',
                    dict(started_at=started, completed=len(rows), total=len(questions), rows=rows))
        print(f"[{len(rows)}/{len(questions)}] {q['id']}: "
              f"abstained={result['abstained']}, generation={result['generation_seconds']:.2f}s",
              file=sys.stderr, flush=True)
    summaries = {}
    for split in ('development', 'holdout', 'all'):
        selected = [r for r in rows if split == 'all' or r['question']['split'] == split]
        positive = [r for r in selected if r['question']['answerable']]
        negative = [r for r in selected if not r['question']['answerable']]
        summaries[split] = dict(
            questions=len(selected), recall_at_k=mean(bool(r['rank']) for r in positive) if positive else None,
            mrr_at_k=mean(1 / r['rank'] if r['rank'] else 0 for r in positive) if positive else None,
            correct_abstention=mean(r['result']['abstained'] for r in negative) if negative else None,
            false_abstention=mean(r['result']['abstained'] for r in positive) if positive else None,
            retrieval_seconds=mean(r['result']['retrieval_seconds'] for r in selected) if selected else None,
            generation_seconds=mean(r['result']['generation_seconds'] for r in selected) if selected else None)
    payload = dict(started_at=started, evaluated_at=datetime.now(timezone.utc).isoformat(),
                   configuration={k: str(v) for k, v in vars(config).items()}, manifest=manifest,
                   generation_prompt_sha256=digest(SYSTEM),
                   questions_sha256=digest(config.questions.read_bytes()), hardware=platform.platform(),
                   summaries=summaries, rows=rows)
    artifact = config.state_dir / 'evaluation_results.json'
    atomic_json(artifact, payload)
    # This archival copy is safe to publish and cannot be used as a live manifest.
    public_path = report_path.with_suffix('.json')
    atomic_json(public_path, public_artifact(payload, config))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = ['# Dense retrieval baseline', '', f'Model: `{config.llm_model}`; top-k: {config.top_k}.',
              '', 'Retrieval metrics match the real section containing each reference.',
              'Latency excludes one-time model/index initialization; first-query warm-up is included.', '',
              '```json', json.dumps(summaries, indent=2), '```', '',
              '## Answer review', '',
              'Accuracy and claim-level grounding require review against excerpts. Not yet reviewed.',
              'Exact quote and citation validation is automatic, but does not prove that every claim follows.',
              f'Full answers, evidence, timings and blank review fields: `{public_path.name}`.', '',
              '## Errors and review samples', '']
    failures = [r for r in rows if (r['question']['answerable'] and (not r['rank'] or r['result']['abstained'])) or
                (not r['question']['answerable'] and not r['result']['abstained'])]
    for r in (failures or rows[:5]):
        report.extend([f"- {r['question']['id']}: {r['question']['question']}",
                       f"  Rank: {r['rank']}; answer: {r['result']['answer']}"])
    report.extend(['', 'Do not adopt hybrid/parent-child retrieval until a specific failure pattern is measured.',
                   'Review answers and abstentions before declaring the baseline sufficient.'])
    report_path.write_text('\n'.join(report) + '\n', encoding='utf-8')
    return summaries
