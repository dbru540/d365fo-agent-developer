"""Tests for embed.py — pure helpers run always; embedder tests are skip-guarded."""
import unittest

# ---------------------------------------------------------------------------
# Availability flag — checked at import time; usable as a skip guard anywhere.
# ---------------------------------------------------------------------------
try:
    from d365fo_agent.embed import EMBED_AVAILABLE
except ImportError:
    EMBED_AVAILABLE = False

# ---------------------------------------------------------------------------
# Conditional import — the module must be importable even without fastembed.
# ---------------------------------------------------------------------------
from d365fo_agent.embed import (  # noqa: E402  (after try/except above)
    blob_to_vector,
    cosine,
    embed_passages,
    embed_query,
    get_embedder,
    vector_to_blob,
)


class TestPureHelpers(unittest.TestCase):
    """These tests run in the base (no-extra) environment — no fastembed needed."""

    def test_vector_to_blob_round_trips(self):
        try:
            import numpy as np  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available (fastembed extra not installed)")
        vec = [1.0, 0.5, -0.25]
        blob = vector_to_blob(vec)
        assert isinstance(blob, bytes)
        assert len(blob) == 12  # 3 × 4 bytes
        back = blob_to_vector(blob)
        # numpy ndarray — compare element-wise
        for a, b in zip(vec, back.tolist()):
            assert abs(a - b) < 1e-6

    def test_blob_to_vector_returns_float32_ndarray(self):
        try:
            import numpy as np
            vec = [1.0, 2.0, 3.0]
            blob = vector_to_blob(vec)
            arr = blob_to_vector(blob)
            assert arr.dtype == np.float32
            assert arr.shape == (3,)
        except ImportError:
            self.skipTest("numpy not available (fastembed extra not installed)")

    def test_cosine_identical_vectors_is_one(self):
        try:
            import numpy as np  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")
        vec = [1.0, 0.0, 0.0]
        blob = vector_to_blob(vec)
        score = cosine(blob, blob)
        assert abs(score - 1.0) < 1e-6

    def test_cosine_orthogonal_vectors_is_zero(self):
        try:
            import numpy as np  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")
        a = vector_to_blob([1.0, 0.0, 0.0])
        b = vector_to_blob([0.0, 1.0, 0.0])
        score = cosine(a, b)
        assert abs(score) < 1e-6

    def test_cosine_opposite_vectors_is_minus_one(self):
        try:
            import numpy as np  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")
        a = vector_to_blob([1.0, 0.0])
        b = vector_to_blob([-1.0, 0.0])
        score = cosine(a, b)
        assert abs(score - (-1.0)) < 1e-6


# ---------------------------------------------------------------------------
# Embedder tests — skip-guarded: only run when fastembed is installed.
# ---------------------------------------------------------------------------
@unittest.skipUnless(EMBED_AVAILABLE, "fastembed extra not installed — skipping embedder tests")
class TestEmbedder(unittest.TestCase):
    """Require real fastembed. Skipped in the base (stdlib-only) environment."""

    def test_get_embedder_returns_text_embedding_instance(self):
        from fastembed import TextEmbedding
        emb = get_embedder()
        assert isinstance(emb, TextEmbedding)

    def test_embed_passages_returns_list_of_bytes(self):
        texts = ["settlement matches vendor invoices", "bank reconciliation"]
        blobs = embed_passages(texts)
        assert isinstance(blobs, list)
        assert len(blobs) == 2
        for b in blobs:
            assert isinstance(b, bytes)
            assert len(b) == 384 * 4  # float32 × 384 dims

    def test_embed_query_returns_bytes(self):
        blob = embed_query("how does vendor invoice matching work?")
        assert isinstance(blob, bytes)
        assert len(blob) == 384 * 4

    def test_embed_passages_applies_passage_prefix(self):
        """Verify the prefix is applied: embed 'passage: X' directly vs embed_passages(['X'])
        should give the same vector (or very close — the wrapper must add the prefix)."""
        import numpy as np
        emb = get_embedder()
        raw = list(emb.embed(["passage: hello world"]))
        via_helper = blob_to_vector(embed_passages(["hello world"])[0])
        direct = raw[0]
        # cosine similarity should be >= 0.999
        sim = float(np.dot(direct, via_helper) / (np.linalg.norm(direct) * np.linalg.norm(via_helper)))
        assert sim >= 0.999

    def test_embed_query_applies_query_prefix(self):
        import numpy as np
        emb = get_embedder()
        raw = list(emb.embed(["query: hello world"]))
        via_helper = blob_to_vector(embed_query("hello world"))
        direct = raw[0]
        sim = float(np.dot(direct, via_helper) / (np.linalg.norm(direct) * np.linalg.norm(via_helper)))
        assert sim >= 0.999
