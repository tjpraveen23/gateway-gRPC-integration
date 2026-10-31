import json

import grpc
import pytest

from bank.transaction.v1 import transaction_pb2 as pb
from crown_common.sql_client import SqlResult, SqlValidationFailed
from crown_common.testing.fakes import AbortError, FakeContext, make_rpc_error
from skills.transaction.service.handlers.get_transactions import GetTransactionsHandler, load_profiles, pick_profile

PROFILES = load_profiles()


class FakeSql:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def query(self, question, customer_id, account_number, lookback_days, correlation_id=""):
        self.calls.append((question, customer_id, account_number, lookback_days, correlation_id))
        if self.error:
            raise self.error
        return self.result


def req(**kw):
    base = dict(customer_id="C1001", account_number="ACC-1001-CC", intent="duplicate_charge",
                question="charged twice", entities_json='{"merchant": "Amazon"}')
    return pb.GetTransactionsRequest(**{**base, **kw})


def test_profile_selection_covers_every_intent():
    for intent, expected in PROFILES["profile_by_intent"].items():
        assert pick_profile(PROFILES, intent)[0] == expected
    name, p = pick_profile(PROFILES, "something_new")
    assert name == "general_transaction_inquiry" and p["lookback_days"] == 30
    assert pick_profile(PROFILES, "unauthorized_transaction")[1]["lookback_days"] == 90
    assert all(PROFILES["profile_by_intent"][i] in PROFILES["profiles"] for i in PROFILES["profile_by_intent"])


def test_success_builds_question_and_reports_downstream_calls():
    calls = [{"call": "generate_sql", "rpc": "crown.common.v1.SqlGenerationService/GenerateSql", "start_ms": 0, "ms": 20},
             {"call": "validate_sql", "rpc": "crown.common.v1.SqlValidationService/ValidateSql", "start_ms": 21, "ms": 3}]
    sql = FakeSql(SqlResult("SELECT 1 LIMIT 200", [{"txn_id": "T1"}], 2, calls))
    ctx = FakeContext((("x-correlation-id", "cid-9"),))
    r = GetTransactionsHandler(sql, PROFILES).handle(req(), ctx)
    assert r.row_count == 1 and json.loads(r.transactions_json) == [{"txn_id": "T1"}]
    assert r.sql == "SELECT 1 LIMIT 200" and r.profile == "duplicate_charge" and r.lookback_days == 30 and r.attempts == 2
    assert [c.call for c in r.downstream_calls] == ["generate_sql", "validate_sql"] and r.downstream_calls[0].ms == 20
    question, cust, acct, days, cid = sql.calls[0]
    assert (cust, acct, days, cid) == ("C1001", "ACC-1001-CC", 30, "cid-9")
    assert "Intent: duplicate_charge" in question and "Amazon" in question and "charged twice" in question


def test_validation_failure_becomes_failed_precondition():
    h = GetTransactionsHandler(FakeSql(error=SqlValidationFailed(["bad"], "x", 3)), PROFILES)
    with pytest.raises(AbortError) as e:
        h.handle(req(), FakeContext())
    assert e.value.code == grpc.StatusCode.FAILED_PRECONDITION and "after 3 attempts" in e.value.details


def test_common_service_error_status_is_passed_on():
    h = GetTransactionsHandler(FakeSql(error=make_rpc_error(grpc.StatusCode.UNAVAILABLE, "down")), PROFILES)
    with pytest.raises(AbortError) as e:
        h.handle(req(), FakeContext())
    assert e.value.code == grpc.StatusCode.UNAVAILABLE and "down" in e.value.details


def test_missing_ids_rejected_and_empty_result_is_not_an_error():
    h = GetTransactionsHandler(FakeSql(SqlResult("S", [], 1, [])), PROFILES)
    with pytest.raises(AbortError) as e:
        h.handle(req(account_number=""), FakeContext())
    assert e.value.code == grpc.StatusCode.INVALID_ARGUMENT
    assert h.handle(req(), FakeContext()).row_count == 0
