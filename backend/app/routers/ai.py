"""AI router: settings (write-only keys) + lyrics analysis + layer decisions.

Endpoint ownership: ai-service (task-8).  Contract: CONTRACT.md §5.5.
No provider is required to be configured: missing keys / provider failures
degrade to the rule engine and are reported via ``provider`` + ``warnings``,
never as a 500.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import storage
from ..ai import base, service
from ..models import ai as schemas

router = APIRouter(tags=["ai"])


def _settings_view(settings: dict) -> schemas.SettingsView:
    deepseek = base.deepseek_config(settings)
    openrouter = base.openrouter_config(settings)
    return schemas.SettingsView(
        deepseek=schemas.DeepSeekSettingsView(
            baseUrl=deepseek["baseUrl"],
            model=deepseek["model"],
            hasKey=bool(deepseek["apiKey"]),
        ),
        openrouter=schemas.OpenRouterSettingsView(
            model=openrouter["model"],
            hasKey=bool(openrouter["apiKey"]),
        ),
    )


@router.get("/settings", response_model=schemas.SettingsView)
def get_settings() -> schemas.SettingsView:
    """Desensitised settings: never returns API keys, only ``hasKey``."""
    return _settings_view(storage.load_settings() or {})


@router.put("/settings", response_model=schemas.SettingsView)
def put_settings(payload: schemas.SettingsUpdate) -> schemas.SettingsView:
    settings = storage.load_settings()
    if not isinstance(settings, dict):
        settings = {}

    deepseek = dict(settings.get("deepseek") or {})
    openrouter = dict(settings.get("openrouter") or {})

    if payload.deepseek is not None:
        update = payload.deepseek
        if update.baseUrl is not None:
            value = update.baseUrl.strip()
            if value:
                if not base.is_http_url(value):
                    raise HTTPException(status_code=400, detail="deepseek.baseUrl 必须是 http(s) URL")
                deepseek["baseUrl"] = value.rstrip("/")
            else:
                deepseek.pop("baseUrl", None)
        if update.model is not None:
            value = update.model.strip()
            if value:
                deepseek["model"] = value
            else:
                deepseek.pop("model", None)
        if update.apiKey is not None:
            value = update.apiKey.strip()
            if value:
                deepseek["apiKey"] = value
            else:  # empty string clears the stored key
                deepseek.pop("apiKey", None)

    if payload.openrouter is not None:
        update = payload.openrouter
        if update.model is not None:
            value = update.model.strip()
            if value:
                openrouter["model"] = value
            else:
                openrouter.pop("model", None)
        if update.apiKey is not None:
            value = update.apiKey.strip()
            if value:
                openrouter["apiKey"] = value
            else:
                openrouter.pop("apiKey", None)

    if deepseek:
        settings["deepseek"] = deepseek
    else:
        settings.pop("deepseek", None)
    if openrouter:
        settings["openrouter"] = openrouter
    else:
        settings.pop("openrouter", None)

    try:
        storage.save_settings(settings)
    except OSError as exc:  # pragma: no cover - disk failure
        raise HTTPException(status_code=500, detail=f"写入 data/settings.json 失败：{base.scrub(str(exc))}") from exc
    return _settings_view(settings)


@router.post("/ai/analyze-lyrics", response_model=schemas.AnalyzeLyricsResponse)
def analyze_lyrics(payload: schemas.AnalyzeLyricsRequest) -> schemas.AnalyzeLyricsResponse:
    lines = [line.model_dump() for line in payload.lines]
    try:
        result = service.analyze_lyrics(
            lines,
            bpm=payload.bpm,
            style=payload.style,
            provider=payload.provider,
        )
    except Exception as exc:  # pragma: no cover - service already degrades gracefully
        raise HTTPException(status_code=500, detail=f"歌词分析失败：{base.scrub(str(exc))}") from exc
    return schemas.AnalyzeLyricsResponse(**result)


@router.post("/ai/decide-layers", response_model=schemas.DecideLayersResponse)
def decide_layers(payload: schemas.DecideLayersRequest) -> schemas.DecideLayersResponse:
    candidates = payload.candidates.model_dump()
    try:
        result = service.decide_layers(payload.state, candidates)
    except Exception as exc:  # pragma: no cover - service already degrades gracefully
        raise HTTPException(status_code=500, detail=f"图层决策失败：{base.scrub(str(exc))}") from exc
    return schemas.DecideLayersResponse(**result)
