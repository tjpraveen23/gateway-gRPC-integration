# Crown Gateway v2

HTTP in: `text` + `customer_id` + `account_number`.

1. **RAG:** `SopRetrievalService.RetrieveSop` (existing gRPC retrieval service) with the input text.
2. **Routing (Groq):** intent, goal, entities and skills, from the SOP context + the skill catalog.
3. **Stage 1, parallel:** `transaction` skill (this account only) and `account` skill (all accounts, disputes, requests).
4. **Stage 2:** `insights` skill (needs both, plus SOP context) returns the analyst action message.
5. Response with per-call timing. `overall_grpc_ms` counts parallel calls once; `sum_of_call_ms` is cumulative.

## Skills
Each skill is a folder: `skills/<name>/skill.json` (intents, steps = gRPC calls, profiles, outputs,
`requires`, `version` + `version_history`) and `skills/<name>/skill.md` (instructions and rules).
The gateway has no per-skill code: it runs the `steps` in skill.json. Add a skill = add a folder.
Bump `version` and append to `version_history` on every change (validated at startup).

## Run
```bash
pip install -r requirements.txt
cp .env.example .env          # set GROQ_API_KEY
./run_all.sh                  # proto, seed demo DB, 6 gRPC services, gateway on :8000
```
Open http://localhost:8000 (UI) or:
```bash
curl -s localhost:8000/v1/analyst/assist -H 'X-API-Key: dev-key' -H 'Content-Type: application/json' -d '{
 "analyst_id":"A1","customer_id":"C1001","account_number":"ACC-1001-CC",
 "text":"Customer says the Amazon transaction of 49.99 was charged twice"}'
curl -s localhost:8000/v1/skills -H 'X-API-Key: dev-key'     # versions + history
```
Demo accounts: C1001/ACC-1001-CC duplicate, C1002/ACC-1002-CC pending hold, C1003/ACC-1003-CC fraud,
C1004/ACC-1004-CC missing refund, C1005/ACC-1005-CC recurring after cancellation.

## Services (gRPC)
| Service | Port | Note |
|---|---|---|
| Text2SqlService | 50051 | wraps text2sql |
| SqlValidatorService | 50052 | direct |
| SqlExecutorService | 50053 | direct, read-only |
| SopRetrievalService | 50054 | **stand-in**: point `SOP_ADDR` at your existing retrieval service |
| InsightService | 50055 | |
| AccountService | 50056 | new; SQLite demo, replace with the real backend |

## Tests
`pytest tests` (validator, skill runtime, and an end-to-end test with the LLM and embeddings mocked).
