# skill-repo

The skills: **transaction**, **account** and **insights** (insights requires the other two). Each skill is one folder
owned by one team: its contract (`skill.json`, `skill.md`, `proto/`), generated stubs and its gRPC backend service.
The gateway and the shared code live in **core-gateway**.

```
skill-repo/
├── skills/
│   ├── transaction/   skill.json  skill.md  proto/  generated/python/  service/ (server.py, handlers/, config/profiles.json, Dockerfile)  tests/
│   ├── account/       same layout; service/clients/account_repository.py
│   └── insights/      same layout; proto imports the common SopChunk
├── scripts/           gen_proto.py, env.sh, run_skills.sh
└── Makefile  conftest.py  pytest.ini  requirements.txt  .env.example  CODEOWNERS  .github/workflows/ci.yml
```

The gateway calls exactly the methods in each `skill.json` `steps`:
`bank.transaction.v1.TransactionService/GetTransactions` (:50057), `bank.account.v1.AccountService/GetCustomerAccounts`
(:50056), `bank.insight.v1.InsightService/Analyze` (:50055). The transaction service itself calls the common SQL
generation / validation / execution services that core-gateway runs.

## Run
Needs core-gateway next to this folder (or `CORE_GATEWAY=/path/to/core-gateway`).
```bash
pip install -r requirements.txt
# 1. in core-gateway:  make run          (common services + gateway :8000)
# 2. here:
make run                                  # starts the three skill services
```
Full steps and a curl example are in core-gateway's README.

## Commands
`make test` (14 tests, no network), `make lint` (checks these skills against the gateway registry), `make proto`.

## Add or change a skill
1. Edit/add `skills/<name>/{skill.json, skill.md, proto/..., service/...}`.
2. `make proto` here, then **`make registry` in core-gateway** (the gateway reads `registry/descriptors.pb`).
3. Add the service address to core-gateway's `gateway/config/services.json` (new skills only).
4. `make lint && make test`. Restart the gateway to reload `skill.json`.

## Notes
- Python path: `scripts/env.sh` (source from this folder) adds this repo, every `skills/*/generated/python`, and
  core-gateway's `common/lib` and `common/generated/python`. `conftest.py` does the same for pytest.
- Docker: `docker build -f skills/transaction/service/Dockerfile --build-context core=../core-gateway -t crown-transaction .`
