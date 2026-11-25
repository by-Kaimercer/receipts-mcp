"""Minimal Ollama client: deterministic JSON chat with an on-disk cache."""
import hashlib
import json
import sqlite3
import threading

import requests

from . import config


class ModelUnavailable(RuntimeError):
    pass


_lock = threading.Lock()
_db = None


def _cache():
    global _db
    if _db is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _db = sqlite3.connect(config.DATA_DIR / "cache.sqlite", check_same_thread=False)
        _db.execute("CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, v TEXT)")
    return _db


def chat_json(system: str, user: str, use_cache: bool = True) -> dict:
    payload = {
        "model": config.MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "seed": 7, "num_ctx": config.NUM_CTX},
    }
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if use_cache:
        with _lock:
            row = _cache().execute("SELECT v FROM c WHERE k=?", (key,)).fetchone()
        if row:
            return json.loads(row[0])
    try:
        r = requests.post(f"{config.OLLAMA_URL}/api/chat", json=payload, timeout=600)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise ModelUnavailable(
            f"Ollama is not reachable at {config.OLLAMA_URL}. Start it with `ollama serve` and retry."
        ) from e
    if r.status_code == 404:
        raise ModelUnavailable(f"Model '{config.MODEL}' is not installed. Run `ollama pull {config.MODEL}`.")
    r.raise_for_status()
    try:
        out = json.loads(r.json()["message"]["content"])
    except json.JSONDecodeError:
        out = {}
    if not isinstance(out, dict):
        out = {}
    with _lock:
        _cache().execute("INSERT OR REPLACE INTO c VALUES (?, ?)", (key, json.dumps(out)))
        _cache().commit()
    return out
