#!/usr/bin/env bash
# Starts the gRPC services + gateway. Requires .env with GROQ_API_KEY.
set -e
cd "$(dirname "$0")"
python -m grpc_tools.protoc -I proto --python_out=app --grpc_python_out=app proto/crown.proto
python app/seed_data.py
python app/text2sql_server.py & python app/sql_validator_server.py & python app/sql_executor_server.py &
python app/account_server.py & python app/sop_retrieval_server.py & python app/insight_server.py &
sleep 3
cd app && uvicorn gateway:app --host 0.0.0.0 --port 8000
