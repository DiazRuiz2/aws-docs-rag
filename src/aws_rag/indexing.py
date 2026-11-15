"""Persistent dense index, owned collections and atomic manifest publication."""
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
import json
import os
import time

from .config import RagError
from .corpus import PARSER_VERSION, digest, load_corpus
from .chunking import CHUNK_VERSION, chunk_sections


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


@contextmanager
def index_lock(config):
    # OS releases this advisory lock after a crash; no stale lock cleanup needed.
    import fcntl
    config.state_dir.mkdir(parents=True, exist_ok=True)
    with (config.state_dir / 'index.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RagError('Index is in use by another process; retry later') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class EmbeddingProvider:
    def __init__(self, config):
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
            self.embeddings = HuggingFaceEmbeddings(
                model_name=config.embedding_model,
                cache_folder=str(config.state_dir / 'models'),
                model_kwargs={'device': config.embedding_device, 'revision': config.embedding_revision},
                encode_kwargs={'normalize_embeddings': True})
            self.model = self.embeddings._client
            self.tokenizer = self.model.tokenizer
            if config.chunk_tokens > self.model.max_seq_length:
                raise RagError(f'chunk_tokens exceeds model limit {self.model.max_seq_length}')
        except ImportError as exc:
            raise RagError('Dependencies unavailable. Install uv and run uv sync.') from exc
        except OSError as exc:
            raise RagError(f'Embedding model unavailable: {config.embedding_model}. Download it with network access.') from exc


def signature(config):
    from importlib.metadata import PackageNotFoundError
    packages = {}
    for name in ('langchain-chroma', 'langchain-huggingface', 'sentence-transformers', 'transformers'):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = 'unavailable'
    return dict(parser=PARSER_VERSION, chunking=CHUNK_VERSION,
                model=config.embedding_model, revision=config.embedding_revision,
                normalized_embeddings=True, chunk_tokens=config.chunk_tokens,
                overlap=config.chunk_overlap, packages=packages)


def read_manifest(config):
    try:
        return json.loads((config.state_dir / 'index_manifest.json').read_text())
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as exc:
        raise RagError('Invalid manifest. Preserve state for diagnosis and rebuild with ingest --force.') from exc


def store_for(config, collection, embeddings=None):
    try:
        from langchain_chroma import Chroma
        from chromadb.config import Settings
        return Chroma(collection_name=collection, persist_directory=str(config.state_dir / 'chroma'),
                      embedding_function=embeddings, collection_metadata={'hnsw:space': 'cosine'},
                      client_settings=Settings(anonymized_telemetry=False))
    except ImportError as exc:
        raise RagError('Chroma integration unavailable. Run uv sync.') from exc


def ingest(config, source, force=False, provider_factory=EmbeddingProvider, store_factory=store_for):
    config.validate_output(source)
    sections = load_corpus(source)  # Validate everything before any index mutation.
    files = {}
    for section in sections:
        files[section.metadata['source_path']] = section.metadata['file_hash']
    sig = signature(config)
    root = str(source.resolve())
    with index_lock(config):
        old = read_manifest(config)
        if not files and (not old or old['source_root'] != root or not (source / 'normalized').is_dir()):
            raise RagError('No verified documents found; check source-dir and normalized/ before ingesting')
        rebuild = force or not old or old['signature'] != sig or old['source_root'] != root
        if old and not rebuild and old['file_hashes'] == files:
            store = store_factory(config, old['collection'])
            present = set(store.get(ids=old['chunk_ids'], include=[])['ids']) if old['chunk_ids'] else set()
            if present == set(old['chunk_ids']):
                return dict(status='unchanged', embedded_chunks=0, total_chunks=len(present))
            rebuild = True
        provider = provider_factory(config)
        # A new owned collection per transaction leaves the last manifest usable if interrupted.
        collection = 'awsrag_' + digest(root + str(time.time_ns()))[:24]
        store = store_factory(config, collection, provider.embeddings)
        previous = {}
        if old and not rebuild and old['chunk_ids']:
            prior = store_factory(config, old['collection'])
            cached = prior.get(ids=old['chunk_ids'], include=['embeddings', 'documents', 'metadatas'])
            for i, chunk_id in enumerate(cached['ids']):
                if cached['embeddings'] is not None:
                    previous[chunk_id] = (cached['documents'][i], cached['metadatas'][i], cached['embeddings'][i])
        chunks = chunk_sections(sections, provider.tokenizer, config.chunk_tokens, config.chunk_overlap)
        embedded = 0
        for start in range(0, len(chunks), 64):
            batch = chunks[start:start + 64]
            missing = [c for c in batch if c.metadata['chunk_id'] not in previous]
            vectors = provider.embeddings.embed_documents([c.page_content for c in missing]) if missing else []
            fresh = dict(zip((c.metadata['chunk_id'] for c in missing), vectors))
            embedded += len(missing)
            embeddings = [fresh[c.metadata['chunk_id']] if c.metadata['chunk_id'] in fresh else previous[c.metadata['chunk_id']][2] for c in batch]
            store._collection.upsert(ids=[c.metadata['chunk_id'] for c in batch],
                documents=[c.page_content for c in batch], metadatas=[c.metadata for c in batch], embeddings=embeddings)
        manifest = dict(version=1, source_root=root, signature=sig, collection=collection,
                        file_hashes=files, chunk_ids=[c.metadata['chunk_id'] for c in chunks],
                        created_at=time.time())
        atomic_json(config.state_dir / 'index_manifest.json', manifest)
        # Only delete the exact previous collection recorded as owned in our manifest.
        if old and old['collection'].startswith('awsrag_'):
            store_factory(config, old['collection']).delete_collection()
        return dict(status='indexed', embedded_chunks=embedded, total_chunks=len(chunks))


def open_index(config):
    manifest = read_manifest(config)
    if not manifest:
        raise RagError('No index found. Run ingest --source-dir data first.')
    if manifest['signature'] != signature(config):
        raise RagError('Index configuration changed. Run ingest again before querying.')
    # Never cite stale offsets after sources were edited or removed.
    current = {}
    # Resolve sources from the current configuration. On WSL the same Windows
    # directory can have different path casing than when the index was built.
    # The file hashes below still reject edited, removed or substituted sources.
    for section in load_corpus(config.source_dir):
        current[section.metadata['source_path']] = section.metadata['file_hash']
    if current != manifest['file_hashes']:
        raise RagError('Corpus changed since ingestion. Run ingest before querying.')
    if not (config.state_dir / 'chroma').is_dir():
        raise RagError('Persisted Chroma directory missing. Run ingest --force.')
    provider = EmbeddingProvider(config)
    store = store_for(config, manifest['collection'], provider.embeddings)
    if manifest['chunk_ids'] and set(store.get(ids=manifest['chunk_ids'], include=[])['ids']) != set(manifest['chunk_ids']):
        raise RagError('Index is incomplete. Run ingest --force.')
    return store, manifest
