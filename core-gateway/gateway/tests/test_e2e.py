"""End to end: every service runs in-process on a free port; the LLM and embeddings are replaced by fakes."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from crown_common import config 

if not config.SKILLS_DIR.is_dir():
    pytest.skip(f"skill-repo not found at {config.SKILLS_DIR} (set SKILLS_DIR / SKILL_REPO)", allow_module_level=True)

from common.services.sop_retrieval import server as sop_server
from common.services.sql_execution import server as exec_server
from common.services.sql_generation import server as gen_server
from common.services.sql_validation import server as val_server
from crown_common import embeddings, llm
from crown_common.sql_client import SqlQueryClient
from crown_common.testing.fakes import fake_embed
from gateway.app.main import create_app
from skills.account.service import server as account_server
from skills.insights.service import server as insight_server
from skills.transaction.service import server as transaction_server
from crown_common.testing.demo_data import seed

H = {"x-api-key": "dev-key"}


def fake_chat(system, user):
    if "intent router" in system:
        p = json.loads(user)
        t = p["input_text"].lower()
        assert p["sop_context"], "router must receive RAG context"
        if "weather" in t:
            return {"intent": "general_transaction_inquiry", "goal": "none", "confidence": 0.2, "skills": [], "entities": {}}
        intent = ("unauthorized_transaction" if "recognise" in t else "merchant_refund_missing" if "refund" in t
                  else "recurring_after_cancellation" if "cancel" in t else "duplicate_charge")
        return {"intent": intent, "goal": "assess_dispute", "confidence": 0.9, "skills": ["insights"],
                "entities": {"amount": 49.99, "merchant": "Amazon"}}
    if "text-to-SQL" in system:
        cust = re.search(r"customer_id: (\S+)", user).group(1)
        acct = re.search(r"account_number: (\S+)", user).group(1)
        if "1002" in acct and "rejected" not in user:        # first attempt invalid -> exercises the retry
            return {"sql": "SELECT * FROM users"}
        return {"sql": f"SELECT txn_id, merchant, amount, txn_ts, status, auth_code FROM card_transactions "
                       f"WHERE customer_id = '{cust}' AND account_number = '{acct}' "
                       f"AND txn_ts >= datetime('now','-30 day') ORDER BY txn_ts"}
    if "Insight Agent" in system:
        assert "ACCOUNT REFERENCE" in user and "TRANSACTIONS" in user and "INSIGHT SKILL" in user
        sid = re.findall(r"^\[(SOP-[\w.\-]+)\]", user, re.M)
        return {"classification": "duplicate_charge", "confidence": 0.93, "evidence": [{"txn_id": "T1003", "reason": "dup"}],
                "recommended_actions": ["provisional_credit"], "analyst_action_message": "Issue credit per " + sid[0],
                "customer_script": "...", "sop_references": [sid[0], "SOP-FAKE-9"], "account_context": ""}
    raise AssertionError("unexpected prompt")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(llm, "chat_json", fake_chat)
    mp.setattr(embeddings, "embed", fake_embed)
    tmp = tmp_path_factory.mktemp("stack")
    db = seed(str(tmp / "bank.db"))
    local = "127.0.0.1:0"
    gen, gp = gen_server.serve(local)
    val, vp = val_server.serve(local)
    exe, ep = exec_server.serve(local, db)
    sop, sp = sop_server.serve(local, str(tmp / "vec.json"))
    acc, ap = account_server.serve(local, db)
    ins, ip = insight_server.serve(local)
    sql = SqlQueryClient.from_addresses(f"127.0.0.1:{gp}", f"127.0.0.1:{vp}", f"127.0.0.1:{ep}")
    trn, tp = transaction_server.serve(local, sql)
    addresses = {"bank.transaction.v1.TransactionService": f"127.0.0.1:{tp}",
                 "bank.account.v1.AccountService": f"127.0.0.1:{ap}",
                 "bank.insight.v1.InsightService": f"127.0.0.1:{ip}",
                 "crown.common.v1.SopRetrievalService": f"127.0.0.1:{sp}"}
    with TestClient(create_app(addresses=addresses)) as c:
        yield c
    for s in (gen, val, exe, sop, acc, ins, trn):
        s.stop(0)
    mp.undo()


def post(c, cust, acct, text):
    return c.post("/v1/analyst/assist", headers=H,
                  json={"analyst_id": "A1", "customer_id": cust, "account_number": acct, "text": text})


def span(calls, skill):
    cs = [c for c in calls if c["skill"] == skill and not c["nested"]]
    return min(c["start_ms"] for c in cs), max(c["start_ms"] + c["ms"] for c in cs)


def test_parallel_skills_and_result(client):
    r = post(client, "C1001", "ACC-1001-CC", "Customer says the Amazon transaction of 49.99 was charged twice")
    assert r.status_code == 200
    d = r.json()
    assert d["plan"] == [["account", "transaction"], ["insights"]]
    assert d["result"]["manual_review"] is False and d["result"]["sop_references"] and "SOP-FAKE-9" not in d["result"]["sop_references"]
    assert d["rag"]["sections"] and d["skills"]["transaction"]["row_count"] == 5
    assert d["skills"]["transaction"]["profile"] == "duplicate_charge" and d["skills"]["insights"]["version"] == "1.1.0"
    assert d["reference"]["primary_account"]["account_number"] == "ACC-1001-CC" and len(d["reference"]["accounts"]) == 2
    t = d["timing"]
    t0, t1 = span(t["calls"], "transaction"); a0, a1 = span(t["calls"], "account"); i0, _ = span(t["calls"], "insights")
    assert a0 <= t1 and t0 <= a1                      # account and transaction overlap (parallel)
    assert i0 >= max(t1, a1)                          # insights starts after both finish
    assert t["overall_grpc_ms"] <= t["sum_of_call_ms"]


def test_nested_common_service_calls_are_in_the_timeline(client):
    d = post(client, "C1001", "ACC-1001-CC", "Amazon charged twice").json()
    nested = [c for c in d["timing"]["calls"] if c["nested"]]
    assert [c["call"].split(" > ")[1] for c in nested] == ["generate_sql", "validate_sql", "execute_sql"]
    assert {c["rpc"] for c in nested} == {"crown.common.v1.SqlGenerationService/GenerateSql",
                                          "crown.common.v1.SqlValidationService/ValidateSql",
                                          "crown.common.v1.SqlExecutionService/ExecuteSql"}
    parent = next(c for c in d["timing"]["calls"] if c["call"] == "transaction.get_transactions")
    assert all(parent["start_ms"] <= c["start_ms"] and c["start_ms"] + c["ms"] <= parent["start_ms"] + parent["ms"] + 2 for c in nested)
    assert d["timing"]["sum_of_call_ms"] == sum(c["ms"] for c in d["timing"]["calls"] if not c["nested"])


def test_validator_retry_happens_inside_the_transaction_service(client):
    d = post(client, "C1002", "ACC-1002-CC", "Customer was charged twice at Marriott").json()
    names = [c["call"].split(" > ")[-1] for c in d["timing"]["calls"] if c["nested"]]
    assert names.count("generate_sql") == 2 and names.count("validate_sql") == 2 and names.count("execute_sql") == 1
    assert d["result"]["manual_review"] is False


def test_unrelated_goes_to_manual_review(client):
    d = post(client, "C1001", "ACC-1001-CC", "What is the weather today?").json()
    assert d["result"]["manual_review"] is True and d["selected_skills"] == []
    assert [c["call"] for c in d["timing"]["calls"]] == ["gateway.rag_retrieve"]


def test_account_not_belonging_to_customer(client):
    d = post(client, "C1001", "ACC-1002-CC", "Customer was charged twice").json()
    assert d["skills"]["account"]["ok"] is False and "PERMISSION_DENIED" in d["skills"]["account"]["error"]
    assert d["skills"]["transaction"]["ok"] is False and d["result"]["manual_review"] is True


def test_auth_skills_endpoint_and_ui(client):
    assert client.post("/v1/analyst/assist", json={"analyst_id": "a", "customer_id": "c", "account_number": "x", "text": "t"}).status_code == 401
    s = client.get("/v1/skills", headers=H).json()
    assert {x["name"] for x in s} == {"transaction", "account", "insights"} and all(x["version_history"] and x["service"] for x in s)
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
