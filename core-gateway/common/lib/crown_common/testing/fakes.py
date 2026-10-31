"""Test doubles (tests only): a deterministic fake embedder. No model download, no network."""
import hashlib
import re

DIM = 256
STOP = set("a an the of on in at to is are was were and or for with that this it its as by be from up says say "
           "customer analyst wants want asks ask what who how i my me you your they their".split())


def fake_embed(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        v = [0.0] * DIM
        for w in (w for w in re.findall(r"[a-z0-9]+", t.lower()) if w not in STOP):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
        out.append(v)
    return out


class AbortError(Exception):
    """Raised by FakeContext.abort, like grpc does."""
    def __init__(self, code, details):
        super().__init__(f"{code}: {details}")
        self.code, self.details = code, details


class FakeContext:
    def __init__(self, metadata=()):
        self._md = metadata

    def invocation_metadata(self):
        return self._md

    def abort(self, code, details):
        raise AbortError(code, details)


def make_rpc_error(code, details="boom"):
    import grpc

    class _Err(grpc.RpcError):
        def code(self):
            return code

        def details(self):
            return details
    return _Err()
