"""Third resolver pass: nearest SKOS label by embedding (D8), used only after exact and fuzzy miss.

A small local ONNX model (fastembed, no API key). It is deliberately narrow:
  * only muscle and structure concepts are candidates -- slang for body parts is the gap it fills
    ("tummy", "hammy", "booty"); filler words score high against regions and equipment
    ("full" -> full body 0.86), so those types are never matched this way
  * a hit needs MIN similarity AND a MARGIN over the best *different* concept, so ambiguous
    words ("spine": lumbar vs cervical) stay unresolved
  * for a safety constraint the result is only a suggestion; the resolver still blocks
Calibration (bge-small-en-v1.5): slang hits 0.79-0.85; filler against muscle/structure tops out at 0.77.
If the model can't load (offline, first run without network), the pass is skipped and says so.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

MODEL = "BAAI/bge-small-en-v1.5"
MIN = 0.78
MARGIN = 0.03
SUGGEST_MIN = 0.65
CACHE = Path(os.getenv("FASTEMBED_CACHE_PATH", Path.home() / ".cache" / "fastembed"))


@lru_cache(maxsize=1)
def _model():
    if os.getenv("FC_EMBEDDINGS", "on") == "off":
        return None
    try:
        from fastembed import TextEmbedding

        return TextEmbedding(MODEL, cache_dir=str(CACHE))
    except Exception:  # noqa: BLE001 -- no network on first run, missing package: the pass is skipped
        return None


def available() -> bool:
    return _model() is not None


@lru_cache(maxsize=4)
def _matrix(texts: tuple[str, ...]):
    import numpy as np

    return np.array(list(_model().embed(list(texts))))


class LabelIndex:
    """Embeddings of every (label, concept, type), computed once per process on first use."""

    def __init__(self, labels: list[tuple[str, str, str]]):
        self.labels = labels
        self.texts = tuple(lab for lab, _, _ in labels)

    def _matrix(self):
        return _matrix(self.texts)

    def ranked(self, text: str, types: set[str]) -> list[tuple[float, str, str, str]]:
        """Best score per concept, highest first: (score, iri, type, label)."""
        if not available():
            return []
        import numpy as np

        v = np.array(list(_model().embed([text])))[0]
        scores = self._matrix() @ v
        best: dict[str, tuple[float, str, str, str]] = {}
        for s, (lab, iri, t) in zip(scores, self.labels, strict=True):
            if t in types and (iri not in best or s > best[iri][0]):
                best[iri] = (float(s), iri, t, lab)
        return sorted(best.values(), reverse=True)

    def match(self, text: str, types: set[str]) -> tuple[str, str, float] | None:
        r = self.ranked(text, types)
        if r and r[0][0] >= MIN and (len(r) == 1 or r[0][0] - r[1][0] >= MARGIN):
            return r[0][1], r[0][2], round(r[0][0], 3)
        return None

    def suggest(self, text: str, types: set[str]) -> tuple[float, list[str]] | None:
        """Up to two candidate concept IRIs worth asking the coach about, with the best score."""
        r = [x for x in self.ranked(text, types)[:2] if x[0] >= SUGGEST_MIN]
        if len(r) == 2 and r[0][0] - r[1][0] >= MARGIN:
            r = r[:1]
        return (r[0][0], [x[1] for x in r]) if r else None
