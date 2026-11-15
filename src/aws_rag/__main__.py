import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from .config import Config, RagError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local AWS documentation RAG (English)')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('inspect', 'ingest'):
        command = commands.add_parser(name)
        command.add_argument('--source-dir', type=Path)
        if name == 'ingest':
            command.add_argument('--force', action='store_true')
    command = commands.add_parser('ask')
    command.add_argument('question')
    command.add_argument('--json', action='store_true')
    command = commands.add_parser('retrieve', help='Show similar chunks without calling the LLM')
    command.add_argument('question')
    command.add_argument('--top-k', type=int)
    command.add_argument('--json', action='store_true')
    command = commands.add_parser('evaluate')
    command.add_argument('--validate-only', action='store_true')
    command.add_argument('--report', type=Path, default=Path('reports/evaluation_baseline.md'))
    args = parser.parse_args(argv)
    try:
        config = Config.load()
        if args.command == 'retrieve':
            if not args.question.strip():
                raise RagError('Question must not be empty')
            if args.top_k is not None:
                if args.top_k < 1:
                    raise RagError('top-k must be positive')
                config = replace(config, top_k=args.top_k)
        if getattr(args, 'source_dir', None):
            config = replace(config, source_dir=args.source_dir)
        config.validate_output()
        if args.command == 'inspect':
            from .corpus import inspect
            print(json.dumps(inspect(config.source_dir), indent=2))
        elif args.command == 'ingest':
            from .indexing import ingest
            print(json.dumps(ingest(config, config.source_dir, args.force), indent=2))
        else:
            if args.command == 'evaluate' and args.validate_only:
                from .evaluation import load_questions
                print(f'Validated {len(load_questions(config.questions, config.source_dir))} questions and source references.')
                return 0
            from .indexing import open_index, index_lock
            with index_lock(config):
                store, manifest = open_index(config)
                if args.command == 'retrieve':
                    from .retrieval import retrieve
                    hits, seconds = retrieve(store, args.question, config.top_k)
                    chunks = [dict(rank=rank, distance=float(distance),
                                   text=document.page_content, metadata=document.metadata)
                              for rank, (document, distance) in enumerate(hits, 1)]
                    if args.json:
                        print(json.dumps(dict(question=args.question, top_k=config.top_k,
                                              retrieval_seconds=seconds, chunks=chunks), indent=2))
                    else:
                        print(f'Retrieved {len(chunks)} chunks in {seconds:.3f}s (lower cosine distance is closer).')
                        for chunk in chunks:
                            meta = chunk['metadata']
                            print(f"\n[{chunk['rank']}] distance={chunk['distance']:.6f} "
                                  f"{meta['source_path']}#{meta['source_locator']}\n{chunk['text']}")
                    return 0
                from .generation import Generator, ask
                generator = Generator(config)
                if args.command == 'ask':
                    result = ask(config, store, generator, args.question)
                    if args.json:
                        print(json.dumps(result, indent=2))
                    else:
                        print(result['answer'])
                        for ref in result['references']:
                            for span in ref['spans']:
                                print(f"[{ref['label']}] {ref['source_path']}#{span['pointer']} (chars {span['start']}:{span['end']})")
                else:
                    from .evaluation import evaluate
                    if config.source_dir.resolve() in args.report.resolve().parents:
                        raise RagError('Report must be outside source directory')
                    print(json.dumps(evaluate(config, store, generator, manifest, args.report), indent=2))
        return 0
    except (RagError, ValueError, OSError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
