"""Tests for the AI domain (task-8).

pytest-compatible and also runnable without pytest in this sandbox:

    python -m pytest tests/test_ai.py -q      # normal (CI) way
    python tests/test_ai.py                   # fallback when pytest is absent

No test performs real network I/O: the DeepSeek/Jev transport
(``app.ai.base.post_json``) is always monkeypatched for provider paths, and
no-key paths never reach the transport at all.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# The platform temp directory is sandbox-protected on this machine (and
# tempfile.mkdtemp dirs deny child creation), so scratch dirs are created
# manually under the runtime data/tmp folder and removed afterwards.
TEST_TMP_ROOT = BACKEND_DIR.parent / "data" / "tmp" / "ai-tests"
_case_counter = itertools.count()

from fastapi import HTTPException  # noqa: E402

from app import config, storage  # noqa: E402
from app.ai import base, cache, jev, rule, service  # noqa: E402
from app.models import ai as schemas  # noqa: E402
from app.routers import ai as ai_router  # noqa: E402

SAMPLE_LINES = [
    {"text": "夜风轻轻吹过窗边…", "start": 0.0, "end": 4.2},
    {"text": "我还在等你的回答？", "start": 4.2, "end": 8.4},
    {"text": "笑一个吧！", "start": 8.4, "end": 11.0},
    {"text": "笑着哭出来！", "start": 11.0, "end": 14.0},
]

DEEPSEEK_KEY = "sk-test-deepseek-secret-0001"
OPENROUTER_KEY = "sk-or-test-openrouter-secret-0002"


# ---------------------------------------------------------------------------
# Helpers (no pytest fixtures, so the file also runs standalone)
# ---------------------------------------------------------------------------


@contextmanager
def temp_env():
    """Relocate data/ (settings + cache) into a throwaway workspace directory."""
    names = ("DATA_DIR", "ASSETS_DIR", "PROJECTS_DIR", "SETTINGS_FILE")
    previous = {name: getattr(config, name) for name in names}
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = TEST_TMP_ROOT / f"case-{os.getpid()}-{next(_case_counter)}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        config.DATA_DIR = tmp
        config.ASSETS_DIR = tmp / "assets"
        config.PROJECTS_DIR = tmp / "projects"
        config.SETTINGS_FILE = tmp / "settings.json"
        config.ensure_dirs()
        yield tmp
    finally:
        for name, value in previous.items():
            setattr(config, name, value)
        shutil.rmtree(tmp, ignore_errors=True)


class _Patcher:
    def __init__(self, target, name, value):
        self.target = target
        self.name = name
        self.value = value
        self.previous = None

    def __enter__(self):
        self.previous = getattr(self.target, self.name)
        setattr(self.target, self.name, self.value)
        return self.value

    def __exit__(self, exc_type, exc, tb):
        setattr(self.target, self.name, self.previous)
        return False


def patch(target, name, value):
    return _Patcher(target, name, value)


class FakeTransport:
    """Records calls and returns queued payloads (or raises queued errors)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, payload, headers=None, timeout=30.0, label="AI 服务"):
        self.calls.append(
            {"url": url, "payload": payload, "headers": headers or {}, "timeout": timeout, "label": label}
        )
        if not self.responses:
            raise AssertionError("unexpected provider call")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def assert_never_called(self):
        assert not self.calls, f"provider was called unexpectedly: {self.calls}"


def deepseek_response(segments):
    content = json.dumps({"segments": segments}, ensure_ascii=False)
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


VALID_SEGMENTS = [
    {
        "start": 0.0,
        "end": 4.2,
        "mood": "calm",
        "intensity": 0.35,
        "effects": [{"type": "breath", "params": {"rate": 0.3}}, {"type": "eye_style", "params": {"style": "soft"}}],
    },
    {
        "start": 4.2,
        "end": 14.0,
        "mood": "bright",
        "intensity": 0.62,
        "effects": [{"type": "beat_bounce", "params": {"amplitude": 0.45}}, {"type": "blush", "params": {}}],
    },
]


def save_settings(*, deepseek_key=None, openrouter_key=None):
    settings = {
        "deepseek": {
            "baseUrl": "https://api.deepseek.com",
            "model": "deepseek-chat",
        },
        "openrouter": {"model": "typesafe/jev-1.13"},
    }
    if deepseek_key:
        settings["deepseek"]["apiKey"] = deepseek_key
    if openrouter_key:
        settings["openrouter"]["apiKey"] = openrouter_key
    storage.save_settings(settings)


def assert_effect_schema(effects):
    assert isinstance(effects, list) and effects
    for effect in effects:
        assert effect["type"] in base.EFFECT_TYPES, effect
        params = effect["params"]
        assert isinstance(params, dict)
        # Every default parameter is present (renderer can rely on defaults).
        for key, value in base.EFFECT_DEFAULTS[effect["type"]].items():
            assert key in params, f"{effect['type']} missing default param {key}"
            assert isinstance(params[key], (int, float, str, bool)), params[key]


def assert_segment_schema(segments):
    assert isinstance(segments, list)
    previous_start = float("-inf")
    for segment in segments:
        assert segment["mood"] in base.MOODS
        assert isinstance(segment["start"], (int, float))
        assert isinstance(segment["end"], (int, float))
        assert segment["end"] > segment["start"]
        assert segment["start"] >= previous_start
        assert 0.0 <= segment["intensity"] <= 1.0
        assert_effect_schema(segment["effects"])
        previous_start = segment["start"]


# ---------------------------------------------------------------------------
# Settings: defaults, masking, persistence, clearing
# ---------------------------------------------------------------------------


def test_settings_defaults_without_file():
    with temp_env():
        view = ai_router.get_settings().model_dump()
        assert view["deepseek"]["baseUrl"] == "https://api.deepseek.com"
        assert view["deepseek"]["model"] == "deepseek-chat"
        assert view["deepseek"]["hasKey"] is False
        assert view["openrouter"]["model"] == "typesafe/jev-1.13"
        assert view["openrouter"]["hasKey"] is False


def test_put_settings_persists_but_masks_key():
    with temp_env() as root:
        payload = schemas.SettingsUpdate(
            deepseek={
                "baseUrl": "https://api.deepseek.com",
                "model": "deepseek-chat",
                "apiKey": DEEPSEEK_KEY,
            },
            openrouter={"model": "typesafe/jev-1.13", "apiKey": OPENROUTER_KEY},
        )
        view = ai_router.put_settings(payload).model_dump()
        serialised = json.dumps(view, ensure_ascii=False)
        assert DEEPSEEK_KEY not in serialised and OPENROUTER_KEY not in serialised
        assert view["deepseek"]["hasKey"] is True
        assert view["openrouter"]["hasKey"] is True
        assert "apiKey" not in view["deepseek"] and "apiKey" not in view["openrouter"]

        stored = json.loads((root / "settings.json").read_text(encoding="utf-8"))
        assert stored["deepseek"]["apiKey"] == DEEPSEEK_KEY
        assert stored["openrouter"]["apiKey"] == OPENROUTER_KEY

        reloaded = ai_router.get_settings().model_dump()
        assert reloaded["deepseek"]["hasKey"] is True
        assert DEEPSEEK_KEY not in json.dumps(reloaded, ensure_ascii=False)


def test_put_settings_empty_string_clears_key():
    with temp_env():
        ai_router.put_settings(schemas.SettingsUpdate(deepseek={"apiKey": DEEPSEEK_KEY}))
        assert ai_router.get_settings().deepseek.hasKey is True
        ai_router.put_settings(schemas.SettingsUpdate(deepseek={"apiKey": ""}))
        view = ai_router.get_settings().model_dump()
        assert view["deepseek"]["hasKey"] is False
        stored = storage.load_settings()
        assert "apiKey" not in stored.get("deepseek", {})


def test_put_settings_rejects_bad_base_url():
    with temp_env():
        try:
            ai_router.put_settings(schemas.SettingsUpdate(deepseek={"baseUrl": "ftp://example.com"}))
        except HTTPException as exc:
            assert exc.status_code == 400
        else:  # pragma: no cover - should never happen
            raise AssertionError("expected HTTPException for invalid baseUrl")


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------


def test_rule_analyse_segments_schema():
    segments = rule.analyse_segments(SAMPLE_LINES, bpm=128.0, style="j-pop")
    assert segments, "rule engine must always produce at least one segment"
    assert_segment_schema(segments)
    assert {segment["mood"] for segment in segments} <= set(base.MOODS)
    assert segments[0]["start"] >= 0.0
    assert segments[-1]["end"] <= 14.0 + 1e-6


def test_rule_analyse_synthesises_timeline_without_timing():
    lines = [{"text": "燃起来！冲！"}, {"text": "笑一个吧！"}, {"text": "夜风轻轻吹过窗边…"}]
    segments = rule.analyse_segments(lines)
    assert len(segments) == 3
    assert segments[0]["start"] == 0.0
    assert segments[1]["start"] > segments[0]["start"]
    assert_segment_schema(segments)


def test_rule_keeps_explicit_timing_for_single_line():
    segments = rule.analyse_segments([{"text": "夜风轻轻吹过窗边…", "start": 0.0, "end": 4.2}])
    assert len(segments) == 1
    assert segments[0]["start"] == 0.0
    assert segments[0]["end"] == 4.2


def test_rule_mood_detection_examples():
    assert rule.classify_mood("燃起来！冲！")[0] == "intense"
    assert rule.classify_mood("笑着哭出来")[0] in ("sad", "bright")  # mixed line, either is defensible
    assert rule.classify_mood("夜风轻轻吹过窗边…")[0] in ("calm", "neutral")


def test_rule_decide_layers_is_deterministic_zero_confidence():
    candidates = {
        "eyes": ["open", "smile", "blink"],
        "brow": ["neutral", "angry", "sad"],
        "mouth": ["n", "a", "closed"],
    }
    state = {"mood": "bright", "intensity": 0.7}
    result = rule.decide_layers(state, candidates)
    for channel, choice in result["choices"].items():
        assert choice in candidates[channel]
    assert set(result["choices"]) == {"eyes", "brow", "mouth"}
    for value in result["confidence"].values():
        assert value == 0.0
    assert result["raw"]["provider"] == "rule"

    # Same input -> same output (deterministic fallback).
    assert rule.decide_layers(state, candidates) == result


def test_rule_decide_respects_explicit_state_hint():
    candidates = {"eyes": ["open", "smile", "blink"]}
    result = rule.decide_layers({"eyes": "blink"}, candidates)
    assert result["choices"]["eyes"] == "blink"


# ---------------------------------------------------------------------------
# analyze-lyrics: fallback, provider path, retries, caching
# ---------------------------------------------------------------------------


def test_analyze_without_key_uses_rule():
    with temp_env():
        fake = FakeTransport([])
        with patch(base, "post_json", fake):
            result = service.analyze_lyrics(SAMPLE_LINES, bpm=100.0)
        fake.assert_never_called()
        assert result["provider"] == "rule"
        assert result["cached"] is False
        assert result["warnings"], "missing key must be reported as a warning"
        assert "DeepSeek" in result["warnings"][0]
        assert_segment_schema(result["segments"])


def test_analyze_explicit_rule_skips_provider_even_with_key():
    with temp_env():
        save_settings(deepseek_key=DEEPSEEK_KEY)
        fake = FakeTransport([])
        with patch(base, "post_json", fake):
            result = service.analyze_lyrics(SAMPLE_LINES, bpm=120.0, provider="rule")
        fake.assert_never_called()
        assert result["provider"] == "rule"
        assert result["warnings"] == []


def test_analyze_empty_lines_returns_empty_segments():
    with temp_env():
        result = service.analyze_lyrics([], bpm=None)
        assert result["segments"] == []
        assert result["provider"] == "rule"
        assert result["warnings"]


def test_analyze_uses_deepseek_and_caches_result():
    with temp_env() as root:
        save_settings(deepseek_key=DEEPSEEK_KEY)
        fake = FakeTransport([deepseek_response(VALID_SEGMENTS)])
        with patch(base, "post_json", fake):
            first = service.analyze_lyrics(SAMPLE_LINES, bpm=128.0, style="j-pop")
            second = service.analyze_lyrics(SAMPLE_LINES, bpm=128.0, style="j-pop")

        assert first["provider"] == "deepseek"
        assert first["cached"] is False
        assert first["warnings"] == []
        assert_segment_schema(first["segments"])

        assert second["provider"] == "deepseek"
        assert second["cached"] is True
        assert second["segments"] == first["segments"]
        assert len(fake.calls) == 1, "cached call must not hit the provider"

        call = fake.calls[0]
        assert call["url"] == "https://api.deepseek.com/chat/completions"
        assert call["headers"]["Authorization"] == f"Bearer {DEEPSEEK_KEY}"
        assert call["payload"]["model"] == "deepseek-chat"
        assert call["payload"]["response_format"] == {"type": "json_object"}
        assert call["timeout"] == base.DEEPSEEK_TIMEOUT
        assert call["payload"]["messages"][0]["role"] == "system"

        cache_files = list((root / "cache" / "ai").glob("*.json"))
        assert len(cache_files) == 1


def test_analyze_cache_key_depends_on_bpm_and_model():
    lines = [{"text": "hello", "start": 0.0, "end": 1.0}]
    key_a = cache.cache_key(lines, 120.0, "deepseek-chat")
    key_b = cache.cache_key(lines, 90.0, "deepseek-chat")
    key_c = cache.cache_key(lines, 120.0, "another-model")
    assert len({key_a, key_b, key_c}) == 3


def test_analyze_retries_once_then_falls_back_to_rule():
    with temp_env():
        save_settings(deepseek_key=DEEPSEEK_KEY)
        bad = {"choices": [{"message": {"content": "这不是 JSON"}}]}
        fake = FakeTransport([bad, bad])
        with patch(base, "post_json", fake):
            result = service.analyze_lyrics(SAMPLE_LINES, bpm=100.0)
        assert len(fake.calls) == 2, "DeepSeek parse failure must be retried exactly once"
        assert result["provider"] == "rule"
        assert result["warnings"]
        assert "DeepSeek" in result["warnings"][0]
        assert_segment_schema(result["segments"])


def test_analyze_retry_recovers_after_one_bad_response():
    with temp_env():
        save_settings(deepseek_key=DEEPSEEK_KEY)
        bad = {"choices": [{"message": {"content": "```json\n{bad\n```"}}]}
        fake = FakeTransport([bad, deepseek_response(VALID_SEGMENTS)])
        with patch(base, "post_json", fake):
            result = service.analyze_lyrics(SAMPLE_LINES, bpm=100.0)
        assert len(fake.calls) == 2
        assert result["provider"] == "deepseek"
        assert result["cached"] is False


def test_analyze_provider_http_error_falls_back_with_readable_warning():
    with temp_env():
        save_settings(deepseek_key=DEEPSEEK_KEY)
        fake = FakeTransport([base.AIError("DeepSeek 返回 HTTP 401：invalid api key")] * 2)
        with patch(base, "post_json", fake):
            result = service.analyze_lyrics(SAMPLE_LINES, bpm=100.0)
        assert len(fake.calls) == 1, "transport errors must degrade immediately (no retry)"
        assert result["provider"] == "rule"
        assert "HTTP 401" in result["warnings"][0]


def test_analyze_rejects_unknown_mood_from_provider():
    with temp_env():
        save_settings(deepseek_key=DEEPSEEK_KEY)
        payload = deepseek_response(
            [{"start": 0.0, "end": 1.0, "mood": "euphoric", "intensity": 0.4, "effects": []}]
        )
        fake = FakeTransport([payload, payload])
        with patch(base, "post_json", fake):
            result = service.analyze_lyrics(SAMPLE_LINES, bpm=100.0)
        assert result["provider"] == "rule"
        assert "mood" in result["warnings"][0]


# ---------------------------------------------------------------------------
# decide-layers: fallback, Jev request shape, validation
# ---------------------------------------------------------------------------

CANDIDATES = {
    "eyes": ["open", "smile", "blink"],
    "brow": ["neutral", "angry", "sad"],
    "mouth": ["n", "a", "closed"],
}

JEV_ANSWERS = {
    "answers": {
        "eyes": {"choice": "smile", "confidence": 0.82},
        "brow": {"choice": "neutral", "confidence": 0.55},
        "mouth": {"choice": "a", "probabilities": {"n": 0.1, "a": 0.7, "closed": 0.2}},
    }
}


def test_decide_without_key_uses_rule():
    with temp_env():
        fake = FakeTransport([])
        with patch(base, "post_json", fake):
            result = service.decide_layers({"mood": "bright"}, CANDIDATES)
        fake.assert_never_called()
        assert result["provider"] == "rule"
        assert result["warnings"]
        assert set(result["choices"]) == {"eyes", "brow", "mouth"}
        assert all(choice in CANDIDATES[channel] for channel, choice in result["choices"].items())
        assert all(value == 0.0 for value in result["confidence"].values())


def test_decide_uses_jev_and_validates_answers():
    with temp_env():
        save_settings(openrouter_key=OPENROUTER_KEY)
        fake = FakeTransport([JEV_ANSWERS])
        with patch(base, "post_json", fake):
            result = service.decide_layers({"mood": "bright", "intensity": 0.7}, CANDIDATES)

        assert result["provider"] == "jev"
        assert result["warnings"] == []
        assert result["choices"] == {"eyes": "smile", "brow": "neutral", "mouth": "a"}
        assert result["confidence"]["eyes"] == 0.82
        assert result["confidence"]["brow"] == 0.55
        assert result["confidence"]["mouth"] == 0.7  # derived from probabilities
        assert result["raw"] == JEV_ANSWERS

        call = fake.calls[0]
        assert call["url"] == "https://openrouter.ai/api/v1/systemone"
        assert call["headers"]["Authorization"] == f"Bearer {OPENROUTER_KEY}"
        assert call["timeout"] == base.JEV_TIMEOUT
        payload = call["payload"]
        assert payload["model"] == "typesafe/jev-1.13"
        assert payload["state"] == {"mood": "bright", "intensity": 0.7}
        questions = {question["name"]: question for question in payload["questions"]}
        assert set(questions) == {"eyes", "brow", "mouth"}
        for channel in ("eyes", "brow", "mouth"):
            assert questions[channel]["type"] == "choice"
            assert set(questions[channel]["criteria"]) == set(CANDIDATES[channel])


def test_decide_rejects_choice_outside_candidates_then_falls_back():
    with temp_env():
        save_settings(openrouter_key=OPENROUTER_KEY)
        bad = {"answers": {"eyes": {"choice": "laser-beam", "confidence": 0.9}}}
        fake = FakeTransport([bad])
        with patch(base, "post_json", fake):
            result = service.decide_layers({"mood": "calm"}, CANDIDATES)
        assert result["provider"] == "rule"
        assert "Jev" in result["warnings"][0]
        assert result["choices"]["eyes"] in CANDIDATES["eyes"]


def test_decide_jev_http_error_falls_back_to_rule():
    with temp_env():
        save_settings(openrouter_key=OPENROUTER_KEY)
        fake = FakeTransport([base.AIError("Jev 请求超时（10s）")])
        with patch(base, "post_json", fake):
            result = service.decide_layers({"mood": "sad"}, CANDIDATES)
        assert result["provider"] == "rule"
        assert "10s" in result["warnings"][0]


def test_decide_empty_candidates_returns_empty_choices():
    with temp_env():
        result = service.decide_layers({"mood": "neutral"}, {})
        assert result["choices"] == {}
        assert result["provider"] == "rule"
        assert result["warnings"]


def test_jev_request_example_is_json_documentable():
    body = jev.build_request(
        {"mood": "bright"},
        {"eyes": ["open", "smile"], "brow": ["neutral"], "mouth": ["n", "a"]},
        {"model": "typesafe/jev-1.13"},
    )
    assert body["model"] == "typesafe/jev-1.13"
    assert [question["name"] for question in body["questions"]] == ["eyes", "brow", "mouth"]
    assert set(body["questions"][0]["criteria"]) == {"open", "smile"}


# ---------------------------------------------------------------------------
# Router endpoints (called directly: no FastAPI TestClient needed)
# ---------------------------------------------------------------------------


def test_router_analyze_without_key_returns_rule_payload():
    with temp_env():
        payload = schemas.AnalyzeLyricsRequest(
            lines=[schemas.LyricLine(**line) for line in SAMPLE_LINES],
            bpm=96.0,
            style="acoustic",
        )
        response = ai_router.analyze_lyrics(payload).model_dump()
        assert response["provider"] == "rule"
        assert response["cached"] is False
        assert response["warnings"]
        assert_segment_schema([segment for segment in response["segments"]])


def test_router_decide_without_key_returns_rule_payload():
    with temp_env():
        payload = schemas.DecideLayersRequest(
            state={"mood": "bright"},
            candidates=schemas.Candidates(**CANDIDATES),
        )
        response = ai_router.decide_layers(payload).model_dump()
        assert response["provider"] == "rule"
        assert set(response["choices"]) == {"eyes", "brow", "mouth"}
        assert all(value == 0.0 for value in response["confidence"].values())


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


def test_scrub_removes_keys_from_error_text():
    text = "Authorization: Bearer sk-abcdef123456 failed; apiKey=sk-or-secret999"
    scrubbed = base.scrub(text)
    assert "sk-abcdef123456" not in scrubbed
    assert "sk-or-secret999" not in scrubbed
    assert "***" in scrubbed


def test_describe_candidate_short_tokens():
    # "n" is a viseme and must not match inside words like "neutral".
    assert "闭" in base.describe_candidate("n")
    neutral = base.describe_candidate("neutral")
    assert "闭合" not in neutral
    assert "常态" in neutral


def test_settings_never_expose_key_through_router():
    with temp_env():
        ai_router.put_settings(
            schemas.SettingsUpdate(deepseek={"apiKey": DEEPSEEK_KEY}, openrouter={"apiKey": OPENROUTER_KEY})
        )
        for view in (ai_router.get_settings(), ai_router.put_settings(schemas.SettingsUpdate())):
            dumped = json.dumps(view.model_dump(), ensure_ascii=False)
            assert DEEPSEEK_KEY not in dumped
            assert OPENROUTER_KEY not in dumped


# ---------------------------------------------------------------------------
# Standalone runner (pytest is unavailable in this sandbox)
# ---------------------------------------------------------------------------


def _run_standalone() -> int:
    tests = [
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    for name, test in tests:
        try:
            test()
        except Exception:
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()
        else:
            print(f"ok   {name}")
    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
