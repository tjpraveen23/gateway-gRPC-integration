"""Common service: SqlExecutionService. Runs validated SQL on a READ-ONLY connection."""
import json
import sqlite3

import grpc

from crown.common.v1 import sql_pb2 as pb
from crown.common.v1 import sql_pb2_grpc as pbg
from crown_common import config
from crown_common.grpc_server import run_forever, start_server
from crown_common.sql_validator import validate_sql


class SqlExecution(pbg.SqlExecutionServiceServicer):
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or config.DB_PATH

    def ExecuteSql(self, request, context):
        ok, sql, errors = validate_sql(request.sql, request.customer_id, request.account_number)  # defense in depth
        if not ok:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "; ".join(errors))
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in conn.execute(sql).fetchall()]
        except sqlite3.Error as e:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"SQL execution error: {e}")
        finally:
            conn.close()
        return pb.ExecuteSqlResponse(rows_json=json.dumps(rows), row_count=len(rows))


def serve(addr: str | None = None, db_path: str | None = None):
    return start_server(lambda s: pbg.add_SqlExecutionServiceServicer_to_server(SqlExecution(db_path), s),
                        addr or config.service_addr("SQL_EXECUTION"))


if __name__ == "__main__":
    run_forever(serve, "SqlExecutionService")
