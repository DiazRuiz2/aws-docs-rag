"""Record a real retrieval/generation run, without downloading models implicitly."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path

# Set before importing model integrations. Populate the cache using ingest first.
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['ANONYMIZED_TELEMETRY'] = 'False'
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('MKL_NUM_THREADS', '2')

from aws_rag.artifacts import public_artifact
from aws_rag.config import Config, RagError
from aws_rag.generation import Generator, ask
from aws_rag.indexing import atomic_json, index_lock, open_index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('question', nargs='?', default='How can S3 Versioning help recover objects?')
    parser.add_argument('--output', type=Path, default=Path('demo.json'))
    args = parser.parse_args()
    config = Config.load()
    config.validate_output()
    output = args.output.resolve()
    if output == config.source_dir.resolve() or config.source_dir.resolve() in output.parents:
        parser.error('Demo output must be outside the source corpus')
    if output == config.state_dir.resolve() or config.state_dir.resolve() in output.parents:
        parser.error('Demo output must be outside the live state directory')
    try:
        with index_lock(config):
            store, manifest = open_index(config)
            generator = Generator(config)
            result = ask(config, store, generator, args.question, include_evidence=True)
        payload = dict(recorded_at=datetime.now(timezone.utc).isoformat(),
                       question=args.question,
                       configuration={k: str(v) for k, v in vars(config).items()},
                       index_created_at=manifest['created_at'], result=result,
                       raw_response=generator.last_response,
                       response_metadata=generator.last_metadata)
        atomic_json(output, public_artifact(payload, config))
        print(result['answer'])
        print(f'Full chunks, context and citations saved to {args.output}')
    except (RagError, ValueError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
