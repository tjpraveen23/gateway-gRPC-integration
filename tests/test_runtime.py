import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import pytest  # noqa: E402
from skill_runtime import (SkillConfigError, build_request, load_skills, plan_stages, resolve,  # noqa: E402
                           union_ms, _validate)
import crown_pb2 as pb  # noqa: E402

SKILLS = load_skills()


def test_skills_load_with_versions():
    assert set(SKILLS) == {"transaction", "account", "insights"}
    for s in SKILLS.values():
        assert s.md.strip() and s.meta["version_history"][-1]["version"] == s.version


def test_plan_adds_requires_and_parallel_stage():
    assert plan_stages(["insights"], SKILLS) == [["account", "transaction"], ["insights"]]
    assert plan_stages(["transaction"], SKILLS) == [["transaction"]]
    assert plan_stages(["account", "transaction"], SKILLS) == [["account", "transaction"]]


def test_version_history_must_match():
    meta = dict(SKILLS["account"].meta, version="9.9.9")
    with pytest.raises(SkillConfigError):
        _validate("account", meta)


def test_unknown_grpc_call_rejected():
    meta = dict(SKILLS["account"].meta, steps=[{"id": "x", "call": "Nope.Nothing"}])
    with pytest.raises(SkillConfigError):
        _validate("account", meta)


def test_resolve_keeps_types_and_interpolates():
    ctx = {"a": {"n": 30, "l": [1, 2]}, "t": "hi"}
    assert resolve("${a.n}", ctx) == 30
    assert resolve("x ${t} ${a.l}", ctx) == "x hi [1, 2]"
    assert resolve({"k": ["${t}"]}, ctx) == {"k": ["hi"]}
    assert resolve("${missing}", ctx) == ""


def test_build_request_converts_and_validates():
    r = build_request(pb.AnalyzeRequest, {"transactions_json": [{"a": 1}], "sop_chunks": [{"section_id": "S-1", "score": 0.5}]})
    assert r.transactions_json == '[{"a": 1}]' and r.sop_chunks[0].section_id == "S-1"
    assert build_request(pb.Text2SqlRequest, {"lookback_days": "30"}).lookback_days == 30
    with pytest.raises(SkillConfigError):
        build_request(pb.Text2SqlRequest, {"bogus": 1})


def test_union_ms_counts_parallel_once():
    calls = [{"start_ms": 0, "ms": 100}, {"start_ms": 50, "ms": 100}, {"start_ms": 300, "ms": 50}]
    assert union_ms(calls) == 200      # 0-150 merged, plus 300-350
    assert union_ms([]) == 0
