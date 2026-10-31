import json

import grpc
import pytest

from bank.insight.v1 import insight_pb2 as pb
from crown.common.v1 import sop_retrieval_pb2 as sop_pb
from crown_common import llm
from crown_common.testing.fakes import AbortError, FakeContext
from skills.insights.service.handlers.analyze import AnalyzeHandler, build_user_prompt


def request():
    return pb.AnalyzeRequest(
        insight_skill="# rules", customer_message="charged twice", intent="duplicate_charge", goal="assess_dispute",
        transactions_json='[{"txn_id": "T1"}]', account_json='{"available": false}', entities_json="{}",
        sop_chunks=[sop_pb.SopChunk(section_id="SOP-DISP-4.2", title="Provisional credit", text="Issue credit", doc_version="v1")])


def test_prompt_contains_all_inputs():
    p = build_user_prompt(request())
    for needle in ("# rules", "duplicate_charge", "assess_dispute", "charged twice", "T1", "available", "[SOP-DISP-4.2]", "Issue credit"):
        assert needle in p


def test_guardrail_drops_references_not_in_retrieved_sop(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda s, u: {"classification": "duplicate_charge", "confidence": 0.9,
                                                       "sop_references": ["SOP-DISP-4.2", "SOP-FAKE-9"]})
    out = json.loads(AnalyzeHandler().handle(request(), FakeContext()).result_json)
    assert out["sop_references"] == ["SOP-DISP-4.2"]


def test_llm_failure_is_internal_error(monkeypatch):
    def boom(s, u):
        raise RuntimeError("groq down")
    monkeypatch.setattr(llm, "chat_json", boom)
    with pytest.raises(AbortError) as e:
        AnalyzeHandler().handle(request(), FakeContext())
    assert e.value.code == grpc.StatusCode.INTERNAL and "groq down" in e.value.details
