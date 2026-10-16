# Crown Gateway: Design Plan (for GitHub Copilot code generation)

How to use this file: open it in the workspace, then feed the prompts in section 12 to Copilot one at a time, in order.
Sections 6 to 8 contain the **exact code** to reproduce (proto, skills, gateway). Section 9 contains **skeletons only** for the gRPC services; Copilot implements the bodies using the contracts in section 10.

---

## 1. Goal

A contact center analyst sends a customer message (for example "Credit card transaction charged twice") to the **Crown Gateway** over HTTP. The gateway:

1. Uses an Groq LLM to detect the intent and goal, extract entities, and select one or more **skills** from the skill catalog.
2. Executes the skill by calling gRPC services in order.
3. Returns an **analyst action message** with evidence, SOP references, confidence and per-call timing.

The gateway only recommends. It never executes financial actions (provisional credit, dispute, card block). The analyst does that manually.

## 2. Components

| Component | Protocol in | Role |
|---|---|---|
| Crown Gateway (FastAPI) | HTTP | Auth, skill selection (Groq), orchestration, timing, response |
| Text2SQL service | gRPC | Wraps the text2sql MCP tool. Natural language to SQL |
| SQL validator service | gRPC | Invoked directly (not via MCP). Validates SQL |
| SQL executor service | gRPC | Invoked directly (not via MCP). Runs validated read-only SQL |
| Ingest agent service | gRPC | Async SOP file ingestion into the enterprise vector DB, plus SOP retrieval |
| Insight agent service | gRPC | Receives the insight skill + data + SOP excerpts, returns insights and recommendations |
| Groq | HTTPS | LLM used by the gateway, text2sql and insight agent |
| Local embedder (fastembed) | in-process | Embeddings for SOP chunks and queries |
| Enterprise vector DB | vendor API | Stores SOP chunks and embeddings |

## 3. Call flow (per analyst request)

| # | From | To | Protocol | Operation |
|---|---|---|---|---|
| 1 | Analyst desktop | Gateway | HTTP | `POST /v1/analyst/assist` |
| 2 | Gateway | Groq | HTTPS | Detect intent, goal, entities; select skill(s) from catalog |
| 3 | Gateway | Text2SQL service | gRPC | `Text2Sql` |
| 4 | Gateway | SQL validator service | gRPC | `ValidateSql` (if invalid, repeat 3 and 4 with validator feedback, max 3 attempts) |
| 5 | Gateway | SQL executor service | gRPC | `ExecuteSql` |
| 6 | Gateway | Ingest agent service | gRPC | `RetrieveSop` |
| 7 | Gateway | Insight agent service | gRPC | `Analyze` (gateway sends the insight skill text) |
| 8 | Gateway | Analyst desktop | HTTP | `200` with the response contract (section 11) |

Steps 3 to 7 run once per selected skill (maximum 2 skills per request, executed sequentially).

SOP ingestion (async):

| # | From | To | Protocol | Operation |
|---|---|---|---|---|
| 1 | Admin | Gateway | HTTP | `POST /v1/sop/ingest` (multipart) |
| 2 | Gateway | Ingest agent | gRPC | `IngestFile` (returns `job_id` immediately) |
| 3 | Gateway | Admin | HTTP | `200` with `job_id`, status `ACCEPTED` |
| 4 | Ingest agent | Local embedder + vector DB | in-process / vendor API | Chunk, embed, upsert (background) |
| 5 | Ingest agent | Gateway | HTTP | Signed callback `POST /v1/callbacks/ingestion` |

## 4. Technology

- Python 3.11+
- FastAPI + uvicorn, gRPC (`grpcio`, `grpcio-tools`, `grpc.aio` in the gateway), protobuf
- Groq Python SDK (chat completions with `response_format={"type": "json_object"}`); the key is read from `.env` as `GROQ_API_KEY`
- `fastembed` for local embeddings (Groq has no embeddings API)
- `sqlglot` (validator), `pyyaml` (skills), `numpy`, `python-dotenv`, `python-multipart`

## 5. Repository layout

```
crown_gateway/
  design-plan.md
  requirements.txt
  .env.example
  run_all.sh
  proto/crown.proto
  skills/
    duplicate_charge_dispute.yaml
    unauthorized_transaction.yaml
    merchant_refund_missing.yaml
    recurring_charge_after_cancellation.yaml
  sop_docs/                      (SOP markdown files, "## <SECTION-ID> <title>" headings)
  data/                          (runtime: uploads, local stores)
  app/
    common.py                    (exact code, section 8.1)
    gateway.py                   (exact code, section 8.2)
    crown_pb2.py                 (generated)
    crown_pb2_grpc.py            (generated)
    text2sql_server.py           (skeleton, section 9.1)
    sql_validator.py             (library skeleton, section 9.2)
    sql_validator_server.py      (skeleton, section 9.2)
    sql_executor_server.py       (skeleton, section 9.3)
    ingest_agent_server.py       (skeleton, section 9.4)
    vectorstore.py               (interface skeleton, section 9.4)
    insight_server.py            (skeleton, section 9.5)
  tests/
```

Generated proto code is placed in `app/` so the generated `import crown_pb2` resolves. Run all scripts from the project root as `python app/<script>.py` and the gateway as `uvicorn --app-dir app gateway:app`.

### requirements.txt

```
fastapi>=0.110
uvicorn[standard]>=0.29
python-multipart>=0.0.9
grpcio>=1.62
grpcio-tools>=1.62
protobuf>=4.25
groq>=0.11
fastembed>=0.3
sqlglot>=23.0
pyyaml>=6.0
numpy>=1.26
python-dotenv>=1.0
pytest>=8.0
httpx>=0.27
```

### .env.example

```
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
EMBED_MODEL=BAAI/bge-small-en-v1.5

GATEWAY_API_KEY=dev-key
CALLBACK_SECRET=dev-secret
GATEWAY_PUBLIC_URL=http://localhost:8000
REQUEST_BUDGET_S=25

TEXT2SQL_ADDR=localhost:50051
VALIDATOR_ADDR=localhost:50052
EXECUTOR_ADDR=localhost:50053
INGEST_ADDR=localhost:50054
INSIGHT_ADDR=localhost:50055
```

### run_all.sh

```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python -m grpc_tools.protoc -I proto --python_out=app --grpc_python_out=app proto/crown.proto
python app/text2sql_server.py &
python app/sql_validator_server.py &
python app/sql_executor_server.py &
python app/ingest_agent_server.py &
python app/insight_server.py &
sleep 2
cd app && uvicorn gateway:app --host 0.0.0.0 --port 8000
```

---

## 6. gRPC contract: `proto/crown.proto` (exact)

Generate with: `python -m grpc_tools.protoc -I proto --python_out=app --grpc_python_out=app proto/crown.proto`

```proto
syntax = "proto3";
package crown;

// ---------- Text2SQL (wraps the text2sql MCP tool) ----------
service Text2SqlService {
  rpc Text2Sql(Text2SqlRequest) returns (Text2SqlResponse);
}
message Text2SqlRequest {
  string question = 1;          // data question + customer message + extracted entities
  string customer_id = 2;
  string card_id = 3;
  int32 lookback_days = 4;
  string feedback = 5;          // validator errors from a previous attempt, empty on first try
}
message Text2SqlResponse { string sql = 1; }

// ---------- SQL validator (invoked directly) ----------
service SqlValidatorService {
  rpc ValidateSql(ValidateSqlRequest) returns (ValidateSqlResponse);
}
message ValidateSqlRequest { string sql = 1; string customer_id = 2; string card_id = 3; }
message ValidateSqlResponse {
  bool valid = 1;
  string sanitized_sql = 2;     // normalized SQL with LIMIT enforced; empty when invalid
  repeated string errors = 3;
}

// ---------- SQL executor (invoked directly) ----------
service SqlExecutorService {
  rpc ExecuteSql(ExecuteSqlRequest) returns (ExecuteSqlResponse);
}
message ExecuteSqlRequest { string sql = 1; string customer_id = 2; string card_id = 3; }
message ExecuteSqlResponse {
  string rows_json = 1;         // JSON array of row objects
  int32 row_count = 2;
}

// ---------- Ingest agent: async SOP ingestion + SOP retrieval ----------
service IngestAgentService {
  rpc IngestFile(IngestRequest) returns (IngestAck);   // returns immediately; callback on completion
  rpc GetJob(JobRequest) returns (IngestAck);
  rpc RetrieveSop(RetrieveSopRequest) returns (RetrieveSopResponse);
}
message IngestRequest {
  string file_path = 1;
  string topic = 2;             // duplicate_charge | unauthorized | refund | recurring
  string doc_version = 3;
  string callback_url = 4;      // optional; HTTP POST with X-Signature (HMAC-SHA256) when finished
}
message IngestAck { string job_id = 1; string status = 2; string detail = 3; }  // ACCEPTED|RUNNING|COMPLETED|FAILED
message JobRequest { string job_id = 1; }
message RetrieveSopRequest { string query = 1; int32 top_k = 2; string topic = 3; }
message SopChunk {
  string section_id = 1;        // e.g. SOP-DISP-4.2
  string title = 2;
  string text = 3;
  double score = 4;
  string doc_version = 5;
}
message RetrieveSopResponse { repeated SopChunk chunks = 1; }

// ---------- Insight agent ----------
service InsightService { rpc Analyze(AnalyzeRequest) returns (AnalyzeResponse); }
message AnalyzeRequest {
  string insight_skill = 1;     // instructions from the skill file
  string customer_message = 2;
  string transactions_json = 3;
  repeated SopChunk sop_chunks = 4;
  string entities_json = 5;
}
message AnalyzeResponse { string result_json = 1; }  // JSON, schema in section 10.5
```

---

## 7. Skill files (exact)

Each skill is one YAML file in `skills/`. The gateway loads every `*.yaml` at startup with `Skill(**yaml.safe_load(...))`, so the keys must match exactly:
`name, description, triggers, lookback_days, sop_topic, sop_query, data_question, insight_skill`.

The first five fields (`name`, `description`, `triggers`) form the **skill catalog** sent to the LLM for selection. `data_question` goes to Text2SQL. `sop_topic` and `sop_query` drive SOP retrieval. `insight_skill` is sent to the insight agent.

### skills/duplicate_charge_dispute.yaml

```yaml
name: duplicate_charge_dispute
description: Customer says a credit card purchase was charged twice or more than once.
triggers: [charged twice, double charge, duplicate transaction, billed two times]
lookback_days: 30
sop_topic: duplicate_charge
sop_query: duplicate charge identification, pending authorization hold, provisional credit eligibility, dispute reason code
data_question: >
  List this card's transactions for the lookback window (txn_id, merchant, amount, currency, txn_ts,
  status, auth_code, channel). If the customer named a merchant or amount, still return all transactions
  so duplicates and look-alikes can be compared.
insight_skill: |
  Task: decide whether the customer was really charged twice.
  1. Find purchases at the same merchant with the same amount within 24 hours.
  2. If one entry is PENDING and shares the auth_code with a POSTED entry, classify as "pending_hold".
  3. Two POSTED entries with different auth_codes -> "duplicate_charge".
  4. Otherwise -> "no_duplicate_found" (a legitimate repeat purchase is possible).
  Recommend provisional credit and a dispute only as the SOP allows (amount thresholds, reason code).
  Put the duplicated txn_ids in evidence.
```

### skills/unauthorized_transaction.yaml

```yaml
name: unauthorized_transaction
description: Customer does not recognise or did not make a credit card transaction (possible fraud).
triggers: [I didn't make this purchase, unrecognised transaction, fraud, unauthorized charge, someone used my card]
lookback_days: 90
sop_topic: unauthorized
sop_query: fraud indicators, immediate actions for unauthorized transactions, provisional credit for fraud, card block and reissue
data_question: >
  List this card's transactions for the lookback window (txn_id, merchant, amount, currency, txn_ts,
  status, channel, country) so the disputed transaction can be compared with normal spending behaviour.
insight_skill: |
  Task: assess whether the disputed transaction(s) look fraudulent.
  1. Identify the disputed transaction(s) from the customer's message and entities (amount, merchant, date).
  2. Count fraud indicators defined in the SOP (foreign country vs usual, online/card-not-present,
     unusual hours, first-time merchant, rapid repeated charges, amount far above usual).
  3. Classify as "likely_fraud", "possible_fraud" or "likely_genuine".
  Recommend card block, reissue, provisional credit and fraud case only as the SOP allows.
  Put the disputed txn_ids and the indicators in evidence.
```

### skills/merchant_refund_missing.yaml

```yaml
name: merchant_refund_missing
description: Customer says a merchant promised or issued a refund that has not appeared on the credit card.
triggers: [refund not received, merchant said they refunded me, return credit missing, where is my refund]
lookback_days: 60
sop_topic: refund
sop_query: merchant refund posting timelines, credit not processed chargeback, documents required from the customer
data_question: >
  List this card's transactions for the lookback window (txn_id, merchant, amount, currency, txn_ts,
  status, txn_type) including both purchases and refunds so the original purchase and any refund
  credit can be matched.
insight_skill: |
  Task: determine the refund status.
  1. Find the original purchase (merchant/amount from the message and entities).
  2. Look for a REFUND with the same merchant and amount (or PENDING) after the purchase.
  3. Compute days elapsed since the customer says the refund was issued (use the message; if unknown, say so).
  4. Classify as "refund_posted", "refund_in_transit" (inside the SOP window) or "refund_overdue".
  Recommend telling the customer the expected date, or a chargeback and required documents, only as the SOP allows.
```

### skills/recurring_charge_after_cancellation.yaml

```yaml
name: recurring_charge_after_cancellation
description: Customer cancelled a subscription or membership but is still being charged on the credit card.
triggers: [still charging me after I cancelled, subscription not cancelled, membership charge after cancellation, recurring payment stop]
lookback_days: 120
sop_topic: recurring
sop_query: charges after cancellation of recurring payments, provisional credit for cancelled subscriptions, stopping recurring payments
data_question: >
  List this card's recurring transactions (is_recurring = 1) for the lookback window with txn_id,
  merchant, amount, currency, txn_ts, status, so the charge cadence can be analysed.
insight_skill: |
  Task: determine which recurring charges happened after the customer's cancellation date.
  1. Extract the cancellation date from the customer message/entities. If it is missing, classify as
     "needs_manual_review" and ask the analyst to obtain it.
  2. List the merchant's charges dated after the cancellation date and sum their amounts.
  3. Classify as "charged_after_cancellation" or "no_charge_after_cancellation".
  Recommend provisional credit, a dispute and a recurring-payment stop only as the SOP allows
  (check cycle limits and proof of cancellation requirements).
```

To add a new use case: add one YAML file and one SOP document. No gateway code change.

---

## 8. Gateway (exact code)

### 8.1 `app/common.py`

```python
"""Shared config + Groq helpers used by the gateway and all gRPC services."""
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CHAT_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")  # local; Groq has no embeddings API
DB_PATH = os.getenv("CARDS_DB", str(ROOT / "data" / "cards.db"))
VECTOR_PATH = os.getenv("VECTOR_STORE_PATH", str(ROOT / "data" / "vector_store.json"))
MCP_ADDR = os.getenv("MCP_ADDR", "localhost:50051")
SOP_ADDR = os.getenv("SOP_ADDR", "localhost:50052")
INSIGHT_ADDR = os.getenv("INSIGHT_ADDR", "localhost:50053")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

_client = None
_embedder = None


def _groq() -> Groq:
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to .env")
        _client = Groq(api_key=key)
    return _client


def chat_json(system: str, user: str) -> dict:
    """Call a Groq chat completion in JSON mode and return the parsed JSON object."""
    resp = _groq().chat.completions.create(
        model=CHAT_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return json.loads(resp.choices[0].message.content)


def embed(texts: list[str]) -> list[list[float]]:
    """Local embeddings (fastembed, ONNX). Groq does not provide an embeddings endpoint."""
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding(model_name=EMBED_MODEL)
    return [v.tolist() for v in _embedder.embed(texts)]


def port_of(addr: str) -> str:
    return addr.rsplit(":", 1)[-1]
```

### 8.2 `app/gateway.py`

```python
"""Crown Gateway (FastAPI). HTTP in -> Groq picks skill(s) -> gRPC calls -> analyst action message."""
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
from common import (EXECUTOR_ADDR, INGEST_ADDR, INSIGHT_ADDR, ROOT, TEXT2SQL_ADDR,
                    VALIDATOR_ADDR, chat_json)

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
    # insecure channels for local dev; use mTLS credentials in production
    chans = [grpc.aio.insecure_channel(a) for a in
             (TEXT2SQL_ADDR, VALIDATOR_ADDR, EXECUTOR_ADDR, INGEST_ADDR, INSIGHT_ADDR)]
    app.state.text2sql = pbg.Text2SqlServiceStub(chans[0])
    app.state.validator = pbg.SqlValidatorServiceStub(chans[1])
    app.state.executor = pbg.SqlExecutorServiceStub(chans[2])
    app.state.ingest = pbg.IngestAgentServiceStub(chans[3])
    app.state.insight = pbg.InsightServiceStub(chans[4])
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
            t2s = await timer.call("text2sql", app.state.text2sql.Text2Sql, pb.Text2SqlRequest(
                question=question, customer_id=req.customer_id, card_id=req.card_id,
                lookback_days=skill.lookback_days, feedback=feedback))
            v = await timer.call("sql_validator", app.state.validator.ValidateSql, pb.ValidateSqlRequest(
                sql=t2s.sql, customer_id=req.customer_id, card_id=req.card_id))
            if v.valid:
                sql = v.sanitized_sql
                break
            feedback = f"Previous SQL: {t2s.sql}\nValidator errors: {list(v.errors)}"
        if not sql:
            raise ManualReview(f"SQL validation failed after {MAX_SQL_ATTEMPTS} attempts: {feedback}")
        partial["sql"] = sql

        # 3. execute validated SQL
        ex = await timer.call("sql_execute", app.state.executor.ExecuteSql, pb.ExecuteSqlRequest(
            sql=sql, customer_id=req.customer_id, card_id=req.card_id))
        rows = json.loads(ex.rows_json)
        partial["transactions"] = rows
        if not rows:
            raise ManualReview("No transactions found for this card in the lookback window")

        # 4. SOP retrieval from vector DB (ingest agent)
        sop = await timer.call("sop_retrieve", app.state.ingest.RetrieveSop, pb.RetrieveSopRequest(
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
    ack = await app.state.ingest.IngestFile(pb.IngestRequest(
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
        j = await app.state.ingest.GetJob(pb.JobRequest(job_id=job_id), timeout=5)
    except grpc.aio.AioRpcError as e:
        raise HTTPException(404, "unknown job") from e
    return {"job_id": j.job_id, "status": j.status, "detail": j.detail}


@app.get("/health")
async def health():
    return {"status": "ok", "skills": list(app.state.skills)}
```

---

## 9. gRPC service skeletons (file name, method name, input, expected output only)

Every service: `grpc.server(futures.ThreadPoolExecutor(max_workers=8))`, `add_insecure_port(f"[::]:{port_of(addr)}")` (mTLS in production), a `serve(addr) -> grpc.Server` function and a `__main__` block that calls `serve(...).wait_for_termination()`. Errors are returned with `context.abort(grpc.StatusCode.<CODE>, "<message>")`. The `x-correlation-id` request metadata must be logged on every call.

### 9.1 `app/text2sql_server.py` (Text2Sql service, wraps the text2sql MCP tool)

```python
import grpc
import crown_pb2 as pb
import crown_pb2_grpc as pbg


class Text2SqlService(pbg.Text2SqlServiceServicer):
    def Text2Sql(self, request: pb.Text2SqlRequest, context: grpc.ServicerContext) -> pb.Text2SqlResponse:
        """
        INPUT  (Text2SqlRequest):
          question       natural-language data question (skill data_question + customer message + entities)
          customer_id    required scope value
          card_id        required scope value
          lookback_days  time window in days
          feedback       validator errors from the previous attempt ("" on first call)
        OUTPUT (Text2SqlResponse):
          sql            one SQLite SELECT on card_transactions, scoped with
                         customer_id = '<id>' AND card_id = '<id>' and a txn_ts lookback filter, LIMIT <= 200
        ERRORS:
          INVALID_ARGUMENT  empty question / customer_id / card_id
          INTERNAL          MCP tool or LLM failure
        """
        raise NotImplementedError


def serve(addr: str = ...) -> grpc.Server:
    raise NotImplementedError
```

### 9.2 `app/sql_validator.py` (pure library) and `app/sql_validator_server.py` (gRPC)

```python
# app/sql_validator.py
ALLOWED_TABLES: set[str]      # {"card_transactions"}
ALLOWED_COLUMNS: set[str]     # txn_id, customer_id, card_id, merchant, amount, currency, txn_ts,
                              # status, auth_code, txn_type, channel, country, is_recurring
MAX_ROWS: int                 # 200


def validate_sql(sql: str, customer_id: str, card_id: str) -> tuple[bool, str, list[str]]:
    """
    INPUT : sql, customer_id, card_id
    OUTPUT: (valid, sanitized_sql, errors)
            valid=True  -> sanitized_sql is the normalized SQLite SQL with LIMIT <= 200 enforced, errors == []
            valid=False -> sanitized_sql == "", errors lists every violated rule (sorted, unique)
    """
    raise NotImplementedError
```

```python
# app/sql_validator_server.py
import grpc
import crown_pb2 as pb
import crown_pb2_grpc as pbg


class SqlValidatorService(pbg.SqlValidatorServiceServicer):
    def ValidateSql(self, request: pb.ValidateSqlRequest, context: grpc.ServicerContext) -> pb.ValidateSqlResponse:
        """
        INPUT  (ValidateSqlRequest): sql, customer_id, card_id
        OUTPUT (ValidateSqlResponse): valid, sanitized_sql, errors[]   (calls validate_sql)
        ERRORS: never aborts for an invalid query; invalid SQL is a normal response with valid=false.
        """
        raise NotImplementedError


def serve(addr: str = ...) -> grpc.Server:
    raise NotImplementedError
```

### 9.3 `app/sql_executor_server.py` (SQL executor service)

```python
import grpc
import crown_pb2 as pb
import crown_pb2_grpc as pbg


class SqlExecutorService(pbg.SqlExecutorServiceServicer):
    def ExecuteSql(self, request: pb.ExecuteSqlRequest, context: grpc.ServicerContext) -> pb.ExecuteSqlResponse:
        """
        INPUT  (ExecuteSqlRequest): sql, customer_id, card_id
        OUTPUT (ExecuteSqlResponse):
          rows_json   JSON array of row objects (column name -> value)
          row_count   number of rows
        BEHAVIOUR: re-run validate_sql first (defense in depth), then execute on a READ-ONLY connection.
        ERRORS:
          INVALID_ARGUMENT  validation failed (message = errors joined by "; ") or SQL execution error
          DEADLINE_EXCEEDED query timeout
        """
        raise NotImplementedError


def serve(addr: str = ...) -> grpc.Server:
    raise NotImplementedError
```

### 9.4 `app/ingest_agent_server.py` (ingest agent) and `app/vectorstore.py`

```python
# app/vectorstore.py  (interface; the real implementation is the enterprise vector DB client)
class VectorStore:
    def upsert(self, records: list[dict]) -> None:
        """INPUT : records with keys key, topic, doc_version, section_id, title, text, embedding
           OUTPUT: None. Existing records with the same key are replaced."""
        raise NotImplementedError

    def search(self, qvec: list[float], top_k: int = 4, topic: str | None = None) -> list[dict]:
        """INPUT : query embedding, top_k, optional topic filter
           OUTPUT: up to top_k records (without embedding), each with a float `score` (cosine similarity), best first."""
        raise NotImplementedError
```

```python
# app/ingest_agent_server.py
import grpc
import crown_pb2 as pb
import crown_pb2_grpc as pbg


def chunk_markdown(text: str) -> list[dict]:
    """INPUT : SOP markdown with one '## <SECTION-ID> <title>' heading per section
       OUTPUT: list of {"section_id": str, "title": str, "text": str}, one per section"""
    raise NotImplementedError


class IngestAgentService(pbg.IngestAgentServiceServicer):
    def IngestFile(self, request: pb.IngestRequest, context: grpc.ServicerContext) -> pb.IngestAck:
        """
        INPUT  (IngestRequest): file_path, topic, doc_version, callback_url (optional)
        OUTPUT (IngestAck): job_id (uuid hex), status="ACCEPTED", detail=""   -- returns IMMEDIATELY
        BEHAVIOUR: start a background thread: read file -> chunk_markdown -> embed (local fastembed) -> vector store
                   upsert with key f"{doc_version}:{section_id}" -> set job COMPLETED/FAILED
                   -> if callback_url: HTTP POST job JSON with header X-Signature = HMAC-SHA256(CALLBACK_SECRET, body),
                   3 attempts.
        """
        raise NotImplementedError

    def GetJob(self, request: pb.JobRequest, context: grpc.ServicerContext) -> pb.IngestAck:
        """
        INPUT  (JobRequest): job_id
        OUTPUT (IngestAck): job_id, status in {ACCEPTED, RUNNING, COMPLETED, FAILED}, detail (e.g. "4 sections ingested")
        ERRORS: NOT_FOUND for an unknown job_id
        """
        raise NotImplementedError

    def RetrieveSop(self, request: pb.RetrieveSopRequest, context: grpc.ServicerContext) -> pb.RetrieveSopResponse:
        """
        INPUT  (RetrieveSopRequest): query, top_k (default 4 when 0), topic (filter, "" = all)
        OUTPUT (RetrieveSopResponse): chunks[] of SopChunk(section_id, title, text, score, doc_version), best first;
                                      empty list when nothing matches
        """
        raise NotImplementedError


def serve(addr: str = ...) -> grpc.Server:
    raise NotImplementedError
```

### 9.5 `app/insight_server.py` (insight agent, called by the gateway)

```python
import grpc
import crown_pb2 as pb
import crown_pb2_grpc as pbg


class InsightService(pbg.InsightServiceServicer):
    def Analyze(self, request: pb.AnalyzeRequest, context: grpc.ServicerContext) -> pb.AnalyzeResponse:
        """
        INPUT  (AnalyzeRequest): insight_skill, customer_message, transactions_json, sop_chunks[], entities_json
        OUTPUT (AnalyzeResponse): result_json -- JSON object, schema in section 10.5
        BEHAVIOUR: Groq call (JSON mode); afterwards drop every sop_references entry whose section_id
                   was not present in request.sop_chunks.
        ERRORS: INTERNAL on LLM failure
        """
        raise NotImplementedError


def serve(addr: str = ...) -> grpc.Server:
    raise NotImplementedError
```

---

## 10. Behaviour contracts for the skeletons

### 10.1 Text2SQL
- Table: `card_transactions(txn_id, customer_id, card_id, merchant, amount REAL positive, currency, txn_ts TEXT UTC 'YYYY-MM-DD HH:MM:SS', status POSTED|PENDING|REVERSED, auth_code, txn_type PURCHASE|REFUND, channel POS|ONLINE|RECURRING, country ISO-2, is_recurring 0|1)`.
- Output must be a single SELECT with top-level `AND` conditions `customer_id = '<id>' AND card_id = '<id>'`, a time filter `txn_ts >= datetime('now', '-N day')`, `ORDER BY txn_ts`, `LIMIT` 200 or lower.
- When `feedback` is non-empty, the previous SQL was rejected. Fix the listed errors.

### 10.2 SQL validator rules
1. Parse with `sqlglot` (dialect `sqlite`). Exactly one statement. Root node must be `SELECT`.
2. Tables must be in `ALLOWED_TABLES`. Columns must be in `ALLOWED_COLUMNS`.
3. **Every** `SELECT` node (including sub-queries and CTEs) must have top-level `AND` conjuncts `customer_id = '<customer_id>'` and `card_id = '<card_id>'` with string literals matching the request. An `OR` at the top level of the `WHERE` fails the check.
4. If there is no `LIMIT`, add `LIMIT 200`. A `LIMIT` above 200 or a non-numeric limit is an error.
5. Return `(True, sanitized_sql, [])` or `(False, "", sorted unique errors)`.

### 10.3 SQL executor
- Open SQLite with `file:<path>?mode=ro` (`uri=True`). Re-validate before executing. Return rows as a JSON list of dicts.

### 10.4 Ingest agent
- Job states: `ACCEPTED -> RUNNING -> COMPLETED | FAILED`.
- Section ids come from the SOP heading, for example `## SOP-DISP-4.2 Provisional credit` gives `section_id = "SOP-DISP-4.2"`.
- Retrieval ranks by cosine similarity and filters by `topic` when given. Topics: `duplicate_charge`, `unauthorized`, `refund`, `recurring`.

### 10.5 Insight agent output (`result_json`)

```json
{
  "classification": "duplicate_charge",
  "confidence": 0.93,
  "evidence": [{"txn_id": "T1003", "reason": "Same merchant and amount as T1004 within 2 minutes"}],
  "recommended_actions": ["provisional_credit", "raise_dispute"],
  "analyst_action_message": "Duplicate charge confirmed. Per SOP-DISP-4.2 issue provisional credit of 49.99 ...",
  "customer_script": "I can see the duplicate ...",
  "sop_references": ["SOP-DISP-4.2"]
}
```

Rules: use only the supplied transactions and SOP excerpts; every recommendation cites an SOP section id; if the SOP does not cover the case, `classification = "needs_manual_review"`; the agent never executes actions.

---

## 11. Gateway API contract

### `POST /v1/analyst/assist` (header `X-API-Key`)

Request:

```json
{"analyst_id": "A1", "customer_id": "C1001", "card_id": "CARD_1001",
 "message": "Customer says the Amazon transaction of 49.99 was charged twice"}
```

Response `200`:

```json
{
  "correlation_id": "uuid",
  "analyst_id": "A1",
  "intent": "duplicate_charge",
  "goal": "Confirm the duplicate and advise provisional credit and dispute",
  "selected_skills": ["duplicate_charge_dispute"],
  "results": [{
    "skill": "duplicate_charge_dispute",
    "manual_review": false,
    "manual_review_reason": null,
    "sql": "SELECT ... LIMIT 200",
    "classification": "duplicate_charge",
    "confidence": 0.93,
    "evidence": [{"txn_id": "T1003", "reason": "..."}],
    "recommended_actions": ["provisional_credit", "raise_dispute"],
    "analyst_action_message": "...",
    "customer_script": "...",
    "sop_references": ["SOP-DISP-4.2"]
  }],
  "timing": {
    "llm_skill_selection_ms": 700,
    "calls": [{"call": "text2sql", "ms": 900}, {"call": "sql_validator", "ms": 8},
              {"call": "sql_execute", "ms": 12}, {"call": "sop_retrieve", "ms": 250},
              {"call": "insight_agent", "ms": 1800}],
    "overall_grpc_ms": 2970,
    "gateway_total_ms": 3700
  }
}
```

`overall_grpc_ms` is the sum of the individual gRPC call durations. `gateway_total_ms` is the wall time including Groq skill selection.

Manual review is returned (`manual_review: true` with `manual_review_reason`) when: no skill matches with confidence >= 0.6, SQL validation fails 3 times, no transactions, no SOP chunks, no SOP-grounded reference, classification `needs_manual_review`, result confidence < 0.6, the 25 s budget is exceeded, or a downstream gRPC error occurs.

Other endpoints: `POST /v1/sop/ingest` (multipart: `file`, `topic`, `doc_version`), `GET /v1/sop/ingest/{job_id}`, `POST /v1/callbacks/ingestion` (HMAC-signed), `GET /health`.

HTTP errors: `401` invalid API key or bad callback signature, `502` Groq failure during skill selection, `404` unknown ingestion job.

---

## 12. Prompts to give GitHub Copilot (run in order)

**Prompt 0: context.** "Read design-plan.md fully. We are building the Crown Gateway in Python 3.11 following sections 1 to 5. Create the folder structure in section 5, `requirements.txt`, `.env.example` and `run_all.sh` exactly as written. Do not implement anything else yet."

**Prompt 1: proto.** "Create `proto/crown.proto` exactly as in section 6. Then run `python -m grpc_tools.protoc -I proto --python_out=app --grpc_python_out=app proto/crown.proto` and confirm `app/crown_pb2.py` and `app/crown_pb2_grpc.py` exist."

**Prompt 2: gateway.** "Create `app/common.py` and `app/gateway.py` by copying the code in sections 8.1 and 8.2 exactly, without changes. Run `python -m py_compile app/common.py app/gateway.py`."

**Prompt 3: skills.** "Create the four YAML files in `skills/` by copying section 7 exactly. Verify that each loads with `yaml.safe_load` and that the keys are exactly `name, description, triggers, lookback_days, sop_topic, sop_query, data_question, insight_skill`."

**Prompt 4: service skeletons.** "Create the files in section 9 with the classes, method names, signatures and docstrings exactly as shown, bodies raising `NotImplementedError`. Add the `serve()` function and `__main__` block to each server file following the rules at the top of section 9."

**Prompt 5: validator.** "Implement `app/sql_validator.py` and `app/sql_validator_server.py` following section 10.2. Write `tests/test_validator.py` covering: valid query gets `LIMIT 200`; DELETE and DROP rejected; other table rejected; missing or wrong customer or card scope rejected; top-level OR rejected; unscoped sub-query rejected; LIMIT 5000 rejected; multi-statement rejected. Make `pytest` pass."

**Prompt 6: executor.** "Implement `app/sql_executor_server.py` following sections 9.3 and 10.3. Create a small `app/seed_data.py` that builds a SQLite demo `card_transactions` table with sample rows for customers C1001 to C1005 covering the four skills."

**Prompt 7: text2sql.** "Implement `app/text2sql_server.py` following sections 9.1 and 10.1. Use the Groq `chat_json` helper from `common.py` (or the text2sql MCP tool client if available) and return `{\"sql\": ...}`."

**Prompt 8: ingest agent.** "Implement `app/ingest_agent_server.py` and a local JSON-file `app/vectorstore.py` implementing the interface in section 9.4, following section 10.4. Add sample SOP files in `sop_docs/` (`## <SECTION-ID> <title>` headings) for the four topics, and a small `app/ingest_cli.py` that submits every file and polls `GetJob` until done."

**Prompt 9: insight agent.** "Implement `app/insight_server.py` following sections 9.5 and 10.5 using Groq JSON mode and the guardrail that removes SOP references not present in `sop_chunks`."

**Prompt 10: end to end test.** "Write `tests/test_e2e_mock.py` that monkeypatches `common.chat_json` and `common.embed`, starts all five gRPC servers in threads, and uses FastAPI `TestClient` to verify: (a) a duplicate-charge message returns a non-manual result with `sop_references`; (b) an unrelated message returns `manual_review: true`; (c) a missing API key returns 401; (d) SOP ingestion completes and the callback is accepted."

---

## 13. Acceptance checklist

- [ ] `python -m py_compile app/*.py` passes and `pytest` passes.
- [ ] `run_all.sh` starts five gRPC services and the gateway; `GET /health` lists four skills.
- [ ] `POST /v1/analyst/assist` for each demo card returns the right classification and cites SOP section ids.
- [ ] `timing.overall_grpc_ms` equals the sum of `timing.calls[].ms`.
- [ ] A validator rejection triggers a Text2SQL retry with `feedback`, and the third failure returns manual review.
- [ ] Injected SQL (other customer, DELETE, OR bypass) never reaches the executor.
- [ ] No SOP reference in a response was absent from the retrieved chunks.
- [ ] The gateway never calls any action or write API.
- [ ] Adding a fifth skill YAML and SOP file works with no gateway code change.
