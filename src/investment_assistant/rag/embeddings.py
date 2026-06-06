"""Text embeddings for hybrid (lexical + semantic) RAG search.

Two embedders are provided:

* :class:`HashingEmbedder` -- a dependency-free, deterministic embedding based on
  hashing tokens into a fixed number of buckets with sublinear term weighting and
  L2 normalization. It needs no network or API key, so it is the default and
  keeps indexing, search, and tests fully offline.
* :class:`GeminiEmbedder` -- optional, lazily imports the Google GenAI SDK and
  calls the embeddings API. Use it for stronger semantic recall when a key and
  the ``[gemini]`` extra are available.

Both return L2-normalized vectors so a dot product equals cosine similarity.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import math
import os
from typing import Protocol

from investment_assistant.rag.tokenize import tokenize

DEFAULT_EMBEDDING_DIM = 256


class Embedder(Protocol):
    """Protocol for text embedders used by hybrid search."""

    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one L2-normalized vector per input text."""


class HashingEmbedder:
    """Deterministic, offline hashing embedder over shared RAG tokens."""

    name = "hashing"

    def __init__(self, dim: int = DEFAULT_EMBEDDING_DIM) -> None:
        if dim < 1:
            msg = "dim must be at least 1"
            raise ValueError(msg)
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        counts: dict[str, int] = {}
        for token in tokenize(text):
            counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            bucket, sign = self._bucket(token)
            vector[bucket] += sign * (1.0 + math.log(count))
        return _l2_normalize(vector)

    def _bucket(self, token: str) -> tuple[int, float]:
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % self.dim
        sign = 1.0 if digest[4] & 1 else -1.0
        return bucket, sign


class GeminiEmbedder:
    """Optional Gemini embeddings via the official Google GenAI SDK (lazy)."""

    name = "gemini"

    def __init__(self, *, model: str = "text-embedding-004", api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key
        self.dim = 0  # Filled after the first embed call.

    def embed(self, texts: list[str]) -> list[list[float]]:
        key = self.api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            msg = "GEMINI_API_KEY is not configured"
            raise RuntimeError(msg)
        if importlib.util.find_spec("google.genai") is None:
            msg = "Install the optional Gemini SDK with: pip install -e '.[gemini]'"
            raise RuntimeError(msg)
        genai = importlib.import_module("google.genai")
        client = genai.Client(api_key=key)
        vectors: list[list[float]] = []
        for text in texts:
            response = client.models.embed_content(model=self.model, contents=text)
            values = [float(value) for value in response.embeddings[0].values]
            self.dim = len(values)
            vectors.append(_l2_normalize(values))
        return vectors


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity; assumes (but does not require) normalized inputs."""

    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    return dot


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
