"""Read-only inventory and strict extraction of the observed normalized schema."""
from dataclasses import dataclass
from pathlib import Path
from collections import Counter
import hashlib
import json

from .config import RagError

PARSER_VERSION = "normalized-1.0-v1"
BLOCK_TYPES = {"paragraph", "list", "admonition", "image_ref", "table"}


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


@dataclass
class Unit:
    text: str
    locator: str
    atomic: bool = False


@dataclass
class Section:
    metadata: dict
    units: list[Unit]


def display_path(path):
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def require(condition):
    if not condition:
        raise ValueError("Schema validation failed")


def extract(path: Path) -> list[Section]:
    raw = path.read_bytes()
    try:
        d = json.loads(raw.decode("utf-8"))
        require(isinstance(d, dict) and d['schema_version'] == '1.0')
        require(d['language'] == 'en')
        require(isinstance(d['document_id'], str) and d['document_id'])
        require(isinstance(d['title'], str))
        require(isinstance(d['source'], dict) and isinstance(d['sections'], list))
        result, ids = [], set()
        for si, section in enumerate(d['sections']):
            require(isinstance(section['section_id'], str) and section['section_id'])
            require(section['section_id'] not in ids)
            ids.add(section['section_id'])
            require(isinstance(section['heading_path'], list))
            require(all(isinstance(h, str) for h in section['heading_path']))
            require(isinstance(section['blocks'], list))
            units = []
            for bi, block in enumerate(section['blocks']):
                require(block['type'] in BLOCK_TYPES)
                require(isinstance(block['text'], str))
                pointer = f"/sections/{si}/blocks/{bi}"
                if block['type'] == 'table':
                    columns, rows = block['attributes']['columns'], block['attributes']['rows']
                    require(isinstance(columns, list) and all(isinstance(c, str) for c in columns))
                    require(isinstance(rows, list))
                    for ri, row in enumerate(rows):
                        require(isinstance(row, list) and len(row) == len(columns))
                        require(all(isinstance(cell, str) for cell in row))
                        text = '\n'.join(f'{c}: {v}' for c, v in zip(columns, row))
                        units.append(Unit(text, pointer + f'/attributes/rows/{ri}', True))
                elif block['text'].strip():
                    units.append(Unit(block['text'], pointer + '/text'))
            meta = dict(source_path=display_path(path), doc_id=d['document_id'],
                        section_id=section['section_id'], source_locator=f'/sections/{si}',
                        heading_path=json.dumps(section['heading_path'], ensure_ascii=False),
                        file_hash=digest(raw), warnings=json.dumps(d.get('warnings', [])))
            url = section.get('anchor_url') or d['source'].get('canonical_url')
            if url:
                require(isinstance(url, str))
                meta['source_url'] = url
            if units:
                result.append(Section(meta, units))
        return result
    except (KeyError, TypeError, AssertionError, ValueError, UnicodeError) as exc:
        raise RagError(f"Invalid verified-schema candidate {path}: {type(exc).__name__}. Source left untouched.") from exc


def candidates(root):
    if not root.is_dir():
        raise RagError(f"Source directory does not exist: {root}")
    for path in sorted((root / 'normalized').rglob('*.json')):
        if path.is_symlink() or root.resolve() not in path.resolve().parents:
            raise RagError(f"Source symlink outside corpus is not supported: {path}")
        yield path


def load_corpus(root):
    sections, ids = [], set()
    for path in candidates(root):
        extracted = extract(path)
        if not extracted:
            continue
        doc_id = extracted[0].metadata['doc_id']
        if doc_id in ids:
            raise RagError(f"Duplicate document_id: {doc_id}")
        ids.add(doc_id)
        sections.extend(extracted)
    return sections


def inspect(root):
    """Inventory by actual parse outcome; unknowns are never auto-selected."""
    selected = {display_path(p) for p in candidates(root)}
    inventory, seen = [], {}
    for p in sorted(root.rglob('*')):
        if not p.is_file():
            continue
        if p.is_symlink():
            inventory.append(dict(path=display_path(p), role='excluded symlink'))
            continue
        raw = p.read_bytes()
        row = dict(path=display_path(p), bytes=len(raw), sha256=digest(raw), extension=p.suffix)
        try:
            text = raw.decode('utf-8')
            try:
                obj = json.loads(text)
                row['format'] = 'json'
                row['schema'] = {k: type(v).__name__ for k, v in obj.items()} if isinstance(obj, dict) else type(obj).__name__
                if row['path'] in selected:
                    sections = extract(p)
                    row.update(role='normalized documentation', sections=len(sections),
                               units=sum(len(s.units) for s in sections))
                elif isinstance(obj, dict) and {'parents', 'children'} <= obj.keys():
                    row['role'] = 'derived chunks (excluded)'
                else:
                    row['role'] = 'metadata/state or unknown JSON (excluded)'
            except json.JSONDecodeError:
                row.update(format='utf-8 text', role='duplicate source representation' if p.suffix == '.md' and p.parts[-2] == 'imports' else 'unselected text')
        except UnicodeDecodeError:
            row.update(format='binary', role='unknown (excluded)')
        if row['sha256'] in seen:
            row['duplicate_of'] = seen[row['sha256']]
        seen[row['sha256']] = row['path']
        inventory.append(row)
    sections = load_corpus(root)
    return dict(files=len(inventory), total_bytes=sum(r.get('bytes', 0) for r in inventory),
                documents=len({s.metadata['doc_id'] for s in sections}), sections=len(sections),
                formats=dict(Counter(r.get('format', 'unknown') for r in inventory)),
                extraction=PARSER_VERSION, inventory=inventory)
