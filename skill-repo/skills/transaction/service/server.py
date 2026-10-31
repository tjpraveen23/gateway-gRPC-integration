"""Transaction skill backend service (gRPC). It consumes the common SQL generation, validation and execution services."""
from bank.transaction.v1 import transaction_pb2_grpc as pbg
from crown_common import config
from crown_common.grpc_server import run_forever, start_server
from crown_common.sql_client import SqlQueryClient
from skills.transaction.service.handlers.get_transactions import GetTransactionsHandler, load_profiles


class TransactionServicer(pbg.TransactionServiceServicer):
    def __init__(self, handler: GetTransactionsHandler):
        self.handler = handler

    def GetTransactions(self, request, context):
        return self.handler.handle(request, context)


def serve(addr: str | None = None, sql_client: SqlQueryClient | None = None):
    handler = GetTransactionsHandler(sql_client or SqlQueryClient.from_env(), load_profiles())
    return start_server(lambda s: pbg.add_TransactionServiceServicer_to_server(TransactionServicer(handler), s),
                        addr or config.service_addr("TRANSACTION"))


if __name__ == "__main__":
    run_forever(serve, "TransactionService")
