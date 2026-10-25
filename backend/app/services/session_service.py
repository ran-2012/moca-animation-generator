"""Session persistence: the last workspace state survives page reloads.

Stored as ``data/session.json`` (single local user, local-only tool).  Writes
are atomic (temp file + replace) so a crash never leaves a half-written file.

Switching the data source (LIVE <-> MOCK) resets the workspace.  To make that
non-destructive, the previously saved project is kept in
``data/session.prev.json`` whenever the incoming save is an empty workspace or
comes from the other data source.  The frontend can therefore offer a
"restore previous project" fallback.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import config, storage
from ..models.session import SessionState


def session_path() -> Path:
    return config.DATA_DIR / "session.json"


def previous_path() -> Path:
    return config.DATA_DIR / "session.prev.json"


def projects_path() -> Path:
    return config.DATA_DIR / "projects.json"


_MAX_PROJECTS = 50


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read(path: Path) -> tuple[SessionState | None, str | None]:
    payload = storage.read_json(path)
    if not isinstance(payload, dict):
        return None, None
    saved_at = payload.get("savedAt")
    raw = payload.get("session") if isinstance(payload.get("session"), dict) else payload
    try:
        state = SessionState.model_validate(raw)
    except Exception:
        return None, saved_at if isinstance(saved_at, str) else None
    state.updatedAt = state.updatedAt or (saved_at if isinstance(saved_at, str) else None)
    return state, saved_at if isinstance(saved_at, str) else None


def load() -> tuple[SessionState | None, str | None]:
    return _read(session_path())


def load_previous() -> tuple[SessionState | None, str | None]:
    """The last non-empty project snapshot, kept when a switch/reset occurs."""
    return _read(previous_path())


def _signature(state: SessionState) -> str:
    psd = (state.psd or {}).get("assetId") or ""
    svp = (state.svp or {}).get("assetId") or ""
    audio = (state.audio or {}).get("assetId") or ""
    return "|".join(("mock" if state.mockMode else "live", str(psd), str(svp), str(audio)))


def _read_projects() -> list[dict]:
    payload = storage.read_json(projects_path())
    items = payload.get("projects") if isinstance(payload, dict) else payload
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _write_projects(items: list[dict]) -> None:
    storage.write_json(projects_path(), {"projects": items})


def record_project(state: SessionState) -> None:
    """Upsert one history entry per asset triple (no growth from autosaves)."""
    if not _has_project(state):
        return
    items = _read_projects()
    signature = _signature(state)
    now = _now_iso()
    entry = next((item for item in items if item.get("signature") == signature), None)
    if entry is None:
        entry = {"id": "prj_" + storage.new_id(), "createdAt": now}
        items.append(entry)
    entry.update(
        {
            "name": state.projectName or "未命名项目",
            "signature": signature,
            "updatedAt": now,
            "psd": (state.psd or {}).get("filename"),
            "svp": (state.svp or {}).get("filename"),
            "audio": (state.audio or {}).get("filename"),
            "mockMode": bool(state.mockMode),
            "session": state.model_dump(mode="json"),
        }
    )
    items.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    _write_projects(items[:_MAX_PROJECTS])


def list_projects() -> list[dict]:
    items = _read_projects()
    if not items:
        # First run after the history feature: adopt the session already on disk
        # so the user's current project is openable without waiting an autosave.
        current, _ = load()
        if _has_project(current):
            record_project(current)
            items = _read_projects()
    return [
        {key: value for key, value in item.items() if key not in ("session", "signature")}
        for item in items
    ]


def load_project(project_id: str) -> tuple[SessionState | None, str | None]:
    for item in _read_projects():
        if item.get("id") != project_id:
            continue
        try:
            state = SessionState.model_validate(item.get("session") or {})
        except Exception:
            return None, None
        return state, str(item.get("updatedAt") or "")
    return None, None


def delete_project(project_id: str) -> bool:
    items = _read_projects()
    remaining = [item for item in items if item.get("id") != project_id]
    if len(remaining) == len(items):
        return False
    _write_projects(remaining)
    return True


def _has_project(state: SessionState | None) -> bool:
    return bool(state and (state.psd or state.svp or state.audio))


def _write(path: Path, state: SessionState, saved_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp name: concurrent autosave requests must not race on one file.
    temp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temp.write_text(
        json.dumps(
            {"savedAt": saved_at, "session": state.model_dump(mode="json")},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    os.replace(temp, path)


def save(state: SessionState) -> str:
    saved_at = _now_iso()
    state.updatedAt = saved_at

    current, _ = load()
    if current is not None and _has_project(current):
        incoming_empty = not _has_project(state)
        mode_changed = bool(current.mockMode) != bool(state.mockMode)
        if incoming_empty or mode_changed:
            _write(previous_path(), current, current.updatedAt or saved_at)

    _write(session_path(), state, saved_at)
    record_project(state)
    return saved_at


def clear() -> None:
    for path in (session_path(), previous_path()):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
