"""Crown Gateway (FastAPI). HTTP in -> OpenAI picks skill(s) -> gRPC calls -> analyst action message."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import grpc
import yaml
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel

import crown_pb2 as pb
import crown_pb2_grpc as pbg
from common import INSIGHT_ADDR, MCP_ADDR, ROOT, SOP_ADDR, chat_json

log = logging.getLogger("gateway")

API_KEY = os.getenv("GATEWAY_API_KEY", "dev-key")
CALLBACK_SECRET = os.getenv("CALLBACK_SECRET", "dev-secret")
PUBLIC_URL = os.getenv("GATEWAY_PUBLIC_URL", "http://localhost:8000")
TIME_BUDGET_S = float(os.getenv("REQUEST_BUDGET_S", "25"))
MAX_SQL_ATTEMPTS = 3
MIN_SKILL_CONF = 0.6
MIN_RESULT_CONF = 0.6
UPLOAD_DIR = ROOT / "data" / "uploads"
JOBS: dict[str, dict] = {}  # ingestion jobs updated by callbacks


# ------------------------------------------------------------------ skills
@dataclass
class Skill:
    name: str
    description: str
    triggers: list
    lookback_days: int
    sop_topic: str
    sop_query: str
    data_question: str
    insight_skill: str


def load_skills() -> dict[str, Skill]:
    skills = {}
    for p in sorted((ROOT / "skills").glob("*.yaml")):
        d = yaml.safe_load(p.read_text())
        skills[d["name"]] = Skill(**d)
    return skills


SELECT_SYSTEM = """You are the intent router of a credit card contact-center assistant.
Given the customer's message (relayed by an analyst) and the catalog of available skills, return JSON:
{"intent": "<short label>", "goal": "<what the analyst needs to achieve>",
 "confidence": <0-1>, "skills": [<skill names, ordered, max 2, empty if none fits>],
 "entities": {"amount": <number|null>, "merchant": <string|null>, "date_hint": <string|null>,
              "cancellation_date": <string|null>, "other": <string|null>}}
Choose only skill names that exist in the catalog. Do not guess: if nothing fits, return an empty skills list."""


# ------------------------------------------------------------------ timing + gRPC helper
class ManualReview(Exception):
    pass


class Timer:
    """Wraps every gRPC call, records its duration, enforces the overall budget."""

    def __init__(self, correlation_id: str):
        self.cid = correlation_id
        self.calls: list[dict] = []
        self.t0 = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self.t0

    async def call(self, name: str, rpc, request, timeout: float = 30):
        if self.elapsed() > TIME_BUDGET_S:
            raise ManualReview(f"Time budget exceeded before '{name}'")
        t = time.perf_counter()
        try:
            return await rpc(request, timeout=timeout, metadata=(("x-correlation-id", self.cid),))
        finally:
            self.calls.append({"call": name, "ms": round((time.perf_counter() - t) * 1000)})


# ------------------------------------------------------------------ app
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.skills = load_skills()
    chans = [grpc.aio.insecure_channel(a) for a in (MCP_ADDR, SOP_ADDR, INSIGHT_ADDR)]  # mTLS in prod
    app.state.mcp = pbg.MCPToolsServiceStub(chans[0])
    app.state.sop = pbg.SOPServiceStub(chans[1])
    app.state.insight = pbg.InsightServiceStub(chans[2])
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Loaded skills: %s", list(app.state.skills))
    yield
    for c in chans:
        await c.close()


app = FastAPI(title="Crown Gateway", lifespan=lifespan)


class AssistRequest(BaseModel):
    analyst_id: str
    customer_id: str
    card_id: str
    message: str


def _auth(key: str | None):
    if not hmac.compare_digest(key or "", API_KEY):
        raise HTTPException(401, "invalid API key")


async def run_skill(app: FastAPI, skill: Skill, req: AssistRequest, entities: dict, timer: Timer) -> dict:
    partial: dict = {}
    try:
        # 1-2. text2sql -> sql_validator (retry with validator feedback)
        question = (f"{skill.data_question}\nCustomer message: {req.message}\n"
                    f"Extracted entities: {json.dumps(entities)}")
        feedback, sql = "", None
        for _ in range(MAX_SQL_ATTEMPTS):
            t2s = await timer.call("text2sql", app.state.mcp.Text2Sql, pb.Text2SqlRequest(
                question=question, customer_id=req.customer_id, card_id=req.card_id,
                lookback_days=skill.lookback_days, feedback=feedback))
            v = await timer.call("sql_validator", app.state.mcp.ValidateSql, pb.ValidateSqlRequest(
                sql=t2s.sql, customer_id=req.customer_id, card_id=req.card_id))
            if v.valid:
                sql = v.sanitized_sql
                break
            feedback = f"Previous SQL: {t2s.sql}\nValidator errors: {list(v.errors)}"
        if not sql:
            raise ManualReview(f"SQL validation failed after {MAX_SQL_ATTEMPTS} attempts: {feedback}")
        partial["sql"] = sql

        # 3. execute validated SQL
        ex = await timer.call("sql_execute", app.state.mcp.ExecuteSql, pb.ExecuteSqlRequest(
            sql=sql, customer_id=req.customer_id, card_id=req.card_id))
        rows = json.loads(ex.rows_json)
        partial["transactions"] = rows
        if not rows:
            raise ManualReview("No transactions found for this card in the lookback window")

        # 4. SOP retrieval from vector DB
        sop = await timer.call("sop_retrieve", app.state.sop.Retrieve, pb.RetrieveRequest(
            query=skill.sop_query, top_k=4, topic=skill.sop_topic))
        if not sop.chunks:
            raise ManualReview("No SOP guideline found for this request")

        # 5. insight agent, sending the insight skill
        ins = await timer.call("insight_agent", app.state.insight.Analyze, pb.AnalyzeRequest(
            insight_skill=skill.insight_skill, customer_message=req.message,
            transactions_json=json.dumps(rows), sop_chunks=sop.chunks,
            entities_json=json.dumps(entities)), timeout=60)
        result = json.loads(ins.result_json)

        reason = None
        if not result.get("sop_references"):
            reason = "Recommendation is not grounded in any SOP section"
        elif result.get("classification") == "needs_manual_review":
            reason = "Insight agent could not decide from the SOP and data"
        elif float(result.get("confidence", 0)) < MIN_RESULT_CONF:
            reason = f"Low confidence ({result.get('confidence')})"
        return {"skill": skill.name, "manual_review": reason is not None,
                "manual_review_reason": reason, "sql": sql, **result}

    except ManualReview as e:
        reason = str(e)
    except grpc.aio.AioRpcError as e:
        log.error("[%s] gRPC error %s: %s", timer.cid, e.code(), e.details())
        reason = f"Downstream service error: {e.code().name} {e.details()}"
    return {"skill": skill.name, "manual_review": True, "manual_review_reason": reason,
            "analyst_action_message": "No automated recommendation available. Please follow the SOP manually.",
            "evidence": partial.get("transactions", [])[:10], "sql": partial.get("sql")}


@app.post("/v1/analyst/assist")
async def assist(req: AssistRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    cid = str(uuid.uuid4())
    timer = Timer(cid)
    skills: dict[str, Skill] = app.state.skills

    # LLM: detect intent + goal, extract entities, select skill(s) from the catalog
    t = time.perf_counter()
    catalog = [{"name": s.name, "description": s.description, "triggers": s.triggers} for s in skills.values()]
    try:
        sel = await asyncio.to_thread(chat_json, SELECT_SYSTEM,
                                      json.dumps({"message": req.message, "skills": catalog}))
    except Exception as e:  # noqa: BLE001
        log.exception("skill selection failed")
        raise HTTPException(502, f"LLM error during skill selection: {e}") from e
    selection_ms = round((time.perf_counter() - t) * 1000)

    chosen = [n for n in sel.get("skills", []) if n in skills][:2]
    entities = sel.get("entities") or {}
    results = []
    if not chosen or float(sel.get("confidence", 0)) < MIN_SKILL_CONF:
        results.append({"skill": None, "manual_review": True,
                        "manual_review_reason": "No skill matched the request with enough confidence",
                        "analyst_action_message": "Request not recognised. Please handle manually per SOP."})
        chosen = []
    for name in chosen:  # one or more skills, sequentially
        results.append(await run_skill(app, skills[name], req, entities, timer))

    overall_grpc_ms = sum(c["ms"] for c in timer.calls)
    log.info("[%s] intent=%s skills=%s grpc_ms=%d", cid, sel.get("intent"), chosen, overall_grpc_ms)
    return {
        "correlation_id": cid, "analyst_id": req.analyst_id,
        "intent": sel.get("intent"), "goal": sel.get("goal"), "selected_skills": chosen,
        "results": results,
        "timing": {"llm_skill_selection_ms": selection_ms, "calls": timer.calls,
                   "overall_grpc_ms": overall_grpc_ms,
                   "gateway_total_ms": round(timer.elapsed() * 1000)},
    }


# ------------------------------------------------------------------ SOP ingestion (async + callback)
@app.post("/v1/sop/ingest")
async def ingest_sop(file: UploadFile = File(...), topic: str = Form(...), doc_version: str = Form("v1"),
                     x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}_{Path(file.filename).name}"
    dest.write_bytes(await file.read())  # use shared object storage in production
    ack = await app.state.sop.IngestFile(pb.IngestRequest(
        file_path=str(dest), topic=topic, doc_version=doc_version,
        callback_url=f"{PUBLIC_URL}/v1/callbacks/ingestion"), timeout=10)
    JOBS.setdefault(ack.job_id, {"job_id": ack.job_id, "status": ack.status})
    return {"job_id": ack.job_id, "status": ack.status}


@app.post("/v1/callbacks/ingestion")
async def ingestion_callback(request: Request, x_signature: str | None = Header(default=None)):
    body = await request.body()
    expected = hmac.new(CALLBACK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_signature or ""):
        raise HTTPException(401, "bad signature")
    data = json.loads(body)
    JOBS[data["job_id"]] = data
    return {"ok": True}


@app.get("/v1/sop/ingest/{job_id}")
async def ingest_status(job_id: str, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    if job_id in JOBS and JOBS[job_id].get("status") in ("COMPLETED", "FAILED"):
        return JOBS[job_id]
    try:
        j = await app.state.sop.GetJob(pb.JobRequest(job_id=job_id), timeout=5)
    except grpc.aio.AioRpcError as e:
        raise HTTPException(404, "unknown job") from e
    return {"job_id": j.job_id, "status": j.status, "detail": j.detail}


@app.get("/health")
async def health():
    return {"status": "ok", "skills": list(app.state.skills)}
