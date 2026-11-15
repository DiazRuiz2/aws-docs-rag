"""Portable copies of run artifacts; never alter the live index manifest."""
from pathlib import Path
import re


def public_artifact(value, config):
    replacements = [(str(config.state_dir.resolve()), '<state_dir>'),
                    (str(Path.cwd().resolve()), '<project>')]

    def clean(item):
        if isinstance(item, str):
            for original, replacement in replacements:
                item = re.sub(re.escape(original), lambda _: replacement, item,
                              flags=re.IGNORECASE)
            return item
        if isinstance(item, dict):
            return {clean(k): clean(v) for k, v in item.items()}
        if isinstance(item, list):
            return [clean(v) for v in item]
        return item

    return clean(value)
