"""
Optional embedding functions for ChromaVectorStore subclasses, beyond
chromadb's bundled default (ONNX MiniLM, 384-dim, no extra install).

See docs/designInterviewTool.md's "Embedding model: nomic-embed-text-v1.5,
run in-process (no server)" section for the full design and the concerns
this resolves (dimension mismatch — avoided by keying each embedding
model's collection to its own path, see InterviewVectorStore.from_config —
and the asymmetric query/document prefixing nomic's model needs to perform
as documented).

sentence-transformers/torch/einops are NOT in the base project dependencies
— they're a heavy, opt-in install (`pip install openresearch[nomic-embeddings]`)
only needed if this embedding function is actually used, so the import stays
lazy here exactly like magika's in integrations/file_type_check.py.
"""

import functools
import logging

logger = logging.getLogger(__name__)

_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"


class NomicEmbeddingFunction:
    """Chroma-compatible embedding function for nomic-embed-text-v1.5, loaded
    in-process via sentence-transformers (trust_remote_code=True) rather than
    through an external server (LM Studio/Ollama) — preserves the "no
    server, no cloud embeddings" invariant chroma_vector_store.py documents.

    IMPORTANT — asymmetric embedding: this class is the *document* side
    (used as the collection's embedding_function, so chromadb calls it for
    every .add()/.upsert()/.upsert_one() with the "search_document: " prefix
    nomic's model expects for indexed content). Query-time text must go
    through embed_query() instead — see ChromaVectorStore._query_embedding()
    and InterviewVectorStore._query() — never through collection.query
    (query_texts=...), which would silently re-use the document prefix and
    degrade retrieval quality with no error.
    """

    def __init__(self):
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading {_MODEL_NAME} (first use — may download ~500MB)...")
            self._model = SentenceTransformer(_MODEL_NAME, trust_remote_code=True)
        return self._model

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Chroma's EmbeddingFunction protocol — called for .add()/.upsert()."""
        return self.embed_documents(list(input))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed = [f"search_document: {t}" for t in texts]
        return self._get_model().encode(prefixed, normalize_embeddings=True).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._get_model().encode(f"search_query: {text}", normalize_embeddings=True).tolist()

    def name(self) -> str:
        # Required by newer chromadb versions to persist which embedding
        # function a collection was created with.
        return "nomic-embed-text-v1.5"


@functools.lru_cache(maxsize=1)
def get_nomic_embedding_function() -> NomicEmbeddingFunction:
    """Shared instance — SentenceTransformer model load is expensive
    (seconds, plus a first-run download); every InterviewVectorStore
    constructed with the nomic embedder should share one loaded model
    instead of each re-loading its own copy."""
    return NomicEmbeddingFunction()
