"""Helpers shared by every gRPC backend service."""
import logging
from concurrent import futures

import grpc

log = logging.getLogger("crown.grpc")


def start_server(register, addr: str, max_workers: int = 8):
    """Start a gRPC server. `register(server)` adds the servicers. Port 0 picks a free port (tests).
    Returns (server, bound_port). Insecure port for local development; use mTLS credentials in production."""
    port = addr.rsplit(":", 1)[-1]
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    register(server)
    bound = server.add_insecure_port("127.0.0.1:0" if port == "0" else f"[::]:{port}")
    if not bound:
        raise RuntimeError(f"could not bind {addr}")
    server.start()
    return server, bound


def correlation_id(context) -> str:
    for key, value in context.invocation_metadata():
        if key == "x-correlation-id":
            return value
    return ""


def run_forever(serve_fn, name: str) -> None:
    server, port = serve_fn()
    log.info("%s listening on port %s", name, port)
    server.wait_for_termination()
