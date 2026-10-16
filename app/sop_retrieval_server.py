"""gRPC: SopRetrievalService.

In your environment this is the EXISTING retrieval service over the enterprise vector DB.
This file is a local stand-in with the same proto contract: at startup it loads sop_docs/*.md
into a local vector store so the gateway can be run end to end."""
import logging
from concurrent import futures

import grpc

import crown_pb2 as pb
import crown_pb2_grpc as pbg
from common import ROOT, SOP_ADDR, VECTOR_PATH, embed, port_of
from vectorstore import VectorStore

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


def load_sop_docs(store: VectorStore) -> int:
    n = 0
    for f in sorted((ROOT / "sop_docs").glob("*.md")):
        chunks = [c for c in chunk_markdown(f.read_text(encoding="utf-8"))
                  if f"{DOC_VERSION}:{c['section_id']}" not in store.records]
        if not chunks:
            continue
        vecs = embed([f"{c['title']}\n{c['text']}" for c in chunks])
        store.upsert([{"key": f"{DOC_VERSION}:{c['section_id']}", "topic": TOPICS.get(f.stem, "general"),
                       "doc_version": DOC_VERSION, "embedding": v, **c} for c, v in zip(chunks, vecs)])
        n += len(chunks)
    return n


class SopRetrieval(pbg.SopRetrievalServiceServicer):
    def __init__(self):
        self.store = VectorStore(VECTOR_PATH)
        log.info("loaded %d new SOP sections (%d total)", load_sop_docs(self.store), len(self.store.records))

    def RetrieveSop(self, request, context):
        if not request.query:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "query is required")
        hits = self.store.search(embed([request.query])[0], request.top_k or 4, request.topic or None)
        return pb.RetrieveSopResponse(chunks=[pb.SopChunk(
            section_id=h["section_id"], title=h["title"], text=h["text"],
            score=h["score"], doc_version=h["doc_version"]) for h in hits])


def serve(addr: str = SOP_ADDR):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pbg.add_SopRetrievalServiceServicer_to_server(SopRetrieval(), server)
    server.add_insecure_port(f"[::]:{port_of(addr)}")
    server.start()
    log.info("SopRetrievalService listening on %s", addr)
    return server


if __name__ == "__main__":
    serve().wait_for_termination()
