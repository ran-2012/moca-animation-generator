"""Shared primitives for the AI domain: defaults, errors, JSON-over-HTTP.

The HTTP transport deliberately uses :mod:`urllib` from the standard library.
This machine ships an old ``httpx`` build (0.13.x) that still imports the
``cgi`` module, which Python 3.13 removed, and the ``openai`` SDK imports
``httpx`` -- importing either would make ``app.main`` drop the ``ai`` router
silently (main.py tolerates import failures).  The standard library keeps the
API bootable with zero extra dependencies.

Tests monkeypatch :func:`post_json`, so no test ever touches the network.
API keys are only ever read from ``data/settings.json`` (via ``storage``) and
never logged; :func:`scrub` strips anything key-shaped from error messages.
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# ---------------------------------------------------------------------------
# Defaults (CONTRACT.md §5.5)
# ---------------------------------------------------------------------------

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_JEV_MODEL = "typesafe/jev-1.13"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Timeouts mandated by task-8 / CONTRACT.
DEEPSEEK_TIMEOUT = 30.0
JEV_TIMEOUT = 10.0

# Allowed enum values shared by providers, rules and the API schema.
MOODS = ("calm", "bright", "intense", "sad", "neutral")
EFFECT_TYPES = ("beat_bounce", "pull", "shake", "breath", "eye_style", "blush")

# Effect parameter defaults, consumed by the renderer/frontend later.
# Every effect always receives the full default set merged with provider params.
EFFECT_DEFAULTS: dict[str, dict[str, Any]] = {
    "beat_bounce": {"amplitude": 0.3, "bpm": 100.0, "smoothing": 0.45},
    "pull": {"strength": 0.3, "axis": "y", "ease": "inOut"},
    "shake": {"amplitude": 0.2, "speed": 8.0, "axis": "xy"},
    "breath": {"rate": 0.4, "depth": 0.3},
    "eye_style": {"style": "soft", "blinkBoost": 0.15},
    "blush": {"opacity": 0.35},
}

# Settings sections (data/settings.json).
SETTINGS_SECTIONS = ("deepseek", "openrouter")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AIError(RuntimeError):
    """A recoverable provider failure.

    The service layer catches this and falls back to the rule engine instead of
    surfacing a 5xx; :class:`AIError` messages are always human readable.
    """


# ---------------------------------------------------------------------------
# Secrets hygiene
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{4,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(api[_\-]?key\s*[=:]\s*)[^\s,;\"'}]+"),
)


def scrub(text: str) -> str:
    """Remove anything key-shaped from a message before it reaches a log/response."""
    if not text:
        return ""
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda match: str(match.group(1)) + "***", text)
        else:
            text = pattern.sub("***", text)
    return text


# ---------------------------------------------------------------------------
# Settings access
# ---------------------------------------------------------------------------


def _settings(settings: dict | None) -> dict:
    if settings is not None:
        return settings
    from .. import storage  # local import keeps this module dependency-light

    return storage.load_settings() or {}


def _section(settings: dict | None, name: str) -> dict:
    section = _settings(settings).get(name)
    return section if isinstance(section, dict) else {}


def deepseek_config(settings: dict | None = None) -> dict:
    """Resolved DeepSeek settings; ``apiKey`` is ``""`` when not configured."""
    section = _section(settings, "deepseek")
    base_url = str(section.get("baseUrl") or DEFAULT_DEEPSEEK_BASE_URL).strip()
    model = str(section.get("model") or DEFAULT_DEEPSEEK_MODEL).strip()
    return {
        "baseUrl": (base_url or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/"),
        "model": model or DEFAULT_DEEPSEEK_MODEL,
        "apiKey": str(section.get("apiKey") or "").strip(),
    }


def openrouter_config(settings: dict | None = None) -> dict:
    """Resolved OpenRouter (Jev) settings; ``apiKey`` is ``""`` when not configured."""
    section = _section(settings, "openrouter")
    model = str(section.get("model") or DEFAULT_JEV_MODEL).strip()
    return {
        "baseUrl": DEFAULT_OPENROUTER_BASE_URL,
        "model": model or DEFAULT_JEV_MODEL,
        "apiKey": str(section.get("apiKey") or "").strip(),
    }


# ---------------------------------------------------------------------------
# HTTP transport (standard library, monkeypatchable in tests)
# ---------------------------------------------------------------------------


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:  # pragma: no cover - defensive
        return ""
    raw = raw.strip()
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return scrub(raw[:300])
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            raw = str(error.get("message") or error.get("code") or error)
        elif isinstance(error, str):
            raw = error
        else:
            raw = str(payload.get("message") or payload)[:300]
    return scrub(str(raw)[:300])


def _parse_response(body: bytes, label: str) -> dict:
    text = body.decode("utf-8", "replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIError(f"{label} 返回了非 JSON 响应（{exc.msg}）") from None
    if not isinstance(payload, dict):
        raise AIError(f"{label} 返回的 JSON 不是对象")
    return payload


def post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    label: str = "AI 服务",
) -> dict[str, Any]:
    """POST ``payload`` as JSON and return the decoded JSON object.

    Raises :class:`AIError` with a readable Chinese message on every failure
    (timeout / network / non-2xx / non-JSON).  Never includes auth headers in
    the message.
    """
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = _error_detail(exc)
        suffix = f"：{detail}" if detail else ""
        raise AIError(f"{label} 返回 HTTP {exc.code}{suffix}") from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise AIError(f"{label} 请求超时（{timeout:g}s）") from None
        raise AIError(f"{label} 网络不可达：{scrub(str(reason))}") from None
    except (TimeoutError, socket.timeout):
        raise AIError(f"{label} 请求超时（{timeout:g}s）") from None
    except OSError as exc:
        raise AIError(f"{label} 网络错误：{scrub(str(exc))}") from None
    return _parse_response(body, label)


_VISEME_DESCRIPTIONS = {
    "a": "张口（啊）",
    "i": "扁唇（衣）",
    "u": "圆唇（乌）",
    "e": "微开（诶）",
    "o": "圆口（哦）",
    "n": "闭口鼻音（嗯）",
    "closed": "闭口",
    "close": "闭口",
}


def describe_candidate(name: str) -> str:
    """Short human description used as Jev choice criteria / rule reasons."""
    text = str(name).strip()
    lower = text.lower()
    if lower in _VISEME_DESCRIPTIONS:
        return _VISEME_DESCRIPTIONS[lower]
    table = (
        (("smile", "happy", "joy", "笑", "开心"), "微笑/愉快"),
        (("cry", "tear", "sad", "wet", "泪", "哭", "悲"), "哭泣/难过"),
        (("blink", "shut", "眨眼", "闭眼"), "闭眼/眨眼"),
        (("angry", "furrow", "mad", "怒", "皱"), "生气/皱眉"),
        (("surprise", "shock", "wide", "惊"), "惊讶"),
        (("question", "confused", "疑", "惑"), "疑惑"),
        (("raised", "up", "扬", "挑"), "挑眉/上扬"),
        (("sharp", "serious", "严", "锐"), "锐利/严肃"),
        (("soft", "gentle", "柔"), "柔和"),
        (("neutral", "normal", "default", "平静", "常态"), "平静/常态"),
        (("open", "睁", "开"), "睁开"),
        (("half", "半"), "半睁"),
        (("closed", "合"), "闭合"),
    )
    for keywords, description in table:
        if any(keyword in lower for keyword in keywords):
            return description
    return "候选图层"


def is_http_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)
