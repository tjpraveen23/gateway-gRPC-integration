"""Configuration shared by the gateway, the common services and the skill services."""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]          # core-gateway repository root
load_dotenv(Path.cwd() / ".env")                    # the repo you run from (skill-repo/.env or core-gateway/.env)
load_dotenv(ROOT / ".env")                          # core-gateway/.env as a fallback (never overrides)

# Where the gateway finds the skill files (skill.json + skill.md). The skills live in the separate skill-repo.
SKILLS_DIR = Path(os.getenv("SKILLS_DIR") or Path(os.getenv("SKILL_REPO", str(ROOT.parent / "skill-repo"))) / "skills")
DESCRIPTOR_PATH = Path(os.getenv("DESCRIPTOR_PATH", str(ROOT / "registry" / "descriptors.pb")))

CHAT_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")   # local model; Groq has no embeddings API
DB_PATH = os.getenv("BANK_DB", str(ROOT / "data" / "bank.db"))
VECTOR_PATH = os.getenv("VECTOR_STORE_PATH", str(ROOT / "data" / "vector_store.json"))
SOP_DIR = ROOT / "sop_docs"

DEFAULT_PORTS = {
    "SQL_GENERATION": 50051, "SQL_VALIDATION": 50052, "SQL_EXECUTION": 50053, "SOP_RETRIEVAL": 50054,
    "INSIGHT": 50055, "ACCOUNT": 50056, "TRANSACTION": 50057,
}


def service_addr(key: str) -> str:
    """Address of a service: env <KEY>_ADDR, else localhost and the default port."""
    return os.getenv(f"{key}_ADDR", f"localhost:{DEFAULT_PORTS[key]}")


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
