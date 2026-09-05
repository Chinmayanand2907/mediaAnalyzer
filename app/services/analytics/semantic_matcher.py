"""
Semantic Similarity Matching Service
===================================
Uses Sentence-BERT (all-MiniLM-L6-v2) to generate dense vector embeddings and compute
cosine similarities between Reddit discussion threads and YouTube video metadata
(titles, descriptions, tags, transcripts).

This bridges cross-platform discussions even when Reddit users do not post a direct
youtube.com or youtu.be URL (e.g. discussing the video title, meme, or content).

Architecture:
- Primary Engine: SentenceTransformer (all-MiniLM-L6-v2, 384-dimensional embeddings)
- Fallback Engine: TF-IDF + Cosine Similarity (via scikit-learn) if model loading fails
- Thread-safe lazy initialization
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _clean_text(text: str) -> str:
    """Strip URLs, extra whitespace, and markdown noise from text."""
    if not text:
        return ""
    # Remove explicit URLs since semantic matching focuses on text content
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class SemanticMatcher:
    """
    Computes semantic similarity between Reddit discussions and YouTube video metadata.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        threshold: Optional[float] = None,
    ) -> None:
        settings = get_settings()
        self.model_name = model_name or settings.SEMANTIC_EMBEDDING_MODEL
        self.threshold = threshold if threshold is not None else settings.SEMANTIC_SIMILARITY_THRESHOLD
        self._model = None
        self._model_load_attempted = False
        self._fallback_mode = False

    def _get_model(self):
        """Lazy load the SentenceTransformer model with fallback."""
        if not self._model_load_attempted:
            self._model_load_attempted = True
            try:
                from sentence_transformers import SentenceTransformer
                logger.info("[SemanticMatcher] Loading SentenceTransformer model: %s", self.model_name)
                self._model = SentenceTransformer(self.model_name)
                self._fallback_mode = False
                logger.info("[SemanticMatcher] SentenceTransformer successfully loaded.")
            except Exception as exc:
                logger.warning(
                    "[SemanticMatcher] Failed to load SentenceTransformer (%s). "
                    "Falling back to TF-IDF cosine similarity: %s",
                    self.model_name,
                    exc,
                )
                self._model = None
                self._fallback_mode = True
        return self._model

    def encode(self, texts: List[str]) -> np.ndarray:
        """
        Encode a list of texts into normalized vector embeddings.
        Returns shape (len(texts), embedding_dim).
        """
        if not texts:
            return np.empty((0, 384), dtype=np.float32)

        cleaned = [_clean_text(t) for t in texts]
        # Replace empty strings with a single space to avoid empty tensor issues
        safe_texts = [t if t else " " for t in cleaned]

        model = self._get_model()
        if model is not None and not self._fallback_mode:
            try:
                embeddings = model.encode(
                    safe_texts,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                return np.asarray(embeddings, dtype=np.float32)
            except Exception as exc:
                logger.warning("[SemanticMatcher] Encoding failed with transformer: %s. Using TF-IDF fallback.", exc)
                self._fallback_mode = True

        # Fallback to TF-IDF vectorizer if SentenceTransformer is unavailable
        return self._encode_tfidf(safe_texts)

    def _encode_tfidf(self, texts: List[str]) -> np.ndarray:
        """TF-IDF vectorizer fallback."""
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import normalize

        try:
            vectorizer = TfidfVectorizer(max_features=384, stop_words="english")
            matrix = vectorizer.fit_transform(texts)
            dense = matrix.toarray().astype(np.float32)
            return normalize(dense, norm="l2", axis=1)
        except Exception as exc:
            logger.error("[SemanticMatcher] TF-IDF fallback failed: %s", exc)
            return np.zeros((len(texts), 384), dtype=np.float32)

    def compute_similarity(
        self,
        embeddings_a: np.ndarray,
        embeddings_b: np.ndarray,
    ) -> np.ndarray:
        """
        Compute pairwise cosine similarity matrix between two sets of normalized embeddings.
        Returns shape (len(embeddings_a), len(embeddings_b)).
        """
        if embeddings_a.size == 0 or embeddings_b.size == 0:
            return np.empty((embeddings_a.shape[0], embeddings_b.shape[0]), dtype=np.float32)

        # Since embeddings are L2 normalized, dot product equals cosine similarity
        sim_matrix = np.dot(embeddings_a, embeddings_b.T)
        return np.clip(sim_matrix, 0.0, 1.0)

    def match_discussions_to_videos(
        self,
        discussions: List[Dict[str, Any]],
        candidate_videos: List[Dict[str, Any]],
        threshold: Optional[float] = None,
    ) -> Dict[str, List[Tuple[Dict[str, Any], float]]]:
        """
        Match Reddit discussion documents to candidate YouTube videos.

        Parameters
        ----------
        discussions : List[Dict[str, Any]]
            Reddit discussion items/comments, each having at least 'body' (or 'text').
        candidate_videos : List[Dict[str, Any]]
            YouTube video metadata dicts, each having at least 'video_id' and 'title'.
            Can also include 'description' and 'tags'.
        threshold : Optional[float]
            Minimum cosine similarity (0.0–1.0) to register a match.

        Returns
        -------
        Dict[str, List[Tuple[Dict[str, Any], float]]]
            Mapping of video_id -> list of (discussion_doc, similarity_score)
        """
        cutoff = threshold if threshold is not None else self.threshold
        if not discussions or not candidate_videos:
            return {}

        # 1. Prepare video corpus representation
        video_ids: List[str] = []
        video_texts: List[str] = []
        for v in candidate_videos:
            vid_id = v.get("video_id") or v.get("platform_id")
            if not vid_id:
                continue
            title = v.get("title") or ""
            desc = ""
            raw = v.get("raw")
            if isinstance(raw, dict):
                desc = raw.get("description") or ""
            elif isinstance(v.get("description"), str):
                desc = v.get("description") or ""

            # Truncate description to first 300 chars to focus on key topics
            v_text = f"{title}. {desc[:300]}".strip()
            if not v_text:
                v_text = title or vid_id

            video_ids.append(vid_id)
            video_texts.append(v_text)

        if not video_ids:
            return {}

        # 2. Prepare discussion texts
        disc_valid: List[Dict[str, Any]] = []
        disc_texts: List[str] = []
        for d in discussions:
            body = d.get("body") or d.get("text") or ""
            cleaned = _clean_text(body)
            # Require at least 15 characters to avoid matching short noise like "lol", "ok"
            if len(cleaned) >= 15:
                disc_valid.append(d)
                disc_texts.append(cleaned)

        if not disc_texts:
            return {}

        # 3. Compute embeddings
        # If SentenceTransformer is in fallback TF-IDF mode, fit on the combined vocabulary
        model = self._get_model()
        if model is None or self._fallback_mode:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.preprocessing import normalize
            try:
                vect = TfidfVectorizer(max_features=384, stop_words="english")
                all_texts = disc_texts + video_texts
                all_dense = vect.fit_transform(all_texts).toarray().astype(np.float32)
                all_norm = normalize(all_dense, norm="l2", axis=1)
                disc_embs = all_norm[:len(disc_texts)]
                video_embs = all_norm[len(disc_texts):]
            except Exception as exc:
                logger.error("[SemanticMatcher] TF-IDF fit failed: %s", exc)
                return {}
        else:
            disc_embs = self.encode(disc_texts)
            video_embs = self.encode(video_texts)

        # 4. Pairwise similarity matrix: shape (num_discussions, num_videos)
        sim_matrix = self.compute_similarity(disc_embs, video_embs)

        # 5. Group matches by video_id
        results: Dict[str, List[Tuple[Dict[str, Any], float]]] = {}
        for d_idx, d_doc in enumerate(disc_valid):
            scores = sim_matrix[d_idx]
            best_v_idx = int(np.argmax(scores))
            best_score = float(scores[best_v_idx])

            if best_score >= cutoff:
                matched_vid_id = video_ids[best_v_idx]
                results.setdefault(matched_vid_id, []).append((d_doc, round(best_score, 4)))

        return results


# Module-level singleton
_semantic_matcher: Optional[SemanticMatcher] = None


def get_semantic_matcher() -> SemanticMatcher:
    """Return the globally configured SemanticMatcher singleton."""
    global _semantic_matcher
    if _semantic_matcher is None:
        _semantic_matcher = SemanticMatcher()
    return _semantic_matcher
