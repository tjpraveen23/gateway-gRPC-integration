import json

import grpc
import pytest

from bank.account.v1 import account_pb2 as pb
from crown_common.testing.fakes import AbortError, FakeContext
from skills.account.service.clients.account_repository import AccountRepository
from skills.account.service.handlers.get_customer_accounts import GetCustomerAccountsHandler
from crown_common.testing.demo_data import seed


@pytest.fixture(scope="module")
def handler(tmp_path_factory):
    return GetCustomerAccountsHandler(AccountRepository(seed(str(tmp_path_factory.mktemp("db") / "bank.db"))))


def call(handler, **kw):
    return handler.handle(pb.GetCustomerAccountsRequest(**kw), FakeContext())


def test_returns_all_info_by_default(handler):
    d = json.loads(call(handler, customer_id="C1003", account_number="ACC-1003-CC").result_json)
    assert d["available"] and d["primary_account"]["account_number"] == "ACC-1003-CC"
    assert {a["account_type"] for a in d["accounts"]} == {"CREDIT_CARD", "SAVINGS"}
    assert d["disputes"][0]["dispute_type"] == "FRAUD" and d["requests"][0]["request_type"] == "CREDIT_LIMIT_INCREASE"


def test_info_types_filter(handler):
    d = json.loads(call(handler, customer_id="C1001", account_number="ACC-1001-CC", info_types=["accounts"]).result_json)
    assert "accounts" in d and "disputes" not in d and "requests" not in d


@pytest.mark.parametrize("kw,code", [
    (dict(customer_id="C1001", account_number="ACC-1002-CC"), grpc.StatusCode.PERMISSION_DENIED),
    (dict(customer_id="C9999", account_number="X"), grpc.StatusCode.NOT_FOUND),
    (dict(customer_id="C1001", account_number="ACC-1001-CC", info_types=["salary"]), grpc.StatusCode.INVALID_ARGUMENT),
    (dict(customer_id="C1001"), grpc.StatusCode.INVALID_ARGUMENT),
])
def test_error_codes(handler, kw, code):
    with pytest.raises(AbortError) as e:
        call(handler, **kw)
    assert e.value.code == code
