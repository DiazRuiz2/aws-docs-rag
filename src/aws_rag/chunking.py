"""Token-aware section/block packing with exact source offsets."""
import json
import re
from dataclasses import dataclass
from .corpus import digest
from .config import RagError

CHUNK_VERSION = 'sections-blocks-v1'


@dataclass
class Chunk:
    page_content: str
    metadata: dict


def chunk_sections(sections, tokenizer, limit=440, overlap=40):
    def count(text):
        return len(tokenizer.encode(text, add_special_tokens=True))

    chunks = []
    for section in sections:
        heading = ' > '.join(json.loads(section.metadata['heading_path']))
        prefix = heading + '\n\n' if heading else ''
        if count(prefix) >= limit - 8:
            raise RagError('Heading exceeds embedding token budget')
        parts = []
        for unit in section.units:
            start = 0
            while start < len(unit.text):
                end = len(unit.text)
                if count(prefix + unit.text[start:end]) > limit:
                    if unit.atomic:
                        raise RagError(f'Atomic table row exceeds token budget: {unit.locator}')
                    lo, hi = start + 1, end
                    while lo < hi:
                        mid = (lo + hi + 1) // 2
                        if count(prefix + unit.text[start:mid]) <= limit:
                            lo = mid
                        else:
                            hi = mid - 1
                    end = lo
                    boundaries = [m.end() for m in re.finditer(r'\s+', unit.text[start:end])]
                    if boundaries and boundaries[-1] > (end - start) // 2:
                        end = start + boundaries[-1]
                parts.append((unit.text[start:end], dict(pointer=unit.locator, start=start, end=end)))
                if end == len(unit.text):
                    break
                next_start = end
                if overlap:
                    for match in reversed(list(re.finditer(r'\S+', unit.text[start:end]))):
                        candidate = start + match.start()
                        if count(unit.text[candidate:end]) > overlap:
                            break
                        next_start = candidate
                start = max(start + 1, next_start)
        current, spans = [], []

        def flush():
            if not current:
                return
            text = prefix + '\n\n'.join(current)
            meta = dict(section.metadata)
            meta['source_spans'] = json.dumps(spans, ensure_ascii=False)
            meta['chunk_id'] = digest(meta['source_path'] + meta['section_id'] + meta['source_spans'] + text)
            chunks.append(Chunk(text, meta))

        for text, span in parts:
            if current and count(prefix + '\n\n'.join(current + [text])) > limit:
                flush()
                current, spans = [], []
            current.append(text)
            spans.append(span)
        flush()
    return chunks
