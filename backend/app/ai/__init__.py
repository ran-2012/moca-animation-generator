"""AI providers (DeepSeek / Jev) and rule-based fallbacks."""

from __future__ import annotations

from .base import AIError
from .service import (
    ANALYZE_PROVIDERS,
    analyze_lyrics,
    available_analyze_providers,
    decide_layers,
    get_analyze_provider,
)

__all__ = [
    "AIError",
    "ANALYZE_PROVIDERS",
    "analyze_lyrics",
    "available_analyze_providers",
    "decide_layers",
    "get_analyze_provider",
]
