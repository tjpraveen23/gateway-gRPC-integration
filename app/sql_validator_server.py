"""gRPC: SqlValidatorService (invoked directly by the gateway)."""
import logging
from concurrent import futures

import grpc

import crown_pb2 as pb
import crown_pb2_grpc as pbg
from common import VALIDATOR_ADDR, port_of
from sql_validator import validate_sql

log = logging.getLogger("validator")


class SqlValidator(pbg.SqlValidatorServiceServicer):
    def ValidateSql(self, request, context):
        ok, sql, errors = validate_sql(request.sql, request.customer_id, request.account_number)
        return pb.ValidateSqlResponse(valid=ok, sanitized_sql=sql, errors=errors)


def serve(addr: str = VALIDATOR_ADDR):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pbg.add_SqlValidatorServiceServicer_to_server(SqlValidator(), server)
    server.add_insecure_port(f"[::]:{port_of(addr)}")
    server.start()
    log.info("SqlValidatorService listening on %s", addr)
    return server


if __name__ == "__main__":
    serve().wait_for_termination()
