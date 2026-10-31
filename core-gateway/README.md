# core-gateway

The gateway and the shared (common) code. Skills live in the separate **skill-repo**; the gateway reads each skill's
`skill.json` / `skill.md` from there and calls the gRPC methods listed in those files.

```
core-gateway/
├── gateway/                  FastAPI app, no skill-specific code (app/, config/services.json, ui/, tests/, Dockerfile)
├── common/
│   ├── proto/crown/common/v1/    sql.proto, sop_retrieval.proto, timing.proto
│   ├── generated/python/         generated common stubs (committed)
│   ├── lib/crown_common/         config, llm (Groq), embeddings, grpc_server, sql_client, sql_validator, vectorstore,
│   │                             testing/ (fakes, demo_data)
│   ├── services/                 sql_generation, sql_validation, sql_execution, sop_retrieval (gRPC, :50051-:50054)
│   └── tests/
├── registry/descriptors.pb   generated from common protos + skill-repo protos; the gateway finds every gRPC method here
├── tools/                    gen_proto.py, lint_skills.py, env.sh, run_all.sh
├── sop_docs/  data/  Makefile  conftest.py  requirements.txt  .env.example
```

## How the two repos connect
| What | Direction | How |
|---|---|---|
| Gateway reads skills | core-gateway -> skill-repo | `SKILLS_DIR` (default `../skill-repo/skills`): `skill.json`, `skill.md` |
| Gateway calls skill methods | gateway -> skill services | gRPC to the addresses in `gateway/config/services.json` (env override `TRANSACTION_ADDR`, `ACCOUNT_ADDR`, `INSIGHT_ADDR`) |
| Skills use shared code | skill-repo -> core-gateway | `crown_common` + common stubs via `PYTHONPATH` (`$CORE_GATEWAY`); skill services also call the common SQL services over gRPC |
| Gateway knows the proto contracts | both | `registry/descriptors.pb`, rebuilt by `make registry` whenever a skill proto changes |

Keep both folders side by side (`workspace/core-gateway`, `workspace/skill-repo`) or set `SKILL_REPO` / `SKILLS_DIR`.

## Run (both repos)
```bash
# one-time, in each repo
pip install -r requirements.txt

# terminal 1: core-gateway  (seeds data/bank.db, builds the registry, starts the 4 common services + gateway on :8000)
cd core-gateway && cp .env.example .env     # set GROQ_API_KEY
make run

# terminal 2: skill-repo  (transaction :50057, account :50056, insights :50055)
cd skill-repo && make run
```
Start core-gateway first: it creates the demo database that the account service reads. Then open
`http://localhost:8000` or call it:
```bash
curl -s localhost:8000/v1/analyst/assist -H 'X-API-Key: dev-key' -H 'Content-Type: application/json' -d '{
 "analyst_id":"A1","customer_id":"C1001","account_number":"ACC-1001-CC",
 "text":"Customer says the Amazon transaction of 49.99 was charged twice"}'
```
Check the link: `curl localhost:8000/health` lists the skills loaded from skill-repo; `curl -H 'X-API-Key: dev-key' localhost:8000/v1/skills`.
Demo accounts: C1001/ACC-1001-CC duplicate, C1002/ACC-1002-CC pending hold, C1003/ACC-1003-CC fraud,
C1004/ACC-1004-CC missing refund, C1005/ACC-1005-CC recurring after cancellation.

## Commands
`make test` (common + registry tests always; runtime, lint and end-to-end tests run when skill-repo is next to it, else they are skipped),
`make lint` (validates every skill-repo `skill.json` against the registry), `make registry` (after a skill proto change), `make proto`.

## Notes
- Gateway Docker image: `docker build -f gateway/Dockerfile --build-context skills=../skill-repo -t crown-gateway .`
  (copies only the skill files and the registry; no skill code runs in the gateway).
- Not exercised here: real Groq calls, the embedding model download, the Dockerfiles, the CI workflows. Services use
  insecure local channels; use mTLS in production.
