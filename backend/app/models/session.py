"""Pydantic schema for persisted workspace sessions.

A session is a small JSON document with the ids and UI state required to
restore the workspace after a page reload.  Heavy artefacts (PSD tree, bake
manifest, SVP timeline) are not duplicated here: the frontend re-fetches them
from the persisted assets/caches using the stored ids.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionSway(BaseModel):
    enabled: bool = False
    amplitude: float = Field(default=0.35, ge=0, le=1)
    frequency: float = Field(default=0.5, ge=0.125, le=4)
    # Phase offset in milliseconds (positive = earlier in the beat).
    offsetMs: float = Field(default=0.0, ge=-2000, le=2000)


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
    exclusiveGroups: list[str] = Field(default_factory=list)
    selectedLayerId: str | None = None

    svp: dict[str, Any] | None = None
    selectedTrack: int | None = None
    mappingSetId: str = "standard"
    animationModeId: Literal["classic", "clear", "natural", "expressive"] = "natural"
    fps: float = 60.0
    timelineView: dict[str, float] | None = None

    audio: dict[str, Any] | None = None
    bpm: float | None = None
    offset: float = 0.0
    sway: SessionSway | None = None
    manifestStale: bool = False

    updatedAt: str | None = None


class SessionResponse(BaseModel):
    session: SessionState | None = None
    savedAt: str | None = None


class SessionSaveResult(BaseModel):
    ok: bool = True
    savedAt: str
