"""Local embeddings (fastembed / ONNX). Call as embeddings.embed(...) so tests can replace it."""
import threading

from . import config

_model = None
_lock = threading.Lock()


def embed(texts: list[str]) -> list[list[float]]:
    global _model
    with _lock:
        if _model is None:
            from fastembed import TextEmbedding
            _model = TextEmbedding(model_name=config.EMBED_MODEL)
        model = _model
    return [v.tolist() for v in model.embed(texts)]
