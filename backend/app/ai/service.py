"""AI orchestration: provider selection, result caching, rule fallback.

Provider abstraction: an :class:`AnalyzeProvider` is any callable with the
signature ``(lines, bpm, style, cfg) -> segments``.  Adding another LLM later
only means registering one more entry in :data:`ANALYZE_PROVIDERS` (e.g. an
OpenAI-compatible local model).  The service guarantees a response: provider
errors and missing keys degrade to :mod:`app.ai.rule` with a readable warning
instead of raising HTTP 500.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from . import base, cache, deepseek, jev, rule
from .base import AIError

MISSING_DEEPSEEK_WARNING = (
    "未配置 DeepSeek API key，已使用规则兜底；"
    "在 PUT /api/settings 写入 deepseek.apiKey 后启用。"
)
MISSING_OPENROUTER_WARNING = (
    "未配置 OpenRouter API key，已使用规则兜底；"
    "在 PUT /api/settings 写入 openrouter.apiKey 后启用。"
)


@dataclass(frozen=True)
class AnalyzeProvider:
    """One registered lyrics-analysis implementation."""

    name: str
    requires: str | None  # settings section needed to run (None = always available)
    run: Callable[..., list[dict]]


ANALYZE_PROVIDERS: dict[str, AnalyzeProvider] = {
    "deepseek": AnalyzeProvider("deepseek", "deepseek", deepseek.analyze),
    "rule": AnalyzeProvider("rule", None, rule.analyse_segments),
}


def get_analyze_provider(name: str | None) -> AnalyzeProvider:
    return ANALYZE_PROVIDERS.get(str(name or "").lower(), ANALYZE_PROVIDERS["rule"])


def available_analyze_providers(settings: dict | None = None) -> list[str]:
    names = ["rule"]
    if base.deepseek_config(settings)["apiKey"]:
        names.insert(0, "deepseek")
    return names


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def analyze_lyrics(
    lines: list[dict],
    bpm: float | None = None,
    style: str | None = None,
    provider: str = "deepseek",
) -> dict[str, Any]:
    """Analyse lyrics, preferring the requested provider and degrading to rules."""
    if not lines:
        return {
            "segments": [],
            "provider": "rule",
            "cached": False,
            "warnings": ["没有可分析的歌词行（lines 为空）。"],
        }

    provider_name = str(provider or "deepseek").lower()
    if provider_name != "deepseek":
        return {
            "segments": rule.analyse_segments(lines, bpm, style),
            "provider": "rule",
            "cached": False,
            "warnings": [],
        }

    cfg = base.deepseek_config()
    if not cfg["apiKey"]:
        return {
            "segments": rule.analyse_segments(lines, bpm, style),
            "provider": "rule",
            "cached": False,
            "warnings": [MISSING_DEEPSEEK_WARNING],
        }

    key = cache.cache_key(lines, bpm, cfg["model"])
    cached = cache.load(key)
    if cached is not None:
        return {
            "segments": cached["segments"],
            "provider": cached.get("provider") or "deepseek",
            "cached": True,
            "warnings": [],
        }

    try:
        segments = deepseek.analyze(lines, bpm, style, cfg)
    except AIError as exc:
        return {
            "segments": rule.analyse_segments(lines, bpm, style),
            "provider": "rule",
            "cached": False,
            "warnings": [f"DeepSeek 调用失败，已使用规则兜底：{base.scrub(str(exc))}"],
        }

    cache.save(
        key,
        {
            "segments": segments,
            "provider": "deepseek",
            "model": cfg["model"],
            "bpm": bpm,
            "style": style,
            "createdAt": _now(),
        },
    )
    return {
        "segments": segments,
        "provider": "deepseek",
        "cached": False,
        "warnings": [],
    }


def decide_layers(
    state: dict[str, Any] | None,
    candidates: dict[str, list[str] | None] | None,
) -> dict[str, Any]:
    """Pick one candidate layer per channel via Jev, degrading to rules."""
    cleaned: dict[str, list[str]] = {}
    for channel in ("eyes", "brow", "mouth"):
        options = (candidates or {}).get(channel) or []
        cleaned[channel] = [str(option) for option in options if str(option).strip()]
    if not any(cleaned.values()):
        return {
            "choices": {},
            "confidence": {},
            "provider": "rule",
            "raw": {"mood": rule.detect_state_mood(state or {}), "reasons": {}, "provider": "rule"},
            "warnings": ["没有可决策的候选图层（candidates 为空）。"],
        }

    cfg = base.openrouter_config()
    if cfg["apiKey"]:
        try:
            result = jev.decide(state or {}, cleaned, cfg)
            return {
                "choices": result["choices"],
                "confidence": result["confidence"],
                "provider": "jev",
                "raw": result.get("raw"),
                "warnings": [],
            }
        except AIError as exc:
            warnings = [f"Jev 调用失败，已使用规则兜底：{base.scrub(str(exc))}"]
    else:
        warnings = [MISSING_OPENROUTER_WARNING]

    result = rule.decide_layers(state or {}, cleaned)
    return {
        "choices": result["choices"],
        "confidence": result["confidence"],
        "provider": "rule",
        "raw": result["raw"],
        "warnings": warnings,
    }
