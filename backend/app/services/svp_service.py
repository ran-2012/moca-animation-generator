"""SVP (Synthesizer V Studio) parsing and single-track viseme timeline.

The parsing / lyric-to-viseme rules are ported from the previous round's
``_work/svp/svp_probe.py`` + ``_work/svp/lyric2viseme.py`` + ``_work/svp/svp2viseme.py``
so the backend has no runtime dependency on the scratch folder.

Design rules (kept from the verified prototype, CONTRACT.md §4.4):

* absolute tick = ``note.onset + groupRef.blickOffset``; tick / 705600000 = quarter
  note, tempo map from ``project["time"]["tempo"]`` (+ ``startTimeSeconds``).
* **one track only** -- the caller passes ``trackIndex``; tracks are never merged
  and no primary/harmony priority is applied here.
* frame i covers ``[i/fps, (i+1)/fps)`` and samples the viseme at ``i/fps``.
* ``'-'`` sustain inherits the previous non-sustain viseme of the same track.
* onset consonant (bilabial closure / f) is held for 2 frames, optionally one
  frame before the onset; a nasal coda is only used at phrase ends.
* gaps shorter than 80 ms are bridged to avoid single-frame flicker.

Generated JSON is cached at ``data/assets/svp/<assetId>/timeline-track{i}-{fps}.json``.
"""

from __future__ import annotations

import bisect
import json
import math
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .. import config, storage

TICKS_PER_QUARTER = 705_600_000

VISEMES = ["closed", "n", "f", "a", "i", "u", "e", "o"]
VISEME_OPENNESS = {
    "closed": 0.0, "n": 0.18, "f": 0.22, "u": 0.38, "o": 0.55,
    "e": 0.62, "i": 0.52, "a": 0.95,
}

ANIMATION_MODES = {"classic", "clear", "natural", "expressive"}
MODE_VERSION = 4

# timeline shaping (same defaults as the verified prototype)
TAIL_SEC = 0.5
CONSONANT_FRAMES = 2
PRE_CONSONANT_FRAMES = 1
CODA_FRAMES = 2
GAP_HOLD_SEC = 0.08
MIN_NOTE_FRAMES = 2
PHRASE_GAP_SEC = 0.35

MAX_CACHE_ENTRIES = 8
_PROJECT_CACHE: dict[tuple[str, int, int], "ProjectData"] = {}


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------
class TempoMap:
    """Piecewise-constant tempo map: absolute tick -> seconds."""

    def __init__(self, time_obj: dict):
        self.start_time = float(time_obj.get("startTimeSeconds") or 0.0)
        raw_points = time_obj.get("tempo") or [{"position": 0, "bpm": 60.0}]
        points: list[tuple[int, float]] = []
        for point in raw_points:
            try:
                position = int(point.get("position") or 0)
                bpm = float(point.get("bpm") or 120.0)
            except (TypeError, ValueError, AttributeError):
                continue
            if bpm > 0:
                points.append((position, bpm))
        points.sort(key=lambda item: item[0])
        if not points:
            points = [(0, 60.0)]
        if points[0][0] != 0:
            points.insert(0, (0, points[0][1]))
        cleaned: list[tuple[int, float]] = []
        for position, bpm in points:
            if cleaned and cleaned[-1][0] == position:
                cleaned[-1] = (position, bpm)
            else:
                cleaned.append((position, bpm))
        self.points = cleaned
        self._positions = [position for position, _ in cleaned]
        self._cum = [0.0] * len(cleaned)
        for index in range(1, len(cleaned)):
            prev_pos, prev_bpm = cleaned[index - 1]
            cur_pos = cleaned[index][0]
            beats = (cur_pos - prev_pos) / TICKS_PER_QUARTER
            self._cum[index] = self._cum[index - 1] + beats * 60.0 / prev_bpm

    @property
    def bpm0(self) -> float:
        return self.points[0][1]

    def sec_at_tick(self, tick: float) -> float:
        index = max(0, bisect.bisect_right(self._positions, tick) - 1)
        position, bpm = self.points[index]
        beats = (tick - position) / TICKS_PER_QUARTER
        return self.start_time + self._cum[index] + beats * 60.0 / bpm

    def to_dict(self) -> dict:
        return {
            "startTimeSeconds": round(self.start_time, 6),
            "points": [{"positionTick": position, "bpm": bpm} for position, bpm in self.points],
        }


# ---------------------------------------------------------------------------
# Lyrics -> phonemes -> viseme (ported from lyric2viseme.py)
# ---------------------------------------------------------------------------
PINYIN_INITIALS = [
    "zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h",
    "j", "q", "x", "r", "z", "c", "s", "y", "w",
]

PINYIN_FINALS = {
    "a": ("a", None), "o": ("o", None), "e": ("e", None), "er": ("e", None),
    "ai": ("a", None), "ei": ("e", None), "ao": ("a", None), "ou": ("o", None),
    "an": ("a", "n"), "en": ("e", "n"), "ang": ("a", "n"), "eng": ("e", "n"),
    "i": ("i", None), "ia": ("a", None), "ie": ("e", None), "iao": ("a", None),
    "iu": ("o", None), "iou": ("o", None), "ian": ("e", "n"), "in": ("i", "n"),
    "iang": ("a", "n"), "ing": ("i", "n"), "iong": ("u", "n"),
    "u": ("u", None), "ua": ("a", None), "uo": ("o", None), "uai": ("a", None),
    "ui": ("e", None), "uei": ("e", None), "uan": ("a", "n"), "un": ("u", "n"),
    "uen": ("u", "n"), "uang": ("a", "n"), "ueng": ("e", "n"), "ong": ("u", "n"),
    "v": ("u", None), "ve": ("e", None), "van": ("e", "n"), "vn": ("u", "n"),
    "ü": ("u", None), "üe": ("e", None), "üan": ("e", "n"), "ün": ("u", "n"),
    "m": ("closed", None), "n": ("n", None), "ng": ("n", None), "ê": ("e", None),
}

PINYIN_INITIAL_VISEME = {"b": "closed", "p": "closed", "m": "closed", "f": "f"}
_Y_FINAL_FIX = {"an": "ian", "uan": "van", "u": "v", "un": "vn", "ue": "ve"}

XS_VOWEL = {
    "a": "a", "A": "a", "o": "o", "@": "e", "e": "e", "7": "e",
    "U": "u", "u": "u", "i": "i", "i\\": "i", "i`": "i", "y": "u",
}
XS_DIPHTHONG = {
    "AU": "a", "@U": "o", "ia": "a", "iA": "a", "iAU": "a",
    "ie": "e", "iE": "e", "iU": "o", "i@U": "o",
    "y{": "e", "yE": "e", "ua": "a", "uA": "a", "u@": "e",
    "ue": "e", "uo": "o",
}
XS_NASAL_CODA = {":n": "n", "N": "n"}
XS_APICAL_VOWEL = {":\\i": "i", "r`": "e"}
XS_STOPS = {"p", "ph", "t", "th", "k", "kh"}
XS_AFFRICATES = {"ts\\", "ts", "tsh", "ts`", "ts`h"}
XS_FRICATIVES = {"f", "s", "s`", "ts\\h", "s\\", "x"}
XS_NASALS = {"m", "n"}
XS_LIQUIDS = {"l"}
XS_SEMIVOWELS = {"z`", "w", "j"}
XS_SILENCE = {"pau", "sil"}
XS_BREATH = {"br"}
XS_CLOSURE = {"cl"}
XS_BILABIAL_CLOSURE = {"p", "ph", "m"}

_XS_SYMBOLS = sorted(
    set(XS_VOWEL) | set(XS_DIPHTHONG) | set(XS_NASAL_CODA) | set(XS_APICAL_VOWEL)
    | XS_STOPS | XS_AFFRICATES | XS_FRICATIVES | XS_NASALS | XS_LIQUIDS
    | XS_SEMIVOWELS | XS_SILENCE | XS_BREATH | XS_CLOSURE,
    key=len,
    reverse=True,
)

_EN_WORD_HINTS = {
    "yeah": ("e", None), "yes": ("e", None), "oh": ("o", None), "ooh": ("u", None),
    "ah": ("a", None), "aah": ("a", None), "hey": ("e", None), "baby": ("e", None),
    "hi": ("i", None), "hello": ("e", None), "la": ("a", None), "na": ("a", None),
    "wow": ("a", None), "mmm": ("closed", None), "hmm": ("closed", None),
}
_EN_VOWEL_LETTER = {"a": "a", "e": "e", "i": "i", "o": "o", "u": "u", "y": "i"}
_EN_DIGRAPHS = {
    "ea": "e", "ee": "i", "oo": "u", "ou": "o", "ow": "o", "oa": "o", "ai": "e",
    "ay": "e", "ey": "e", "oi": "o", "oy": "o", "au": "a", "aw": "a", "ie": "i",
    "ei": "e", "ue": "u", "ui": "u",
}

SUSTAIN_TOKENS = {"-", "—", "–", "～", "~", "ー"}
BREATH_TOKENS = {"br", "breath", "sil", "pau"}
PUNCT_CHARS = set("，。！？、,.!?;；:：…·—~～\"'“”‘’()（）[]【】 \t")
_APOSTROPHE_RE = re.compile(r"^['’‘`´]")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002a6df]")
_KANA_RE = re.compile(r"[\u3041-\u309f\u30a1-\u30ff]")
_SILENT_CHARS = set("，。！？、,.!?;；:：…·—~～\"'“”‘’()（）[]【】")

_KANA_ROMAJI = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo", "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho", "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho", "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo", "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo", "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo", "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo",
    "てぃ": "ti", "でぃ": "di", "とぅ": "tu", "どぅ": "du", "うぃ": "wi", "うぇ": "we", "うぉ": "wo",
    "ゔぁ": "va", "ゔぃ": "vi", "ゔ": "vu", "ゔぇ": "ve", "ゔぉ": "vo",
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo", "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "wi", "ゑ": "we", "を": "o", "ん": "n", "っ": "cl",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
}

# 小书假名把前一个音节的元音替换掉（ちぇ / ふゅ / つぁ），而不是新增一个音节。
_SMALL_VOWELS = {"ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o"}
# 单独出现的鼻音歌词（Synthesizer V 会把「ん」写成 n，也有 hm / hng）。
_STANDALONE_NASALS = {"n", "m", "ng", "hm", "hng"}
# 日语长音：第二个元音延长前一个口型，而不是换一个嘴形（おう -> oː / えい -> eː）。
_LONG_VOWEL_PAIRS = {
    ("a", "a"), ("i", "i"), ("u", "u"), ("e", "e"), ("o", "o"), ("o", "u"), ("e", "i"),
}
_LONG_VOWEL_CHARS = {"ー", "ｰ"}

# Small baked table for the characters used by the bundled projects.  When
# pypinyin is available it is preferred (see _load_pypinyin); the table keeps
# the common case working offline.
_FALLBACK_PINYIN = {
    "一": "yi", "下": "xia", "不": "bu", "並": "bing", "主": "zhu", "也": "ye",
    "以": "yi", "你": "ni", "像": "xiang", "全": "quan", "其": "qi", "再": "zai",
    "去": "qu", "又": "you", "吧": "ba", "回": "hui", "好": "hao", "它": "ta",
    "害": "hai", "實": "shi", "己": "ji", "已": "yi", "幸": "xing", "心": "xin",
    "怕": "pa", "恍": "huang", "情": "qing", "惚": "hu", "想": "xiang", "愛": "ai",
    "我": "wo", "扎": "zha", "掙": "zheng", "掛": "gua", "放": "fang", "早": "zao",
    "是": "shi", "會": "hui", "有": "you", "样": "yang", "楚": "chu", "沙": "sha",
    "流": "liu", "清": "qing", "為": "wei", "爱": "ai", "牽": "qian", "由": "you",
    "的": "de", "看": "kan", "真": "zhen", "眼": "yan", "福": "fu", "而": "er",
    "自": "zi", "著": "zhe", "裡": "li", "讓": "rang", "走": "zou", "路": "lu",
    "这": "zhe", "過": "guo", "還": "hai", "都": "dou", "隨": "sui", "頭": "tou",
    "願": "yuan", "騙": "pian",
}


def _load_pypinyin():
    """Best-effort pypinyin import (system package, then vendored copies)."""
    candidates = [
        config.BACKEND_DIR.parent / "_work" / "svp" / "_vendor",
        config.BACKEND_DIR.parents[1] / "_work" / "svp" / "_vendor",
    ]
    for vendor in candidates:
        try:
            if vendor.is_dir() and str(vendor) not in sys.path:
                sys.path.append(str(vendor))
        except OSError:
            continue
    try:  # pragma: no cover - depends on the machine
        from pypinyin import lazy_pinyin  # type: ignore

        return lazy_pinyin, "pypinyin"
    except Exception:
        return None, "fallback-table"


_LAZY_PINYIN, _PINYIN_SOURCE = _load_pypinyin()


def _normalize_pinyin(value: str) -> str:
    value = value.strip().lower().replace("ü", "v").replace("ê", "e")
    value = re.sub(r"[1-5]", "", value)
    return re.sub(r"[^a-z]", "", value)


def _split_pinyin_syllable(syllable: str) -> tuple[str, str]:
    normalized = _normalize_pinyin(syllable)
    if not normalized:
        return "", ""
    for initial in PINYIN_INITIALS:
        if normalized.startswith(initial):
            return initial, normalized[len(initial):]
    return "", normalized


def _unmapped_plan(raw: str, why: str) -> dict:
    return {
        "method": "unmapped", "raw": raw, "normalized": raw, "initial": "", "final": "",
        "phones": [], "onset_viseme": None, "main_viseme": None, "coda_viseme": None,
        "confidence": "none", "why": why,
    }


def _plan_pinyin_syllable(syllable: str) -> dict:
    normalized = _normalize_pinyin(syllable)
    if not normalized:
        return _unmapped_plan(syllable, "empty pinyin")
    if normalized in _STANDALONE_NASALS:
        return {
            "method": "pinyin", "raw": syllable, "normalized": normalized,
            "initial": "", "final": normalized,
            "phones": [{"sym": normalized, "kind": "coda", "viseme": "n"}],
            "onset_viseme": None, "main_viseme": "n", "coda_viseme": "n",
            "confidence": "rule",
        }
    initial, final = _split_pinyin_syllable(normalized)
    if initial == "y" and final in _Y_FINAL_FIX:
        final = _Y_FINAL_FIX[final]
    if final in PINYIN_FINALS:
        main, coda = PINYIN_FINALS[final]
        onset = PINYIN_INITIAL_VISEME.get(initial)
        if final == "i" and initial in ("zh", "ch", "sh", "r", "z", "c", "s"):
            main = "i"
        phones = []
        if initial:
            phones.append({"sym": initial, "kind": "initial", "viseme": onset})
        phones.append({"sym": final, "kind": "final", "viseme": main})
        if coda:
            phones.append({"sym": "n", "kind": "coda", "viseme": coda})
        return {
            "method": "pinyin", "raw": syllable, "normalized": normalized,
            "initial": initial, "final": final, "phones": phones,
            "onset_viseme": onset, "main_viseme": main, "coda_viseme": coda,
            "confidence": "rule",
        }
    for char in final:
        if char in "aiueo":
            vowel = "u" if char == "u" else char
            return {
                "method": "pinyin_heuristic", "raw": syllable, "normalized": normalized,
                "initial": initial, "final": final,
                "phones": [{"sym": final, "kind": "final", "viseme": vowel}],
                "onset_viseme": PINYIN_INITIAL_VISEME.get(initial),
                "main_viseme": vowel,
                "coda_viseme": "n" if final.endswith(("n", "ng")) else None,
                "confidence": "heuristic",
            }
    return _unmapped_plan(syllable, "no vowel in pinyin final %r" % final)


def _classify_xs(symbol: str) -> dict:
    if symbol in XS_VOWEL:
        return {"sym": symbol, "kind": "vowel", "viseme": XS_VOWEL[symbol]}
    if symbol in XS_DIPHTHONG:
        return {"sym": symbol, "kind": "diphthong", "viseme": XS_DIPHTHONG[symbol]}
    if symbol in XS_NASAL_CODA:
        return {"sym": symbol, "kind": "coda", "viseme": XS_NASAL_CODA[symbol]}
    if symbol in XS_APICAL_VOWEL:
        return {"sym": symbol, "kind": "vowel", "viseme": XS_APICAL_VOWEL[symbol]}
    if symbol in XS_CLOSURE:
        return {"sym": symbol, "kind": "closure", "viseme": "closed"}
    if symbol in XS_SILENCE:
        return {"sym": symbol, "kind": "silence", "viseme": "closed"}
    if symbol in XS_BREATH:
        return {"sym": symbol, "kind": "breath", "viseme": "closed"}
    if symbol in XS_BILABIAL_CLOSURE:
        return {"sym": symbol, "kind": "stop", "viseme": "closed"}
    if symbol in XS_STOPS:
        return {"sym": symbol, "kind": "stop", "viseme": None}
    if symbol in XS_AFFRICATES:
        return {"sym": symbol, "kind": "affricate", "viseme": None}
    if symbol in XS_FRICATIVES:
        return {"sym": symbol, "kind": "fricative", "viseme": "f" if symbol == "f" else None}
    if symbol in XS_NASALS:
        return {"sym": symbol, "kind": "nasal", "viseme": None}
    if symbol in XS_LIQUIDS:
        return {"sym": symbol, "kind": "liquid", "viseme": None}
    if symbol in XS_SEMIVOWELS:
        return {"sym": symbol, "kind": "semivowel", "viseme": None}
    return {"sym": symbol, "kind": "unknown", "viseme": None}


def _tokenize_xsampa(phone_string: str) -> tuple[list[dict], list[str]]:
    text = phone_string.strip()
    if text.startswith("."):
        text = text[1:]
    phones: list[dict] = []
    unknown: list[str] = []
    for chunk in text.split():
        index = 0
        while index < len(chunk):
            matched = None
            for symbol in _XS_SYMBOLS:
                if chunk.startswith(symbol, index):
                    matched = symbol
                    break
            if matched is None:
                if chunk[index] in ":\\`~h^":
                    index += 1
                    continue
                unknown.append(chunk[index])
                phones.append({"sym": chunk[index], "kind": "unknown", "viseme": None})
                index += 1
                continue
            phones.append(_classify_xs(matched))
            index += len(matched)
    return phones, unknown


def _plan_phoneme_string(text: str) -> dict:
    phones, unknown = _tokenize_xsampa(text)
    vowels = [p for p in phones if p["kind"] in ("vowel", "diphthong")]
    codas = [p for p in phones if p["kind"] == "coda"]
    onsets = []
    for phone in phones:
        if phone["kind"] in ("vowel", "diphthong", "coda"):
            break
        if phone["viseme"]:
            onsets.append(phone["viseme"])
    if vowels:
        if len(vowels) > 1 and vowels[0]["viseme"] in ("i", "u"):
            main = vowels[1]["viseme"]
        else:
            main = vowels[0]["viseme"]
    else:
        main = "closed"
        if any(p["kind"] == "fricative" and p["sym"] == "f" for p in phones):
            main = "f"
    return {
        "method": "xsampa", "raw": text, "normalized": text, "initial": "", "final": "",
        "phones": phones, "unknown_chars": unknown,
        "onset_viseme": onsets[0] if onsets else None,
        "main_viseme": main,
        "coda_viseme": codas[-1]["viseme"] if codas else None,
        "confidence": "rule" if not unknown else "heuristic",
    }


def _plan_english_word(word: str) -> dict:
    normalized = _normalize_pinyin(word)
    if not normalized:
        return _unmapped_plan(word, "empty english word")
    if normalized in _EN_WORD_HINTS:
        main, coda = _EN_WORD_HINTS[normalized]
        onset = "closed" if normalized[:1] in ("b", "p", "m") else (
            "f" if normalized[:1] == "f" else None)
        return {
            "method": "english", "raw": word, "normalized": normalized,
            "initial": normalized[:1], "final": normalized,
            "phones": [{"sym": normalized, "kind": "word", "viseme": main}],
            "onset_viseme": onset, "main_viseme": main, "coda_viseme": coda,
            "confidence": "heuristic",
        }
    match = re.search(r"([aeiouy]+)", normalized)
    if match:
        group = match.group(1)
        if len(group) >= 2 and group[:2] in _EN_DIGRAPHS:
            main = _EN_DIGRAPHS[group[:2]]
        else:
            main = _EN_VOWEL_LETTER.get(group[0], "e")
        onset = "closed" if normalized[0] in ("b", "p", "m") else (
            "f" if normalized[0] == "f" else None)
        return {
            "method": "english_heuristic", "raw": word, "normalized": normalized,
            "initial": normalized[:1], "final": normalized,
            "phones": [{"sym": group, "kind": "vowel_group", "viseme": main}],
            "onset_viseme": onset, "main_viseme": main,
            "coda_viseme": "n" if normalized.endswith(("n", "ng")) else None,
            "confidence": "heuristic",
        }
    return _unmapped_plan(word, "no vowel in latin token")


def _pinyin_for_char(char: str) -> str:
    if _LAZY_PINYIN is not None:
        try:  # pragma: no cover - depends on the machine
            result = _LAZY_PINYIN(char)
            if result and not _CJK_RE.search(result[0]):
                return result[0]
        except Exception:
            pass
    return _FALLBACK_PINYIN.get(char, "")


def _vowel_bearing(plan: dict) -> bool:
    """A syllable carries the mouth shape only when it ends in a vowel."""
    final = str(plan.get("final") or "")
    return bool(final) and final[-1] in "aiueo"


def _collect_vowels(plans: list[dict]) -> list[str]:
    """Every vowel of the lyric, so ない sings a → i instead of just i.

    长音（おう / えい）与延长的重复元音会合并成同一个口型。
    """
    vowels: list[str] = []
    for plan in plans:
        if not _vowel_bearing(plan):
            continue
        viseme = plan.get("main_viseme")
        if not viseme or viseme == "closed":
            continue
        if vowels and vowels[-1] == viseme:
            continue
        vowels.append(viseme)
    return vowels


def _merge_syllable_plans(plans: list[dict], raw: str) -> dict:
    if len(plans) == 1:
        merged = dict(plans[0])
        merged["raw"] = raw
        main = merged.get("main_viseme")
        merged["vowels"] = [main] if main in ("a", "i", "u", "e", "o") else []
        return merged
    phones: list[dict] = []
    for plan in plans:
        phones.extend(plan.get("phones") or [])
    last_vowel = None
    # 促音（cl）与拨音（n）不携带元音，不能覆盖前一个音节的嘴形；否则「まっ」
    # 会被判成全程闭口，「あん」会变成纯鼻音。
    for plan in reversed(plans):
        if _vowel_bearing(plan) and plan.get("main_viseme"):
            last_vowel = plan["main_viseme"]
            break
    if last_vowel is None:
        for plan in reversed(plans):
            if plan.get("main_viseme") and plan.get("initial") != "cl":
                last_vowel = plan["main_viseme"]
                break
    if last_vowel is None:
        for plan in reversed(plans):
            if plan.get("main_viseme"):
                last_vowel = plan["main_viseme"]
                break
    first = plans[0]
    return {
        "method": "pinyin_words", "raw": raw,
        "normalized": " ".join(plan.get("normalized", "") for plan in plans),
        "initial": first.get("initial", ""),
        "final": "".join(plan.get("final", "") for plan in plans),
        "phones": phones,
        "onset_viseme": first.get("onset_viseme"),
        "main_viseme": last_vowel or first.get("main_viseme"),
        "coda_viseme": plans[-1].get("coda_viseme"),
        "vowels": _collect_vowels(plans),
        "confidence": "rule",
    }


def _split_initial_phones(initial: str) -> list[dict]:
    """``kyo`` -> k + semivowel y, ``bya`` -> b(closed) + y(i).

    Without this the yōon onset (by / ky / gy / ny...) has no viseme at all, so
    「びょ」开头的闭口动作会丢掉。
    """
    if len(initial) >= 2 and initial.endswith("y"):
        base = initial[:-1]
        return [
            {"sym": base, "kind": "initial", "viseme": PINYIN_INITIAL_VISEME.get(base)},
            {"sym": "y", "kind": "semivowel", "viseme": "i"},
        ]
    if not initial:
        return []
    return [{"sym": initial, "kind": "initial", "viseme": PINYIN_INITIAL_VISEME.get(initial)}]


def _apply_small_vowel(romaji: str, vowel: str) -> str:
    """ち + ぇ -> che / ふ + ぃ -> fi / う + ぃ -> wi."""
    stem = romaji[:-1] if romaji[-1:] in "aiueo" else romaji
    if not stem:
        if romaji == "u":
            return "w" + vowel
        if romaji == "i" and vowel == "e":
            return "ye"
        return vowel
    if stem in ("sh", "ch", "j", "ts"):
        return stem + vowel
    if stem.endswith(("i", "u")):
        stem = stem[:-1]
    return (stem or "") + vowel


def _plan_kana(text: str) -> dict:
    hiragana = "".join(chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char for char in text)
    plans: list[dict] = []
    index = 0
    previous_main: str | None = None
    while index < len(hiragana):
        char = hiragana[index]
        if char in _SILENT_CHARS or char.isspace():
            index += 1
            continue
        if char in _LONG_VOWEL_CHARS:
            index += 1
            if previous_main:
                plans.append({
                    "method": "kana", "raw": char, "normalized": "ー",
                    "initial": "", "final": previous_main,
                    "phones": [{"sym": char, "kind": "vowel_group", "viseme": previous_main}],
                    "onset_viseme": None, "main_viseme": previous_main,
                    "coda_viseme": None, "confidence": "rule",
                })
            continue
        if char.isascii() and char.isalpha():
            # 假名歌词里混进罗马字（てi / na い 这类）：整段按拼音/罗马字规则处理，
            # 不要逐字母当成不支持字符丢掉。
            run = ""
            while index < len(hiragana) and hiragana[index].isascii() and hiragana[index].isalpha():
                run += hiragana[index]
                index += 1
            run_plan = _plan_pinyin_syllable(run)
            if run_plan["method"] == "unmapped":
                run_plan = _plan_english_word(run)
            if run_plan["method"] == "unmapped":
                plans.append(_unmapped_plan(run, "unsupported romaji %r" % run))
                previous_main = None
            else:
                run_plan["method"] = "kana_romaji"
                plans.append(run_plan)
                previous_main = run_plan.get("main_viseme") or previous_main
            continue
        token = hiragana[index:index + 2]
        romaji = _KANA_ROMAJI.get(token)
        if romaji:
            index += 2
        else:
            token = char
            romaji = _KANA_ROMAJI.get(char)
            index += 1
            if romaji and romaji not in ("cl", "n"):
                small = _SMALL_VOWELS.get(hiragana[index:index + 1])
                if small:
                    romaji = _apply_small_vowel(romaji, small)
                    token += hiragana[index]
                    index += 1
        if not romaji:
            # 日文歌词里常混汉字（死ん / 数 等）：用拼音兜底，至少保住元音口型，
            # 避免整条歌词只剩后面的拨音。
            if _CJK_RE.match(token):
                pinyin = _pinyin_for_char(token)
                if pinyin:
                    kanji_plan = _plan_pinyin_syllable(pinyin)
                    if kanji_plan["method"] != "unmapped":
                        kanji_plan["method"] = "kana_kanji"
                        plans.append(kanji_plan)
                        previous_main = kanji_plan.get("main_viseme") or previous_main
                        continue
            plans.append(_unmapped_plan(token, "unsupported kana %r" % token))
            previous_main = None
            continue
        if romaji == "cl":
            plans.append({
                "method": "kana", "raw": token, "normalized": romaji,
                "initial": "cl", "final": "", "phones": [{"sym": "cl", "kind": "closure", "viseme": "closed"}],
                "onset_viseme": "closed", "main_viseme": "closed", "coda_viseme": None, "confidence": "rule",
            })
            continue
        if romaji == "n":
            initial, final, main = "", "n", "n"
            phones = [{"sym": "n", "kind": "coda", "viseme": "n"}]
            previous_main = None
        else:
            vowel_index = next((i for i, char in enumerate(romaji) if char in "aiueo"), -1)
            initial, final = romaji[:vowel_index], romaji[vowel_index:]
            main = romaji[vowel_index]
            kind = "final"
            if not initial and previous_main and (previous_main, main) in _LONG_VOWEL_PAIRS:
                # 长音：おう / えい / おお 保持前一个元音的嘴形。
                main = previous_main
                kind = "vowel_group"
            phones = _split_initial_phones(initial)
            phones.append({"sym": final, "kind": kind, "viseme": main})
            previous_main = main
        onset_viseme = next(
            (phone["viseme"] for phone in phones
             if phone.get("kind") == "initial" and phone.get("viseme")),
            None,
        )
        plans.append({
            "method": "kana", "raw": token, "normalized": romaji,
            "initial": initial, "final": final, "phones": phones,
            "onset_viseme": onset_viseme, "main_viseme": main,
            "coda_viseme": "n" if romaji == "n" else None, "confidence": "rule",
        })
    if not plans:
        return _unmapped_plan(text, "kana lyric without syllables")
    merged = _merge_syllable_plans(plans, text)
    merged["method"] = "kana" if len(plans) == 1 else "kana_words"
    return merged


def lyric_to_plan(lyric: str, language: str = "mandarin", phoneset: str = "xsampa") -> dict:
    """Map one SVP lyric token to a viseme plan (same rules as lyric2viseme.py)."""
    raw = lyric if lyric is not None else ""
    text = raw.strip()

    if text in SUSTAIN_TOKENS or text == "":
        return {
            "method": "sustain" if text else "silence", "raw": raw, "normalized": "",
            "phones": [], "onset_viseme": None, "main_viseme": None,
            "coda_viseme": None, "confidence": "rule",
        }
    lowered = text.lower()
    if lowered in BREATH_TOKENS:
        return {
            "method": "breath", "raw": raw, "normalized": lowered, "phones": [],
            "onset_viseme": None, "main_viseme": "closed", "coda_viseme": None,
            "confidence": "rule",
        }
    if text.startswith("."):
        return _plan_phoneme_string(text)

    stripped = _APOSTROPHE_RE.sub("", text).strip()
    if not stripped:
        return _unmapped_plan(raw, "only punctuation")

    if (language or "").lower().startswith("english") or (phoneset or "").lower() == "arpabet":
        return _plan_english_word(stripped)

    if _KANA_RE.search(stripped):
        return _plan_kana(stripped)

    if _CJK_RE.search(stripped):
        plans: list[dict] = []
        if _LAZY_PINYIN is not None and len(stripped) > 1:
            try:  # pragma: no cover - depends on the machine
                syllables = _LAZY_PINYIN(stripped)
                if len(syllables) == len(stripped) and all(
                        s and not _CJK_RE.search(s) for s in syllables):
                    plans = [_plan_pinyin_syllable(s) for s in syllables]
            except Exception:
                plans = []
        if not plans:
            for char in stripped:
                if _CJK_RE.match(char):
                    pinyin = _pinyin_for_char(char)
                    if pinyin:
                        plans.append(_plan_pinyin_syllable(pinyin))
                    else:
                        plans.append(_unmapped_plan(char, "no pinyin for %r" % char))
                elif char in _SILENT_CHARS or char.isspace():
                    continue
                else:
                    plans.append(_unmapped_plan(char, "unsupported char in CJK lyric"))
        if not plans:
            return _unmapped_plan(raw, "CJK lyric without pinyin")
        return _merge_syllable_plans(plans, raw)

    if re.fullmatch(r"[a-zA-Zvüê:]+", stripped) and stripped.lower() not in _EN_WORD_HINTS:
        plan = _plan_pinyin_syllable(stripped)
        if plan["method"] == "unmapped":
            plan = _plan_english_word(stripped)
        return plan
    if re.fullmatch(r"[a-zA-Z']+", stripped):
        return _plan_english_word(stripped)
    return _unmapped_plan(raw, "unrecognised lyric form")


# ---------------------------------------------------------------------------
# Project parsing
# ---------------------------------------------------------------------------
@dataclass
class NoteInfo:
    start_sec: float
    end_sec: float
    pitch_midi: float
    lyric: str
    group: str
    language: str = ""
    phoneset: str = ""
    muted: bool = False


@dataclass
class GroupInfo:
    name: str
    note_count: int
    muted: bool
    notes: list[NoteInfo] = field(default_factory=list)


@dataclass
class TrackData:
    index: int
    name: str
    is_instrumental: bool
    mixer_mute: bool
    groups: list[GroupInfo] = field(default_factory=list)
    notes: list[NoteInfo] = field(default_factory=list)

    def sec_range(self) -> tuple[float, float]:
        if not self.notes:
            return 0.0, 0.0
        return (min(note.start_sec for note in self.notes),
                max(note.end_sec for note in self.notes))


@dataclass
class ProjectData:
    version: str | None
    tempo: TempoMap
    tracks: list[TrackData]

    @property
    def vocal_tracks(self) -> list[TrackData]:
        return [track for track in self.tracks
                if not track.is_instrumental and track.notes]


def _notes_from_group(group: dict, offset: int, tempo: TempoMap, default_language: str,
                      default_phoneset: str, group_name: str, group_muted: bool) -> list[NoteInfo]:
    notes: list[NoteInfo] = []
    for raw_note in group.get("notes") or []:
        try:
            onset = int(raw_note.get("onset") or 0) + offset
            duration = int(raw_note.get("duration") or 0)
            raw_pitch = float(raw_note.get("pitch") or 60)
        except (TypeError, ValueError):
            continue
        attributes = raw_note.get("attributes") or {}
        takes = raw_note.get("takes") or {}
        take_list = takes.get("takes") or []
        active_take = takes.get("activeTakeId", 0)
        muted = group_muted
        if take_list:
            try:
                active = int(active_take)
            except (TypeError, ValueError):
                active = 0
            if 0 <= active < len(take_list) and take_list[active].get("muted"):
                muted = True
        if attributes.get("muted"):
            muted = True
        pitch_offset = 0.0
        notes.append(NoteInfo(
            start_sec=tempo.sec_at_tick(onset),
            end_sec=tempo.sec_at_tick(onset + max(0, duration)),
            pitch_midi=raw_pitch + pitch_offset,
            lyric=(raw_note.get("lyrics") or ""),
            group=group_name,
            language=attributes.get("languageOverride") or default_language,
            phoneset=attributes.get("phonesetOverride") or default_phoneset,
            muted=muted,
        ))
    return notes


def parse_project(raw: dict) -> ProjectData:
    """Turn the raw .svp JSON into the timing/note model used by the timeline."""
    tempo = TempoMap(raw.get("time") or {})
    library = {group.get("uuid"): group for group in (raw.get("library") or [])
               if isinstance(group, dict) and group.get("uuid")}
    tracks: list[TrackData] = []

    for track_index, raw_track in enumerate(raw.get("tracks") or []):
        if not isinstance(raw_track, dict):
            continue
        main_ref = raw_track.get("mainRef") or {}
        track = TrackData(
            index=track_index,
            name=str(raw_track.get("name") or f"track{track_index}"),
            is_instrumental=bool(main_ref.get("isInstrumental", False)),
            mixer_mute=bool((raw_track.get("mixer") or {}).get("mute", False)),
        )
        refs = raw_track.get("groups") or []
        for raw_ref in refs:
            if not isinstance(raw_ref, dict):
                continue
            group_uuid = raw_ref.get("groupID")
            group = library.get(group_uuid)
            if group is None:
                group = raw_ref  # inline note group
            database = raw_ref.get("database") or {}
            try:
                offset = int(raw_ref.get("blickOffset") or 0)
            except (TypeError, ValueError):
                offset = 0
            group_name = str(group.get("name") or raw_ref.get("name") or "")
            group_muted = bool(raw_ref.get("mute", False))
            notes = _notes_from_group(
                group, offset, tempo,
                database.get("languageOverride") or "",
                database.get("phonesetOverride") or "",
                group_name, group_muted,
            )
            for note in notes:
                note.group = group_name
            track.groups.append(GroupInfo(
                name=group_name, note_count=len(notes), muted=group_muted, notes=notes))
            track.notes.extend(notes)

        # Some projects keep the notes inline in mainGroup instead of a placed ref.
        main_group = raw_track.get("mainGroup") or {}
        if isinstance(main_group, dict) and main_group.get("notes"):
            main_uuid = main_group.get("uuid")
            already_loaded = any(ref.get("groupID") == main_uuid for ref in refs
                                 if isinstance(ref, dict))
            if not already_loaded:
                database = main_ref.get("database") or {}
                group_name = str(main_group.get("name") or "mainGroup")
                notes = _notes_from_group(
                    main_group, 0, tempo,
                    database.get("languageOverride") or "",
                    database.get("phonesetOverride") or "",
                    group_name, False,
                )
                for note in notes:
                    note.group = group_name
                track.groups.append(GroupInfo(
                    name=group_name, note_count=len(notes), muted=False, notes=notes))
                track.notes.extend(notes)

        track.notes.sort(key=lambda note: note.start_sec)
        tracks.append(track)

    return ProjectData(version=raw.get("version"), tempo=tempo, tracks=tracks)


def _track_info(track: TrackData) -> dict:
    start, end = track.sec_range()
    return {
        "index": track.index,
        "name": track.name,
        "isInstrumental": track.is_instrumental,
        "isVocal": (not track.is_instrumental) and bool(track.notes),
        "noteCount": len(track.notes),
        "rangeStartSec": round(start, 6),
        "rangeEndSec": round(end, 6),
        "groups": [{"name": group.name, "noteCount": group.note_count}
                   for group in track.groups],
    }


# ---------------------------------------------------------------------------
# Asset lifecycle
# ---------------------------------------------------------------------------
def _project_cache_key(asset_id: str, path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
        return asset_id, stat.st_mtime_ns, stat.st_size
    except OSError:
        return asset_id, 0, 0


def get_project(asset_id: str) -> ProjectData:
    source = storage.find_source("svp", asset_id)
    if source is None:
        raise FileNotFoundError(f"SVP 资产不存在: {asset_id}")
    key = _project_cache_key(asset_id, source)
    cached = _PROJECT_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"SVP 文件无法解析: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("SVP 文件格式错误：根节点必须是对象")
    project = parse_project(raw)
    if len(_PROJECT_CACHE) >= MAX_CACHE_ENTRIES:
        _PROJECT_CACHE.clear()
    _PROJECT_CACHE[key] = project
    return project


def save_upload(filename: str, data: bytes) -> dict:
    """Persist an uploaded .svp and return the CONTRACT §5.3 upload payload."""
    if not data:
        raise ValueError("上传文件为空")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise ValueError("文件超过 200MB 上限")
    try:
        raw = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("不是合法的 SVP/JSON 文件") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("tracks"), list):
        raise ValueError("SVP 文件缺少 tracks 字段，可能不是 Synthesizer V 工程")
    project = parse_project(raw)

    asset_id = storage.new_id()
    stored = storage.save_upload("svp", asset_id, filename, data)
    warnings: list[str] = []
    if not project.vocal_tracks:
        warnings.append("未找到含音符的人声轨道，请确认工程内容")
    summary = {
        "assetId": asset_id,
        "filename": storage.safe_name(filename),
        "version": str(project.version) if project.version is not None else None,
        "tracks": [_track_info(track) for track in project.tracks],
        "warnings": warnings,
    }
    storage.write_json(storage.asset_meta_path("svp", asset_id), {
        **summary,
        "storedFile": stored.name,
        "trackCount": len(project.tracks),
        "vocalTrackCount": len(project.vocal_tracks),
        "uploadedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return summary


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
def _build_events(track: TrackData) -> tuple[list[dict], list[str]]:
    events: list[dict] = []
    warnings: list[str] = []
    muted_count = 0
    for note in track.notes:
        if note.muted:
            muted_count += 1
            continue
        plan = lyric_to_plan(note.lyric, note.language, note.phoneset)
        events.append({
            "index": len(events),
            "note": note,
            "plan": plan,
            "main": plan.get("main_viseme") or "closed",
            "sustained": False,
        })
    events.sort(key=lambda event: (event["note"].start_sec, event["index"]))
    for index, event in enumerate(events):
        event["index"] = index
    # '-' sustain carries the previous non-sustain viseme of the same track
    last_viseme: str | None = None
    for event in events:
        if event["plan"].get("method") == "sustain":
            event["sustained"] = True
            event["main"] = last_viseme or "closed"
        else:
            last_viseme = event["main"]
    if muted_count:
        warnings.append(f"跳过 {muted_count} 个静音音符（muted）")
    return events, warnings


def _paint_frames(events: list[dict], n_frames: int, fps: int) -> tuple[list[str], list[int]]:
    viseme = ["closed"] * n_frames
    note_index = [-1] * n_frames
    gap_hold_frames = max(0, int(round(GAP_HOLD_SEC * fps)))
    if n_frames <= 0:
        return viseme, note_index

    for event in events:  # later onset wins, which matches the prototype
        note = event["note"]
        if note.end_sec <= note.start_sec:
            continue
        f0 = int(round(note.start_sec * fps))
        f1 = int(round(note.end_sec * fps))
        if f1 - f0 < MIN_NOTE_FRAMES:
            f1 = f0 + MIN_NOTE_FRAMES
        f0 = max(0, min(f0, n_frames - 1))
        f1 = max(f0 + 1, min(f1, n_frames))
        span = f1 - f0
        main = event["main"]
        plan = event["plan"]
        onset = plan.get("onset_viseme")
        coda = plan.get("coda_viseme")
        is_sustain = event["sustained"]
        consonant = CONSONANT_FRAMES if (onset and not is_sustain) else 0
        consonant = min(consonant, max(0, span - 1))
        if onset and not is_sustain and PRE_CONSONANT_FRAMES:
            for frame in range(max(0, f0 - PRE_CONSONANT_FRAMES), f0):
                viseme[frame] = onset
                note_index[frame] = event["index"]
        for frame in range(f0, f0 + consonant):
            viseme[frame] = onset
            note_index[frame] = event["index"]
        coda_len = 0
        if coda and not is_sustain and CODA_FRAMES:
            next_event = _next_event(events, event)
            phrase_final = (next_event is None
                            or next_event["note"].start_sec > note.end_sec + 0.12)
            if phrase_final:
                coda_len = min(CODA_FRAMES, max(0, span - consonant - 1))
        vowels = plan.get("vowels") or []
        segments = _vowel_segments(f0 + consonant, f1 - coda_len, len(vowels))
        if segments:
            for value, (seg_start, seg_end) in zip(vowels, segments):
                for frame in range(seg_start, seg_end):
                    viseme[frame] = value
                    note_index[frame] = event["index"]
        else:
            for frame in range(f0 + consonant, f1 - coda_len):
                viseme[frame] = main
                note_index[frame] = event["index"]
        for frame in range(f1 - coda_len, f1):
            viseme[frame] = coda
            note_index[frame] = event["index"]

    # bridge short rests between two notes so the mouth does not flicker shut
    if gap_hold_frames > 0:
        index = 0
        while index < n_frames:
            if note_index[index] != -1:
                index += 1
                continue
            end = index
            while end < n_frames and note_index[end] == -1:
                end += 1
            run = end - index
            if run <= gap_hold_frames and index > 0 and end < n_frames:
                for frame in range(index, end):
                    viseme[frame] = viseme[index - 1]
            index = end
    return viseme, note_index


def _vowel_segments(start: int, end: int, count: int) -> list[tuple[int, int]]:
    """Split one note's sustain range into `count` vowel segments.

    Returns an empty list when the split is not worth it (single vowel, or the
    note is too short to give each vowel at least one frame).
    """
    total = end - start
    if count < 2 or total < count:
        return []
    return [
        (start + total * index // count, start + total * (index + 1) // count)
        for index in range(count)
    ]


def _next_event(events: list[dict], event: dict) -> dict | None:
    best = None
    for other in events:
        if other is event:
            continue
        if other["note"].start_sec >= event["note"].end_sec - 1e-6:
            if best is None or other["note"].start_sec < best["note"].start_sec:
                best = other
    return best


def _viseme_runs(viseme: list[str], note_index: list[int], fps: int) -> list[dict]:
    runs: list[dict] = []
    if not viseme:
        return runs
    current = viseme[0]
    start = 0
    current_note = note_index[0]
    for frame in range(1, len(viseme)):
        if viseme[frame] != current or note_index[frame] != current_note:
            runs.append({
                "startSec": round(start / fps, 6),
                "endSec": round(frame / fps, 6),
                "frames": frame - start,
                "viseme": current,
                "noteIndex": current_note if current_note >= 0 else None,
            })
            current, start, current_note = viseme[frame], frame, note_index[frame]
    runs.append({
        "startSec": round(start / fps, 6),
        "endSec": round(len(viseme) / fps, 6),
        "frames": len(viseme) - start,
        "viseme": current,
        "noteIndex": current_note if current_note >= 0 else None,
    })
    return runs


def _pitch_bounds(events: list[dict]) -> tuple[float, float]:
    pitches = sorted(float(event["note"].pitch_midi) for event in events)
    if not pitches:
        return 60.0, 72.0
    low = pitches[min(len(pitches) - 1, int(len(pitches) * 0.2))]
    high = pitches[min(len(pitches) - 1, int(len(pitches) * 0.85))]
    return low, max(low + 1.0, high)


def _vowel_pose(vowel: str, span: int, pitch_level: float, mode: str) -> str:
    """Mouth pose for one vowel inside a note (same rules as the single-vowel peak)."""
    if vowel == "a" and span >= 8 and pitch_level >= 0.75:
        if mode == "expressive" and pitch_level >= 0.92 and span >= 12:
            return "openXLarge"
        return "openLarge"
    if vowel == "a" and mode == "expressive" and span >= 8:
        return "wide"
    return vowel


def _onset_pose(event: dict) -> str | None:
    phones = event["plan"].get("phones") or []
    symbols = {str(phone.get("sym") or "") for phone in phones[:-1] or phones}
    if symbols & {"m", "b", "p", "ph", "cl"}:
        return "pressed"
    if symbols & {"w"}:
        return "roundSmall"
    if symbols & {"n", "f", "v", "s", "z", "sh", "s`", "s\\"}:
        return "narrow"
    onset = event["plan"].get("onset_viseme")
    return {"closed": "pressed", "n": "narrow", "f": "narrow"}.get(onset)


def _pose_frames(events: list[dict], viseme: list[str], note_index: list[int], fps: int,
                 mode: str) -> tuple[list[str], list[str]]:
    poses = list(viseme)
    phases = ["idle" if value == "closed" else "sustain" for value in viseme]
    if mode == "classic":
        return poses, phases

    low_pitch, high_pitch = _pitch_bounds(events)
    strength = {"clear": 0.25, "natural": 0.6, "expressive": 1.0}[mode]
    for event in events:
        if event["sustained"]:
            continue
        note = event["note"]
        start = max(0, min(len(poses), int(round(note.start_sec * fps))))
        end = max(start, min(len(poses), int(round(note.end_sec * fps))))
        span = end - start
        if span < 2:
            continue
        main = event["main"]
        onset = _onset_pose(event)
        attack = "roundSmall" if main in {"u", "o"} else ("aSoft" if main == "a" else main)
        pitch_level = max(0.0, min(1.0, (float(note.pitch_midi) - low_pitch) / (high_pitch - low_pitch)))
        peak = _vowel_pose(main, span, pitch_level, mode)

        onset_len = min(2 if strength < 1 else 3, max(0, span // 4)) if onset else 0
        attack_len = min(2, max(0, (span - onset_len) // 4))
        release_len = min(2, max(0, (span - onset_len - attack_len) // 4))
        if span <= 5:
            onset_len = 1 if onset else 0
            attack_len = 0
            release_len = 0
        elif span <= 9:
            release_len = 1

        cursor = start
        for frame in range(cursor, min(end, cursor + onset_len)):
            poses[frame], phases[frame] = onset or main, "onset"
        cursor += onset_len
        for frame in range(cursor, min(end, cursor + attack_len)):
            poses[frame], phases[frame] = attack, "attack"
        cursor += attack_len
        sustain_end = max(cursor, end - release_len)
        vowels = event["plan"].get("vowels") or []
        segments = _vowel_segments(cursor, sustain_end, len(vowels))
        if segments:
            for value, (seg_start, seg_end) in zip(vowels, segments):
                pose = _vowel_pose(value, span, pitch_level, mode)
                for frame in range(seg_start, seg_end):
                    poses[frame], phases[frame] = pose, "sustain"
        else:
            for frame in range(cursor, sustain_end):
                poses[frame], phases[frame] = peak, "sustain"
        release = attack if attack != main else main
        for frame in range(sustain_end, end):
            poses[frame], phases[frame] = release, "release"
    return poses, phases


def _sparse_mouth_track(frames: list[dict]) -> list[dict]:
    track: list[dict] = []
    previous: tuple | None = None
    for frame in frames:
        current = (frame["mouthPose"], frame["viseme"], frame["phase"], frame.get("noteIndex"))
        if current == previous:
            continue
        track.append({
            "t": frame["t"], "state": frame["mouthPose"], "viseme": frame["viseme"],
            "phase": frame["phase"], "openness": frame["openness"],
            "noteIndex": frame.get("noteIndex"),
        })
        previous = current
    return track


def _source_tracks(events: list[dict]) -> dict[str, list[dict]]:
    notes: list[dict] = []
    phonemes: list[dict] = []
    pitch: list[dict] = []
    for event in events:
        note = event["note"]
        start, end = note.start_sec, note.end_sec
        notes.append({"index": event["index"], "start": round(start, 6), "end": round(end, 6),
                      "lyric": note.lyric, "pitchMidi": round(note.pitch_midi, 3)})
        pitch.append({"start": round(start, 6), "end": round(end, 6),
                      "midi": round(note.pitch_midi, 3), "source": "note"})
        phones = event["plan"].get("phones") or []
        if not phones:
            continue
        duration = max(0.0, end - start)
        onset_duration = min(duration * 0.35, 2 / 60) if len(phones) > 1 else duration
        for index, phone in enumerate(phones):
            phone_start = start if index == 0 else start + onset_duration
            phone_end = start + onset_duration if index == 0 and len(phones) > 1 else end
            phonemes.append({
                "start": round(phone_start, 6), "end": round(max(phone_start, phone_end), 6),
                "symbol": str(phone.get("sym") or ""), "kind": str(phone.get("kind") or "unknown"),
                "timing": "estimated", "noteIndex": event["index"],
            })
    return {"notes": notes, "phonemes": phonemes, "pitch": pitch}


def _merge_intervals(intervals: Iterable[tuple[float, float]], gap: float) -> list[list[float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _build_blinks(events: list[dict], duration: float, fps: int) -> list[dict]:
    """Rule-based blinks: phrase gaps, a start blink, and a max-open interval.

    Blinks never sit within 2 frames of a note onset (they are nudged by 3
    frames, or dropped when no nearby slot is free).
    """
    if duration <= 0 or not events:
        return []
    rng = random.Random(42)
    candidates: list[tuple[float, str]] = []

    activity = _merge_intervals(
        ((event["note"].start_sec, event["note"].end_sec) for event in events),
        PHRASE_GAP_SEC,
    )

    def add(time_value: float, reason: str) -> None:
        value = max(0.0, min(duration, float(time_value)))
        if any(abs(value - existing[0]) < 0.25 for existing in candidates):
            return
        candidates.append((value, reason))

    if activity:
        add(min(activity[0][0] + 0.6, 2.0), "song_start")
        for previous, current in zip(activity, activity[1:]):
            gap = current[0] - previous[1]
            if gap >= 0.7:
                add(previous[1] + min(0.35, gap * 0.4), "phrase_boundary")
            elif gap >= 0.35:
                add(previous[1] + gap * 0.5, "short_gap")
        for start, end in activity:
            moment = start + 2.0
            while moment < end - 0.5:
                if not any(start <= value <= end for value, _ in candidates):
                    add(moment, "max_open_interval")
                moment += 4.5

    onsets = [event["note"].start_sec for event in events]
    onset_window = 2.0 / fps
    step = 3.0 / fps
    accepted: list[tuple[float, str]] = []
    for value, reason in candidates:
        chosen = None
        for shift in (0, step, -step, 2 * step, -2 * step, 3 * step, -3 * step):
            proposed = value + shift
            if proposed < 0 or proposed > duration:
                continue
            if any(abs(proposed - onset) <= onset_window for onset in onsets):
                continue
            chosen = proposed
            break
        if chosen is not None:
            accepted.append((max(0.0, min(duration, chosen)), reason))

    accepted.sort(key=lambda item: item[0])
    blinks: list[dict] = []
    for value, _reason in accepted:
        if blinks and value - blinks[-1]["t"] < 0.25:
            continue
        blinks.append({"t": round(value, 4), "duration": round(rng.uniform(0.11, 0.18), 3)})
    return blinks


def _timeline_stats(events: list[dict], viseme: list[str], note_index: list[int],
                    duration: float, fps: int, track: TrackData, warnings: list[str]) -> dict:
    n_frames = len(viseme)
    counts = {name: 0 for name in VISEMES}
    for value in viseme:
        counts[value] = counts.get(value, 0) + 1
    distribution = {
        name: {
            "frames": counts.get(name, 0),
            "percent": round(100.0 * counts.get(name, 0) / n_frames, 2) if n_frames else 0.0,
            "seconds": round(counts.get(name, 0) / fps, 2) if n_frames else 0.0,
        }
        for name in VISEMES
    }
    longest, longest_start, current, current_start = 0, 0.0, 0, 0
    for frame, value in enumerate(viseme):
        if value == "closed":
            if current == 0:
                current_start = frame
            current += 1
            if current > longest:
                longest, longest_start = current, current_start / fps
        else:
            current = 0
    transitions = sum(1 for a, b in zip(viseme, viseme[1:]) if a != b)
    singing = sum(1 for index in note_index if index >= 0)

    checked = matched = 0
    examples: list[dict] = []
    for event in events:
        if event["sustained"]:
            continue
        frame = int(round(event["note"].start_sec * fps)) + CONSONANT_FRAMES
        frame = max(0, min(n_frames - 1, frame)) if n_frames else 0
        if n_frames == 0 or note_index[frame] != event["index"]:
            continue
        checked += 1
        allowed = {event["main"]}
        for value in event["plan"].get("vowels") or []:
            allowed.add(value)
        for key in ("onset_viseme", "coda_viseme"):
            if event["plan"].get(key):
                allowed.add(event["plan"][key])
        if viseme[frame] in allowed:
            matched += 1
        elif len(examples) < 6:
            examples.append({
                "t": round(frame / fps, 3),
                "lyric": event["note"].lyric,
                "expected": event["main"],
                "got": viseme[frame],
            })

    mapped = 0
    unmapped = 0
    tokens: set[str] = set()
    for event in events:
        tokens.add(event["note"].lyric)
        plan = event["plan"]
        if plan.get("method") in ("sustain", "breath", "silence"):
            mapped += 1
            continue
        if plan.get("method") == "unmapped" or plan.get("main_viseme") is None:
            unmapped += 1
        else:
            mapped += 1
    total_notes = len(events)
    coverage = (100.0 * mapped / total_notes) if total_notes else 100.0

    return {
        "fps": fps,
        "frames": n_frames,
        "durationSec": round(duration, 6),
        "trackIndex": track.index,
        "trackName": track.name,
        "noteCount": total_notes,
        "mutedNotes": len(track.notes) - total_notes,
        "sustainedNotes": sum(1 for event in events if event["sustained"]),
        "lyricCoveragePercent": round(coverage, 2),
        "unmappedLyricNotes": unmapped,
        "distinctLyricTokens": len(tokens),
        "pinyinSource": _PINYIN_SOURCE,
        "noteBoundaryCheck": {
            "checked": checked,
            "matched": matched,
            "ratioPercent": round(100.0 * matched / checked, 2) if checked else 100.0,
            "examples": examples,
        },
        "visemeDistribution": distribution,
        "closedRatioPercent": distribution["closed"]["percent"],
        "singingFrameRatioPercent": round(100.0 * singing / n_frames, 2) if n_frames else 0.0,
        "longestClosedSeconds": round(longest / fps, 3) if n_frames else 0.0,
        "longestClosedStartsAtSec": round(longest_start, 3),
        "transitions": transitions,
        "transitionsPerSecond": round(transitions / duration, 2) if duration else 0.0,
        "warnings": warnings,
    }


def _cache_path(asset_id: str, track_index: int, fps: int, mapping_set_id: str = "standard",
                animation_mode_id: str = "classic") -> Path:
    if animation_mode_id == "classic" and mapping_set_id == "standard":
        return storage.asset_dir("svp", asset_id) / f"timeline-track{track_index}-{fps}.json"
    safe_mapping = re.sub(r"[^a-zA-Z0-9_-]", "_", mapping_set_id)
    return storage.asset_dir("svp", asset_id) / (
        f"timeline-v2-track{track_index}-{fps}-{safe_mapping}-{animation_mode_id}.json")


def generate_timeline(asset_id: str, track_index: int, fps: int = 60, *,
                      psd_asset_id: str | None = None, mapping_set_id: str = "standard",
                      animation_mode_id: str = "classic") -> dict:
    """Build (or reuse from disk) the single-track timeline payload."""
    try:
        fps = int(fps)
        track_index = int(track_index)
    except (TypeError, ValueError) as exc:
        raise ValueError("trackIndex / fps 必须是整数") from exc
    if not 1 <= fps <= 240:
        raise ValueError("fps 必须在 1..240 之间")
    if animation_mode_id not in ANIMATION_MODES:
        raise ValueError(f"未知动画模式: {animation_mode_id}")
    project = get_project(asset_id)
    if not 0 <= track_index < len(project.tracks):
        raise IndexError(
            f"轨道 {track_index} 不存在（共 {len(project.tracks)} 条轨道）")

    cache_file = _cache_path(asset_id, track_index, fps, mapping_set_id, animation_mode_id)
    cached = storage.read_json(cache_file)
    cached_timeline = cached.get("timeline") if isinstance(cached, dict) else None
    cached_mode = cached_timeline.get("mode") if isinstance(cached_timeline, dict) else None
    if (
        isinstance(cached, dict)
        and isinstance(cached_timeline, dict)
        and isinstance(cached_mode, dict)
        and cached_mode.get("animationModeVersion") == MODE_VERSION
    ):
        cached["cached"] = True
        return cached

    started = time.perf_counter()
    track = project.tracks[track_index]
    warnings: list[str] = []
    if track.is_instrumental:
        warnings.append(
            f"轨道 {track_index} 是伴奏轨（isInstrumental=true），没有歌词，时间轴将全程闭口")
    if track.mixer_mute:
        warnings.append(f"轨道 {track_index} 在工程中处于静音（mixer.mute），仍按音符数据生成")
    events, event_warnings = _build_events(track)
    warnings.extend(event_warnings)
    if not events:
        warnings.append(f"轨道 {track_index} 没有可用音符，时间轴为空")

    last_end = max((event["note"].end_sec for event in events), default=0.0)
    duration = round(last_end + TAIL_SEC, 6) if last_end > 0 else 0.0
    n_frames = int(math.ceil(duration * fps)) if duration > 0 else 0
    viseme, note_index = _paint_frames(events, n_frames, fps)
    poses, phases = _pose_frames(events, viseme, note_index, fps, animation_mode_id)
    rich_frames = [
        {"t": round(frame / fps, 6), "viseme": viseme[frame],
         "openness": VISEME_OPENNESS.get(viseme[frame], 0.0),
         "mouthPose": poses[frame], "phase": phases[frame],
         "noteIndex": note_index[frame] if note_index[frame] >= 0 else None}
        for frame in range(n_frames)
    ]
    frames = rich_frames if animation_mode_id != "classic" else [
        {"t": frame["t"], "viseme": frame["viseme"], "openness": frame["openness"]}
        for frame in rich_frames
    ]
    notes = [{
        "index": event["index"],
        "startSec": round(event["note"].start_sec, 6),
        "endSec": round(event["note"].end_sec, 6),
        "durationSec": round(event["note"].end_sec - event["note"].start_sec, 6),
        "pitchMidi": round(event["note"].pitch_midi, 3),
        "lyric": event["note"].lyric,
        "group": event["note"].group,
        "method": event["plan"].get("method"),
        "onsetViseme": event["plan"].get("onset_viseme"),
        "mainViseme": event["main"],
        "codaViseme": event["plan"].get("coda_viseme"),
        "phones": [phone.get("sym") for phone in (event["plan"].get("phones") or [])],
        "sustained": event["sustained"],
    } for event in events]

    stats = _timeline_stats(events, viseme, note_index, duration, fps, track, warnings)
    generation_ms = round((time.perf_counter() - started) * 1000.0, 2)
    stats["generationMs"] = generation_ms
    stats["alignedOnsets"] = stats["noteBoundaryCheck"]["matched"]
    if stats["lyricCoveragePercent"] < 100.0:
        examples = [event["note"].lyric for event in events
                    if event["plan"].get("method") == "unmapped"
                    or event["plan"].get("main_viseme") is None][:6]
        warnings.append(
            "歌词覆盖 %.2f%%：%d 个音符没有映射到 viseme（例如 %s）"
            % (stats["lyricCoveragePercent"], stats["unmappedLyricNotes"],
               "、".join(repr(item) for item in examples)))

    blinks = _build_blinks(events, duration, fps)
    eyes_track: list[dict] = []
    for blink in blinks:
        eyes_track.extend([
            {"t": blink["t"], "state": "blink"},
            {"t": round(blink["t"] + blink["duration"], 6), "state": "open"},
        ])
    payload = {
        "timeline": {
            "fps": fps,
            "duration": duration,
            "frames": frames,
            "source": {"kind": "svp", "assetId": asset_id, "trackIndex": track_index},
            "notes": notes,
            "mouthRuns": _viseme_runs(viseme, note_index, fps),
            "mode": {"mappingSetId": mapping_set_id, "animationModeId": animation_mode_id,
                     "animationModeVersion": MODE_VERSION},
            "sourceTracks": _source_tracks(events),
            "tracks": {
                "mouth": _sparse_mouth_track(rich_frames),
                "blink": blinks,
                "eyes": eyes_track,
                "brow": [], "cheek": [], "sweat": [], "eyeEffect": [],
            },
        },
        "blinks": blinks,
        "stats": stats,
        "warnings": warnings,
        "cached": False,
    }
    try:
        storage.write_json(cache_file, payload)
    except OSError:
        warnings.append("时间轴缓存写入失败（不影响本次返回）")
    return payload


def list_tracks(asset_id: str) -> dict:
    """Re-read the stored project and return the upload-shaped summary."""
    project = get_project(asset_id)
    meta = storage.read_json(storage.asset_meta_path("svp", asset_id), {}) or {}
    return {
        "assetId": asset_id,
        "filename": meta.get("filename") or f"{asset_id}.svp",
        "version": str(project.version) if project.version is not None else None,
        "tracks": [_track_info(track) for track in project.tracks],
        "warnings": list(meta.get("warnings") or []),
    }
