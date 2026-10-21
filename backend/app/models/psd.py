"""Pydantic schemas for the PSD domain (CONTRACT.md §4.1-4.3, §5.2).

Every payload is camelCase to match the JSON wire format.  ``extra="allow"`` keeps
the schemas forward compatible while the team iterates in parallel.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LayerNode(BaseModel):
    """One node of the PSD layer tree (CONTRACT.md §4.1)."""

    model_config = ConfigDict(extra="allow")

    id: str
    path: str
    name: str
    kind: str = "pixel"  # "group" | "pixel"
    visible: bool = True
    bbox: list[int] = Field(default_factory=lambda: [0, 0, 0, 0])
    width: int = 0
    height: int = 0
    opacity: int = 255
    blendMode: str = "normal"
    children: list["LayerNode"] = Field(default_factory=list)


class MappingBase(BaseModel):
    model_config = ConfigDict(extra="allow")

    hiddenGroups: list[str] = Field(default_factory=list)
    hiddenLayers: list[str] = Field(default_factory=list)
    defaultState: dict[str, str] = Field(default_factory=dict)


class MappingProfile(BaseModel):
    """Semantic mapping produced by automap and edited by the frontend."""

    model_config = ConfigDict(extra="allow")

    psdAssetId: str = ""
    canvas: list[int] = Field(default_factory=lambda: [0, 0])
    base: MappingBase = Field(default_factory=MappingBase)
    channels: dict[str, dict[str, str | None]] = Field(default_factory=dict)
    zorder: list[str] = Field(default_factory=lambda: ["cheek", "mouth", "eyes", "brow"])
    meta: dict[str, Any] = Field(default_factory=dict)


class PsdUploadInfo(BaseModel):
    assetId: str
    filename: str
    width: int
    height: int
    dpi: float | None = None
    layerCount: int = 0
    groupCount: int = 0


class AutomapResult(BaseModel):
    profile: MappingProfile
    warnings: list[str] = Field(default_factory=list)


class BakePatch(BaseModel):
    url: str
    offset: list[int] = Field(default_factory=lambda: [0, 0])
    width: int = 0
    height: int = 0


class BakeBase(BaseModel):
    url: str


class BakeManifest(BaseModel):
    """Baked base + differential patches (CONTRACT.md §4.3)."""

    model_config = ConfigDict(extra="allow")

    assetId: str
    width: int
    height: int
    base: BakeBase
    patches: dict[str, BakePatch] = Field(default_factory=dict)
    zorder: list[str] = Field(default_factory=lambda: ["cheek", "mouth", "eyes", "brow"])
    profileVersion: str
    bakedAt: str


class BakeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    profile: MappingProfile | None = None
