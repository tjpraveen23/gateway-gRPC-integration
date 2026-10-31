"""Data access for the account service. Replace the SQLite queries with calls to the real account backend."""
import sqlite3

ALL_TYPES = {"accounts", "disputes", "requests"}


class BadRequest(Exception):
    pass


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


class AccountRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _rows(self, conn, sql, *args) -> list[dict]:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]

    def get(self, customer_id: str, account_number: str, info_types: list[str]) -> dict:
        want = set(info_types) or ALL_TYPES
        if want - ALL_TYPES:
            raise BadRequest(f"unknown info_types: {sorted(want - ALL_TYPES)}")
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            accounts = self._rows(conn, "SELECT * FROM accounts WHERE customer_id = ? ORDER BY account_number", customer_id)
            if not accounts:
                raise NotFound("customer not found")
            primary = next((a for a in accounts if a["account_number"] == account_number), None)
            if primary is None:
                raise Forbidden("account_number does not belong to customer_id")
            out = {"available": True, "customer_id": customer_id, "primary_account": primary}
            if "accounts" in want:
                out["accounts"] = accounts
            if "disputes" in want:
                out["disputes"] = self._rows(conn, "SELECT * FROM disputes WHERE customer_id = ? ORDER BY opened_ts DESC", customer_id)
            if "requests" in want:
                out["requests"] = self._rows(conn, "SELECT * FROM service_requests WHERE customer_id = ? ORDER BY created_ts DESC", customer_id)
            return out
        finally:
            conn.close()
