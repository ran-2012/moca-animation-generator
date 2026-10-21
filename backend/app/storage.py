"""Filesystem helpers shared by every backend domain.

Maintained by the Lead.  Keep this module free of domain logic so the
parallel feature modules can depend on it without stepping on each other.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from . import config


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def safe_name(name: str) -> str:
    """Keep only a conservative filename part (never a path)."""
    name = Path(name or "file").name
    name = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff\u3040-\u30ff]", "_", name)
    return name[:120] or "file"


def asset_dir(kind: str, asset_id: str) -> Path:
    if kind not in config.ASSET_KINDS:
        raise ValueError(f"unknown asset kind: {kind}")
    path = config.ASSETS_DIR / kind / asset_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_dir(project_id: str) -> Path:
    path = config.PROJECTS_DIR / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_upload(kind: str, asset_id: str, filename: str, data: bytes) -> Path:
    """Persist an uploaded file; returns the stored path."""
    directory = asset_dir(kind, asset_id)
    target = directory / ("source" + Path(filename).suffix.lower())
    target.write_bytes(data)
    return target


def find_source(kind: str, asset_id: str) -> Path | None:
    directory = config.ASSETS_DIR / kind / asset_id
    if not directory.is_dir():
        return None
    for path in sorted(directory.glob("source.*")):
        return path
    return None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def asset_meta_path(kind: str, asset_id: str) -> Path:
    return config.ASSETS_DIR / kind / asset_id / "meta.json"


def media_url(path: Path) -> str:
    """Map a file under data/assets to a /media URL."""
    try:
        relative = path.resolve().relative_to(config.ASSETS_DIR.resolve())
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError("file is outside the assets directory") from exc
    return "/media/" + relative.as_posix()


def settings_path() -> Path:
    return config.SETTINGS_FILE


def load_settings() -> dict:
    return read_json(config.SETTINGS_FILE, {}) or {}


def save_settings(payload: dict) -> None:
    write_json(config.SETTINGS_FILE, payload)
