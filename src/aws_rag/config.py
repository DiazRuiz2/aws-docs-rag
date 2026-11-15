"""One configuration surface: defaults, .env, then environment variables."""
from dataclasses import dataclass, fields
from pathlib import Path
import os


@dataclass(frozen=True)
class Config:
    source_dir: Path = Path("data")
    state_dir: Path = Path(".rag_state")
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_revision: str = "main"
    embedding_device: str = "cpu"
    llm_model: str = "qwen3:1.7b"
    ollama_host: str = "http://localhost:11434"
    top_k: int = 4
    chunk_tokens: int = 440
    chunk_overlap: int = 40
    context_tokens: int = 3000
    ollama_num_ctx: int = 8192
    temperature: float = 0.0
    questions: Path = Path("evaluation/questions.jsonl")

    @classmethod
    def load(cls):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        defaults = cls()
        values = {}
        for f in fields(cls):
            old = getattr(defaults, f.name)
            values[f.name] = type(old)(os.getenv("RAG_" + f.name.upper(), old))
        config = cls(**values)
        if config.top_k < 1 or config.chunk_tokens < 32:
            raise ValueError("top_k must be positive and chunk_tokens must be at least 32")
        if not 0 <= config.chunk_overlap < config.chunk_tokens // 2:
            raise ValueError("chunk_overlap must be nonnegative and less than half chunk_tokens")
        if config.context_tokens < 128 or config.context_tokens + 4096 > config.ollama_num_ctx:
            raise ValueError("Reserve context_tokens + 4096 in ollama_num_ctx (conservative UTF-8 budget)")
        return config

    def validate_output(self, source=None):
        root = (source or self.source_dir).resolve()
        if self.state_dir.resolve() == root or root in self.state_dir.resolve().parents:
            raise ValueError("State directory must be outside the source directory")


class RagError(RuntimeError):
    """An actionable user-facing failure."""
