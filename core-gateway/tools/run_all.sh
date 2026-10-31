#!/usr/bin/env bash
# core-gateway: seeds the demo DB, builds the descriptor registry from common + skill-repo protos, starts the four
# common services and the gateway on :8000. Start the skill-repo services separately (skill-repo: make run).
# Needs .env with GROQ_API_KEY.
set -e
cd "$(dirname "$0")/.."
. tools/env.sh
python tools/gen_proto.py
python -c "from crown_common.testing.demo_data import seed; seed()"
python -m common.services.sql_generation.server &
python -m common.services.sql_validation.server &
python -m common.services.sql_execution.server &
python -m common.services.sop_retrieval.server &
sleep 3
exec uvicorn gateway.app.main:app --host 0.0.0.0 --port 8000
