"""Read-only, scope-enforcing SQL validator (the 'sql_validator' MCP tool)."""
import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {"card_transactions"}
ALLOWED_COLUMNS = {
    "txn_id", "customer_id", "account_number", "merchant", "amount", "currency", "txn_ts",
    "status", "auth_code", "txn_type", "channel", "country", "is_recurring",
}
MAX_ROWS = 200


def _conjuncts(node):
    if isinstance(node, exp.And):
        return _conjuncts(node.left) + _conjuncts(node.right)
    if isinstance(node, exp.Paren):
        return _conjuncts(node.this)
    return [node]


def _scoped(select: exp.Select, customer_id: str, account_number: str) -> bool:
    where = select.args.get("where")
    if not where:
        return False
    found = set()
    for c in _conjuncts(where.this):
        if (isinstance(c, exp.EQ) and isinstance(c.left, exp.Column)
                and isinstance(c.right, exp.Literal) and c.right.is_string):
            found.add((c.left.name.lower(), c.right.name))
    return {("customer_id", customer_id), ("account_number", account_number)} <= found


def validate_sql(sql: str, customer_id: str, account_number: str) -> tuple[bool, str, list[str]]:
    """Returns (valid, sanitized_sql, errors)."""
    errors: list[str] = []
    try:
        stmts = [s for s in sqlglot.parse(sql or "", read="sqlite") if s]
    except sqlglot.errors.SqlglotError as e:
        return False, "", [f"SQL parse error: {e}"]
    if len(stmts) != 1:
        return False, "", ["Exactly one statement is allowed"]
    tree = stmts[0]
    if not isinstance(tree, exp.Select):
        return False, "", ["Only SELECT statements are allowed"]

    for t in tree.find_all(exp.Table):
        if t.name.lower() not in ALLOWED_TABLES:
            errors.append(f"Table not allowed: {t.name}")
    for c in tree.find_all(exp.Column):
        if c.name.lower() not in ALLOWED_COLUMNS:
            errors.append(f"Column not allowed: {c.name}")
    for sel in tree.find_all(exp.Select):
        if not _scoped(sel, customer_id, account_number):
            errors.append(
                f"Every SELECT must be filtered with customer_id = '{customer_id}' AND account_number = '{account_number}' "
                "using top-level AND conditions")
            break

    limit = tree.args.get("limit")
    if limit is None:
        tree = tree.limit(MAX_ROWS)
    else:
        try:
            if int(limit.expression.name) > MAX_ROWS:
                errors.append(f"LIMIT must be <= {MAX_ROWS}")
        except ValueError:
            errors.append("LIMIT must be a numeric literal")

    if errors:
        return False, "", sorted(set(errors))
    return True, tree.sql(dialect="sqlite"), []
