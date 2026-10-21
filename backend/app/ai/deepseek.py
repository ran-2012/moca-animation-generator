"""DeepSeek provider: lyrics -> mood / intensity / motion-effect segments.

DeepSeek exposes an OpenAI-compatible ``/chat/completions`` endpoint.  We ask
for ``response_format={"type": "json_object"}`` and *still* validate the
payload strictly; a parse/validation failure is retried once (with a nudging
message), then the service layer falls back to :mod:`app.ai.rule`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import base
from .base import AIError, EFFECT_DEFAULTS, EFFECT_TYPES, MOODS

_SYSTEM_PROMPT = """你是动画 MV 的歌词情绪与动作效果分析器。你的输出必须是一个 JSON 对象，供前端直接渲染。
硬性要求：
1. 只输出 JSON 本身，禁止输出 markdown 代码块、解释、前后缀文字。
2. mood 只能是 calm / bright / intense / sad / neutral 之一。
3. effects[].type 只能是 beat_bounce / pull / shake / breath / eye_style / blush 之一。
4. 时间使用输入行给出的 start / end（秒，float），段落不要超出输入时间范围。
5. 相邻情绪相同的歌词行请合并成一段；不要输出空段落。"""

_JSON_SHAPE = """{"segments":[{"start":0.0,"end":3.2,"mood":"calm","intensity":0.4,"effects":[{"type":"breath","params":{"rate":0.4,"depth":0.3}},{"type":"eye_style","params":{"style":"soft","blinkBoost":0.1}}]}]}"""

_EFFECT_HINTS = """效果参数建议（params 均需给默认值）：
- beat_bounce {"amplitude":0.2-0.6,"bpm":歌曲BPM,"smoothing":0.3-0.6}
- pull {"strength":0.1-0.8,"axis":"x|y|xy","ease":"in|out|inOut"}
- shake {"amplitude":0.1-0.5,"speed":4-16,"axis":"x|y|xy"}
- breath {"rate":0.2-0.8,"depth":0.2-0.8}
- eye_style {"style":"soft|sharp|wet|sparkle|closed","blinkBoost":0-0.5}
- blush {"opacity":0.2-0.9}"""


def _format_lines(lines: list[dict]) -> str:
    rows = []
    for index, line in enumerate(lines):
        rows.append(
            {
                "index": index,
                "text": str(line.get("text") or ""),
                "start": float(line.get("start") or 0.0),
                "end": float(line.get("end") or 0.0),
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def build_prompt(lines: list[dict], bpm: float | None, style: str | None) -> str:
    bpm_text = f"{float(bpm):g}" if bpm is not None else "未知"
    style_text = style or "未指定"
    return (
        f"BPM：{bpm_text}\n风格：{style_text}\n"
        f"输出 JSON 形状：{_JSON_SHAPE}\n{_EFFECT_HINTS}\n"
        f"歌词行（JSON 数组，index 从 0 开始）：\n{_format_lines(lines)}\n\n"
        "请输出合并后的 segments。每段 1-3 个 effects，intensity 为 0-1 的 float。"
    )


def _extract_content(data: dict) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AIError("DeepSeek 返回缺少 choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise AIError("DeepSeek 返回内容为空")
    return content


def _loads_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise AIError("DeepSeek 返回的不是合法 JSON") from None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AIError(f"DeepSeek 返回的不是合法 JSON（{exc.msg}）") from None
    if not isinstance(payload, dict):
        raise AIError("DeepSeek 返回的 JSON 不是对象")
    return payload


def _coerce_float(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise AIError(f"DeepSeek 返回的 {field} 不是数字") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise AIError(f"DeepSeek 返回的 {field} 不是有限数字")
    return number


def normalise_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate/normalise the provider payload into the contract segment shape."""
    raw_segments = payload.get("segments")
    if raw_segments is None:
        raw_segments = payload.get("data")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise AIError("DeepSeek 返回的 segments 为空")

    segments: list[dict[str, Any]] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            raise AIError("DeepSeek 返回的 segment 不是对象")
        mood = str(item.get("mood") or "").strip().lower()
        if mood not in MOODS:
            raise AIError(f"DeepSeek 返回了未知 mood：{mood!r}")
        start = _coerce_float(item.get("start"), "start")
        end = _coerce_float(item.get("end"), "end")
        if end <= start:
            end = start + 2.5
        intensity = _coerce_float(item.get("intensity", 0.5), "intensity")
        intensity = round(max(0.0, min(1.0, intensity)), 2)

        effects: list[dict[str, Any]] = []
        raw_effects = item.get("effects")
        if raw_effects is None:
            raw_effects = []
        if not isinstance(raw_effects, list):
            raise AIError("DeepSeek 返回的 effects 不是数组")
        for effect in raw_effects:
            if not isinstance(effect, dict):
                raise AIError("DeepSeek 返回的 effect 不是对象")
            effect_type = str(effect.get("type") or "").strip()
            if effect_type not in EFFECT_TYPES:
                raise AIError(f"DeepSeek 返回了未知效果类型：{effect_type!r}")
            params = effect.get("params")
            if params is None:
                params = {}
            if not isinstance(params, dict):
                raise AIError("DeepSeek 返回的 effect.params 不是对象")
            merged = dict(EFFECT_DEFAULTS[effect_type])
            merged.update(params)
            effects.append({"type": effect_type, "params": merged})
        if not effects:
            effects = [{"type": "beat_bounce", "params": dict(EFFECT_DEFAULTS["beat_bounce"])}]

        segments.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "mood": mood,
                "intensity": intensity,
                "effects": effects,
            }
        )

    segments.sort(key=lambda segment: segment["start"])
    return segments


def analyze(
    lines: list[dict],
    bpm: float | None = None,
    style: str | None = None,
    cfg: dict | None = None,
) -> list[dict[str, Any]]:
    """Call DeepSeek and return validated segments; raises :class:`AIError`."""
    config = cfg or base.deepseek_config()
    if not config.get("apiKey"):
        raise AIError("未配置 DeepSeek API key")
    if not lines:
        return []

    url = config["baseUrl"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {config['apiKey']}"}
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": build_prompt(lines, bpm, style)},
    ]

    last_error: AIError | None = None
    for attempt in range(2):
        payload = {
            "model": config["model"],
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
            "max_tokens": 4096,
            "stream": False,
        }
        if attempt > 0:
            payload["messages"] = messages + [
                {"role": "user", "content": "上一次响应不是合法 JSON。请只输出一个符合要求的 JSON 对象，不要任何解释。"}
            ]
        try:
            data = base.post_json(
                url,
                payload,
                headers=headers,
                timeout=base.DEEPSEEK_TIMEOUT,
                label="DeepSeek",
            )
        except AIError:
            # Transport failure (timeout / network / HTTP status): retrying the
            # identical request is unlikely to help, degrade to rules instead.
            raise

        # Parse/validation failures are retried once (task-8 requirement).
        try:
            content = _extract_content(data)
            return normalise_segments(_loads_json(content))
        except AIError as exc:
            last_error = exc

    raise last_error or AIError("DeepSeek 分析失败")
