"""Pydantic schemas for the AI domain (CONTRACT.md §5.5).

JSON field names are camelCase (``baseUrl`` / ``hasKey`` / ``apiKey``) as the
contract requires.  Responses are deliberately lenient about extra provider
metadata (``warnings``, ``cached``, ``raw``): the frontend may ignore them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Mood = Literal["calm", "bright", "intense", "sad", "neutral"]
AnalyzeProviderName = Literal["deepseek", "rule"]
DecideProviderName = Literal["jev", "rule"]


class LyricLine(BaseModel):
    text: str = ""
    start: float = 0.0
    end: float = 0.0


class AnalyzeLyricsRequest(BaseModel):
    lines: list[LyricLine] = Field(default_factory=list)
    bpm: float | None = None
    style: str | None = None
    provider: AnalyzeProviderName = "deepseek"


class EffectSpec(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class Segment(BaseModel):
    start: float
    end: float
    mood: Mood
    intensity: float
    effects: list[EffectSpec] = Field(default_factory=list)


class AnalyzeLyricsResponse(BaseModel):
    segments: list[Segment]
    provider: AnalyzeProviderName
    cached: bool = False
    warnings: list[str] = Field(default_factory=list)


class Candidates(BaseModel):
    eyes: list[str] | None = None
    brow: list[str] | None = None
    mouth: list[str] | None = None


class DecideLayersRequest(BaseModel):
    state: dict[str, Any] = Field(default_factory=dict)
    candidates: Candidates = Field(default_factory=Candidates)


class DecideLayersResponse(BaseModel):
    choices: dict[str, str] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    provider: DecideProviderName = "rule"
    raw: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Settings (GET/PUT /api/settings) -- keys are write-only, never echoed back
# ---------------------------------------------------------------------------


class DeepSeekSettingsUpdate(BaseModel):
    baseUrl: str | None = None
    model: str | None = None
    apiKey: str | None = None


class OpenRouterSettingsUpdate(BaseModel):
    model: str | None = None
    apiKey: str | None = None


class SettingsUpdate(BaseModel):
    deepseek: DeepSeekSettingsUpdate | None = None
    openrouter: OpenRouterSettingsUpdate | None = None


class DeepSeekSettingsView(BaseModel):
    baseUrl: str
    model: str
    hasKey: bool


class OpenRouterSettingsView(BaseModel):
    model: str
    hasKey: bool


class SettingsView(BaseModel):
    deepseek: DeepSeekSettingsView
    openrouter: OpenRouterSettingsView
