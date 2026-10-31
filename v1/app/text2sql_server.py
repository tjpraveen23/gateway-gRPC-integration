"""gRPC: Text2SqlService (wraps the text2sql tool). Natural language -> scoped SQLite SELECT."""
import logging
from concurrent import futures

import grpc

import crown_pb2 as pb
import crown_pb2_grpc as pbg
from common import TEXT2SQL_ADDR, chat_json, port_of

log = logging.getLogger("text2sql")

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


class Text2Sql(pbg.Text2SqlServiceServicer):
    def Text2Sql(self, request, context):
        if not (request.question and request.customer_id and request.account_number):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "question, customer_id and account_number are required")
        user = (f"Question: {request.question}\ncustomer_id: {request.customer_id}\n"
                f"account_number: {request.account_number}\nLookback days: {request.lookback_days}\n")
        if request.feedback:
            user += f"\nYour previous attempt was rejected. Fix it.\n{request.feedback}\n"
        try:
            out = chat_json(SYSTEM, user)
        except Exception as e:  # noqa: BLE001
            log.exception("text2sql failed")
            context.abort(grpc.StatusCode.INTERNAL, f"LLM error: {e}")
        return pb.Text2SqlResponse(sql=(out.get("sql") or "").strip())


def serve(addr: str = TEXT2SQL_ADDR):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pbg.add_Text2SqlServiceServicer_to_server(Text2Sql(), server)
    server.add_insecure_port(f"[::]:{port_of(addr)}")  # mTLS in production
    server.start()
    log.info("Text2SqlService listening on %s", addr)
    return server


if __name__ == "__main__":
    serve().wait_for_termination()
