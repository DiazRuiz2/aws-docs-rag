"""Runs against real local Chroma after uv sync; no embedding downloads required."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest

from aws_rag.config import Config
from aws_rag.indexing import ingest, read_manifest, store_for

try:
    from langchain_core.embeddings import Embeddings
    import langchain_chroma
    AVAILABLE = True
except ImportError:
    Embeddings = object
    AVAILABLE = False


class LocalTestEmbeddings(Embeddings):
    calls = 0

    def embed_documents(self, texts):
        self.calls += len(texts)
        return [[1., float(len(t) % 11) / 11., .5] for t in texts]

    def embed_query(self, text):
        return [1., float(len(text) % 11) / 11., .5]


class Tokenizer:
    def encode(self, text, add_special_tokens=True):
        return text.split() + ['<s>', '</s>']


@unittest.skipUnless(AVAILABLE, 'Real Chroma dependencies unavailable; run uv sync')
class ChromaIntegrationTests(unittest.TestCase):
    def test_persistence_reuse_and_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'data'
            (source / 'normalized').mkdir(parents=True)
            path = source / 'normalized/doc.json'
            shutil.copyfile('data/normalized/aws-cloud-definition.json', path)
            config = Config(source_dir=source, state_dir=root / 'state')
            embedding = LocalTestEmbeddings()

            class Provider:
                def __init__(self, config):
                    self.embeddings = embedding
                    self.tokenizer = Tokenizer()

            first = ingest(config, source, provider_factory=Provider)
            self.assertGreater(first['embedded_chunks'], 0)
            self.assertEqual(ingest(config, source, provider_factory=Provider)['embedded_chunks'], 0)
            manifest = read_manifest(config)
            store = store_for(config, manifest['collection'], embedding)
            hits = store.similarity_search_with_score('What is cloud computing?', k=1)
            self.assertEqual(hits[0][0].metadata['doc_id'], 'aws-cloud-definition')
            self.assertIn('/sections/0/blocks/0/text', hits[0][0].metadata['source_spans'])
            path.unlink()
            result = ingest(config, source, provider_factory=Provider)
            self.assertEqual(result['total_chunks'], 0)
            self.assertEqual(ingest(config, source, provider_factory=Provider)['embedded_chunks'], 0)
