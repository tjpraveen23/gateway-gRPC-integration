"""Crown Gateway v2 (FastAPI).

HTTP in (text + customer_id + account_number)
 -> RAG: SopRetrievalService.RetrieveSop with the input text            (gRPC)
 -> Groq LLM: intent, goal, skills from SOP context + skill catalog      (HTTPS)
 -> stage 1, in parallel: transaction skill + account skill              (gRPC, steps from skill.json)
 -> stage 2: insights skill                                              (gRPC)
 -> analyst action message + per-call timing (HTTP out)."""
import asyncio
import hmac
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import crown_pb2 as pb
import crown_pb2_grpc as pbg
from common import ROOT, SERVICE_ADDRS, chat_json
from skill_runtime import (ManualReview, execute_skill, load_skills, plan_stages, to_dict, union_ms)

log = logging.getLogger("gateway")

API_KEY = os.getenv("GATEWAY_API_KEY", "dev-key")
TIME_BUDGET_S = float(os.getenv("REQUEST_BUDGET_S", "25"))
MIN_ROUTE_CONF = 0.6
MIN_RESULT_CONF = 0.6
FALLBACK_INTENT = "general_transaction_inquiry"
RAG_TOP_K = 6


# ------------------------------------------------------------------ timing
class Timer:
    """Records every gRPC call with its start offset and duration (parallel calls overlap)."""

    def __init__(self, correlation_id: str):
        self.cid = correlation_id
        self.t0 = time.perf_counter()
        self.calls: list[dict] = []

    def elapsed(self) -> float:
        return time.perf_counter() - self.t0

    async def call(self, skill: str, step: str, rpc_name: str, rpc, request, timeout: float = 30):
        if self.elapsed() > TIME_BUDGET_S:
            raise ManualReview(f"Time budget exceeded before '{skill}.{step}'")
        start = time.perf_counter()
        rec = {"call": f"{skill}.{step}", "skill": skill, "rpc": rpc_name,
               "start_ms": round((start - self.t0) * 1000), "ms": 0}
        self.calls.append(rec)
        try:
            return await rpc(request, timeout=timeout, metadata=(("x-correlation-id", self.cid),))
        finally:
            rec["ms"] = round((time.perf_counter() - start) * 1000)

    def block(self, routing_ms: int) -> dict:
        calls = sorted(self.calls, key=lambda c: c["start_ms"])
        return {"llm_routing_ms": routing_ms, "calls": calls,
                "overall_grpc_ms": union_ms(calls),          # wall time with parallel calls counted once
                "sum_of_call_ms": sum(c["ms"] for c in calls),  # cumulative time of all calls
                "gateway_total_ms": round(self.elapsed() * 1000)}


# ------------------------------------------------------------------ app
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.skills = load_skills()
    chans, stubs = {}, {}
    for svc, addr in SERVICE_ADDRS.items():  # insecure for local dev; use mTLS in production
        ch = chans.setdefault(addr, grpc.aio.insecure_channel(addr))
        stubs[svc] = getattr(pbg, f"{svc}Stub")(ch)
    app.state.stubs = stubs
    log.info("Loaded skills: %s", {n: s.version for n, s in app.state.skills.items()})
    yield
    for c in chans.values():
        await c.close()


app = FastAPI(title="Crown Gateway", lifespan=lifespan)


class AssistRequest(BaseModel):
    analyst_id: str
    customer_id: str
    account_number: str
    text: str


def _auth(key: str | None):
    if not hmac.compare_digest(key or "", API_KEY):
        raise HTTPException(401, "invalid API key")


ROUTER_SYSTEM = """You are the intent router of a credit card contact-center assistant.
Use the analyst's input text, the SOP policy context retrieved for it, and the catalog of available skills.
Return JSON: {"intent": "<one of allowed_intents>", "goal": "<what the analyst needs to achieve>",
 "confidence": <0-1>, "skills": [<skill names from the catalog>],
 "entities": {"amount": <number|null>, "merchant": <string|null>, "date_hint": <string|null>,
              "cancellation_date": <string|null>, "other": <string|null>}}
Rules:
- Pick the intent only from allowed_intents and skills only from the catalog.
- For a customer issue that needs a recommendation, select "insights"; the gateway adds the skills it requires.
  Select only "transaction" or "account" when the analyst just wants that data.
- If nothing fits, return an empty skills list and confidence below 0.5. Do not guess."""


def _empty_result(reason: str) -> dict:
    return {"manual_review": True, "manual_review_reason": reason,
            "analyst_action_message": "No automated recommendation available. Please follow the SOP manually.",
            "evidence": [], "sop_references": [], "recommended_actions": []}


def _finalize_insight(insight_json: str) -> dict:
    r = json.loads(insight_json)
    reason = None
    if not r.get("sop_references"):
        reason = "Recommendation is not grounded in any SOP section"
    elif r.get("classification") == "needs_manual_review":
        reason = "Insight agent could not decide from the SOP and data"
    elif float(r.get("confidence", 0)) < MIN_RESULT_CONF:
        reason = f"Low confidence ({r.get('confidence')})"
    r["manual_review"] = reason is not None
    r["manual_review_reason"] = reason
    return r


def _safe_json(s, default):
    try:
        return json.loads(s) if isinstance(s, str) and s else default
    except json.JSONDecodeError:
        return default


@app.post("/v1/analyst/assist")
async def assist(req: AssistRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    cid = str(uuid.uuid4())
    timer = Timer(cid)
    skills = app.state.skills
    stubs = app.state.stubs

    def response(intent=None, goal=None, selected=None, stages=None, sections=None, skill_info=None,
                 result=None, reference=None, routing_ms=0):
        return {"correlation_id": cid, "analyst_id": req.analyst_id, "customer_id": req.customer_id,
                "account_number": req.account_number, "intent": intent, "goal": goal,
                "selected_skills": selected or [], "plan": stages or [],
                "rag": {"query": req.text, "sections": sections or []},
                "skills": skill_info or {}, "result": result, "reference": reference,
                "timing": timer.block(routing_ms)}

    # 1. RAG: input text -> SOP context (gRPC)
    try:
        rag = await timer.call("gateway", "rag_retrieve", "SopRetrievalService.RetrieveSop",
                               stubs["SopRetrievalService"].RetrieveSop,
                               pb.RetrieveSopRequest(query=req.text, top_k=RAG_TOP_K))
        sop_chunks = [to_dict(c) for c in rag.chunks]
    except (grpc.aio.AioRpcError, ManualReview) as e:
        return response(result=_empty_result(f"SOP retrieval failed: {getattr(e, 'details', lambda: e)()}"))
    sections = [{"section_id": c["section_id"], "title": c["title"], "score": round(c["score"], 3)}
                for c in sop_chunks]
    if not sop_chunks:
        return response(result=_empty_result("No SOP context found for this request"))

    # 2. LLM routing: intent, goal, entities, skills (from SOP context + skill catalog)
    allowed_intents = sorted({i for s in skills.values() for i in s.meta.get("intents", [])})
    payload = {"input_text": req.text, "allowed_intents": allowed_intents,
               "skills": [s.catalog_entry() for s in skills.values()],
               "sop_context": [{"section_id": c["section_id"], "title": c["title"], "text": c["text"][:500]}
                               for c in sop_chunks]}
    t = time.perf_counter()
    try:
        sel = await asyncio.to_thread(chat_json, ROUTER_SYSTEM, json.dumps(payload))
    except Exception as e:  # noqa: BLE001
        log.exception("routing failed")
        raise HTTPException(502, f"LLM error during routing: {e}") from e
    routing_ms = round((time.perf_counter() - t) * 1000)

    chosen = [n for n in sel.get("skills", []) if n in skills]
    intent = sel.get("intent") if sel.get("intent") in allowed_intents else FALLBACK_INTENT
    goal, entities = sel.get("goal"), sel.get("entities") or {}
    if not chosen or float(sel.get("confidence", 0)) < MIN_ROUTE_CONF:
        return response(intent=intent, goal=goal, sections=sections, routing_ms=routing_ms,
                        result=_empty_result("No skill matched the request with enough confidence"))

    stages = plan_stages(chosen, skills)

    # 3. execute stages; skills inside a stage run in parallel
    async def invoke(skill_name, step_id, svc, meth, request, timeout):
        return await timer.call(skill_name, step_id, f"{svc}.{meth}", getattr(stubs[svc], meth), request, timeout)

    base_ctx = {"customer_id": req.customer_id, "account_number": req.account_number, "text": req.text,
                "intent": intent, "goal": goal, "entities": entities, "entities_json": json.dumps(entities),
                "sop_chunks": sop_chunks}
    results: dict[str, dict] = {}

    async def run_one(name: str) -> tuple[str, dict]:
        skill, t0 = skills[name], time.perf_counter()
        for dep in skill.requires:  # a failed REQUIRED dependency stops this skill
            r = results.get(dep)
            if r and not r["ok"] and skills[dep].required:
                return name, {"ok": False, "outputs": {}, "ms": 0, "error": f"Dependency '{dep}' failed: {r['error']}"}
        ctx = {**base_ctx, **{n: r["outputs"] for n, r in results.items()}}
        outputs, error = {}, None
        try:
            outputs = await execute_skill(skill, ctx, invoke)
        except ManualReview as e:
            error = str(e)
        except grpc.aio.AioRpcError as e:
            error = f"{e.code().name}: {e.details()}"
            log.error("[%s] %s failed: %s", cid, name, error)
        except Exception as e:  # noqa: BLE001
            log.exception("skill %s crashed", name)
            error = f"{type(e).__name__}: {e}"
        if error and not skill.required:
            outputs = skill.meta.get("fallback_outputs", {})
        return name, {"ok": error is None, "outputs": outputs, "error": error,
                      "ms": round((time.perf_counter() - t0) * 1000)}

    for stage in stages:
        for name, r in await asyncio.gather(*(run_one(n) for n in stage)):
            results[name] = r

    # 4. assemble response
    skill_info = {}
    for name, r in results.items():
        info = {"ok": r["ok"], "ms": r["ms"], "version": skills[name].version, "error": r["error"]}
        if name == "transaction" and r["ok"]:
            info.update(row_count=r["outputs"].get("row_count"), profile=r["outputs"].get("profile"),
                        sql=r["outputs"].get("sql"))
        skill_info[name] = info

    reference = _safe_json(results.get("account", {}).get("outputs", {}).get("account_json"), None)
    if "insights" in results and results["insights"]["ok"]:
        result = _finalize_insight(results["insights"]["outputs"]["insight_json"])
    elif "insights" in results:
        result = _empty_result(results["insights"]["error"])
    else:  # data-only request (no insights skill selected)
        failed = [f"{n}: {r['error']}" for n, r in results.items() if not r["ok"]]
        result = {"manual_review": bool(failed), "manual_review_reason": "; ".join(failed) or None,
                  "analyst_action_message": "Requested data retrieved. No recommendation was requested.",
                  "evidence": [], "sop_references": [], "recommended_actions": []}
    log.info("[%s] intent=%s stages=%s grpc_ms=%d", cid, intent, stages, union_ms(timer.calls))
    return response(intent, goal, chosen, stages, sections, skill_info, result, reference, routing_ms)


@app.get("/v1/skills")
async def list_skills(x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    return [{"name": s.name, "version": s.version, "requires": s.requires, "required": s.required,
             "version_history": s.meta["version_history"]} for s in app.state.skills.values()]


@app.get("/", include_in_schema=False)
async def ui():
    """Demo UI (ui/index.html), same origin as the API so no CORS is needed."""
    return FileResponse(ROOT / "ui" / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "skills": {n: s.version for n, s in app.state.skills.items()}}
