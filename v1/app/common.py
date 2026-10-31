"""Shared config + Groq / embedding helpers."""
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CHAT_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")  # local; Groq has no embeddings API
DB_PATH = os.getenv("BANK_DB", str(ROOT / "data" / "bank.db"))
VECTOR_PATH = os.getenv("VECTOR_STORE_PATH", str(ROOT / "data" / "vector_store.json"))

TEXT2SQL_ADDR = os.getenv("TEXT2SQL_ADDR", "localhost:50051")
VALIDATOR_ADDR = os.getenv("VALIDATOR_ADDR", "localhost:50052")
EXECUTOR_ADDR = os.getenv("EXECUTOR_ADDR", "localhost:50053")
SOP_ADDR = os.getenv("SOP_ADDR", "localhost:50054")
INSIGHT_ADDR = os.getenv("INSIGHT_ADDR", "localhost:50055")
ACCOUNT_ADDR = os.getenv("ACCOUNT_ADDR", "localhost:50056")

# service name (as used in skill.json "call") -> address
SERVICE_ADDRS = {
    "Text2SqlService": TEXT2SQL_ADDR,
    "SqlValidatorService": VALIDATOR_ADDR,
    "SqlExecutorService": EXECUTOR_ADDR,
    "SopRetrievalService": SOP_ADDR,
    "InsightService": INSIGHT_ADDR,
    "AccountService": ACCOUNT_ADDR,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

_client = None
_embedder = None


def _groq() -> Groq:
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to .env")
        _client = Groq(api_key=key)
    return _client


def chat_json(system: str, user: str) -> dict:
    """Groq chat completion in JSON mode, returns the parsed JSON object."""
    resp = _groq().chat.completions.create(
        model=CHAT_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return json.loads(resp.choices[0].message.content)


def embed(texts: list[str]) -> list[list[float]]:
    """Local embeddings (fastembed, ONNX)."""
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding(model_name=EMBED_MODEL)
    return [v.tolist() for v in _embedder.embed(texts)]


def port_of(addr: str) -> str:
    return addr.rsplit(":", 1)[-1]
