"""Pydantic schemas for projects (CONTRACT.md §4.5, §5.4).

Projects are intentionally loose: the timeline / characters payloads are owned by
the frontend and keep evolving, so unknown keys are preserved end to end.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = "未命名项目"
    fps: int = 24
    width: int = 1080
    height: int = 1524


class ProjectPatch(BaseModel):
    """Partial update payload for ``PUT /api/projects/{id}``."""

    model_config = ConfigDict(extra="allow")

    name: str | None = None
    fps: int | None = None
    width: int | None = None
    height: int | None = None
    audio: dict[str, Any] | None = None
    characters: list[dict[str, Any]] | None = None
    timeline: dict[str, Any] | None = None


class Project(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str = "未命名项目"
    fps: int = 24
    width: int = 1080
    height: int = 1524
    createdAt: str = ""
    updatedAt: str = ""
    audio: dict[str, Any] | None = None
    characters: list[dict[str, Any]] = Field(default_factory=list)
    timeline: dict[str, Any] = Field(default_factory=dict)


class ProjectSummary(BaseModel):
    id: str
    name: str
    updatedAt: str
