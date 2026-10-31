import json

import grpc
import pytest

from common.services.sql_execution.server import SqlExecution
from common.services.sql_validation.server import SqlValidation
from crown.common.v1 import sql_pb2 as pb
from crown_common.testing.fakes import AbortError, FakeContext
from crown_common.testing.demo_data import seed

GOOD = ("SELECT txn_id, merchant, amount FROM card_transactions WHERE customer_id = 'C1001' "
        "AND account_number = 'ACC-1001-CC' ORDER BY txn_ts")


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return seed(str(tmp_path_factory.mktemp("db") / "bank.db"))


def test_validation_service_replies_not_aborts():
    r = SqlValidation().ValidateSql(pb.ValidateSqlRequest(sql="DROP TABLE x", customer_id="C1001", account_number="A"), FakeContext())
    assert r.valid is False and r.errors and r.sanitized_sql == ""


def test_execution_returns_only_scoped_rows(db):
    r = SqlExecution(db).ExecuteSql(pb.ExecuteSqlRequest(sql=GOOD, customer_id="C1001", account_number="ACC-1001-CC"), FakeContext())
    rows = json.loads(r.rows_json)
    assert r.row_count == 5 == len(rows) and {x["merchant"] for x in rows} >= {"Amazon Marketplace", "Starbucks"}


def test_execution_revalidates_and_blocks_unscoped_sql(db):
    with pytest.raises(AbortError) as e:
        SqlExecution(db).ExecuteSql(pb.ExecuteSqlRequest(sql="SELECT * FROM card_transactions", customer_id="C1001", account_number="ACC-1001-CC"), FakeContext())
    assert e.value.code == grpc.StatusCode.INVALID_ARGUMENT


def test_execution_connection_is_read_only(db):
    import sqlite3
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM card_transactions")
