"""Offline rule engine: deterministic lyrics analysis + layer decisions.

Used whenever a provider is not configured or fails, so the API never returns
a 5xx just because no API key is present (task-8 requirement).  Everything here
is pure Python and has no network access.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Iterable

from .base import EFFECT_DEFAULTS, EFFECT_TYPES, MOODS

# ---------------------------------------------------------------------------
# Lyrics analysis
# ---------------------------------------------------------------------------

# Keyword hints.  Latin words are matched case-insensitively; CJK by substring.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "intense": (
        "喊", "叫", "冲", "燃", "爆", "怒", "吵", "吼", "炸", "拼命",
        "run", "shout", "loud", "fire", "fight", "scream", "burn", "rush",
    ),
    "sad": (
        "泪", "哭", "悲", "寂", "痛", "伤", "失恋", "别离", "离开", "孤单",
        "想念", "遗憾", "告别", "miss", "sad", "tear", "cry", "alone",
        "goodbye", "lost", "lonely", "regret",
    ),
    "bright": (
        "笑", "光", "星", "夏", "梦", "希望", "甜", "爱", "开心", "快乐",
        "阳光", "闪耀", "happy", "smile", "light", "sun", "dream", "joy",
        "love", "shine", "sparkle", "bright",
    ),
    "calm": (
        "静", "睡", "夜", "月", "风", "轻", "慢", "呼吸", "温柔", "安静",
        "calm", "quiet", "night", "sleep", "soft", "breath", "gentle",
        "slow", "moon",
    ),
}

_MOOD_TIE_ORDER = ("intense", "sad", "bright", "calm")

_MEANINGFUL = re.compile(r"[0-9A-Za-z\u00c0-\u024f\u3040-\u30ff\u3400-\u9fff]")
_ELLIPSIS = re.compile(r"…+|\.{3,}")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):  # NaN/inf
        return default
    return result


def visual_length(text: str) -> int:
    """Length counting only visible characters (spaces/punctuation excluded)."""
    return len(_MEANINGFUL.findall(text or ""))


def normalise_text(text: str) -> str:
    """Lowercase, width-normalised text used for repetition detection."""
    return unicodedata.normalize("NFKC", text or "").strip().lower()


def _score_line(text: str) -> dict[str, float]:
    lower = (text or "").lower()
    scores = {mood: 0.0 for mood in MOODS}

    for mood, words in _KEYWORDS.items():
        hits = sum(1 for word in words if word in lower)
        scores[mood] += min(hits, 3) * 1.0

    exclamations = (text or "").count("!") + (text or "").count("！")
    scores["intense"] += 0.8 * min(exclamations, 3)

    tildes = (text or "").count("~") + (text or "").count("～")
    scores["bright"] += 0.6 * min(tildes, 2)

    ellipses = len(_ELLIPSIS.findall(text or ""))
    scores["calm"] += 0.5 * min(ellipses, 2)
    scores["sad"] += 0.3 * min(ellipses, 2)

    questions = (text or "").count("?") + (text or "").count("？")
    scores["bright"] += 0.3 * min(questions, 2)

    # Long, unpunctuated flowing lines read as calm.
    if visual_length(text) >= 16 and exclamations == 0:
        scores["calm"] += 0.4

    return scores


def classify_mood(text: str) -> tuple[str, float]:
    """Return ``(mood, score)`` for a single line."""
    scores = _score_line(text)
    best_mood = "neutral"
    best_score = 0.25  # below this everything is ``neutral``
    for mood in _MOOD_TIE_ORDER:
        if scores[mood] > best_score + 1e-9:
            best_mood, best_score = mood, scores[mood]
    return best_mood, round(best_score, 3)


def _line_intensity(
    text: str,
    mood: str,
    bpm: float | None,
    repeat_count: int,
) -> float:
    exclamations = (text or "").count("!") + (text or "").count("！")
    value = 0.28 + 0.42 * min(visual_length(text), 28) / 28
    value += 0.14 * min(exclamations, 2)
    if bpm is not None:
        value += (float(bpm) - 100.0) / 220.0  # ~±0.14 for 70-130 BPM
    value += {
        "calm": -0.22,
        "sad": -0.12,
        "intense": 0.16,
        "bright": 0.04,
        "neutral": 0.0,
    }.get(mood, 0.0)
    value += 0.06 * max(0, repeat_count - 1)  # repeated lines are usually hooks
    return round(max(0.15, min(0.95, value)), 2)


def _effect(effect_type: str, **params: Any) -> dict[str, Any]:
    merged = dict(EFFECT_DEFAULTS[effect_type])
    merged.update(params)
    return {"type": effect_type, "params": merged}


def effects_for(mood: str, intensity: float, bpm: float | None) -> list[dict[str, Any]]:
    """Deterministic effect suggestions for a mood (all params have defaults)."""
    beat_bpm = round(float(bpm), 1) if bpm is not None else 100.0
    intensity = max(0.0, min(1.0, float(intensity)))
    if mood == "calm":
        return [
            _effect("breath", rate=0.35, depth=round(0.2 + 0.25 * intensity, 2)),
            _effect("eye_style", style="soft", blinkBoost=0.1),
            _effect("pull", strength=round(0.1 + 0.2 * intensity, 2), axis="y", ease="inOut"),
        ]
    if mood == "bright":
        return [
            _effect("beat_bounce", amplitude=round(0.2 + 0.35 * intensity, 2), bpm=beat_bpm),
            _effect("eye_style", style="sparkle", blinkBoost=0.15),
            _effect("blush", opacity=round(0.15 + 0.35 * intensity, 2)),
        ]
    if mood == "intense":
        return [
            _effect("shake", amplitude=round(0.12 + 0.3 * intensity, 2), speed=round(6 + 8 * intensity, 1)),
            _effect("pull", strength=round(0.3 + 0.4 * intensity, 2), axis="xy", ease="out"),
            _effect("eye_style", style="sharp", blinkBoost=0.05),
        ]
    if mood == "sad":
        return [
            _effect("breath", rate=0.3, depth=round(0.3 + 0.3 * intensity, 2)),
            _effect("eye_style", style="wet", blinkBoost=0.25),
            _effect("pull", strength=round(0.15 + 0.25 * intensity, 2), axis="y", ease="in"),
        ]
    return [
        _effect("beat_bounce", amplitude=round(0.1 + 0.2 * intensity, 2), bpm=beat_bpm),
        _effect("pull", strength=0.12, axis="y", ease="inOut"),
    ]


def analyse_line_timings(lines: list[dict]) -> list[dict]:
    """Normalise input lines into ``{text,start,end}`` with sane timings.

    Lyrics-only input (all timings zero) gets a synthetic 2.5s-per-line
    timeline so the editor still shows a usable result.
    """
    timed = False
    for line in lines:
        start = _to_float(line.get("start"), 0.0)
        end = _to_float(line.get("end"), 0.0)
        if end > start:
            timed = True
            break

    normalised: list[dict] = []
    for index, line in enumerate(lines):
        text = str(line.get("text") or "")
        if timed:
            start = _to_float(line.get("start"), 0.0)
            end = _to_float(line.get("end"), 0.0)
            if end <= start:
                end = start + 2.5
        else:
            start = round(index * 2.5, 2)
            end = round(start + 2.4, 2)
        normalised.append({"text": text, "start": round(start, 3), "end": round(end, 3)})
    return normalised


def analyse_segments(
    lines: list[dict],
    bpm: float | None = None,
    style: str | None = None,
) -> list[dict[str, Any]]:
    """Rule-based analysis: merge adjacent same-mood lines into segments."""
    if not lines:
        return []

    entries = analyse_line_timings(lines)
    repeat_counts = Counter(
        normalise_text(entry["text"]) for entry in entries if normalise_text(entry["text"])
    )

    items: list[dict[str, Any]] = []
    for entry in entries:
        text = entry["text"]
        mood, _ = classify_mood(text)
        key = normalise_text(text)
        repeats = repeat_counts.get(key, 0) if key else 1
        intensity = _line_intensity(text, mood, bpm, repeats)
        items.append({"start": entry["start"], "end": entry["end"], "mood": mood, "intensity": intensity})

    items.sort(key=lambda item: (item["start"], item["end"]))

    segments: list[dict[str, Any]] = []
    for item in items:
        if (
            segments
            and item["mood"] == segments[-1]["mood"]
            and item["start"] - segments[-1]["end"] <= 0.75
        ):
            segment = segments[-1]
            segment["end"] = max(segment["end"], item["end"])
            segment["intensity"] = round((segment["intensity"] + item["intensity"]) / 2, 2)
            continue
        segments.append(
            {
                "start": item["start"],
                "end": item["end"],
                "mood": item["mood"],
                "intensity": item["intensity"],
            }
        )

    for segment in segments:
        segment["effects"] = effects_for(segment["mood"], segment["intensity"], bpm)
    return segments


# ---------------------------------------------------------------------------
# Layer decision
# ---------------------------------------------------------------------------

_CHANNEL_HINTS: dict[str, dict[str, tuple[str, ...]]] = {
    "eyes": {
        "bright": ("smile", "sparkle", "happy", "star", "笑"),
        "sad": ("cry", "wet", "tear", "sad", "泪", "哭"),
        "intense": ("sharp", "angry", "wide", "open", "睁"),
        "calm": ("soft", "half", "closed", "柔", "半", "闭"),
        "neutral": ("open", "normal", "常态", "睁"),
    },
    "brow": {
        "bright": ("raised", "happy", "neutral", "扬", "上"),
        "sad": ("sad", "down", "悲", "下"),
        "intense": ("angry", "furrow", "sharp", "怒", "皱"),
        "calm": ("neutral", "relaxed", "常态", "平"),
        "neutral": ("neutral", "常态", "平"),
    },
    "mouth": {
        "bright": ("a", "e", "open", "smile", "笑"),
        "sad": ("u", "o", "n", "closed", "闭"),
        "intense": ("a", "o", "open"),
        "calm": ("closed", "n", "m", "闭"),
        "neutral": ("n", "closed", "闭"),
    },
}


def _flatten_values(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _flatten_values(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _flatten_values(item)
    elif isinstance(value, (str, int, float, bool)):
        yield str(value)


def detect_state_mood(state: Any) -> str:
    """Best-effort mood for a free-form character state object."""
    if isinstance(state, dict):
        explicit = str(state.get("mood") or state.get("emotion") or "").strip().lower()
        if explicit in MOODS:
            return explicit
    text = " ".join(_flatten_values(state))[:400]
    if not text.strip():
        return "neutral"
    mood, _ = classify_mood(text)
    return mood


def _explicit_hint(channel: str, state: Any) -> str | None:
    if not isinstance(state, dict):
        return None
    for key in (channel, "viseme" if channel == "mouth" else None, "expression", "face"):
        if not key:
            continue
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _pick_candidate(channel: str, options: list[str], state: Any, mood: str) -> str:
    hint = _explicit_hint(channel, state)
    if hint is not None:
        for option in options:
            if option == hint:
                return option
        lowered_hint = hint.lower()
        for option in options:
            if lowered_hint in option.lower() or option.lower() in lowered_hint:
                return option

    preferences = _CHANNEL_HINTS.get(channel, {}).get(mood, ())
    for preference in preferences:
        for option in options:
            if preference.lower() in option.lower():
                return option
    return options[0]


def decide_layers(
    state: dict[str, Any] | None,
    candidates: dict[str, list[str] | None],
) -> dict[str, Any]:
    """Rule-based layer choice: deterministic fallback, confidence always 0."""
    mood = detect_state_mood(state or {})
    choices: dict[str, str] = {}
    confidence: dict[str, float] = {}
    reasons: dict[str, str] = {}

    for channel in ("eyes", "brow", "mouth"):
        options = [str(option) for option in (candidates.get(channel) or []) if str(option).strip()]
        if not options:
            continue
        pick = _pick_candidate(channel, options, state or {}, mood)
        choices[channel] = pick
        confidence[channel] = 0.0
        reasons[channel] = f"规则兜底：mood={mood}"

    return {
        "choices": choices,
        "confidence": confidence,
        "raw": {"mood": mood, "reasons": reasons, "provider": "rule"},
    }


# A neutral sanity check used by tests / providers.
def is_valid_effect(effect: dict) -> bool:
    return (
        isinstance(effect, dict)
        and effect.get("type") in EFFECT_TYPES
        and isinstance(effect.get("params"), dict)
    )
