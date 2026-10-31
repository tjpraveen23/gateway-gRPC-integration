import json

import pytest

from crown.common.v1 import sql_pb2 as pb
from crown_common.sql_client import SqlQueryClient, SqlValidationFailed


class Stub:
    """Callable stand-in for a gRPC stub method."""
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def __call__(self, request, timeout=None, metadata=()):
        self.requests.append((request, metadata))
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


class Svc:
    def __init__(self, **methods):
        self.__dict__.update(methods)


def client(gen, val, exe, **kw):
    return SqlQueryClient(Svc(GenerateSql=gen), Svc(ValidateSql=val), Svc(ExecuteSql=exe), **kw)


OK = pb.ValidateSqlResponse(valid=True, sanitized_sql="SELECT 1 LIMIT 200")
BAD = pb.ValidateSqlResponse(valid=False, errors=["Table not allowed: users"])


def test_happy_path_records_timings_and_correlation():
    gen, val = Stub([pb.GenerateSqlResponse(sql="SELECT 1")]), Stub([OK])
    exe = Stub([pb.ExecuteSqlResponse(rows_json=json.dumps([{"a": 1}]), row_count=1)])
    r = client(gen, val, exe).query("q", "C1", "A1", 30, correlation_id="cid-1")
    assert r.rows == [{"a": 1}] and r.attempts == 1 and r.sql == "SELECT 1 LIMIT 200"
    assert [c["call"] for c in r.calls] == ["generate_sql", "validate_sql", "execute_sql"]
    assert all(c["rpc"].startswith("crown.common.v1.") for c in r.calls)
    assert gen.requests[0][1] == (("x-correlation-id", "cid-1"),)


def test_retry_sends_validator_feedback():
    gen = Stub([pb.GenerateSqlResponse(sql="SELECT * FROM users"), pb.GenerateSqlResponse(sql="SELECT 1")])
    val = Stub([BAD, OK])
    exe = Stub([pb.ExecuteSqlResponse(rows_json="[]", row_count=0)])
    r = client(gen, val, exe).query("q", "C1", "A1", 30)
    assert r.attempts == 2 and len(gen.requests) == 2
    assert gen.requests[0][0].feedback == ""
    assert "SELECT * FROM users" in gen.requests[1][0].feedback and "Table not allowed" in gen.requests[1][0].feedback


def test_fails_after_max_attempts_without_executing():
    gen, val, exe = Stub([pb.GenerateSqlResponse(sql="bad")]), Stub([BAD]), Stub([pb.ExecuteSqlResponse()])
    with pytest.raises(SqlValidationFailed) as e:
        client(gen, val, exe, max_attempts=3).query("q", "C1", "A1", 30)
    assert e.value.attempts == 3 and e.value.errors == ["Table not allowed: users"] and exe.requests == []
