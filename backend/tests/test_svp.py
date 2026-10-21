"""SVP domain tests (CONTRACT.md §7): upload summary + single-track timeline.

Runs under the vendored pytest and also standalone:

    python -m pytest tests/test_svp.py -q
    python tests/test_svp.py

Uses the read-only ``流沙.svp`` from the workspace root.  Runtime directories are
redirected to a throw-away folder under ``backend/`` (never ``tempfile``: the
Windows sandbox turns tempfile's 0o700 ACL into an unreadable explicit ACL).
"""

from __future__ import annotations

import atexit
import gc
import hashlib
import json
import shutil
import sys
import time
import traceback
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

WORKSPACE = BACKEND_DIR.parents[1]
SVP_FILE = WORKSPACE / "流沙.svp"

from app import config  # noqa: E402
from app.services import svp_service  # noqa: E402

_ORIGINAL_PATHS = {
    "DATA_DIR": config.DATA_DIR,
    "ASSETS_DIR": config.ASSETS_DIR,
    "PROJECTS_DIR": config.PROJECTS_DIR,
    "SETTINGS_FILE": config.SETTINGS_FILE,
}
_ENV: dict | None = None


def _make_env() -> dict:
    root = BACKEND_DIR / f".test_data_svp_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True)
    config.DATA_DIR = root / "data"
    config.ASSETS_DIR = root / "data" / "assets"
    config.PROJECTS_DIR = root / "data" / "projects"
    config.SETTINGS_FILE = root / "data" / "settings.json"
    config.ensure_dirs()
    assert SVP_FILE.is_file(), f"找不到测试素材: {SVP_FILE}"
    original_hash = hashlib.sha1(SVP_FILE.read_bytes()).hexdigest()
    upload = svp_service.save_upload(SVP_FILE.name, SVP_FILE.read_bytes())
    return {
        "root": root,
        "upload": upload,
        "assetId": upload["assetId"],
        "sourceHash": original_hash,
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
    svp_service._PROJECT_CACHE.clear()
    gc.collect()
    for _ in range(10):
        try:
            shutil.rmtree(_ENV["root"])
            return
        except OSError:
            time.sleep(0.2)
    print(f"[test_svp] 警告：临时目录未能删除，可手动清理 {_ENV['root']}")


atexit.register(_cleanup)


def _asset_id() -> str:
    return _env()["assetId"]


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------
def test_upload_returns_six_tracks_with_measured_ranges():
    upload = _env()["upload"]
    assert len(upload["assetId"]) == 12
    assert upload["filename"] == SVP_FILE.name
    assert upload["version"] == "196"
    tracks = upload["tracks"]
    assert len(tracks) == 6
    assert [track["index"] for track in tracks] == [0, 1, 2, 3, 4, 5]
    assert [track["isInstrumental"] for track in tracks] == [True] * 4 + [False] * 2
    assert [track["isVocal"] for track in tracks] == [False] * 4 + [True] * 2

    track4, track5 = tracks[4], tracks[5]
    assert track4["noteCount"] == 435 and track4["isInstrumental"] is False
    assert abs(track4["rangeStartSec"] - 15.789474) < 0.001
    assert abs(track4["rangeEndSec"] - 238.815789) < 0.001
    assert len(track4["groups"]) == 9
    assert track5["noteCount"] == 220 and track5["isInstrumental"] is False
    assert abs(track5["rangeStartSec"] - 84.473684) < 0.001
    assert abs(track5["rangeEndSec"] - 238.618421) < 0.001
    assert len(track5["groups"]) == 7
    # drums need no mouth: instrumental tracks carry no notes in this project
    assert [track["noteCount"] for track in tracks[:4]] == [0, 0, 0, 0]

    asset_dir = config.ASSETS_DIR / "svp" / upload["assetId"]
    assert (asset_dir / "source.svp").is_file()
    meta = json.loads((asset_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["assetId"] == upload["assetId"]
    assert meta["trackCount"] == 6


def test_upload_does_not_modify_the_original_svp():
    env = _env()
    current = hashlib.sha1(SVP_FILE.read_bytes()).hexdigest()
    assert current == env["sourceHash"], "上传/解析不得改写原始 .svp"


def test_upload_rejects_invalid_payloads():
    for bad in (b"", b"{not json", b'"just a string"', b'{"tracks": 3}'):
        try:
            svp_service.save_upload("bad.svp", bad)
        except ValueError:
            continue
        raise AssertionError(f"非法 SVP 负载应被拒绝: {bad!r}")


# ---------------------------------------------------------------------------
# timeline: track 5
# ---------------------------------------------------------------------------
def test_track5_timeline_matches_verified_numbers():
    result = svp_service.generate_timeline(_asset_id(), 5, 60)
    timeline = result["timeline"]
    stats = result["stats"]

    assert timeline["source"] == {
        "kind": "svp", "assetId": _asset_id(), "trackIndex": 5}
    assert timeline["fps"] == 60
    assert abs(timeline["duration"] - 239.118421) < 0.002
    frames = timeline["frames"]
    assert len(frames) == 14348
    assert frames[0] == {"t": 0.0, "viseme": "closed", "openness": 0.0}
    assert frames[1]["t"] == 0.016667
    assert all(frame["viseme"] in svp_service.VISEMES for frame in frames)
    assert all(0.0 <= frame["openness"] <= 1.0 for frame in frames)
    assert len(timeline["notes"]) == 220
    assert timeline["mouthRuns"]

    assert stats["lyricCoveragePercent"] == 100.0
    assert stats["unmappedLyricNotes"] == 0
    assert stats["distinctLyricTokens"] == 97
    boundary = stats["noteBoundaryCheck"]
    assert boundary["checked"] == 183
    assert boundary["matched"] == 183
    assert boundary["ratioPercent"] == 100.0
    assert result["cached"] is False
    assert result["blinks"]


def test_track5_timeline_is_single_track_only():
    """No merged primary/harmony logic: track 5 starts singing at 84.47 s."""
    timeline = svp_service.generate_timeline(_asset_id(), 5, 60)["timeline"]
    first_moving = next(frame for frame in timeline["frames"]
                        if frame["viseme"] != "closed")
    assert 84.3 <= first_moving["t"] <= 84.6, first_moving
    # track 5's groups never appear when track 4 is requested
    track5_groups = {group["name"] for group in
                     _env()["upload"]["tracks"][5]["groups"]}
    assert all(note["group"] in track5_groups for note in timeline["notes"])


def test_blinks_avoid_note_onsets_by_two_frames():
    result = svp_service.generate_timeline(_asset_id(), 5, 60)
    blinks = result["blinks"]
    assert len(blinks) > 10
    onsets = [note["startSec"] for note in result["timeline"]["notes"]]
    window = 2.0 / 60.0
    for blink in blinks:
        assert 0.0 <= blink["t"] <= result["timeline"]["duration"]
        assert blink["duration"] > 0
        nearest = min(abs(blink["t"] - onset) for onset in onsets)
        assert nearest > window - 1e-4, f"眨眼 {blink['t']} 落在音符 onset ±2 帧内"


def test_timeline_cache_is_written_and_reused():
    asset_id = _asset_id()
    first = svp_service.generate_timeline(asset_id, 5, 60)
    cache_file = config.ASSETS_DIR / "svp" / asset_id / "timeline-track5-60.json"
    assert cache_file.is_file()
    started = time.perf_counter()
    second = svp_service.generate_timeline(asset_id, 5, 60)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert second["cached"] is True
    assert len(second["timeline"]["frames"]) == len(first["timeline"]["frames"])
    assert elapsed_ms < 2000.0


def test_track4_timeline_matches_measured_numbers():
    result = svp_service.generate_timeline(_asset_id(), 4, 60)
    timeline = result["timeline"]
    assert abs(timeline["duration"] - 239.315789) < 0.002
    assert len(timeline["frames"]) == 14359
    assert len(timeline["notes"]) == 435
    assert result["stats"]["lyricCoveragePercent"] == 100.0
    boundary = result["stats"]["noteBoundaryCheck"]
    assert boundary["matched"] == boundary["checked"] == 356
    assert boundary["ratioPercent"] == 100.0


def test_timeline_supports_other_fps():
    result = svp_service.generate_timeline(_asset_id(), 5, 30)
    timeline = result["timeline"]
    assert timeline["fps"] == 30
    assert len(timeline["frames"]) == 7174  # ceil(239.118421 * 30)
    assert timeline["frames"][1]["t"] == 0.033333
    cache_file = (config.ASSETS_DIR / "svp" / _asset_id()
                  / "timeline-track5-30.json")
    assert cache_file.is_file()


def test_timeline_rejects_bad_parameters():
    asset_id = _asset_id()
    for track_index in (6, 99, -1):
        try:
            svp_service.generate_timeline(asset_id, track_index, 60)
        except IndexError:
            continue
        raise AssertionError(f"不存在的轨道应报错: {track_index}")
    for fps in (0, -5, 1000):
        try:
            svp_service.generate_timeline(asset_id, 5, fps)
        except ValueError:
            continue
        raise AssertionError(f"非法 fps 应报错: {fps}")
    try:
        svp_service.generate_timeline("deadbeef0000", 5, 60)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("不存在的资产应报 404/FileNotFoundError")


def test_list_tracks_round_trips_upload_summary():
    info = svp_service.list_tracks(_asset_id())
    assert info["assetId"] == _asset_id()
    assert info["version"] == "196"
    assert [track["noteCount"] for track in info["tracks"]] == [
        0, 0, 0, 0, 435, 220]


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
