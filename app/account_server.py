"""gRPC: AccountService (new). Secondary reference data for a customer: all accounts
(credit card, checking, loan, ...), disputes (incl. fraud) and service requests.
Backed by SQLite here; replace the queries with calls to the real backend service."""
import json
import logging
import sqlite3
from concurrent import futures

import grpc

import crown_pb2 as pb
import crown_pb2_grpc as pbg
from common import ACCOUNT_ADDR, DB_PATH, port_of

log = logging.getLogger("account")
ALL_TYPES = {"accounts", "disputes", "requests"}


def _rows(conn, sql, *args):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


class Account(pbg.AccountServiceServicer):
    def GetCustomerAccounts(self, request, context):
        if not (request.customer_id and request.account_number):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "customer_id and account_number are required")
        want = set(request.info_types) or ALL_TYPES
        unknown = want - ALL_TYPES
        if unknown:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"unknown info_types: {sorted(unknown)}")

        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            accounts = _rows(conn, "SELECT * FROM accounts WHERE customer_id = ? ORDER BY account_number",
                             request.customer_id)
            if not accounts:
                context.abort(grpc.StatusCode.NOT_FOUND, "customer not found")
            primary = next((a for a in accounts if a["account_number"] == request.account_number), None)
            if primary is None:
                context.abort(grpc.StatusCode.PERMISSION_DENIED, "account_number does not belong to customer_id")
            out = {"available": True, "customer_id": request.customer_id, "primary_account": primary}
            if "accounts" in want:
                out["accounts"] = accounts
            if "disputes" in want:
                out["disputes"] = _rows(conn, "SELECT * FROM disputes WHERE customer_id = ? ORDER BY opened_ts DESC",
                                        request.customer_id)
            if "requests" in want:
                out["requests"] = _rows(conn, "SELECT * FROM service_requests WHERE customer_id = ? "
                                              "ORDER BY created_ts DESC", request.customer_id)
        finally:
            conn.close()
        return pb.AccountResponse(result_json=json.dumps(out))


def serve(addr: str = ACCOUNT_ADDR):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pbg.add_AccountServiceServicer_to_server(Account(), server)
    server.add_insecure_port(f"[::]:{port_of(addr)}")
    server.start()
    log.info("AccountService listening on %s", addr)
    return server


if __name__ == "__main__":
    serve().wait_for_termination()
