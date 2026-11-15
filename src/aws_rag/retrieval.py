"""Dense top-k retrieval and bounded deduplicated context."""
from dataclasses import dataclass
from time import perf_counter
import json
from .corpus import digest
from .config import RagError


@dataclass
class Evidence:
    label: str
    text: str
    metadata: dict
    distance: float

    def citation(self):
        spans = json.loads(self.metadata['source_spans'])
        return dict(label=self.label, source_path=self.metadata['source_path'],
                    section_id=self.metadata['section_id'], spans=spans)


def retrieve(store, question, k):
    start = perf_counter()
    hits = store.similarity_search_with_score(question, k=k)
    return hits, perf_counter() - start


def pack_context(hits, budget):
    """UTF-8 bytes upper-bound ordinary byte-fallback model tokens conservatively."""
    evidence, blocks, seen = [], [], set()
    for document, distance in hits:
        key = digest(document.page_content)
        if key in seen:
            continue
        seen.add(key)
        label = f'S{len(evidence) + 1}'
        block = f'[{label}]\n{document.page_content}'
        if len(('\n\n'.join(blocks + [block])).encode('utf-8')) > budget:
            continue  # Never cut through a table row or source fragment.
        evidence.append(Evidence(label, document.page_content, document.metadata, float(distance)))
        blocks.append(block)
    return '\n\n'.join(blocks), evidence
