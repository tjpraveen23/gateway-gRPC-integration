"""gRPC module: SOP file ingestion (async + callback) and retrieval from the vector DB."""
import hashlib
import hmac
import json
import logging
import os
import threading
import urllib.request
import uuid
from concurrent import futures
from pathlib import Path

import grpc

import crown_pb2 as pb
import crown_pb2_grpc as pbg
from common import SOP_ADDR, VECTOR_PATH, embed, port_of
from vectorstore import VectorStore

log = logging.getLogger("sop")


def chunk_markdown(text: str) -> list[dict]:
    """Split a SOP markdown file into one chunk per '## <SECTION-ID> <title>' section."""
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


class SOPService(pbg.SOPServiceServicer):
    def __init__(self):
        self.store = VectorStore(VECTOR_PATH)
        self.jobs: dict[str, dict] = {}

    # ---- async ingestion: ack immediately, work in background, call back when done ----
    def IngestFile(self, request, context):
        job_id = uuid.uuid4().hex
        self.jobs[job_id] = {"job_id": job_id, "status": "ACCEPTED", "detail": ""}
        threading.Thread(target=self._ingest, args=(job_id, request), daemon=True).start()
        return pb.IngestAck(job_id=job_id, status="ACCEPTED")

    def GetJob(self, request, context):
        j = self.jobs.get(request.job_id)
        if not j:
            context.abort(grpc.StatusCode.NOT_FOUND, "unknown job")
        return pb.IngestAck(job_id=j["job_id"], status=j["status"], detail=j["detail"])

    def _ingest(self, job_id: str, req) -> None:
        try:
            self.jobs[job_id]["status"] = "RUNNING"
            text = Path(req.file_path).read_text(encoding="utf-8")
            chunks = chunk_markdown(text)
            if not chunks:
                raise ValueError("no '## <SECTION-ID> title' sections found")
            vecs = embed([f"{c['title']}\n{c['text']}" for c in chunks])
            self.store.upsert([{
                "key": f"{req.doc_version}:{c['section_id']}", "topic": req.topic,
                "doc_version": req.doc_version, "embedding": v, **c,
            } for c, v in zip(chunks, vecs)])
            self.jobs[job_id].update(status="COMPLETED", detail=f"{len(chunks)} sections ingested")
        except Exception as e:  # noqa: BLE001
            log.exception("ingestion failed")
            self.jobs[job_id].update(status="FAILED", detail=str(e))
        if req.callback_url:
            self._callback(req.callback_url, self.jobs[job_id])

    @staticmethod
    def _callback(url: str, payload: dict) -> None:
        body = json.dumps(payload).encode()
        sig = hmac.new(os.getenv("CALLBACK_SECRET", "dev-secret").encode(), body, hashlib.sha256).hexdigest()
        for attempt in range(3):  # simple retry; use a durable queue/event bus in production
            try:
                r = urllib.request.Request(url, data=body, headers={
                    "Content-Type": "application/json", "X-Signature": sig})
                urllib.request.urlopen(r, timeout=5).read()
                return
            except Exception as e:  # noqa: BLE001
                log.warning("callback attempt %d failed: %s", attempt + 1, e)

    # ---- retrieval ----
    def Retrieve(self, request, context):
        qvec = embed([request.query])[0]
        hits = self.store.search(qvec, request.top_k or 4, request.topic or None)
        return pb.RetrieveResponse(chunks=[pb.SopChunk(
            section_id=h["section_id"], title=h["title"], text=h["text"],
            score=h["score"], doc_version=h["doc_version"]) for h in hits])


def serve(addr: str = SOP_ADDR):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pbg.add_SOPServiceServicer_to_server(SOPService(), server)
    server.add_insecure_port(f"[::]:{port_of(addr)}")
    server.start()
    log.info("SOP service listening on %s", addr)
    return server


if __name__ == "__main__":
    serve().wait_for_termination()
