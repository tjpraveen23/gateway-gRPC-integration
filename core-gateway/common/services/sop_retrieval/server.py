"""Common service: SopRetrievalService.

In your environment this is the EXISTING retrieval service over the enterprise vector DB. This file is a local
stand-in with the same proto contract: at startup it loads sop_docs/*.md into a local vector store."""
import logging
from pathlib import Path

import grpc

from crown.common.v1 import sop_retrieval_pb2 as pb
from crown.common.v1 import sop_retrieval_pb2_grpc as pbg
from crown_common import config, embeddings
from crown_common.grpc_server import run_forever, start_server
from crown_common.vectorstore import VectorStore

log = logging.getLogger("sop_retrieval")
TOPICS = {"sop_duplicate_charge": "duplicate_charge", "sop_unauthorized": "unauthorized",
          "sop_refund": "refund", "sop_recurring": "recurring"}
DOC_VERSION = "2026-01"


def chunk_markdown(text: str) -> list[dict]:
    """One chunk per '## <SECTION-ID> <title>' section."""
    doc_title, chunks, cur = "", [], None
    for line in text.splitlines():
        if line.startswith("# "):
            doc_title = line[2:].strip()
        elif line.startswith("## "):
            if cur:
                chunks.append(cur)
            sid, _, title = line[3:].strip().partition(" ")
            cur = {"section_id": sid, "title": title or doc_title, "lines": []}
        elif cur is not None:
            cur["lines"].append(line)
    if cur:
        chunks.append(cur)
    return [{"section_id": c["section_id"], "title": c["title"], "text": "\n".join(c["lines"]).strip()}
            for c in chunks]


def load_sop_docs(store: VectorStore, sop_dir: Path) -> int:
    n = 0
    for f in sorted(Path(sop_dir).glob("*.md")):
        chunks = [c for c in chunk_markdown(f.read_text(encoding="utf-8"))
                  if f"{DOC_VERSION}:{c['section_id']}" not in store.records]
        if not chunks:
            continue
        vecs = embeddings.embed([f"{c['title']}\n{c['text']}" for c in chunks])
        store.upsert([{"key": f"{DOC_VERSION}:{c['section_id']}", "topic": TOPICS.get(f.stem, "general"),
                       "doc_version": DOC_VERSION, "embedding": v, **c} for c, v in zip(chunks, vecs)])
        n += len(chunks)
    return n


class SopRetrieval(pbg.SopRetrievalServiceServicer):
    def __init__(self, vector_path: str | None = None, sop_dir: Path | None = None):
        self.store = VectorStore(vector_path or config.VECTOR_PATH)
        added = load_sop_docs(self.store, sop_dir or config.SOP_DIR)
        log.info("loaded %d new SOP sections (%d total)", added, len(self.store.records))

    def RetrieveSop(self, request, context):
        if not request.query:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "query is required")
        hits = self.store.search(embeddings.embed([request.query])[0], request.top_k or 4, request.topic or None)
        return pb.RetrieveSopResponse(chunks=[pb.SopChunk(
            section_id=h["section_id"], title=h["title"], text=h["text"], score=h["score"],
            doc_version=h["doc_version"]) for h in hits])


def serve(addr: str | None = None, vector_path: str | None = None, sop_dir: Path | None = None):
    servicer = SopRetrieval(vector_path, sop_dir)
    return start_server(lambda s: pbg.add_SopRetrievalServiceServicer_to_server(servicer, s),
                        addr or config.service_addr("SOP_RETRIEVAL"))


if __name__ == "__main__":
    run_forever(serve, "SopRetrievalService")
