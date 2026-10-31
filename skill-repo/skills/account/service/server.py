"""Account skill backend service (gRPC)."""
from bank.account.v1 import account_pb2_grpc as pbg
from crown_common import config
from crown_common.grpc_server import run_forever, start_server
from skills.account.service.clients.account_repository import AccountRepository
from skills.account.service.handlers.get_customer_accounts import GetCustomerAccountsHandler


class AccountServicer(pbg.AccountServiceServicer):
    def __init__(self, handler: GetCustomerAccountsHandler):
        self.handler = handler

    def GetCustomerAccounts(self, request, context):
        return self.handler.handle(request, context)


def serve(addr: str | None = None, db_path: str | None = None):
    handler = GetCustomerAccountsHandler(AccountRepository(db_path or config.DB_PATH))
    return start_server(lambda s: pbg.add_AccountServiceServicer_to_server(AccountServicer(handler), s),
                        addr or config.service_addr("ACCOUNT"))


if __name__ == "__main__":
    run_forever(serve, "AccountService")
