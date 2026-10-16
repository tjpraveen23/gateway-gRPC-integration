"""Demo bank data: card transactions (per account_number) + accounts, disputes, service requests."""
import datetime as dt
import os
import sqlite3

from common import DB_PATH

FMT = "%Y-%m-%d %H:%M:%S"


def seed() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE card_transactions (
        txn_id TEXT PRIMARY KEY, customer_id TEXT, account_number TEXT, merchant TEXT,
        amount REAL, currency TEXT, txn_ts TEXT, status TEXT, auth_code TEXT,
        txn_type TEXT, channel TEXT, country TEXT, is_recurring INTEGER);
    CREATE TABLE accounts (
        customer_id TEXT, account_number TEXT PRIMARY KEY, account_type TEXT, status TEXT,
        product_name TEXT, opened_date TEXT);
    CREATE TABLE disputes (
        dispute_id TEXT PRIMARY KEY, customer_id TEXT, account_number TEXT, txn_id TEXT,
        dispute_type TEXT, status TEXT, opened_ts TEXT, amount REAL, reason_code TEXT);
    CREATE TABLE service_requests (
        request_id TEXT PRIMARY KEY, customer_id TEXT, account_number TEXT,
        request_type TEXT, status TEXT, created_ts TEXT);
    """)

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)

    def ago(days=0, minutes=0):
        return (now - dt.timedelta(days=days, minutes=minutes)).strftime(FMT)

    def at(days, hh, mm):
        return (now - dt.timedelta(days=days)).replace(hour=hh, minute=mm, second=0).strftime(FMT)

    def row(txn, cust, acct, merchant, amount, ts, status="POSTED", auth=None, ttype="PURCHASE",
            channel="POS", country="US", recurring=0):
        return (txn, cust, acct, merchant, amount, "USD", ts, status, auth, ttype, channel, country, recurring)

    txns = [
        # duplicate charge (C1001) and pending-hold look-alike (C1002)
        row("T1001", "C1001", "ACC-1001-CC", "Starbucks", 6.45, ago(6), auth="S10001"),
        row("T1002", "C1001", "ACC-1001-CC", "Shell", 52.10, ago(5), auth="S10002"),
        row("T1003", "C1001", "ACC-1001-CC", "Amazon Marketplace", 49.99, ago(3), auth="A77121", channel="ONLINE"),
        row("T1004", "C1001", "ACC-1001-CC", "Amazon Marketplace", 49.99, ago(3, -2), auth="A77125", channel="ONLINE"),
        row("T1005", "C1001", "ACC-1001-CC", "Walmart", 83.20, ago(2), auth="S10005"),
        row("T2001", "C1002", "ACC-1002-CC", "Marriott Downtown", 220.00, ago(1), auth="M55102"),
        row("T2002", "C1002", "ACC-1002-CC", "Marriott Downtown", 220.00, ago(1), status="PENDING", auth="M55102"),
        row("T2003", "C1002", "ACC-1002-CC", "Uber", 18.40, ago(4), auth="U20003"),
        # unauthorized (C1003)
        row("T3001", "C1003", "ACC-1003-CC", "Kroger", 64.12, ago(9), auth="K30001"),
        row("T3002", "C1003", "ACC-1003-CC", "Chevron", 41.00, ago(6), auth="C30002"),
        row("T3003", "C1003", "ACC-1003-CC", "Target", 112.75, ago(4), auth="T30003"),
        row("T3004", "C1003", "ACC-1003-CC", "GLOBALTECH-STORE", 899.00, at(2, 3, 12), auth="G90001", channel="ONLINE", country="RO"),
        row("T3005", "C1003", "ACC-1003-CC", "GLOBALTECH-STORE", 450.00, at(2, 4, 5), auth="G90002", channel="ONLINE", country="RO"),
        # missing refund (C1004)
        row("T4001", "C1004", "ACC-1004-CC", "BestGadgets", 129.50, ago(20), auth="B40001", channel="ONLINE"),
        row("T4002", "C1004", "ACC-1004-CC", "Costco", 210.33, ago(12), auth="C40002"),
        row("T4003", "C1004", "ACC-1004-CC", "Home Depot", 35.00, ago(5), ttype="REFUND", auth="H40003"),
        # recurring after cancellation (C1005)
        row("T5001", "C1005", "ACC-1005-CC", "FitLife Gym", 29.99, ago(65), auth="F50001", channel="RECURRING", recurring=1),
        row("T5002", "C1005", "ACC-1005-CC", "FitLife Gym", 29.99, ago(35), auth="F50002", channel="RECURRING", recurring=1),
        row("T5003", "C1005", "ACC-1005-CC", "FitLife Gym", 29.99, ago(5), auth="F50003", channel="RECURRING", recurring=1),
        row("T5004", "C1005", "ACC-1005-CC", "Netflix", 15.49, ago(10), auth="N50004", channel="RECURRING", recurring=1),
    ]
    conn.executemany("INSERT INTO card_transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", txns)

    accounts = [
        ("C1001", "ACC-1001-CC", "CREDIT_CARD", "ACTIVE", "Platinum Rewards Card", "2019-03-14"),
        ("C1001", "ACC-1001-CHK", "CHECKING", "ACTIVE", "Everyday Checking", "2018-06-02"),
        ("C1002", "ACC-1002-CC", "CREDIT_CARD", "ACTIVE", "Travel Card", "2020-01-20"),
        ("C1002", "ACC-1002-LOAN", "AUTO_LOAN", "ACTIVE", "Auto Loan 60 months", "2023-04-11"),
        ("C1003", "ACC-1003-CC", "CREDIT_CARD", "ACTIVE", "Cash Back Card", "2021-09-30"),
        ("C1003", "ACC-1003-SAV", "SAVINGS", "ACTIVE", "High Yield Savings", "2021-09-30"),
        ("C1004", "ACC-1004-CC", "CREDIT_CARD", "ACTIVE", "Platinum Rewards Card", "2017-11-08"),
        ("C1004", "ACC-1004-CHK", "CHECKING", "ACTIVE", "Everyday Checking", "2017-11-08"),
        ("C1005", "ACC-1005-CC", "CREDIT_CARD", "ACTIVE", "Cash Back Card", "2022-02-17"),
        ("C1005", "ACC-1005-LOAN", "PERSONAL_LOAN", "ACTIVE", "Personal Loan 36 months", "2024-07-01"),
    ]
    conn.executemany("INSERT INTO accounts VALUES (?,?,?,?,?,?)", accounts)

    disputes = [
        ("D-8001", "C1001", "ACC-1001-CC", "T0900", "FRAUD", "CLOSED_RESOLVED", ago(200), 120.00, "10.4"),
        ("D-8002", "C1003", "ACC-1003-CC", "T0850", "FRAUD", "CLOSED_RESOLVED", ago(250), 75.00, "10.4"),
    ]
    conn.executemany("INSERT INTO disputes VALUES (?,?,?,?,?,?,?,?,?)", disputes)

    requests = [
        ("R-7001", "C1003", "ACC-1003-CC", "CREDIT_LIMIT_INCREASE", "PENDING", ago(6)),
        ("R-7002", "C1004", "ACC-1004-CC", "MERCHANT_CREDIT_INQUIRY", "OPEN", ago(10)),
        ("R-7003", "C1001", "ACC-1001-CHK", "ADDRESS_CHANGE", "COMPLETED", ago(30)),
        ("R-7004", "C1005", "ACC-1005-LOAN", "PAYMENT_DATE_CHANGE", "PENDING", ago(3)),
    ]
    conn.executemany("INSERT INTO service_requests VALUES (?,?,?,?,?,?)", requests)
    conn.commit()
    conn.close()
    print(f"Seeded {len(txns)} transactions, {len(accounts)} accounts into {DB_PATH}")


if __name__ == "__main__":
    seed()
