"""Audio assets: probing, waveform peaks, BPM detection and byte-range serving.

* metadata comes from ``ffprobe``;
* peaks are computed with numpy from an ``ffmpeg``-decoded mono 16 kHz WAV
  cached at ``data/assets/audio/<assetId>/mono16k.wav``;
* BPM uses ``librosa.beat.beat_track`` on the first 60 s.  librosa is imported
  in a short-lived subprocess with a hard timeout because this machine's
  librosa/numba pair can hang on import; if it does not answer quickly (or
  fails) a cheap numpy onset-autocorrelation estimate is used instead.  A
  missing BPM never fails the upload -- the frontend lets the user type one.
"""

from __future__ import annotations

import json
import math
import mimetypes
import os
import shutil
import subprocess
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import config, storage

DEFAULT_POINTS = 2000
MIN_POINTS = 16
MAX_POINTS = 20000
LIBROSA_TIMEOUT_SEC = 6.0
BPM_MIN_AUDIO_SEC = 6.0
_MONO_NAME = "mono16k.wav"

_LIBROSA_STATE = "unknown"  # unknown | ok | broken

_LIBROSA_SCRIPT = r"""
import json, sys
try:
    import librosa
    audio, sr = librosa.load(sys.argv[1], sr=22050, mono=True, duration=60.0)
    bpm, _beats = librosa.beat.beat_track(y=audio, sr=sr)
    print(json.dumps({"bpm": float(bpm)}))
except Exception as exc:  # pragma: no cover - depends on the machine
    print(json.dumps({"error": type(exc).__name__ + ": " + str(exc)[:160]}))
"""


# ---------------------------------------------------------------------------
# ffmpeg / ffprobe helpers
# ---------------------------------------------------------------------------
def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"未找到 {name}，请确认 ffmpeg 已加入 PATH")
    return path


def _probe(path: Path) -> dict:
    """ffprobe metadata -> {duration, sampleRate, channels, codec, format}."""
    command = [
        _tool("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("ffprobe 超时，无法读取音频信息") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise ValueError("无法解析音频文件" + (f"（{detail[-1]}）" if detail else ""))
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe 输出无法解析") from exc
    streams = [stream for stream in (payload.get("streams") or [])
               if stream.get("codec_type") == "audio"]
    if not streams:
        raise ValueError("文件中没有音频流")
    stream = streams[0]
    fmt = payload.get("format") or {}
    duration = _as_float(fmt.get("duration")) or _as_float(stream.get("duration"))
    return {
        "duration": duration,
        "sampleRate": _as_int(stream.get("sample_rate")),
        "channels": _as_int(stream.get("channels")),
        "codec": stream.get("codec_name"),
        "format": fmt.get("format_name"),
        "bitRate": _as_int(fmt.get("bit_rate")),
    }


def _as_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _as_int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _decode_mono16k(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        _tool("ffmpeg"), "-y", "-v", "error", "-i", str(source),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target),
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("ffmpeg 解码超时") from exc
    if proc.returncode != 0 or not target.is_file():
        detail = (proc.stderr or "").strip().splitlines()
        raise ValueError("ffmpeg 无法解码该音频" + (f"（{detail[-1]}）" if detail else ""))


def _read_mono16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError("内部的 mono 缓存不是 16-bit PCM")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:  # defensive: ffmpeg already downmixes
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples


# ---------------------------------------------------------------------------
# Peaks
# ---------------------------------------------------------------------------
def compute_peaks(samples: np.ndarray, points: int = DEFAULT_POINTS) -> list[float]:
    """Bucket the absolute waveform into ``points`` values in 0..1."""
    points = max(1, int(points))
    if samples.size == 0:
        return [0.0] * points
    absolute = np.abs(samples)
    total = absolute.size
    if total < points:
        indices = np.clip((np.arange(points) * total) // points, 0, total - 1)
        values = absolute[indices]
    else:
        starts = (np.arange(points) * total) // points
        values = np.maximum.reduceat(absolute, starts)
    peak = float(values.max()) if values.size else 0.0
    if peak > 1e-9:
        values = values / peak
    return [round(float(value), 4) for value in values]


# ---------------------------------------------------------------------------
# BPM
# ---------------------------------------------------------------------------
def _librosa_bpm(mono_path: Path) -> float | None:
    """Try librosa in a subprocess; remember when the environment is unusable."""
    global _LIBROSA_STATE
    if _LIBROSA_STATE == "broken":
        return None
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _LIBROSA_SCRIPT, str(mono_path)],
            capture_output=True, text=True, timeout=LIBROSA_TIMEOUT_SEC,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except (subprocess.TimeoutExpired, OSError):
        _LIBROSA_STATE = "broken"
        return None
    if proc.returncode != 0:
        _LIBROSA_STATE = "broken"
        return None
    try:
        payload = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        _LIBROSA_STATE = "broken"
        return None
    bpm = _as_float(payload.get("bpm"))
    if not bpm:
        _LIBROSA_STATE = "broken"
        return None
    _LIBROSA_STATE = "ok"
    return round(bpm, 2)


def _autocorr_bpm(samples: np.ndarray, sample_rate: int = 16000) -> float | None:
    """Cheap tempo estimate from the onset-strength envelope (60..90 s max)."""
    if samples.size < sample_rate * 3:
        return None
    window = 1024
    hop = 512
    audio = samples[: sample_rate * 90].astype(np.float64)
    squares = audio * audio
    cumulative = np.concatenate(([0.0], np.cumsum(squares)))
    starts = np.arange(0, audio.size - window + 1, hop)
    if starts.size < 32:
        return None
    energy = np.sqrt((cumulative[starts + window] - cumulative[starts]) / window)
    onset = np.maximum(0.0, np.diff(energy))
    if onset.size < 32 or float(onset.std()) < 1e-7:
        return None
    envelope = onset - onset.mean()
    autocorr = np.correlate(envelope, envelope, mode="full")[envelope.size - 1:]
    frame_rate = sample_rate / hop
    lag_min = max(1, int(round(frame_rate * 60.0 / 200.0)))
    lag_max = min(autocorr.size - 1, int(round(frame_rate * 60.0 / 50.0)))
    if lag_max <= lag_min:
        return None
    segment = autocorr[lag_min:lag_max + 1]
    lag = int(np.argmax(segment)) + lag_min
    if autocorr[lag] <= 0:
        return None
    bpm = 60.0 * frame_rate / lag
    while bpm < 70.0:
        bpm *= 2.0
    while bpm > 180.0:
        bpm /= 2.0
    return round(bpm, 2)


def detect_bpm(mono_path: Path, samples: np.ndarray, duration: float | None) -> tuple[float | None, str]:
    if duration is not None and duration < BPM_MIN_AUDIO_SEC:
        return None, "skipped-short-audio"
    bpm = _librosa_bpm(mono_path)
    if bpm is not None:
        return bpm, "librosa"
    bpm = _autocorr_bpm(samples)
    if bpm is not None:
        return bpm, "autocorr"
    return None, "unavailable"


# ---------------------------------------------------------------------------
# Asset lifecycle
# ---------------------------------------------------------------------------
def _mono_path(asset_id: str) -> Path:
    return storage.asset_dir("audio", asset_id) / _MONO_NAME


def _meta_path(asset_id: str):
    return storage.asset_meta_path("audio", asset_id)


def load_meta(asset_id: str) -> dict:
    path = _meta_path(asset_id)
    meta = storage.read_json(path)
    if not isinstance(meta, dict) or not meta.get("assetId"):
        raise FileNotFoundError(f"音频资产不存在: {asset_id}")
    return meta


def save_upload(filename: str, data: bytes, points: int = DEFAULT_POINTS) -> dict:
    if not data:
        raise ValueError("上传文件为空")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise ValueError("文件超过 200MB 上限")
    asset_id = storage.new_id()
    stored = storage.save_upload("audio", asset_id, filename, data)
    warnings: list[str] = []
    try:
        info = _probe(stored)
        mono = _mono_path(asset_id)
        _decode_mono16k(stored, mono)
        samples = _read_mono16k(mono)
    except ValueError:
        # do not keep half-written assets around
        shutil.rmtree(storage.asset_dir("audio", asset_id), ignore_errors=True)
        raise
    duration = info["duration"]
    if duration is None and samples.size:
        duration = samples.size / 16000.0
        warnings.append("ffprobe 未提供时长，使用解码后的采样数估算")
    peaks = compute_peaks(samples, points)
    bpm, bpm_source = detect_bpm(mono, samples, duration)
    if bpm is None:
        warnings.append("BPM 自动检测不可用，请手动填写")
    summary = {
        "assetId": asset_id,
        "filename": storage.safe_name(filename),
        "durationSec": round(duration, 6) if duration is not None else None,
        "sampleRate": info["sampleRate"],
        "channels": info["channels"],
        "codec": info["codec"],
        "format": info["format"],
        "sizeBytes": len(data),
        "bpm": bpm,
        "bpmSource": bpm_source,
        "offsetSec": 0.0,
        "peaksPoints": len(peaks),
        "peaks": peaks,
        "warnings": warnings,
    }
    storage.write_json(_meta_path(asset_id), {
        **summary,
        "peaks": [],
        "storedFile": stored.name,
        "monoCache": _MONO_NAME,
        "uploadedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return summary


def get_peaks(asset_id: str, points: int = DEFAULT_POINTS) -> dict:
    points = max(MIN_POINTS, min(MAX_POINTS, int(points)))
    load_meta(asset_id)
    source = storage.find_source("audio", asset_id)
    if source is None:
        raise FileNotFoundError(f"音频资产源文件不存在: {asset_id}")
    mono = _mono_path(asset_id)
    if not mono.is_file():
        _decode_mono16k(source, mono)
    samples = _read_mono16k(mono)
    return {"points": points, "peaks": compute_peaks(samples, points)}


def set_bpm(asset_id: str, bpm: float, offset_sec: float = 0.0) -> dict:
    meta = load_meta(asset_id)
    meta["bpm"] = round(float(bpm), 3)
    meta["bpmSource"] = "manual"
    meta["offsetSec"] = float(offset_sec)
    meta["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    storage.write_json(_meta_path(asset_id), meta)
    return {"ok": True}


def get_source_file(asset_id: str) -> tuple[Path, str]:
    source = storage.find_source("audio", asset_id)
    if source is None:
        raise FileNotFoundError(f"音频资产不存在: {asset_id}")
    media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    return source, media_type


def list_audio(asset_id: str) -> dict:
    meta = load_meta(asset_id)
    return {key: meta.get(key) for key in (
        "assetId", "filename", "durationSec", "sampleRate", "channels", "codec",
        "format", "sizeBytes", "bpm", "bpmSource", "offsetSec", "peaksPoints",
    )}
