"""Common service: SqlGenerationService. Natural language -> scoped SQLite SELECT (Groq)."""
import logging

import grpc

from crown.common.v1 import sql_pb2 as pb
from crown.common.v1 import sql_pb2_grpc as pbg
from crown_common import config, llm
from crown_common.grpc_server import correlation_id, run_forever, start_server

log = logging.getLogger("sql_generation")

SCHEMA = """Table card_transactions (SQLite):
  txn_id TEXT, customer_id TEXT, account_number TEXT, merchant TEXT, amount REAL (always positive),
  currency TEXT, txn_ts TEXT (UTC 'YYYY-MM-DD HH:MM:SS'), status TEXT (POSTED|PENDING|REVERSED),
  auth_code TEXT, txn_type TEXT (PURCHASE|REFUND), channel TEXT (POS|ONLINE|RECURRING),
  country TEXT (ISO-2), is_recurring INTEGER (0|1)"""

SYSTEM = f"""You are a text-to-SQL tool for a credit card contact center. Return JSON: {{"sql": "<query>"}}.
{SCHEMA}
Rules:
- SQLite dialect, a single SELECT on card_transactions only. Never use other tables or write statements.
- WHERE must contain top-level AND conditions: customer_id = '<customer_id>' AND account_number = '<account_number>'
  (string literals, exactly as provided), plus a time filter like txn_ts >= datetime('now', '-N day').
- Select the columns needed to answer the question, ORDER BY txn_ts, and add LIMIT 200 or lower."""


class SqlGeneration(pbg.SqlGenerationServiceServicer):
    def GenerateSql(self, request, context):
        if not (request.question and request.customer_id and request.account_number):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "question, customer_id and account_number are required")
        user = (f"Question: {request.question}\ncustomer_id: {request.customer_id}\n"
                f"account_number: {request.account_number}\nLookback days: {request.lookback_days}\n")
        if request.feedback:
            user += f"\nYour previous attempt was rejected. Fix it.\n{request.feedback}\n"
        try:
            out = llm.chat_json(SYSTEM, user)
        except Exception as e:  # noqa: BLE001
            log.exception("[%s] sql generation failed", correlation_id(context))
            context.abort(grpc.StatusCode.INTERNAL, f"LLM error: {e}")
        return pb.GenerateSqlResponse(sql=(out.get("sql") or "").strip())


def serve(addr: str | None = None):
    return start_server(lambda s: pbg.add_SqlGenerationServiceServicer_to_server(SqlGeneration(), s),
                        addr or config.service_addr("SQL_GENERATION"))


if __name__ == "__main__":
    run_forever(serve, "SqlGenerationService")
