"""Optional semantic embedding layer for the D365 doc index.

The base package is standard-library-only. This module lazy-imports ``fastembed``
inside functions so the module is always importable — ``EMBED_AVAILABLE`` tells
callers whether the extra is actually installed.

Model: ``intfloat/multilingual-e5-small`` (dim 384, MEAN pooling, multilingual FR/EN).
Registered once via ``TextEmbedding.add_custom_model`` (guarded against double-registration).

e5 prefix convention (required by the model):
  documents → ``"passage: "``   (stored in chunk_vectors)
  queries   → ``"query: "``     (applied at search time, never stored)

Blob encoding: ``np.asarray(v, dtype="float32").tobytes()`` → 4 × dim bytes.
Reload:        ``np.frombuffer(blob, dtype="float32")`` → float32 ndarray.
numpy ships with fastembed; blob helpers guard their numpy import so that
``vector_to_blob`` / ``blob_to_vector`` / ``cosine`` are testable without fastembed
only when numpy is available (which it is when the extra is installed).
"""

from __future__ import annotations

_MODEL_NAME = "intfloat/multilingual-e5-small"
_DIM = 384

# ---------------------------------------------------------------------------
# Availability flag — set at import time; never raises.
# ---------------------------------------------------------------------------
try:
    import fastembed as _fastembed_probe  # noqa: F401

    EMBED_AVAILABLE: bool = True
except ImportError:
    EMBED_AVAILABLE = False


# ---------------------------------------------------------------------------
# Pure blob helpers — usable without fastembed IF numpy is available (it ships
# with fastembed, so numpy ↔ EMBED_AVAILABLE in practice).
# ---------------------------------------------------------------------------

def vector_to_blob(vector: object) -> bytes:
    """Encode a float vector to a raw bytes blob (float32, little-endian)."""
    import numpy as np

    return np.asarray(vector, dtype="float32").tobytes()


def blob_to_vector(blob: bytes) -> object:
    """Decode a raw bytes blob back to a float32 numpy array."""
    import numpy as np

    return np.frombuffer(blob, dtype="float32")


def cosine(a_blob: bytes, b_blob: bytes) -> float:
    """Cosine similarity between two blobs. Returns float in [-1, 1]."""
    import numpy as np

    a = blob_to_vector(a_blob)
    b = blob_to_vector(b_blob)
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Embedder — lazy-imports fastembed; raises ImportError if extra is absent.
# ---------------------------------------------------------------------------

_embedder_cache: dict[str, object] = {}


def _register_model() -> None:
    """Register the multilingual-e5-small model with fastembed if not already known.

    fastembed raises ``ValueError`` when ``add_custom_model`` is called twice with
    the same model name (the model is already in the registry).  We suppress that
    specific error so repeated calls are idempotent.
    """
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    try:
        TextEmbedding.add_custom_model(
            model=_MODEL_NAME,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=_MODEL_NAME),
            dim=_DIM,
            model_file="onnx/model.onnx",
        )
    except Exception as exc:  # noqa: BLE001
        # The common case is "already registered" (idempotent re-call). Surface anything
        # unexpected to stderr instead of swallowing it silently — otherwise a wrong
        # fastembed import path would degrade to FTS5 with no diagnostic.
        import sys

        if "already" not in str(exc).lower() and "exist" not in str(exc).lower():
            print(f"[embed] add_custom_model({_MODEL_NAME!r}) failed: {exc}", file=sys.stderr)


def get_embedder(model_name: str = _MODEL_NAME) -> object:
    """Return a cached ``TextEmbedding`` instance for ``model_name``.

    Raises ``ImportError`` when the ``[semantic]`` extra is not installed — callers
    must check ``EMBED_AVAILABLE`` before calling this.
    """
    from fastembed import TextEmbedding

    if model_name not in _embedder_cache:
        _register_model()
        _embedder_cache[model_name] = TextEmbedding(model_name=model_name)
    return _embedder_cache[model_name]  # type: ignore[return-value]


def embed_passages(texts: list[str], model_name: str = _MODEL_NAME) -> list[bytes]:
    """Embed a list of document passages (adds ``"passage: "`` prefix, stores as blobs).

    Raises ``ImportError`` when the ``[semantic]`` extra is not installed.
    """
    emb = get_embedder(model_name)
    prefixed = [f"passage: {t}" for t in texts]
    return [vector_to_blob(v) for v in emb.embed(prefixed)]


def embed_query(text: str, model_name: str = _MODEL_NAME) -> bytes:
    """Embed a single query string (adds ``"query: "`` prefix, returns blob).

    Raises ``ImportError`` when the ``[semantic]`` extra is not installed.
    """
    emb = get_embedder(model_name)
    vectors = list(emb.embed([f"query: {text}"]))
    return vector_to_blob(vectors[0])
