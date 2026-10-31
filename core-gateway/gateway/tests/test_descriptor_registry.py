import pytest

from crown_common.config import ROOT
from gateway.app.descriptor_registry import DescriptorRegistry, UnknownMethod, load_addresses

REGISTRY = DescriptorRegistry(ROOT / "registry" / "descriptors.pb")


def test_every_service_method_is_resolvable():
    for call in ("bank.transaction.v1.TransactionService/GetTransactions", "bank.account.v1.AccountService/GetCustomerAccounts",
                 "bank.insight.v1.InsightService/Analyze", "crown.common.v1.SopRetrievalService/RetrieveSop",
                 "crown.common.v1.SqlGenerationService/GenerateSql", "crown.common.v1.SqlValidationService/ValidateSql",
                 "crown.common.v1.SqlExecutionService/ExecuteSql"):
        m = REGISTRY.method(call)
        assert m.path == "/" + call and m.input_cls().DESCRIPTOR.name.endswith("Request")


def test_unknown_method_raises():
    for bad in ("nope", "bank.transaction.v1.TransactionService/Nope", "x.Y/z"):
        with pytest.raises(UnknownMethod):
            REGISTRY.method(bad)


def test_transaction_response_carries_downstream_calls():
    out = REGISTRY.method("bank.transaction.v1.TransactionService/GetTransactions").output_cls
    assert "downstream_calls" in out.DESCRIPTOR.fields_by_name


def test_addresses_env_override(monkeypatch):
    monkeypatch.setenv("TRANSACTION_ADDR", "tx.internal:9000")
    a = load_addresses(ROOT / "gateway" / "config" / "services.json")
    assert a["bank.transaction.v1.TransactionService"] == "tx.internal:9000"
    assert a["bank.account.v1.AccountService"] == "localhost:50056"
