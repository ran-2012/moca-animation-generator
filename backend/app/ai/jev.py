"""Jev (TypeSafe) provider: pick one candidate layer per channel.

Endpoint: ``POST https://openrouter.ai/api/v1/systemone`` with an OpenRouter
key.  Each channel becomes one ``choice`` question whose ``criteria`` map is
``candidate name -> description``; the answer is validated against the
candidate list, otherwise :class:`AIError` is raised and the service falls back
to :mod:`app.ai.rule`.
"""

from __future__ import annotations

import json
from typing import Any

from . import base
from .base import AIError

_CHANNEL_LABELS = {
    "eyes": "眼睛（眼型/表情）图层",
    "brow": "眉毛图层",
    "mouth": "嘴型图层",
}

_CHANNEL_ORDER = ("eyes", "brow", "mouth")


def build_questions(candidates: dict[str, list[str] | None]) -> list[dict[str, Any]]:
    """Build one Jev ``choice`` question per non-empty channel."""
    questions: list[dict[str, Any]] = []
    for channel in _CHANNEL_ORDER:
        options = [str(option) for option in (candidates.get(channel) or []) if str(option).strip()]
        if not options:
            continue
        label = _CHANNEL_LABELS[channel]
        criteria = {
            option: f"{option}：{base.describe_candidate(option)}"
            for option in options
        }
        questions.append(
            {
                "name": channel,
                "type": "choice",
                "prompt": f"根据当前角色状态，从候选中选择最合适的{label}。",
                "criteria": criteria,
            }
        )
    return questions


def build_request(
    state: dict[str, Any] | None,
    candidates: dict[str, list[str] | None],
    cfg: dict,
) -> dict[str, Any]:
    """The exact JSON body sent to the Jev endpoint (also useful for docs/tests)."""
    questions = build_questions(candidates)
    if not questions:
        raise AIError("没有可决策的候选图层")
    return {
        "model": cfg.get("model") or base.DEFAULT_JEV_MODEL,
        "state": state or {},
        "questions": questions,
    }


def _confidence(answer: dict, choice: str) -> float:
    value = answer.get("confidence")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        probabilities = answer.get("probabilities")
        if isinstance(probabilities, dict):
            value = probabilities.get(choice)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 0.0
    return round(max(0.0, min(1.0, float(value))), 3)


def parse_answers(
    data: dict[str, Any],
    candidates: dict[str, list[str] | None],
) -> dict[str, Any]:
    """Validate ``data["answers"]`` against the candidate lists."""
    answers = data.get("answers")
    if not isinstance(answers, dict):
        raise AIError("Jev 返回缺少 answers")

    choices: dict[str, str] = {}
    confidence: dict[str, float] = {}
    for channel in _CHANNEL_ORDER:
        options = [str(option) for option in (candidates.get(channel) or []) if str(option).strip()]
        if not options:
            continue
        answer = answers.get(channel)
        if isinstance(answer, str):
            answer = {"choice": answer}
        if not isinstance(answer, dict):
            continue  # channel left undecided; the response just omits it
        choice = answer.get("choice")
        if choice is None:
            continue
        if not isinstance(choice, str) or choice not in options:
            raise AIError(f"Jev 返回了候选外的选择：{choice!r}")
        choices[channel] = choice
        confidence[channel] = _confidence(answer, choice)

    if not choices:
        raise AIError("Jev 没有返回任何有效选择")
    return {"choices": choices, "confidence": confidence}


def decide(
    state: dict[str, Any] | None,
    candidates: dict[str, list[str] | None],
    cfg: dict | None = None,
) -> dict[str, Any]:
    """Call Jev; returns ``{choices, confidence, raw}`` or raises :class:`AIError`."""
    config = cfg or base.openrouter_config()
    if not config.get("apiKey"):
        raise AIError("未配置 OpenRouter API key")

    payload = build_request(state, candidates, config)
    headers = {
        "Authorization": f"Bearer {config['apiKey']}",
        "HTTP-Referer": "http://127.0.0.1:8787",
        "X-Title": "MocaDiff Studio",
    }
    data = base.post_json(
        config["baseUrl"].rstrip("/") + "/systemone",
        payload,
        headers=headers,
        timeout=base.JEV_TIMEOUT,
        label="Jev",
    )
    parsed = parse_answers(data, candidates)
    parsed["raw"] = data
    return parsed


# Re-exported for callers that need the documented body without importing json.
def request_example() -> str:  # pragma: no cover - documentation helper
    payload = build_request(
        {"mood": "bright", "intensity": 0.7, "bpm": 128},
        {"eyes": ["open", "smile", "blink"], "brow": ["neutral", "raised"], "mouth": ["n", "a", "closed"]},
        {"model": base.DEFAULT_JEV_MODEL},
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)
