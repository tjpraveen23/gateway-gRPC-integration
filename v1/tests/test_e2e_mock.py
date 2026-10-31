"""End-to-end test with the LLM and embeddings mocked: real gRPC servers + real gateway."""
import hashlib, json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

H = {"x-api-key": "dev-key"}


def fake_embed(texts):
    out = []
    for t in texts:
        v = [0.0] * 64
        for w in t.lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
        out.append(v)
    return out


def fake_chat(system, user):
    if "intent router" in system:
        p = json.loads(user)
        t = p["input_text"].lower()
        assert p["sop_context"], "router must receive RAG context"
        if "weather" in t:
            return {"intent": "general_transaction_inquiry", "goal": "none", "confidence": 0.2, "skills": [], "entities": {}}
        intent = ("unauthorized_transaction" if "recognise" in t else "merchant_refund_missing" if "refund" in t
                  else "recurring_after_cancellation" if "cancel" in t else "duplicate_charge")
        return {"intent": intent, "goal": "advise analyst", "confidence": 0.9, "skills": ["insights"],
                "entities": {"amount": 49.99, "merchant": "Amazon"}}
    if "text-to-SQL" in system:
        cust = re.search(r"customer_id: (\S+)", user).group(1)
        acct = re.search(r"account_number: (\S+)", user).group(1)
        if "1002" in acct and "rejected" not in user:      # first attempt invalid -> exercises retry
            return {"sql": "SELECT * FROM users"}
        return {"sql": f"SELECT txn_id, merchant, amount, txn_ts, status, auth_code FROM card_transactions "
                       f"WHERE customer_id = '{cust}' AND account_number = '{acct}' "
                       f"AND txn_ts >= datetime('now','-30 day') ORDER BY txn_ts"}
    if "Insight Agent" in system:
        assert "ACCOUNT REFERENCE" in user and "TRANSACTIONS" in user
        sid = re.findall(r"^\[(SOP-[\w.\-]+)\]", user, re.M)
        return {"classification": "duplicate_charge", "confidence": 0.93, "evidence": [{"txn_id": "T1003", "reason": "dup"}],
                "recommended_actions": ["provisional_credit"], "analyst_action_message": "Issue credit per " + sid[0],
                "customer_script": "...", "sop_references": [sid[0], "SOP-FAKE-9"], "account_context": ""}
    raise AssertionError("unexpected prompt")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import seed_data, account_server, sql_executor_server, sop_retrieval_server
    import text2sql_server, sql_validator_server, insight_server, gateway
    tmp = tmp_path_factory.mktemp("data")
    db = str(tmp / "bank.db")
    for m in (seed_data, account_server, sql_executor_server):
        m.DB_PATH = db
    sop_retrieval_server.VECTOR_PATH = str(tmp / "vec.json")
    for m in (sop_retrieval_server,):
        m.embed = fake_embed
    for m in (text2sql_server, insight_server, gateway):
        m.chat_json = fake_chat
    seed_data.seed()
    servers = [m.serve() for m in (text2sql_server, sql_validator_server, sql_executor_server,
                                   account_server, sop_retrieval_server, insight_server)]
    with TestClient(gateway.app) as c:
        yield c
    for s in servers:
        s.stop(0)


def post(c, cust, acct, text):
    return c.post("/v1/analyst/assist", headers=H,
                  json={"analyst_id": "A1", "customer_id": cust, "account_number": acct, "text": text})


def span(calls, skill):
    cs = [c for c in calls if c["skill"] == skill]
    return min(c["start_ms"] for c in cs), max(c["start_ms"] + c["ms"] for c in cs)


def test_parallel_skills_and_result(client):
    r = post(client, "C1001", "ACC-1001-CC", "Customer says the Amazon transaction of 49.99 was charged twice")
    assert r.status_code == 200
    d = r.json()
    assert d["plan"] == [["account", "transaction"], ["insights"]]
    assert d["result"]["manual_review"] is False and "SOP-FAKE-9" not in d["result"]["sop_references"]
    assert d["rag"]["sections"] and d["skills"]["transaction"]["row_count"] == 5
    assert {len(d["reference"]["accounts"]), d["reference"]["primary_account"]["account_number"]} == {2, "ACC-1001-CC"}
    assert d["skills"]["insights"]["version"] == "1.0.0"
    calls = d["timing"]["calls"]
    t0, t1 = span(calls, "transaction"); a0, a1 = span(calls, "account"); i0, _ = span(calls, "insights")
    assert a0 <= t1 and t0 <= a1                     # account and transaction overlap (parallel)
    assert i0 >= max(t1, a1)                         # insights starts after both finish
    assert d["timing"]["overall_grpc_ms"] <= d["timing"]["sum_of_call_ms"]


def test_validator_retry(client):
    d = post(client, "C1002", "ACC-1002-CC", "Customer was charged twice at Marriott").json()
    names = [c["call"] for c in d["timing"]["calls"]]
    assert names.count("transaction.generate_sql") == 2 and names.count("transaction.validate_sql") == 2
    assert d["result"]["manual_review"] is False


def test_unrelated_goes_to_manual_review(client):
    d = post(client, "C1001", "ACC-1001-CC", "What is the weather today?").json()
    assert d["result"]["manual_review"] is True and d["selected_skills"] == []
    assert [c["call"] for c in d["timing"]["calls"]] == ["gateway.rag_retrieve"]


def test_account_not_belonging_to_customer(client):
    d = post(client, "C1001", "ACC-1002-CC", "Customer was charged twice").json()
    assert d["skills"]["account"]["ok"] is False and "PERMISSION_DENIED" in d["skills"]["account"]["error"]
    assert d["skills"]["transaction"]["ok"] is False
    assert d["result"]["manual_review"] is True and "insights" in d["skills"]


def test_auth_skills_and_ui(client):
    assert client.post("/v1/analyst/assist", json={"analyst_id": "a", "customer_id": "c", "account_number": "x", "text": "t"}).status_code == 401
    s = client.get("/v1/skills", headers=H).json()
    assert {x["name"] for x in s} == {"transaction", "account", "insights"} and all(x["version_history"] for x in s)
    r = client.get("/"); assert r.status_code == 200 and "text/html" in r.headers["content-type"]
