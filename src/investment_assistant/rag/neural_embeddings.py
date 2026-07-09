"""Neural sentence embeddings via sentence-transformers (optional, lazy).

:class:`SentenceTransformersEmbedder` implements the same ``Embedder``
protocol as the default :class:`~investment_assistant.rag.embeddings.HashingEmbedder`,
but embeds text with a real neural sentence-embedding model on CPU. It fixes
the known weakness of the hashing embedder on multi-term Japanese queries
(e.g. 「高配当銘柄の根拠を探す」 retrieving unrelated decliner/volume-ranking
chunks at ~0.97), because token-bucket overlap is replaced by semantic
similarity.

Importing this module never requires the ``sentence-transformers`` package:
the dependency is imported lazily on first use, so indexing, search, and
tests stay offline-first. Install it with ``pip install -e '.[embeddings]'``.

Asymmetric models (the e5 family, and ruri) require different instruction
prefixes for queries vs. documents, so this embedder exposes
``embed_queries`` in addition to the protocol's ``embed`` (used for
documents/passages at index time). Search-side code should embed queries via
:func:`investment_assistant.rag.embeddings.embed_queries`, which falls back
to plain ``embed`` for symmetric embedders like the hashing one.
"""

from __future__ import annotations

import importlib
import importlib.util
from typing import Any, Protocol, cast

from investment_assistant.rag.embeddings import _l2_normalize

DEFAULT_ST_MODEL = "intfloat/multilingual-e5-small"

# Persisted-name prefix. ``RagStore`` records ``embedder.name`` in DB meta and
# ``resolve_embedder`` must round-trip it, so the name encodes the model id.
ST_NAME_PREFIX = "st:"

# Short, user-friendly aliases accepted by ``resolve_embedder`` (see
# docs/brainstem.md section 5). Values are full sentence-transformers ids.
_MODEL_ALIASES: dict[str, str] = {
    "multilingual-e5-small": "intfloat/multilingual-e5-small",
    "multilingual-e5-base": "intfloat/multilingual-e5-base",
    "multilingual-e5-large": "intfloat/multilingual-e5-large",
    "ruri-small": "cl-nagoya/ruri-small",
    "ruri-base": "cl-nagoya/ruri-base",
    "ruri-large": "cl-nagoya/ruri-large",
}

# Indirection so tests can simulate a missing package without uninstalling it.
_find_spec = importlib.util.find_spec


class SentenceTransformerLike(Protocol):
    """Structural type for ``sentence_transformers.SentenceTransformer``.

    Lets tests inject a deterministic fake model without downloading weights.
    """

    def encode(self, sentences: list[str], **kwargs: Any) -> Any:
        """Return one vector per sentence (any sequence-of-sequences shape)."""


class SentenceTransformersEmbedder:
    """CPU sentence-transformers embedder implementing the Embedder protocol.

    ``embed`` embeds documents/passages (index time); ``embed_queries`` embeds
    search queries. For prefix-instructed model families (e5, ruri) the two
    apply the family's required prefixes; for other models both are plain.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_ST_MODEL,
        *,
        model: SentenceTransformerLike | None = None,
        batch_size: int = 16,
    ) -> None:
        resolved = _MODEL_ALIASES.get(model_id.strip().lower(), model_id.strip())
        if not resolved:
            msg = "model_id must not be empty"
            raise ValueError(msg)
        if batch_size < 1:
            msg = "batch_size must be at least 1"
            raise ValueError(msg)
        self.model_id = resolved
        self.name = ST_NAME_PREFIX + resolved
        self.batch_size = batch_size
        self.dim = 0  # Filled after the first embed call (mirrors GeminiEmbedder).
        self._model = model
        self._query_prefix, self._passage_prefix = _prompt_prefixes(resolved)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed documents/passages (the Embedder protocol method)."""

        return self._encode([self._passage_prefix + text for text in texts])

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """Embed search queries in the same space as :meth:`embed`."""

        return self._encode([self._query_prefix + text for text in texts])

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        raw = model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True)
        vectors = [_l2_normalize([float(value) for value in row]) for row in raw]
        if vectors:
            self.dim = len(vectors[0])
        return vectors

    def _load_model(self) -> SentenceTransformerLike:
        model = self._model
        if model is None:
            if _find_spec("sentence_transformers") is None:
                msg = (
                    "sentence-transformers is not installed; install the optional "
                    "extra with: pip install -e '.[embeddings]'"
                )
                raise RuntimeError(msg)
            module = importlib.import_module("sentence_transformers")
            model = cast(
                SentenceTransformerLike,
                module.SentenceTransformer(self.model_id, device="cpu"),
            )
            self._model = model
        return model


def resolve_sentence_transformers_embedder(name: str) -> SentenceTransformersEmbedder | None:
    """Map a neural embedder name to an instance, or ``None`` if not neural.

    Accepted forms:

    * ``"st:<model_id>"`` -- the canonical form persisted in RAG DB meta
      (``SentenceTransformersEmbedder.name``), so stored names round-trip.
    * A registered short alias such as ``"multilingual-e5-small"``.
    * Any Hugging Face style ``"org/model"`` sentence-transformers model id.

    Anything else returns ``None`` so ``resolve_embedder`` can keep its
    existing fallback behavior (hashing).
    """

    candidate = name.strip()
    lowered = candidate.lower()
    if lowered.startswith(ST_NAME_PREFIX):
        model_id = candidate[len(ST_NAME_PREFIX) :].strip()
        if not model_id:
            return None
        return SentenceTransformersEmbedder(model_id)
    if lowered in _MODEL_ALIASES:
        return SentenceTransformersEmbedder(_MODEL_ALIASES[lowered])
    if "/" in candidate:
        return SentenceTransformersEmbedder(candidate)
    return None


def _prompt_prefixes(model_id: str) -> tuple[str, str]:
    """Return the ``(query, passage)`` prefixes a model family requires.

    e5 models are trained with English ``"query: "``/``"passage: "``
    instruction prefixes; ruri models use the Japanese equivalents. Models
    outside these families get no prefixes.
    """

    base = model_id.rsplit("/", 1)[-1].lower()
    if "e5" in base.split("-"):
        return "query: ", "passage: "
    if base.startswith("ruri"):
        return "クエリ: ", "文章: "
    return "", ""
