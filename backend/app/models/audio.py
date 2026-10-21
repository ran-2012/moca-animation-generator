"""Pydantic schemas for the audio domain (CONTRACT.md §5.3)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AudioSummary(CamelModel):
    asset_id: str
    filename: str
    duration_sec: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    codec: str | None = None
    format: str | None = None
    size_bytes: int | None = None
    bpm: float | None = None
    bpm_source: str | None = None
    offset_sec: float = 0.0
    peaks_points: int = 0
    peaks: list[float] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PeaksResponse(CamelModel):
    points: int
    peaks: list[float] = Field(default_factory=list)


class BpmUpdate(CamelModel):
    bpm: float = Field(gt=0, le=400)
    offset_sec: float = 0.0


class OkResponse(CamelModel):
    ok: bool = True
