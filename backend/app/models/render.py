"""Pydantic schemas for the render/export API.

Wire shape (all camelCase, matching the rest of MocaDiff):

* ``POST /api/render`` – submit a job;
* ``GET  /api/render/{jobId}`` – job status/progress;
* ``GET  /api/render/{jobId}/download`` – finished artifact.

``progress`` is a 0..1 fraction; ``doneFrames`` / ``frameCount`` give the exact
frame counter for UIs that prefer integers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RenderFormat = Literal["png_zip", "prores4444", "webm_alpha", "mp4"]
Viseme = Literal["closed", "n", "f", "a", "i", "u", "e", "o"]
JobStatus = Literal["queued", "running", "done", "failed"]

VISEMES: tuple[str, ...] = ("closed", "n", "f", "a", "i", "u", "e", "o")
RENDER_FORMATS: tuple[str, ...] = ("png_zip", "prores4444", "webm_alpha", "mp4")

MAX_TIMELINE_FRAMES = 200_000
MAX_BLINKS = 10_000


class TimelineFrameIn(BaseModel):
    t: float = Field(ge=0)
    viseme: Viseme = "closed"
    openness: float | None = Field(default=None, ge=0, le=1)
    mouthPose: str | None = None
    phase: str | None = None
    noteIndex: int | None = None


class TimelineEventIn(BaseModel):
    t: float = Field(ge=0)
    state: str | None = None
    duration: float | None = Field(default=None, ge=0)


class TimelineIn(BaseModel):
    """Mouth timeline.  ``fps`` is informational: ``t`` is always seconds."""

    fps: float = Field(default=60.0, ge=1, le=240)
    duration: float = Field(default=0.0, ge=0)
    frames: list[TimelineFrameIn] = Field(default_factory=list, max_length=MAX_TIMELINE_FRAMES)
    tracks: dict[str, list[TimelineEventIn]] = Field(default_factory=dict)


class BlinkIn(BaseModel):
    t: float = Field(ge=0)
    duration: float = Field(default=0.15, gt=0, le=5.0)


class SwayIn(BaseModel):
    enabled: bool = False
    amplitude: float = Field(default=0.35, ge=0, le=1)
    frequency: float = Field(default=0.5, ge=0.125, le=4)
    offset: float = Field(default=0.0, ge=-64, le=64)
    bpm: float | None = Field(default=None, gt=0, le=1000)
    audioStart: float = Field(default=0.0, ge=-300, le=300)


class RenderRequest(BaseModel):
    psdAssetId: str = Field(pattern=r"^[0-9A-Za-z_-]{1,64}$")
    timeline: TimelineIn
    blinks: list[BlinkIn] = Field(default_factory=list, max_length=MAX_BLINKS)
    startSec: float = Field(default=0.0, ge=0)
    durationSec: float | None = Field(default=None, gt=0, le=300)
    outFps: float = Field(default=24.0, ge=1, le=60)
    width: int = Field(default=1080, ge=200, le=2480)
    format: RenderFormat = "png_zip"
    # mp4 only: canvas background ("#RRGGBB" / a Pillow colour name).
    background: str = "#101010"
    # Optional fixed expression overrides; otherwise manifest defaultState wins.
    brow: str | None = None
    cheek: str | None = None
    sway: SwayIn | None = None
    # Static (non-semantic) layers hidden by the user in the layer tree.
    hiddenLayers: list[str] = Field(default_factory=list, max_length=10_000)


class RenderJobInfo(BaseModel):
    jobId: str
    status: JobStatus
    progress: float = 0.0
    format: RenderFormat
    fps: float
    width: int
    height: int
    frameCount: int
    doneFrames: int = 0
    fileUrl: str | None = None
    fileName: str | None = None
    error: str | None = None
    elapsedSec: float = 0.0
    createdAt: str = ""
