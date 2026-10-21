"""Pydantic schema for persisted workspace sessions.

A session is a small JSON document with the ids and UI state required to
restore the workspace after a page reload.  Heavy artefacts (PSD tree, bake
manifest, SVP timeline) are not duplicated here: the frontend re-fetches them
from the persisted assets/caches using the stored ids.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SessionState(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: int = 1
    projectName: str = "未命名项目"
    mockMode: bool = False
    time: float = 0.0

    psd: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None
    hiddenGroups: list[str] = Field(default_factory=list)
    hiddenLayers: list[str] = Field(default_factory=list)
    selectedLayerId: str | None = None

    svp: dict[str, Any] | None = None
    selectedTrack: int | None = None
    fps: float = 60.0

    audio: dict[str, Any] | None = None
    bpm: float | None = None
    offset: float = 0.0

    updatedAt: str | None = None


class SessionResponse(BaseModel):
    session: SessionState | None = None
    savedAt: str | None = None


class SessionSaveResult(BaseModel):
    ok: bool = True
    savedAt: str
