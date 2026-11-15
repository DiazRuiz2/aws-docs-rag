import copy
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from aws_rag.config import Config, RagError
from aws_rag.corpus import extract, load_corpus, inspect, digest
from aws_rag.chunking import chunk_sections, Chunk
from aws_rag.indexing import ingest, index_lock, open_index
from aws_rag.retrieval import pack_context, Evidence
from aws_rag.generation import validate_answer, ABSTENTION, ask
from aws_rag.evaluation import load_questions, resolve_pointer, rank_of_reference, evaluate
from aws_rag.__main__ import main
from aws_rag.artifacts import public_artifact


class Tokenizer:
    def encode(self, text, add_special_tokens=True):
        return list(range(len(re.findall(r'\w+|[^\w\s]', text)))) + ([0, 0] if add_special_tokens else [])


class Embeddings:
    calls = 0
    def embed_documents(self, texts):
        self.calls += len(texts)
        return [[float(len(t)), 1.] for t in texts]


class Provider:
    def __init__(self, config):
        self.tokenizer = Tokenizer()
        self.embeddings = embeddings


class Store:
    databases = {}
    def __init__(self, config, collection, embeddings=None):
        self.name = collection
        self.rows = self.databases.setdefault(collection, {})
        self._collection = self
    def upsert(self, ids, documents, metadatas, embeddings):
        self.rows.update({k: (d, m, e) for k, d, m, e in zip(ids, documents, metadatas, embeddings)})
    def get(self, ids, include):
        ids = [k for k in ids if k in self.rows]
        return dict(ids=ids, documents=[self.rows[k][0] for k in ids], metadatas=[self.rows[k][1] for k in ids], embeddings=[self.rows[k][2] for k in ids])
    def delete_collection(self):
        del self.databases[self.name]


embeddings = Embeddings()


class CorpusTests(unittest.TestCase):
    def test_inventory(self):
        result = inspect(Path('data'))
        self.assertEqual((result['files'], result['documents'], result['sections']), (44, 10, 83))
        self.assertEqual(sum(r.get('role') == 'derived chunks (excluded)' for r in result['inventory']), 1)

    def test_rows_and_provenance(self):
        sections = extract(Path('data/normalized/aws-s3-storage-classes.json'))
        rows = [u for s in sections for u in s.units if u.atomic]
        self.assertEqual(len(rows), 9)
        self.assertIn('99.99%', rows[0].text)
        self.assertEqual(rows[0].locator, '/sections/7/blocks/1/attributes/rows/0')

    def test_chunk_source_spans(self):
        sections = load_corpus(Path('data'))
        chunks = chunk_sections(sections, Tokenizer(), 440, 40)
        self.assertTrue(chunks)
        self.assertEqual(len({c.metadata['chunk_id'] for c in chunks}), len(chunks))
        for chunk in chunks:
            self.assertLessEqual(len(Tokenizer().encode(chunk.page_content)), 440)
            doc = json.loads(Path(chunk.metadata['source_path']).read_text())
            for span in json.loads(chunk.metadata['source_spans']):
                value = resolve_pointer(doc, span['pointer'])
                if isinstance(value, str):
                    self.assertIn(value[span['start']:span['end']], chunk.page_content)
                else:
                    for cell in value:
                        self.assertIn(cell, chunk.page_content)

    def test_reject_bad_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'bad.json'
            p.write_text('{"schema_version":"99"}')
            with self.assertRaises(RagError):
                extract(p)

    def test_unknown_block_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'doc.json'
            doc = json.loads(Path('data/normalized/aws-cloud-definition.json').read_text())
            doc['sections'][0]['blocks'][0]['type'] = 'new-format'
            p.write_text(json.dumps(doc))
            with self.assertRaises(RagError):
                extract(p)

    def test_references(self):
        questions = load_questions(Path('evaluation/questions.jsonl'), Path('data'))
        self.assertEqual(len(questions), 23)
        q = questions[0]
        self.assertEqual(rank_of_reference(q, [dict(source_path=q['reference_source_path'], source_locator='/sections/0')]), 1)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'data'
        shutil.copytree('data/normalized', self.source / 'normalized')
        self.config = Config(source_dir=self.source, state_dir=self.root / 'state')
        embeddings.calls = 0
        Store.databases = {}
    def tearDown(self):
        self.temp.cleanup()
    def run_ingest(self, force=False):
        return ingest(self.config, self.source, force, Provider, Store)
    def test_incremental_edit_add_delete_force(self):
        first = self.run_ingest()
        self.assertGreater(first['embedded_chunks'], 0)
        self.assertEqual(self.run_ingest()['embedded_chunks'], 0)
        path = self.source / 'normalized/aws-cloud-definition.json'
        data = json.loads(path.read_text())
        data['sections'][0]['blocks'][0]['text'] += ' Additional verified test sentence.'
        path.write_text(json.dumps(data))
        self.assertGreater(self.run_ingest()['embedded_chunks'], 0)
        data['document_id'] = 'new-document'
        for section in data['sections']:
            section['section_id'] = 'new#section'
        extra = path.with_name('new.json')
        extra.write_text(json.dumps(data))
        self.assertGreater(self.run_ingest()['embedded_chunks'], 0)
        extra.unlink()
        after = self.run_ingest()
        self.assertEqual(after['embedded_chunks'], 0)
        self.assertEqual(len(Store.databases), 1)
        self.assertEqual(self.run_ingest(True)['embedded_chunks'], after['total_chunks'])
    def test_delete_last_document(self):
        self.run_ingest()
        for path in (self.source / 'normalized').glob('*.json'):
            path.unlink()
        result = self.run_ingest()
        self.assertEqual(result['total_chunks'], 0)
        self.assertEqual(result['embedded_chunks'], 0)

    def test_unrelated_collection_preserved(self):
        Store.databases['unrelated'] = {'private': ('private', {}, [0., 0.])}
        self.run_ingest()
        self.run_ingest(True)
        self.assertIn('private', Store.databases['unrelated'])

    def test_missing_vectors_rebuilt(self):
        self.run_ingest()
        collection = next(iter(Store.databases.values()))
        collection.pop(next(iter(collection)))
        result = self.run_ingest()
        self.assertEqual(result['embedded_chunks'], result['total_chunks'])

    def test_invalid_update_preserves_manifest(self):
        self.run_ingest()
        manifest = (self.config.state_dir / 'index_manifest.json').read_bytes()
        (self.source / 'normalized/aws-cloud-definition.json').write_text('{broken')
        with self.assertRaises(RagError):
            self.run_ingest()
        self.assertEqual(manifest, (self.config.state_dir / 'index_manifest.json').read_bytes())
    def test_failure_preserves_previous_index(self):
        self.run_ingest()
        manifest = (self.config.state_dir / 'index_manifest.json').read_bytes()
        with patch.object(embeddings, 'embed_documents', side_effect=RuntimeError('test interruption')):
            with self.assertRaises(RuntimeError):
                self.run_ingest(True)
        self.assertEqual(manifest, (self.config.state_dir / 'index_manifest.json').read_bytes())
    def test_model_change_invalidates(self):
        first = self.run_ingest()
        self.config = replace(self.config, embedding_revision='test-revision')
        self.assertEqual(self.run_ingest()['embedded_chunks'], first['total_chunks'])
    def test_query_checks_current_source_after_root_path_changes(self):
        self.run_ingest()
        path = self.config.state_dir / 'index_manifest.json'
        manifest = json.loads(path.read_text())
        manifest['source_root'] = str(self.root / 'old-path-spelling')
        path.write_text(json.dumps(manifest))
        (self.config.state_dir / 'chroma').mkdir()
        with patch('aws_rag.indexing.EmbeddingProvider', Provider), patch('aws_rag.indexing.store_for', Store):
            store, loaded = open_index(self.config)
            self.assertEqual(loaded, manifest)
            self.assertEqual(set(store.rows), set(manifest['chunk_ids']))
            source = self.source / 'normalized/aws-cloud-definition.json'
            document = json.loads(source.read_text())
            document['sections'][0]['blocks'][0]['text'] += ' Changed source.'
            source.write_text(json.dumps(document))
            with self.assertRaisesRegex(RagError, 'Corpus changed'):
                open_index(self.config)
    def test_output_guard(self):
        with self.assertRaises(ValueError):
            replace(self.config, state_dir=self.source / 'state').validate_output()
    def test_lock(self):
        with index_lock(self.config):
            with self.assertRaises(RagError):
                with index_lock(self.config):
                    pass


class ArtifactTests(unittest.TestCase):
    def test_export_removes_local_paths_without_mutating_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Config(state_dir=Path(directory) / 'runtime')
            manifest = {'source_root': str(Path.cwd()).lower() + '/data',
                        'signature': {'model': str(config.state_dir / 'models/bge')}}
            exported = public_artifact(manifest, config)
            self.assertEqual(exported['source_root'], '<project>/data')
            self.assertEqual(exported['signature']['model'], '<state_dir>/models/bge')
            self.assertNotEqual(exported, manifest)
            self.assertIn(str(config.state_dir), manifest['signature']['model'])

    def test_evaluation_checkpoints_and_exports_measured_results(self):
        questions = load_questions(Path('evaluation/questions.jsonl'), Path('data'))
        positive, negative = questions[0], questions[-1]
        results = [dict(answer='On-demand resources with pay-as-you-go pricing.',
                        abstained=False, references=[], retrieval_seconds=.01,
                        generation_seconds=.1, retrieved=[dict(
                            source_path=positive['reference_source_path'], source_locator='/sections/0')]),
                   dict(answer=ABSTENTION, abstained=True, references=[],
                        retrieval_seconds=.02, generation_seconds=.2, retrieved=[])]
        with tempfile.TemporaryDirectory() as directory:
            config = Config(state_dir=Path(directory) / 'runtime')
            report = Path(directory) / 'reports/baseline.md'
            generator = Mock(last_response='{}', last_metadata={})
            with patch('aws_rag.evaluation.load_questions', return_value=[positive, negative]), \
                 patch('aws_rag.evaluation.ask', side_effect=results) as generate, \
                 redirect_stderr(io.StringIO()):
                summary = evaluate(config, Mock(), generator, {}, report)
            self.assertEqual(summary['all']['recall_at_k'], 1)
            self.assertEqual(summary['all']['correct_abstention'], 1)
            self.assertEqual(summary['all']['false_abstention'], 0)
            self.assertTrue(generate.call_args.kwargs['include_evidence'])
            progress = json.loads((config.state_dir / 'evaluation_progress.json').read_text())
            self.assertEqual(progress['completed'], 2)
            self.assertEqual(progress['rows'][0]['result'], results[0])
            exported = json.loads(report.with_suffix('.json').read_text())
            self.assertEqual(exported['configuration']['state_dir'], '<state_dir>')
            self.assertEqual(exported['rows'][0]['raw_response'], '{}')


class RetrievalCliTests(unittest.TestCase):
    def test_retrieve_outputs_chunks_without_generator(self):
        chunk = Chunk('Versioning preserves multiple object versions.',
                      dict(source_path='data/normalized/aws-s3-overview.json',
                           source_locator='/sections/14', chunk_id='test-chunk'))
        with tempfile.TemporaryDirectory() as directory:
            config = Config(state_dir=Path(directory))
            with patch('aws_rag.__main__.Config.load', return_value=config), \
                 patch('aws_rag.indexing.open_index') as open_store, \
                 patch('aws_rag.generation.Generator', side_effect=AssertionError('LLM invoked')):
                store = Mock()
                open_store.return_value = (store, {})
                store.similarity_search_with_score.return_value = [(chunk, 0.12)]
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(['retrieve', 'S3 versioning?', '--top-k', '8', '--json']), 0)
                store.similarity_search_with_score.assert_called_once_with('S3 versioning?', k=8)
                result = json.loads(output.getvalue())
                self.assertEqual(result['chunks'][0]['text'], chunk.page_content)
                self.assertEqual(result['chunks'][0]['metadata'], chunk.metadata)
                self.assertEqual(result['chunks'][0]['distance'], 0.12)
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(['retrieve', 'S3 versioning?']), 0)
                self.assertIn(chunk.page_content, output.getvalue())
                self.assertIn('distance=0.120000', output.getvalue())

    def test_invalid_retrieval_rejected_before_opening_index(self):
        with patch('aws_rag.__main__.Config.load', return_value=Config()), \
             patch('aws_rag.indexing.open_index') as open_store:
            for args in (['retrieve', 'S3?', '--top-k', '0'], ['retrieve', ' ']):
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(main(args), 2)
            open_store.assert_not_called()


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.chunk = chunk_sections(load_corpus(Path('data')), Tokenizer())[0]
        self.evidence = Evidence('S1', self.chunk.page_content, self.chunk.metadata, 0.2)
    def test_context_dedup_and_limit(self):
        hits = [(self.chunk, .2), (self.chunk, .3)]
        context, evidence = pack_context(hits, 3000)
        self.assertLessEqual(len(context.encode()), 3000)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(pack_context(hits, 1), ('', []))
    def test_recorded_evidence_is_the_exact_context_sent_to_generator(self):
        store = Mock()
        store.similarity_search_with_score.return_value = [(self.chunk, .2), (self.chunk, .3)]
        generator = Mock()
        generator.generate.return_value = dict(answer=ABSTENTION, abstained=True, references=[])
        result = ask(Config(), store, generator, 'What is cloud computing?', include_evidence=True)
        self.assertEqual(len(result['retrieved']), 2)
        self.assertEqual(len(result['evidence']), 1)
        self.assertEqual(result['retrieved'][0]['text'], self.chunk.page_content)
        self.assertEqual(generator.generate.call_args.args[1], result['context'])
        self.assertEqual(generator.generate.call_args.args[2][0].text, result['evidence'][0]['text'])
    def test_valid_quote(self):
        payload = dict(answerable=True, answer='Cloud computing supplies resources on demand.', support=[dict(source='S1', quote=self.evidence.text[-100:])])
        result = validate_answer(payload, [self.evidence])
        self.assertFalse(result['abstained'])
        self.assertEqual(result['references'][0]['source_path'], self.chunk.metadata['source_path'])
    def test_invented_reference_or_quote_abstains(self):
        for source, quote in [('S9', self.evidence.text[-100:]), ('S1', 'a fabricated source quotation')]:
            result = validate_answer(dict(answerable=True, answer='Invented', support=[dict(source=source, quote=quote)]), [self.evidence])
            self.assertTrue(result['abstained'])
    def test_abstention(self):
        self.assertEqual(validate_answer(dict(answerable=False), [])['answer'], ABSTENTION)
        self.assertTrue(validate_answer(dict(answerable=True, answer='Unsupported', support=[]), [])['abstained'])
    def test_default_configuration(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(Config.load().top_k, 4)


if __name__ == '__main__':
    unittest.main()
