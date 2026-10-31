"""Groq chat in JSON mode. Call as llm.chat_json(...) so tests can replace it."""
import json
import os

from groq import Groq

from . import config

_client = None


def chat_json(system: str, user: str) -> dict:
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to .env")
        _client = Groq(api_key=key)
    resp = _client.chat.completions.create(
        model=config.CHAT_MODEL, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return json.loads(resp.choices[0].message.content)
