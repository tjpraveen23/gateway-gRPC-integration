"""Descriptor registry: lets the gateway call ANY gRPC method by name, without importing generated code.

registry/descriptors.pb is a FileDescriptorSet (with imports) produced by tools/gen_proto.py. Adding a skill
service means publishing its proto into this file; the gateway code does not change."""
import json
import os
from dataclasses import dataclass
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory


class UnknownMethod(KeyError):
    pass


@dataclass(frozen=True)
class MethodInfo:
    service: str            # "bank.transaction.v1.TransactionService"
    name: str               # "GetTransactions"
    display: str            # "bank.transaction.v1.TransactionService/GetTransactions"
    path: str               # "/bank.transaction.v1.TransactionService/GetTransactions"
    input_cls: type
    output_cls: type


class DescriptorRegistry:
    def __init__(self, descriptor_set_path: str | Path):
        fds = descriptor_pb2.FileDescriptorSet()
        fds.ParseFromString(Path(descriptor_set_path).read_bytes())
        self.pool = descriptor_pool.DescriptorPool()
        for f in fds.file:                         # include_imports lists dependencies before dependents
            self.pool.AddSerializedFile(f.SerializeToString())
        self._cache: dict[str, MethodInfo] = {}

    def method(self, call: str) -> MethodInfo:
        """call = 'package.Service/Method'"""
        if call in self._cache:
            return self._cache[call]
        try:
            service, name = call.split("/")
            desc = self.pool.FindServiceByName(service).FindMethodByName(name)
        except (ValueError, KeyError) as e:
            raise UnknownMethod(f"unknown gRPC method '{call}'") from e
        info = MethodInfo(service=service, name=name, display=call, path=f"/{call}",
                          input_cls=message_factory.GetMessageClass(desc.input_type),
                          output_cls=message_factory.GetMessageClass(desc.output_type))
        self._cache[call] = info
        return info


def load_addresses(path: str | Path) -> dict[str, str]:
    """service full name -> address. The env variable named in the file overrides the address."""
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    return {svc: os.getenv(v.get("env", ""), v["address"]) for svc, v in cfg.items()}
