"""gRPC module: MCP tools (text2sql, sql_validator, sql executor)."""
import json
import logging
import sqlite3
from concurrent import futures

import grpc

import crown_pb2 as pb
import crown_pb2_grpc as pbg
from common import DB_PATH, MCP_ADDR, chat_json, port_of
from sql_validator import validate_sql

log = logging.getLogger("mcp_tools")

SCHEMA = """Table card_transactions (SQLite):
  txn_id TEXT, customer_id TEXT, card_id TEXT, merchant TEXT, amount REAL (always positive),
  currency TEXT, txn_ts TEXT (UTC 'YYYY-MM-DD HH:MM:SS'), status TEXT (POSTED|PENDING|REVERSED),
  auth_code TEXT, txn_type TEXT (PURCHASE|REFUND), channel TEXT (POS|ONLINE|RECURRING),
  country TEXT (ISO-2), is_recurring INTEGER (0|1)"""

SYSTEM = f"""You are a text-to-SQL tool for a credit card contact center. Return JSON: {{"sql": "<query>"}}.
{SCHEMA}
Rules:
- SQLite dialect, a single SELECT on card_transactions only. Never use other tables or write statements.
- WHERE must contain top-level AND conditions: customer_id = '<customer_id>' AND card_id = '<card_id>'
  (string literals, exactly as provided), plus a time filter like txn_ts >= datetime('now', '-N day').
- Select the columns needed to answer the question, ORDER BY txn_ts, and add LIMIT 200 or lower."""


class MCPTools(pbg.MCPToolsServiceServicer):
    def Text2Sql(self, request, context):
        user = (f"Question: {request.question}\ncustomer_id: {request.customer_id}\n"
                f"card_id: {request.card_id}\nLookback days: {request.lookback_days}\n")
        if request.feedback:
            user += f"\nYour previous attempt was rejected. Fix it.\n{request.feedback}\n"
        try:
            out = chat_json(SYSTEM, user)
        except Exception as e:  # noqa: BLE001
            log.exception("text2sql failed")
            context.abort(grpc.StatusCode.INTERNAL, f"LLM error: {e}")
        return pb.Text2SqlResponse(sql=(out.get("sql") or "").strip())

    def ValidateSql(self, request, context):
        ok, sql, errors = validate_sql(request.sql, request.customer_id, request.card_id)
        return pb.ValidateSqlResponse(valid=ok, sanitized_sql=sql, errors=errors)

    def ExecuteSql(self, request, context):
        # Defense in depth: re-validate before running.
        ok, sql, errors = validate_sql(request.sql, request.customer_id, request.card_id)
        if not ok:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "; ".join(errors))
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in conn.execute(sql).fetchall()]
        except sqlite3.Error as e:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"SQL execution error: {e}")
        finally:
            conn.close()
        return pb.ExecuteSqlResponse(rows_json=json.dumps(rows), row_count=len(rows))


def serve(addr: str = MCP_ADDR):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pbg.add_MCPToolsServiceServicer_to_server(MCPTools(), server)
    server.add_insecure_port(f"[::]:{port_of(addr)}")  # use mTLS credentials in production
    server.start()
    log.info("MCP tools service listening on %s", addr)
    return server


if __name__ == "__main__":
    serve().wait_for_termination()
