#!/usr/bin/env bash
# skill-repo: starts the three skill gRPC services (transaction :50057, account :50056, insights :50055).
# They call the common services (SQL generation/validation/execution) that core-gateway runs, so start core-gateway
# first (core-gateway: make run). Needs core-gateway at $CORE_GATEWAY (default ../core-gateway).
set -e
cd "$(dirname "$0")/.."
. scripts/env.sh
python -m skills.transaction.service.server &
python -m skills.account.service.server &
python -m skills.insights.service.server &
wait
