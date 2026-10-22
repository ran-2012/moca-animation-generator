"""Render/export tests (task-9).

Runs under the vendored pytest (``$env:PYTHONPATH="$PWD\\vendor"``) and also
standalone:

    python -m pytest tests/test_render.py -q
    python tests/test_render.py

The integration test uses a **real** bake cache from
``data/assets/psd/*/cache/`` and exercises the HTTP API on 127.0.0.1:8795
(8787 belongs to the Lead's integration server).  When no bake cache exists
the integration tests skip with an explicit ``SKIP`` message.

Runtime directories are redirected to ``backend/.test_data_render_<id>`` --
never ``tempfile`` / ``tmp_path`` (their 0o700 ACL is unreadable inside the
Windows sandbox) and never the real ``data/assets`` tree.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
VENDOR_DIR = BACKEND_DIR / "vendor"
for _candidate in (str(BACKEND_DIR), str(VENDOR_DIR)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from app import config  # noqa: E402
from app.models.render import RenderRequest, TimelineIn  # noqa: E402
from app.services import render_service  # noqa: E402

REAL_ASSETS = config.PROJECT_ROOT / "data" / "assets"
PORT = 8795
BASE_URL = f"http://127.0.0.1:{PORT}"
SERVER_START_TIMEOUT = 20.0


# ---------------------------------------------------------------------------
# real bake-cache discovery
# ---------------------------------------------------------------------------


def _asset_media_file(url: object) -> Path | None:
    if not isinstance(url, str) or not url.startswith("/media/"):
        return None
    relative = url[len("/media/"):]
    if not relative or ".." in Path(relative).parts:
        return None
    return REAL_ASSETS / Path(*Path(relative).parts)


def _manifest_files_ok(manifest: dict) -> bool:
    base = (manifest.get("base") or {}).get("url")
    base_file = _asset_media_file(base)
    if base_file is None or not base_file.is_file():
        return False
    patches = manifest.get("patches")
    if not isinstance(patches, dict) or not patches:
        return False
    for patch in patches.values():
        if not isinstance(patch, dict):
            return False
        path = _asset_media_file(patch.get("url"))
        if path is None or not path.is_file():
            return False
    return True


def _find_manifest() -> tuple[str, dict] | None:
    root = REAL_ASSETS / "psd"
    if not root.is_dir():
        return None
    for path in sorted(root.glob("*/cache/manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict) or not _manifest_files_ok(manifest):
            continue
        patches = manifest.get("patches") or {}
        if not any(key.startswith("mouth.") for key in patches):
            continue
        if not any(key.startswith("eyes.") for key in patches):
            continue
        return path.parents[1].name, manifest
    return None


# ---------------------------------------------------------------------------
# HTTP / server helpers
# ---------------------------------------------------------------------------


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http(method: str, path: str, payload: dict | None = None,
          timeout: float = 180.0) -> tuple[int, bytes, dict]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        BASE_URL + path, data=body, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _json(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))


def _wait_for(job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        status, raw, _ = _http("GET", f"/api/render/{job_id}")
        assert status == 200, raw[:400]
        last = _json(raw)
        if last["status"] in ("done", "failed"):
            return last
        time.sleep(0.1)
    raise AssertionError(f"渲染任务超时：{last}")


def _timeline(duration: float = 1.0) -> dict:
    return {
        "fps": 60,
        "duration": duration,
        "frames": [
            {"t": 0.0, "viseme": "closed"},
            {"t": 0.15, "viseme": "a"},
            {"t": 0.45, "viseme": "i"},
            {"t": 0.70, "viseme": "o"},
            {"t": 0.90, "viseme": "u"},
        ],
    }


def _restore_paths(originals: dict) -> None:
    for name, value in originals.items():
        setattr(config, name, value)


def _remove_root(root: Path) -> None:
    import gc

    gc.collect()
    for _ in range(20):
        try:
            shutil.rmtree(root)
            return
        except OSError:
            time.sleep(0.2)
    print(f"[test_render] 警告：临时目录未能删除，可手动清理 {root}")


@pytest.fixture(scope="module")
def server() -> dict:
    info = _find_manifest()
    if info is None:
        pytest.skip("SKIP: 没有可用的 PSD bake 缓存（data/assets/psd/*/cache/manifest.json）")
    asset_id, manifest = info
    if not _port_free(PORT):
        pytest.skip(f"SKIP: 端口 {PORT} 已被占用，无法启动测试服务器")

    try:
        import uvicorn  # noqa: F401
    except ImportError:
        pytest.skip("SKIP: uvicorn 不可用")

    originals = {
        name: getattr(config, name)
        for name in ("DATA_DIR", "ASSETS_DIR", "PROJECTS_DIR", "SETTINGS_FILE")
    }
    root = BACKEND_DIR / f".test_data_render_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True)
    config.DATA_DIR = root / "data"
    config.ASSETS_DIR = REAL_ASSETS
    config.PROJECTS_DIR = root / "data" / "projects"
    config.SETTINGS_FILE = root / "data" / "settings.json"
    config.ensure_dirs()

    import uvicorn

    server_instance = None
    thread = None
    try:
        # Imported after the config redirect so the /media mount points at the
        # real asset tree while render outputs land in the throw-away root.
        import app.main as main_module

        server_instance = uvicorn.Server(uvicorn.Config(
            main_module.app,
            host="127.0.0.1",
            port=PORT,
            log_level="warning",
            access_log=False,
        ))
        thread = threading.Thread(target=server_instance.run, name="test-render-uvicorn",
                                  daemon=True)
        thread.start()
        deadline = time.time() + SERVER_START_TIMEOUT
        while time.time() < deadline:
            if getattr(server_instance, "started", False):
                break
            if not thread.is_alive():
                break
            time.sleep(0.05)
        if not getattr(server_instance, "started", False):
            raise RuntimeError("uvicorn 未能在限定时间内启动")
    except Exception as exc:  # noqa: BLE001 - skip cleanly
        if server_instance is not None:
            server_instance.should_exit = True
        if thread is not None:
            thread.join(5)
        _restore_paths(originals)
        _remove_root(root)
        pytest.skip(f"SKIP: 无法在 127.0.0.1:{PORT} 启动测试服务器：{exc}")

    env = {
        "assetId": asset_id,
        "manifest": manifest,
        "root": root,
        "server": server_instance,
        "thread": thread,
        "originals": originals,
    }
    try:
        yield env
    finally:
        render_service.wait_until_idle(30)
        if server_instance is not None:
            server_instance.should_exit = True
        if thread is not None:
            thread.join(10)
        _restore_paths(originals)
        _remove_root(root)


# ---------------------------------------------------------------------------
# integration tests (real manifest, HTTP API on 8795)
# ---------------------------------------------------------------------------


def test_png_zip_export_with_real_manifest(server: dict) -> None:
    manifest = server["manifest"]
    payload = {
        "psdAssetId": server["assetId"],
        "timeline": _timeline(1.0),
        "blinks": [{"t": 0.35, "duration": 0.15}],
        "startSec": 0.0,
        "durationSec": 1.0,
        "outFps": 12,
        "width": 480,
        "format": "png_zip",
    }
    status, raw, _ = _http("POST", "/api/render", payload)
    assert status == 200, raw[:400]
    created = _json(raw)
    job_id = created["jobId"]
    assert job_id.startswith("r_") and len(job_id) == 14
    assert created["status"] == "queued"
    assert created["frameCount"] == 12
    assert created["width"] == 480
    expected_height = round(manifest["height"] * 480 / manifest["width"])
    assert created["height"] % 2 == 0
    assert abs(created["height"] - expected_height) <= 1
    assert created["format"] == "png_zip"
    assert created["fps"] == 12.0

    job = _wait_for(job_id, timeout=120)
    assert job["status"] == "done", job.get("error")
    assert job["progress"] == 1.0
    assert job["doneFrames"] == 12
    assert job["error"] is None
    assert job["fileUrl"] == f"/api/render/{job_id}/download"
    assert job["fileName"] == "frames.zip"
    assert job["elapsedSec"] >= 0.0

    # job metadata is persisted next to the artifact
    job_json = server["root"] / "data" / "renders" / job_id / "job.json"
    assert job_json.is_file()
    persisted = json.loads(job_json.read_text(encoding="utf-8"))
    assert persisted["status"] == "done"
    assert persisted["params"]["psdAssetId"] == server["assetId"]

    status, archive_bytes, headers = _http("GET", job["fileUrl"])
    assert status == 200
    assert headers.get("content-type", "").startswith("application/zip")
    assert archive_bytes[:2] == b"PK"

    archive_path = server["root"] / "download.zip"
    archive_path.write_bytes(archive_bytes)
    with zipfile.ZipFile(archive_path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".png")]
        assert len(names) == 12
        assert names[0] == "frame_0000.png"
        assert names[-1] == "frame_0011.png"
        frames = [archive.read(name) for name in names]
    assert len(set(frames)) > 1  # different visemes must produce different pixels

    first_path = server["root"] / "frame_0000.png"
    first_path.write_bytes(frames[0])
    with Image.open(first_path) as image:
        assert image.mode == "RGBA"
        assert image.size == (created["width"], created["height"])
        low, high = image.getchannel("A").getextrema()
        assert low == 0 and high == 255, (low, high)


def test_render_validation_errors(server: dict) -> None:
    base_payload = {
        "psdAssetId": server["assetId"],
        "timeline": _timeline(1.0),
        "durationSec": 1.0,
        "format": "png_zip",
    }

    status, raw, _ = _http("POST", "/api/render", {
        **base_payload, "psdAssetId": "deadbeef0000",
    })
    assert status == 404
    assert "烘焙" in _json(raw)["detail"]

    status, _, _ = _http("POST", "/api/render", {**base_payload, "width": 100})
    assert status == 422  # below the 200 px contract minimum

    status, _, _ = _http("POST", "/api/render", {**base_payload, "durationSec": 301})
    assert status == 422  # above the 300 s cap

    status, _, _ = _http("POST", "/api/render", {**base_payload, "format": "gif"})
    assert status == 422

    status, _, _ = _http("POST", "/api/render", {**base_payload, "outFps": 120})
    assert status == 422  # above the 60 fps cap

    status, raw, _ = _http("POST", "/api/render", {
        **base_payload, "durationSec": 300, "outFps": 60,
    })
    assert status == 400
    assert "6000" in _json(raw)["detail"]

    status, raw, _ = _http("POST", "/api/render", {
        **base_payload, "format": "mp4", "background": "not-a-colour",
    })
    assert status == 400
    assert "背景色" in _json(raw)["detail"]

    status, raw, _ = _http("POST", "/api/render", {
        **base_payload, "brow": "definitely-not-a-brow",
    })
    assert status == 400
    assert "brow" in _json(raw)["detail"]

    status, _, _ = _http("GET", "/api/render/r_ffffffffffff")
    assert status == 404
    status, _, _ = _http("GET", "/api/render/not-a-job")
    assert status == 404


def test_duration_defaults_to_timeline_duration(server: dict) -> None:
    payload = {
        "psdAssetId": server["assetId"],
        "timeline": _timeline(0.5),
        "outFps": 6,
        "width": 200,
        "format": "png_zip",
    }
    status, raw, _ = _http("POST", "/api/render", payload)
    assert status == 200, raw[:400]
    created = _json(raw)
    assert created["frameCount"] == 3
    job = _wait_for(created["jobId"], timeout=60)
    assert job["status"] == "done", job.get("error")


def test_finished_job_survives_in_memory_reset(server: dict) -> None:
    """A page reload (or backend restart) must still answer from job.json."""
    payload = {
        "psdAssetId": server["assetId"],
        "timeline": _timeline(0.25),
        "durationSec": 0.25,
        "outFps": 8,
        "width": 200,
        "format": "png_zip",
    }
    status, raw, _ = _http("POST", "/api/render", payload)
    assert status == 200, raw[:400]
    job_id = _json(raw)["jobId"]
    assert _wait_for(job_id, timeout=60)["status"] == "done"

    with render_service._JOBS_LOCK:  # simulate a fresh process
        render_service._JOBS.clear()

    status, raw, _ = _http("GET", f"/api/render/{job_id}")
    assert status == 200
    job = _json(raw)
    assert job["status"] == "done"
    assert job["fileUrl"] == f"/api/render/{job_id}/download"
    assert render_service.output_path(job_id) is not None


@pytest.mark.parametrize(("fmt", "suffix"), [
    ("prores4444", ".mov"),
    ("webm_alpha", ".webm"),
    ("mp4", ".mp4"),
])
def test_video_formats(server: dict, fmt: str, suffix: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("SKIP: 未找到 ffmpeg / ffprobe")

    payload = {
        "psdAssetId": server["assetId"],
        "timeline": _timeline(0.5),
        "startSec": 0.0,
        "durationSec": 0.5,
        "outFps": 12,
        "width": 480,
        "format": fmt,
        "background": "#336699",
    }
    status, raw, _ = _http("POST", "/api/render", payload)
    assert status == 200, raw[:400]
    job = _wait_for(_json(raw)["jobId"], timeout=180)
    assert job["status"] == "done", job.get("error")

    status, video_bytes, headers = _http("GET", job["fileUrl"])
    assert status == 200 and len(video_bytes) > 0
    artifact = server["root"] / f"video_{fmt}{suffix}"
    artifact.write_bytes(video_bytes)

    probe = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-print_format", "json",
         "-show_streams", str(artifact)],
        capture_output=True, text=True, timeout=120,
    )
    assert probe.returncode == 0, probe.stderr
    stream = json.loads(probe.stdout)["streams"][0]

    if fmt == "prores4444":
        assert stream["codec_name"] == "prores"
        assert str(stream["pix_fmt"]).startswith("yuva444")
    elif fmt == "webm_alpha":
        assert stream["codec_name"] == "vp9"
        tags = {str(key).lower(): value for key, value in (stream.get("tags") or {}).items()}
        assert str(tags.get("alpha_mode", "")) == "1"
    else:
        assert stream["codec_name"] == "h264"
        assert stream["pix_fmt"] == "yuv420p"

    # Decode frame 0 back to RGBA and prove the alpha channel survived.  WebM
    # stores VP9 alpha as a side channel that only libvpx-vp9 decodes (ffmpeg's
    # native vp9 decoder silently drops it).
    decoded = server["root"] / f"decoded_{fmt}.png"
    decode_command = [ffmpeg, "-y", "-v", "error"]
    if fmt == "webm_alpha":
        decode_command += ["-c:v", "libvpx-vp9"]
    decode_command += ["-i", str(artifact), "-frames:v", "1", str(decoded)]
    decode = subprocess.run(decode_command, capture_output=True, timeout=120)
    assert decode.returncode == 0, decode.stderr.decode("utf-8", "replace")
    with Image.open(decoded) as image:
        low, high = image.convert("RGBA").getchannel("A").getextrema()
    if fmt == "mp4":
        assert (low, high) == (255, 255)  # flattened over the background colour
    else:
        assert low == 0 and high == 255, (low, high)


# ---------------------------------------------------------------------------
# unit tests (no server / no disk writes)
# ---------------------------------------------------------------------------


def _tiny_assets() -> render_service.PreparedAssets:
    transparent = Image.new("RGBA", (2, 2), (0, 0, 0, 255))
    return render_service.PreparedAssets(
        width=10,
        height=10,
        base=Image.new("RGBA", (10, 10), (0, 0, 0, 0)),
        patches={
            "mouth.closed": (transparent, (0, 0)),
            "mouth.a": (Image.new("RGBA", (2, 2), (255, 0, 0, 255)), (0, 0)),
            "mouth.openLarge": (Image.new("RGBA", (2, 2), (255, 255, 0, 255)), (0, 0)),
            "eyes.open": (Image.new("RGBA", (2, 2), (0, 255, 0, 255)), (5, 5)),
            "eyes.blink": (Image.new("RGBA", (2, 2), (0, 0, 255, 255)), (5, 5)),
            "sweat.drop": (Image.new("RGBA", (1, 1), (0, 255, 255, 255)), (9, 0)),
        },
        zorder=["mouth", "eyes", "sweat"],
        default_state={"mouth": "closed", "eyes": "open", "sweat": "off"},
        source_width=10,
        source_height=10,
    )


def test_even_size_and_media_path_safety() -> None:
    assert render_service.even_size(2480, 3500, 1080) == (1080, 1524)
    assert render_service.even_size(2480, 3500, 480) == (480, 678)
    assert render_service.even_size(100, 120, 100) == (200, 240)  # clamped + even
    assert render_service.media_path("/media/psd/abc/cache/base.png") is not None
    assert render_service.media_path("/media/../secret.png") is None
    assert render_service.media_path("C:/Windows/win.ini") is None
    assert render_service.media_path("/tmp/base.png") is None
    assert render_service.media_path("") is None


def test_frame_source_viseme_and_blink_selection() -> None:
    assets = _tiny_assets()
    timeline = {"frames": [
        {"t": 1.0, "viseme": "a"},
        {"t": 0.0, "viseme": "closed"},
    ]}
    source = render_service.FrameSource(timeline, [], assets)
    assert source.state_at(0.0)["mouth"] == "mouth.closed"
    assert source.state_at(0.999)["mouth"] == "mouth.closed"
    assert source.state_at(1.0)["mouth"] == "mouth.a"
    assert source.state_at(9.0)["mouth"] == "mouth.a"

    # before the first keyframe the first (sorted) frame wins
    early = render_service.FrameSource({"frames": [{"t": 5.0, "viseme": "a"}]},
                                       [], assets)
    assert early.state_at(0.0)["mouth"] == "mouth.a"

    # overlapping blinks: a long blink must stay active after a short one ends
    blinks = [{"t": 2.0, "duration": 0.1}, {"t": 2.05, "duration": 0.5}]
    blink_source = render_service.FrameSource(timeline, blinks, assets)
    assert blink_source.state_at(2.04)["eyes"] == "eyes.blink"
    assert blink_source.state_at(2.3)["eyes"] == "eyes.blink"
    assert blink_source.state_at(2.6)["eyes"] == "eyes.open"

    composed = source.compose(1.0)
    assert composed.mode == "RGBA" and composed.size == (10, 10)
    assert composed.getpixel((0, 0)) == (255, 0, 0, 255)
    assert composed.getpixel((5, 5)) == (0, 255, 0, 255)


def test_frame_source_uses_mouth_pose_and_animation_tracks() -> None:
    assets = _tiny_assets()
    timeline = {
        "frames": [
            {"t": 0.0, "viseme": "a", "mouthPose": "openLarge"},
            {"t": 1.0, "viseme": "a", "mouthPose": "wide"},
        ],
        "tracks": {
            "sweat": [
                {"t": 0.0, "state": "off"},
                {"t": 0.5, "state": "drop"},
                {"t": 1.5, "state": "off"},
            ],
        },
    }
    source = render_service.FrameSource(timeline, [], assets)

    assert source.state_at(0.0)["mouth"] == "mouth.openLarge"
    assert "sweat" not in source.state_at(0.0)
    assert source.state_at(0.75)["sweat"] == "sweat.drop"
    assert source.state_at(1.0)["mouth"] == "mouth.a"
    assert "sweat" not in source.state_at(1.5)

    no_effects = render_service.FrameSource({"frames": timeline["frames"]}, [], assets)
    assert "sweat" not in no_effects.state_at(0.0)

    delayed_effect = render_service.FrameSource({
        "frames": timeline["frames"],
        "tracks": {"sweat": [{"t": 1.0, "state": "drop"}]},
    }, [], assets)
    assert "sweat" not in delayed_effect.state_at(0.5)
    assert delayed_effect.state_at(1.0)["sweat"] == "sweat.drop"


def test_frame_source_applies_beat_sway_without_changing_canvas_size() -> None:
    assets = _tiny_assets()
    assets.base.putpixel((2, 2), (255, 255, 255, 255))
    timeline = {"frames": [{"t": 0.0, "viseme": "closed"}]}
    disabled = render_service.FrameSource(timeline, [], assets)
    enabled = render_service.FrameSource(
        timeline,
        [],
        assets,
        sway={"enabled": True, "amplitude": 1, "frequency": 0.5, "offset": 0, "bpm": 120},
    )

    assert disabled.compose(0.25).tobytes() == disabled.compose_state(disabled.state_at(0.25)).tobytes()
    moved = enabled.compose(0.25)
    assert moved.size == (10, 10)
    assert moved.tobytes() != enabled.compose_state(enabled.state_at(0.25)).tobytes()

    edge_assets = _tiny_assets()
    edge_assets.base = Image.new("RGBA", (10, 10), (255, 255, 255, 255))
    edge_source = render_service.FrameSource(
        timeline,
        [],
        edge_assets,
        sway={"enabled": True, "amplitude": 1, "frequency": 0.5, "offset": 0, "bpm": 120},
    )
    edge_frame = edge_source.compose(0.25)
    assert edge_frame.getbbox() == (0, 0, 10, 10)


def test_frame_source_composes_static_layers_in_z_order() -> None:
    assets = render_service.PreparedAssets(
        width=10,
        height=10,
        base=Image.new("RGBA", (10, 10), (0, 0, 0, 0)),
        patches={},
        zorder=[],
        default_state={},
        source_width=10,
        source_height=10,
        layers={
            "back": (Image.new("RGBA", (10, 10), (0, 0, 255, 255)), (0, 0), 0),
            "front": (Image.new("RGBA", (2, 2), (255, 0, 0, 255)), (0, 0), 100),
        },
    )
    source = render_service.FrameSource({"frames": []}, [], assets)
    assert source.compose(0.0).getpixel((0, 0)) == (255, 0, 0, 255)

    hidden = render_service.FrameSource({"frames": []}, [], assets, hidden_layers=["front"])
    assert hidden.compose(0.0).getpixel((0, 0)) == (0, 0, 255, 255)


def test_ffmpeg_command_flags() -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("SKIP: 未找到 ffmpeg")
    prores = render_service.build_ffmpeg_command("prores4444", 1080, 1524, 24, Path("x.mov"))
    assert "prores_ks" in prores
    assert prores[prores.index("-profile:v") + 1] == "4"
    assert "yuva444p10le" in prores

    webm = render_service.build_ffmpeg_command("webm_alpha", 720, 1016, 24, Path("x.webm"))
    assert "libvpx-vp9" in webm and "yuva420p" in webm

    mp4 = render_service.build_ffmpeg_command("mp4", 720, 1016, 24, Path("x.mp4"))
    assert "libx264" in mp4 and "yuv420p" in mp4 and "rgb24" in mp4


def test_render_request_limits_are_enforced() -> None:
    request = RenderRequest(
        psdAssetId="a" * 12,
        timeline=TimelineIn(duration=60.0, frames=[]),
        durationSec=300.0,
        outFps=60.0,
        width=1080,
    )
    with pytest.raises(render_service.RenderError) as excinfo:
        render_service._validate(request)
    assert "6000" in excinfo.value.detail


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
