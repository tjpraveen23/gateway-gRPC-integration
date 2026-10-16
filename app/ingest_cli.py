"""Ingest every sop_docs/*.md into the vector DB through the SOP gRPC module (async job + polling)."""
import time

import grpc

import crown_pb2 as pb
import crown_pb2_grpc as pbg
from common import ROOT, SOP_ADDR

TOPICS = {"sop_duplicate_charge": "duplicate_charge", "sop_unauthorized": "unauthorized",
          "sop_refund": "refund", "sop_recurring": "recurring"}

stub = pbg.SOPServiceStub(grpc.insecure_channel(SOP_ADDR))
jobs = {}
for f in sorted((ROOT / "sop_docs").glob("*.md")):
    ack = stub.IngestFile(pb.IngestRequest(file_path=str(f), topic=TOPICS[f.stem], doc_version="2026-01"))
    jobs[ack.job_id] = f.name
    print(f"submitted {f.name} -> job {ack.job_id}")

while jobs:
    for job_id in list(jobs):
        j = stub.GetJob(pb.JobRequest(job_id=job_id))
        if j.status in ("COMPLETED", "FAILED"):
            print(f"{jobs.pop(job_id)}: {j.status} {j.detail}")
    time.sleep(1)
