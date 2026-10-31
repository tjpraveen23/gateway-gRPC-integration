import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from sql_validator import validate_sql  # noqa: E402

C, A = "C1001", "ACC-1001-CC"
GOOD = (f"SELECT txn_id, merchant, amount FROM card_transactions "
        f"WHERE customer_id = '{C}' AND account_number = '{A}' AND txn_ts >= datetime('now','-30 day') ORDER BY txn_ts")


def test_valid_adds_limit():
    ok, sql, errs = validate_sql(GOOD, C, A)
    assert ok and not errs and "LIMIT 200" in sql.upper()

def test_rejects_write():
    assert not validate_sql("DELETE FROM card_transactions", C, A)[0]
    assert not validate_sql("DROP TABLE card_transactions", C, A)[0]

def test_rejects_other_table():
    assert not validate_sql(f"SELECT * FROM accounts WHERE customer_id = '{C}' AND account_number = '{A}'", C, A)[0]

def test_rejects_missing_or_wrong_scope():
    assert not validate_sql("SELECT txn_id FROM card_transactions", C, A)[0]
    assert not validate_sql(GOOD.replace(C, "C9999"), C, A)[0]
    assert not validate_sql(GOOD.replace(A, "ACC-OTHER"), C, A)[0]

def test_rejects_or_bypass_and_subquery():
    assert not validate_sql(f"SELECT txn_id FROM card_transactions WHERE customer_id = '{C}' OR account_number = '{A}'", C, A)[0]
    sub = GOOD + " AND amount IN (SELECT amount FROM card_transactions)"
    assert not validate_sql(sub.replace(" ORDER BY txn_ts", "") , C, A)[0]

def test_rejects_big_limit_and_multi_statement():
    assert not validate_sql(GOOD + " LIMIT 5000", C, A)[0]
    assert not validate_sql(GOOD + "; DROP TABLE card_transactions", C, A)[0]
