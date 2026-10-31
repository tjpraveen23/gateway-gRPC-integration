import pytest

from gateway.app.descriptor_registry import DescriptorRegistry
from gateway.app.skill_runtime import (SkillConfigError, build_request, load_skills, plan_stages, resolve, to_dict,
                                       union_ms, validate_skill)
from crown_common import config
from crown_common.config import ROOT


if not config.SKILLS_DIR.is_dir():
    pytest.skip(f"skill-repo not found at {config.SKILLS_DIR} (set SKILLS_DIR / SKILL_REPO)", allow_module_level=True)

REGISTRY = DescriptorRegistry(ROOT / "registry" / "descriptors.pb")
SKILLS = load_skills(config.SKILLS_DIR, REGISTRY)


def test_three_skills_load_with_versions_and_services():
    assert set(SKILLS) == {"transaction", "account", "insights"}
    for s in SKILLS.values():
        assert s.md.strip() and s.meta["version_history"][-1]["version"] == s.version and s.meta["service"]


def test_plan_adds_requires_and_parallel_stage():
    assert plan_stages(["insights"], SKILLS) == [["account", "transaction"], ["insights"]]
    assert plan_stages(["transaction"], SKILLS) == [["transaction"]]


def test_invalid_skill_json_rejected():
    meta = dict(SKILLS["account"].meta, version="9.9.9")
    with pytest.raises(SkillConfigError, match="version_history"):
        validate_skill("account", meta, REGISTRY)
    meta = dict(SKILLS["account"].meta, steps=[{"id": "x", "call": "no.Such/Method"}])
    with pytest.raises(SkillConfigError, match="unknown gRPC method"):
        validate_skill("account", meta, REGISTRY)


def test_resolve_keeps_types_and_interpolates():
    ctx = {"a": {"n": 30, "l": [1, 2]}, "t": "hi"}
    assert resolve("${a.n}", ctx) == 30 and resolve("x ${t} ${a.l}", ctx) == "x hi [1, 2]"
    assert resolve({"k": ["${t}"]}, ctx) == {"k": ["hi"]} and resolve("${missing}", ctx) == ""


def test_dynamic_request_building_and_to_dict():
    m = REGISTRY.method("bank.insight.v1.InsightService/Analyze")
    r = build_request(m.input_cls, {"transactions_json": [{"a": 1}], "sop_chunks": [{"section_id": "S-1", "score": 0.5}]})
    assert r.transactions_json == '[{"a": 1}]' and r.sop_chunks[0].section_id == "S-1"
    d = to_dict(r)
    assert d["sop_chunks"][0]["section_id"] == "S-1" and d["sop_chunks"][0]["title"] == "" and d["intent"] == ""
    with pytest.raises(SkillConfigError):
        build_request(m.input_cls, {"bogus": 1})
    t = REGISTRY.method("bank.transaction.v1.TransactionService/GetTransactions")
    assert build_request(t.input_cls, {"customer_id": "C1"}).customer_id == "C1"


def test_union_ms_counts_parallel_once():
    calls = [{"start_ms": 0, "ms": 100}, {"start_ms": 50, "ms": 100}, {"start_ms": 300, "ms": 50}]
    assert union_ms(calls) == 200 and union_ms([]) == 0
