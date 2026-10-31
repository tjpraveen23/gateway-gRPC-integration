"""Common service: SqlValidationService. Read-only, scope-enforcing SQL validation."""
from crown.common.v1 import sql_pb2 as pb
from crown.common.v1 import sql_pb2_grpc as pbg
from crown_common import config
from crown_common.grpc_server import run_forever, start_server
from crown_common.sql_validator import validate_sql


class SqlValidation(pbg.SqlValidationServiceServicer):
    def ValidateSql(self, request, context):
        ok, sql, errors = validate_sql(request.sql, request.customer_id, request.account_number)
        return pb.ValidateSqlResponse(valid=ok, sanitized_sql=sql, errors=errors)   # invalid SQL is a normal reply


def serve(addr: str | None = None):
    return start_server(lambda s: pbg.add_SqlValidationServiceServicer_to_server(SqlValidation(), s),
                        addr or config.service_addr("SQL_VALIDATION"))


if __name__ == "__main__":
    run_forever(serve, "SqlValidationService")
