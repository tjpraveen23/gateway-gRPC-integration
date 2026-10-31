"""Dynamic gRPC invoker (grpc.aio): one channel per address, calls any method found in the descriptor registry."""
import grpc

from .descriptor_registry import MethodInfo


class ServiceNotConfigured(Exception):
    pass


class GrpcInvoker:
    def __init__(self, addresses: dict[str, str]):
        self.addresses = addresses
        self._channels: dict[str, grpc.aio.Channel] = {}

    def _channel(self, address: str) -> grpc.aio.Channel:
        if address not in self._channels:      # created lazily inside the running event loop
            self._channels[address] = grpc.aio.insecure_channel(address)   # mTLS credentials in production
        return self._channels[address]

    async def call(self, method: MethodInfo, request, timeout: float, metadata: tuple = ()):
        address = self.addresses.get(method.service)
        if not address:
            raise ServiceNotConfigured(f"no address configured for {method.service}")
        rpc = self._channel(address).unary_unary(
            method.path, request_serializer=lambda m: m.SerializeToString(),
            response_deserializer=method.output_cls.FromString)
        return await rpc(request, timeout=timeout, metadata=metadata)

    async def close(self) -> None:
        for ch in self._channels.values():
            await ch.close()
