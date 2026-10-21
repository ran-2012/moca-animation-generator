"""Result cache for AI analyses (``data/cache/ai/``).

Only successful provider results are cached; rule fallbacks are re-evaluated on
every request so that adding a key immediately upgrades the output.
The key is a deterministic hash of the lyrics timeline + bpm + model
(task-8: ``hash(lines+bpm+model)``).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .. import config, storage


def cache_dir() -> Path:
    """``data/cache/ai`` - resolved on every call so tests can relocate DATA_DIR."""
    return config.DATA_DIR / "cache" / "ai"


def cache_key(lines: list[dict], bpm: float | None, model: str) -> str:
    canonical = {
        "lines": [
            [
                str(line.get("text") or ""),
                round(float(line.get("start") or 0.0), 3),
                round(float(line.get("end") or 0.0), 3),
            ]
            for line in lines
        ],
        "bpm": None if bpm is None else round(float(bpm), 2),
        "model": str(model or ""),
    }
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def cache_path(key: str) -> Path:
    return cache_dir() / f"{key}.json"


def load(key: str) -> dict | None:
    payload = storage.read_json(cache_path(key), None)
    if not isinstance(payload, dict):
        return None
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        return None
    return payload


def save(key: str, payload: dict[str, Any]) -> None:
    try:
        storage.write_json(cache_path(key), payload)
    except OSError:  # pragma: no cover - cache is best effort
        pass
