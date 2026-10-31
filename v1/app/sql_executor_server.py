"""gRPC: SqlExecutorService (invoked directly by the gateway). Read-only execution."""
import json
import logging
import sqlite3
from concurrent import futures

import grpc

import crown_pb2 as pb
import crown_pb2_grpc as pbg
from common import DB_PATH, EXECUTOR_ADDR, port_of
from sql_validator import validate_sql

log = logging.getLogger("executor")


class SqlExecutor(pbg.SqlExecutorServiceServicer):
    def ExecuteSql(self, request, context):
        # Defense in depth: re-validate before running.
        ok, sql, errors = validate_sql(request.sql, request.customer_id, request.account_number)
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


def serve(addr: str = EXECUTOR_ADDR):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pbg.add_SqlExecutorServiceServicer_to_server(SqlExecutor(), server)
    server.add_insecure_port(f"[::]:{port_of(addr)}")
    server.start()
    log.info("SqlExecutorService listening on %s", addr)
    return server


if __name__ == "__main__":
    serve().wait_for_termination()
