"""Handler for TransactionService.GetTransactions: pick the data profile for the intent, then ask the
common SQL services (generate -> validate -> execute) for this account's transactions."""
import json
import logging
from pathlib import Path

import grpc

from bank.transaction.v1 import transaction_pb2 as pb
from crown.common.v1 import timing_pb2 as timing_pb
from crown_common.grpc_server import correlation_id
from crown_common.sql_client import SqlQueryClient, SqlValidationFailed

log = logging.getLogger("transaction")
PROFILES_PATH = Path(__file__).resolve().parent.parent / "config" / "profiles.json"


def load_profiles(path: Path | None = None) -> dict:
    return json.loads((path or PROFILES_PATH).read_text(encoding="utf-8"))


def pick_profile(profiles: dict, intent: str) -> tuple[str, dict]:
    name = profiles["profile_by_intent"].get(intent, profiles["default_profile"])
    return name, profiles["profiles"][name]


class GetTransactionsHandler:
    def __init__(self, sql: SqlQueryClient, profiles: dict):
        self.sql, self.profiles = sql, profiles

    def handle(self, request, context) -> pb.GetTransactionsResponse:
        if not (request.customer_id and request.account_number):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "customer_id and account_number are required")
        name, profile = pick_profile(self.profiles, request.intent)
        question = (f"{profile['data_question']}\nAnalyst input text: {request.question}\n"
                    f"Intent: {request.intent}\nExtracted entities: {request.entities_json or '{}'}")
        cid = correlation_id(context)
        try:
            result = self.sql.query(question, request.customer_id, request.account_number,
                                    profile["lookback_days"], correlation_id=cid)
        except SqlValidationFailed as e:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(e))
        except grpc.RpcError as e:     # a common SQL service failed: pass its status on
            log.error("[%s] common SQL service error: %s %s", cid, e.code(), e.details())
            context.abort(e.code(), f"common SQL service: {e.details()}")
        return pb.GetTransactionsResponse(
            transactions_json=json.dumps(result.rows), row_count=len(result.rows), sql=result.sql, profile=name,
            lookback_days=profile["lookback_days"], attempts=result.attempts,
            downstream_calls=[timing_pb.CallTiming(call=c["call"], rpc=c["rpc"], start_ms=c["start_ms"], ms=c["ms"])
                              for c in result.calls])
