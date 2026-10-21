"""Audio domain tests (CONTRACT.md §7): upload, peaks, BPM storage, file lookup.

Runs under the vendored pytest and also standalone:

    python -m pytest tests/test_audio.py -q
    python tests/test_audio.py

A 3 s sine WAV is generated with the standard library so the test does not
depend on extra fixture files.  Runtime directories are redirected to a
throw-away folder under ``backend/`` (not ``tempfile`` -- its 0o700 ACL is
unreadable inside the Windows sandbox).
"""

from __future__ import annotations

import atexit
import gc
import hashlib
import json
import math
import shutil
import sys
import time
import traceback
import uuid
import wave
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import config  # noqa: E402
from app.services import audio_service  # noqa: E402

_ORIGINAL_PATHS = {
    "DATA_DIR": config.DATA_DIR,
    "ASSETS_DIR": config.ASSETS_DIR,
    "PROJECTS_DIR": config.PROJECTS_DIR,
    "SETTINGS_FILE": config.SETTINGS_FILE,
}
_ENV: dict | None = None


def _write_sine_wav(path: Path, seconds: float = 3.0,
                    rate: int = 22050, freq: float = 440.0) -> None:
    count = int(rate * seconds)
    samples = np.array(
        [0.5 * math.sin(2.0 * math.pi * freq * index / rate) for index in range(count)],
        dtype=np.float64,
    )
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())


def _make_env() -> dict:
    root = BACKEND_DIR / f".test_data_audio_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True)
    config.DATA_DIR = root / "data"
    config.ASSETS_DIR = root / "data" / "assets"
    config.PROJECTS_DIR = root / "data" / "projects"
    config.SETTINGS_FILE = root / "data" / "settings.json"
    config.ensure_dirs()
    wav_path = root / "sine3s.wav"
    _write_sine_wav(wav_path)
    data = wav_path.read_bytes()
    summary = audio_service.save_upload("sine3s.wav", data)
    return {
        "root": root,
        "wavPath": wav_path,
        "wavSize": len(data),
        "wavSha1": hashlib.sha1(data).hexdigest(),
        "summary": summary,
        "assetId": summary["assetId"],
    }


def _env() -> dict:
    global _ENV
    if _ENV is None:
        _ENV = _make_env()
    return _ENV


def _cleanup() -> None:
    for key, value in _ORIGINAL_PATHS.items():
        setattr(config, key, value)
    if _ENV is None:
        return
    gc.collect()
    for _ in range(10):
        try:
            shutil.rmtree(_ENV["root"])
            return
        except OSError:
            time.sleep(0.2)
    print(f"[test_audio] 警告：临时目录未能删除，可手动清理 {_ENV['root']}")


atexit.register(_cleanup)


def test_upload_probes_metadata_and_returns_peaks():
    summary = _env()["summary"]
    assert len(summary["assetId"]) == 12
    assert summary["filename"] == "sine3s.wav"
    assert abs(summary["durationSec"] - 3.0) < 0.05
    assert summary["sampleRate"] == 22050
    assert summary["channels"] == 1
    assert summary["codec"] == "pcm_s16le"
    assert summary["format"] == "wav"
    assert summary["sizeBytes"] == _env()["wavSize"]
    assert summary["offsetSec"] == 0.0
    assert summary["peaksPoints"] == 2000
    peaks = summary["peaks"]
    assert len(peaks) == 2000
    assert all(isinstance(value, float) and 0.0 <= value <= 1.0 for value in peaks)
    assert max(peaks) > 0.9  # normalized to the loudest bucket
    # 3 s is too short for a meaningful tempo estimate -> null, never an error
    assert summary["bpm"] is None
    assert summary["bpmSource"] == "skipped-short-audio"
    assert any("BPM" in warning for warning in summary["warnings"])

    asset_dir = config.ASSETS_DIR / "audio" / summary["assetId"]
    assert (asset_dir / "source.wav").is_file()
    assert (asset_dir / "mono16k.wav").is_file()
    meta = json.loads((asset_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["assetId"] == summary["assetId"]
    assert meta["durationSec"] is not None


def test_upload_does_not_rewrite_the_source_bytes():
    summary = _env()["summary"]
    stored = config.ASSETS_DIR / "audio" / summary["assetId"] / "source.wav"
    assert hashlib.sha1(stored.read_bytes()).hexdigest() == _env()["wavSha1"]


def test_upload_rejects_non_audio_bytes():
    for bad in (b"", b"definitely not audio", b"RIFF\x00\x00\x00\x00WAVE"):
        try:
            audio_service.save_upload("broken.wav", bad)
        except ValueError:
            continue
        raise AssertionError(f"非法音频应被拒绝: {bad[:16]!r}")


def test_get_peaks_resamples_and_clamps_points():
    asset_id = _env()["assetId"]
    result = audio_service.get_peaks(asset_id, 1200)
    assert result["points"] == 1200
    assert len(result["peaks"]) == 1200
    assert all(0.0 <= value <= 1.0 for value in result["peaks"])
    clamped = audio_service.get_peaks(asset_id, 1)
    assert clamped["points"] == audio_service.MIN_POINTS
    assert len(clamped["peaks"]) == audio_service.MIN_POINTS


def test_save_bpm_persists_to_meta():
    asset_id = _env()["assetId"]
    assert audio_service.set_bpm(asset_id, 76.5, 0.12) == {"ok": True}
    meta = audio_service.load_meta(asset_id)
    assert meta["bpm"] == 76.5
    assert meta["bpmSource"] == "manual"
    assert meta["offsetSec"] == 0.12
    listed = audio_service.list_audio(asset_id)
    assert listed["bpm"] == 76.5 and listed["offsetSec"] == 0.12
    # a fresh read from disk survives (no in-memory state involved)
    on_disk = json.loads(
        (config.ASSETS_DIR / "audio" / asset_id / "meta.json").read_text(encoding="utf-8"))
    assert on_disk["bpm"] == 76.5


def test_source_file_lookup_reports_media_type():
    asset_id = _env()["assetId"]
    path, media_type = audio_service.get_source_file(asset_id)
    assert path.is_file() and path.name == "source.wav"
    assert media_type == "audio/wav"


def test_missing_assets_raise_file_not_found():
    for call in (
        lambda: audio_service.get_peaks("deadbeef0000", 100),
        lambda: audio_service.set_bpm("deadbeef0000", 120.0),
        lambda: audio_service.get_source_file("deadbeef0000"),
        lambda: audio_service.load_meta("deadbeef0000"),
    ):
        try:
            call()
        except FileNotFoundError:
            continue
        raise AssertionError("不存在的音频资产应报 FileNotFoundError")


def test_compute_peaks_handles_silence_and_full_scale():
    silence = audio_service.compute_peaks(np.zeros(5000, dtype=np.float32), 100)
    assert silence == [0.0] * 100
    full = audio_service.compute_peaks(np.ones(5000, dtype=np.float32), 64)
    assert len(full) == 64
    assert all(abs(value - 1.0) < 1e-6 for value in full)


def test_upload_returns_distinct_asset_ids():
    env = _env()
    again = audio_service.save_upload("sine3s.wav", env["wavPath"].read_bytes())
    assert again["assetId"] != env["assetId"]


# ---------------------------------------------------------------------------
# bare-python runner (used when pytest is unavailable)
# ---------------------------------------------------------------------------
def _run_all() -> int:
    tests = [
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    started = time.perf_counter()
    for name, test in tests:
        t0 = time.perf_counter()
        try:
            test()
        except Exception:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name} ({time.perf_counter() - t0:.2f}s)")
            traceback.print_exc()
        else:
            print(f"PASS {name} ({time.perf_counter() - t0:.2f}s)")
    print(f"\n{len(tests) - failures} passed, {failures} failed in "
          f"{time.perf_counter() - started:.2f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
