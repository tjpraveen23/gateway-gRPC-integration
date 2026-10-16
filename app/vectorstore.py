"""Minimal vector store (JSON-persisted). Replace with the enterprise vector DB client
by keeping the same upsert/search interface."""
import json
import threading
from pathlib import Path

import numpy as np


class VectorStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.records: dict[str, dict] = {}
        if self.path.exists():
            self.records = json.loads(self.path.read_text())

    def upsert(self, records: list[dict]) -> None:
        with self.lock:
            for r in records:
                self.records[r["key"]] = r
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.records))

    def search(self, qvec: list[float], top_k: int = 4, topic: str | None = None) -> list[dict]:
        with self.lock:
            cands = [r for r in self.records.values() if not topic or r["topic"] == topic]
        if not cands:
            return []
        q = np.array(qvec)
        mat = np.array([r["embedding"] for r in cands])
        sims = mat @ q / (np.linalg.norm(mat, axis=1) * np.linalg.norm(q) + 1e-9)
        order = np.argsort(-sims)[:top_k]
        return [{**{k: v for k, v in cands[i].items() if k != "embedding"}, "score": float(sims[i])}
                for i in order]
