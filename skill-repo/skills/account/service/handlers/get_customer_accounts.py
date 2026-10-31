"""Handler for AccountService.GetCustomerAccounts."""
import json

import grpc

from bank.account.v1 import account_pb2 as pb
from skills.account.service.clients.account_repository import AccountRepository, BadRequest, Forbidden, NotFound


class GetCustomerAccountsHandler:
    def __init__(self, repository: AccountRepository):
        self.repository = repository

    def handle(self, request, context) -> pb.GetCustomerAccountsResponse:
        if not (request.customer_id and request.account_number):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "customer_id and account_number are required")
        try:
            data = self.repository.get(request.customer_id, request.account_number, list(request.info_types))
        except BadRequest as e:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        except NotFound as e:
            context.abort(grpc.StatusCode.NOT_FOUND, str(e))
        except Forbidden as e:
            context.abort(grpc.StatusCode.PERMISSION_DENIED, str(e))
        return pb.GetCustomerAccountsResponse(result_json=json.dumps(data))
