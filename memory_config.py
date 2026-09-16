import os
from typing import Sequence

from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings

load_dotenv()


# Postgres connection string — used by fastAPI.py lifespan to spin up
# AsyncPostgresSaver + AsyncPostgresStore inside proper async context managers.
CONN_STRING = os.getenv(
    "POSTGRES_CONN_STRING",
    "postgresql://postgres:postgres@127.0.0.1:5433/postgres?sslmode=disable"
)

# ── Lazy embedding model singleton
# HuggingFaceEmbeddings must NOT be instantiated at import time because
# it triggers a synchronous HF Hub network request (via httpx) which fails
# when the httpx client is already closed inside an async startup context.
_embedding_model = None


def get_embedding_model():
    """Return the shared HuggingFaceEmbeddings instance, initialising on first call."""
    global _embedding_model
    if _embedding_model is None:
        from langchain_huggingface import HuggingFaceEmbeddings
        _embedding_model = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
        )
    return _embedding_model


# Backwards-compatible alias — resolves lazily on first attribute access.
#
# NOTE: This MUST subclass `Embeddings`. LangGraph's store (see
# `fastAPI_backend.py`, `index={"dims": 384, "embed": embedding_model}`)
# checks `isinstance(embed, Embeddings)`. If that check fails, it treats the
# object as a plain embedding *function* and calls `embed(texts)`, which
# previously blew up with "'_LazyEmbeddingProxy' object is not callable"
# because dunders like `__call__` bypass `__getattr__`. Subclassing
# `Embeddings` makes the isinstance path succeed while still deferring the
# expensive HuggingFace load until first use.
class _LazyEmbeddingProxy(Embeddings):
    """Behaves like the real HuggingFaceEmbeddings instance but defers loading."""

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return get_embedding_model().embed_documents(list(texts))

    def embed_query(self, text: str) -> list[float]:
        return get_embedding_model().embed_query(text)

    async def aembed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await get_embedding_model().aembed_documents(list(texts))

    async def aembed_query(self, text: str) -> list[float]:
        return await get_embedding_model().aembed_query(text)

    # Fallback for the "embed is a callable" code path some stores use.
    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    # Forward any other attribute access to the real model.
    def __getattr__(self, name):
        return getattr(get_embedding_model(), name)


embedding_model = _LazyEmbeddingProxy()


