"""Pydantic schemas for the SVP domain (CONTRACT.md §4.4 / §5.3).

JSON is camelCase; Python attributes stay snake_case and are aliased.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

VISEMES = ["closed", "n", "f", "a", "i", "u", "e", "o"]


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TrackGroup(CamelModel):
    name: str = ""
    note_count: int = 0


class TrackInfo(CamelModel):
    index: int
    name: str
    is_instrumental: bool = False
    # Extra hint for the picker: non-instrumental track that actually has notes.
    is_vocal: bool = False
    note_count: int = 0
    range_start_sec: float = 0.0
    range_end_sec: float = 0.0
    groups: list[TrackGroup] = Field(default_factory=list)


class SvpUploadResponse(CamelModel):
    asset_id: str
    filename: str
    version: str | None = None
    tracks: list[TrackInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TimelineRequest(CamelModel):
    track_index: int
    fps: int = Field(default=60, ge=1, le=240)
    psd_asset_id: str | None = None
    mapping_set_id: str = "standard"
    animation_mode_id: Literal["classic", "clear", "natural", "expressive"] = "natural"


class TimelineFrame(CamelModel):
    t: float
    viseme: str
    openness: float = 0.0
    mouth_pose: str | None = None
    phase: str | None = None
    note_index: int | None = None


class TimelineSource(CamelModel):
    kind: Literal["svp"] = "svp"
    asset_id: str
    track_index: int


class NoteEvent(CamelModel):
    index: int
    start_sec: float
    end_sec: float
    duration_sec: float
    pitch_midi: float
    lyric: str
    group: str = ""
    method: str | None = None
    onset_viseme: str | None = None
    main_viseme: str
    coda_viseme: str | None = None
    phones: list[str] = Field(default_factory=list)
    sustained: bool = False


class MouthRun(CamelModel):
    start_sec: float
    end_sec: float
    frames: int
    viseme: str
    note_index: int | None = None


class TimelineMode(CamelModel):
    mapping_set_id: str = "standard"
    animation_mode_id: str = "natural"
    animation_mode_version: int = 1


class Timeline(CamelModel):
    fps: int
    duration: float
    frames: list[TimelineFrame] = Field(default_factory=list)
    source: TimelineSource
    notes: list[NoteEvent] = Field(default_factory=list)
    mouth_runs: list[MouthRun] = Field(default_factory=list)
    mode: TimelineMode = Field(default_factory=TimelineMode)
    source_tracks: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    tracks: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class Blink(CamelModel):
    t: float
    duration: float = 0.15


class TimelineResponse(CamelModel):
    timeline: Timeline
    blinks: list[Blink] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    # True when served from data/assets/svp/<id>/timeline-track{i}-{fps}.json
    cached: bool = False
