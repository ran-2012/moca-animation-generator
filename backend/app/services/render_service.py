"""Transparent render/export service.

Consumes the one-time PSD bake (`base.png` + per-state patch PNGs +
`zorder` / `defaultState`) and renders animation frames with Pillow:

* ``png_zip``    – RGBA PNG sequence in a ZIP (FilmCraft friendly);
* ``prores4444`` – MOV / ProRes 4444 with alpha;
* ``webm_alpha`` – WebM / VP9 with alpha;
* ``mp4``        – H.264 flattened over a solid background colour.

Design notes
------------
* Jobs are queued and executed by **one** daemon worker thread, so two
  exports never fight over CPU / ffmpeg pipes.  Inside one PNG job the frames
  are composed + PNG-encoded on a thread pool (``MOCADIFF_RENDER_WORKERS``,
  default: every CPU core) and written to the archive in order.
* Every job lives in ``data/renders/<jobId>/`` with a ``job.json`` so
  ``GET /api/render/{id}`` still answers after a page reload (a process
  restart marks unfinished jobs as failed instead of hanging).
* Frames are composed by overlaying the manifest patches on a copy of the
  cached base; psd-tools is never touched here.  Identical expression states
  are memoised on two levels (the composed RGBA frame and the encoded PNG
  bytes, both bounded), which is what makes a 10 s / 1080p PNG export take
  seconds instead of minutes.
* All raster sizes are forced even: ProRes/H.264/VP9 reject odd dimensions
  on some builds.
* Media URLs from the manifest are resolved strictly below
  ``config.ASSETS_DIR``; absolute paths and ``..`` are rejected.
"""

from __future__ import annotations

import bisect
import io
import logging
import math
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from PIL import Image, ImageColor

from .. import config, storage
from ..models.render import RenderJobInfo, RenderRequest

log = logging.getLogger("mocadiff.render")

MAX_FRAMES = 6000
MAX_DURATION_SEC = 300.0
MIN_WIDTH = 200
MAX_WIDTH = 2480
MAX_OUT_FPS = 60.0
PNG_CACHE_BYTES = 96 * 1024 * 1024
# Composed pre-sway frames kept in memory (reused while a viseme/expression
# combination repeats, which is most of a song).
STATE_CACHE_BYTES = 192 * 1024 * 1024

DEFAULT_ZORDER = ["cheek", "mouth", "eyes", "brow"]
DEFAULT_STATE = {"mouth": "closed", "eyes": "open", "brow": "neutral", "cheek": "normal"}
OUTPUT_NAMES = {
    "png_zip": "frames.zip",
    "prores4444": "render.mov",
    "webm_alpha": "render.webm",
    "mp4": "render.mp4",
}
MEDIA_TYPES = {
    ".zip": "application/zip",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mp4": "video/mp4",
}

_JOB_ID_RE = re.compile(r"^r_[0-9a-f]{12}$")
_ASSET_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")


class RenderError(Exception):
    """Error with an HTTP status code and a human-readable Chinese message."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = int(status_code)
        self.detail = str(detail)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _even(value: float | int, minimum: int = 2) -> int:
    """Round to the nearest even integer (encoders require even dimensions)."""
    result = max(minimum, int(round(float(value))))
    return result if result % 2 == 0 else result + 1


def even_size(source_width: int, source_height: int, out_width: int) -> tuple[int, int]:
    """Scale a source canvas to ``out_width`` keeping the aspect, both sides even."""
    if source_width <= 0 or source_height <= 0:
        raise RenderError(400, "画布尺寸无效。")
    width = max(MIN_WIDTH, min(MAX_WIDTH, int(out_width)))
    width = _even(width)
    height = _even(source_height * (width / float(source_width)))
    return width, height


def renders_dir() -> Path:
    path = config.DATA_DIR / "renders"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_dir(job_id: str) -> Path:
    return renders_dir() / job_id


def _job_file(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def _valid_job_id(job_id: str) -> bool:
    return isinstance(job_id, str) and _JOB_ID_RE.fullmatch(job_id) is not None


def media_path(url: Any) -> Path | None:
    """Resolve a ``/media/...`` URL to a file strictly below ``ASSETS_DIR``."""
    if not isinstance(url, str) or not url.startswith("/media/"):
        return None
    relative = url[len("/media/"):]
    if not relative or "\\" in relative:
        return None
    parts = Path(relative).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        return None
    base = config.ASSETS_DIR.resolve()
    candidate = (base / Path(*parts)).resolve()
    if candidate == base or base not in candidate.parents:
        return None
    return candidate


def _require_media(url: Any, what: str) -> Path:
    path = media_path(url)
    if path is None or not path.is_file():
        raise RenderError(404, f"{what} 文件缺失，请重新烘焙该 PSD。")
    return path


# ---------------------------------------------------------------------------
# manifest + asset preparation
# ---------------------------------------------------------------------------


def _validate_asset_id(psd_asset_id: str) -> str:
    if not isinstance(psd_asset_id, str) or not _ASSET_ID_RE.fullmatch(psd_asset_id):
        raise RenderError(404, f"未知 PSD 资产：{psd_asset_id}")
    return psd_asset_id


def manifest_path(psd_asset_id: str) -> Path:
    _validate_asset_id(psd_asset_id)
    return config.ASSETS_DIR / "psd" / psd_asset_id / "cache" / "manifest.json"


def load_manifest(psd_asset_id: str) -> dict:
    """Read and validate the bake manifest (raises :class:`RenderError`)."""
    path = manifest_path(psd_asset_id)
    payload = storage.read_json(path)
    if not isinstance(payload, dict) or not payload.get("base"):
        raise RenderError(
            404,
            "该 PSD 还没有烘焙纹理（manifest 不存在）。请先在图层映射页点击“烘焙”。",
        )
    try:
        source_width = int(payload.get("width") or 0)
        source_height = int(payload.get("height") or 0)
    except (TypeError, ValueError):
        source_width = source_height = 0
    if source_width <= 0 or source_height <= 0:
        raise RenderError(404, "manifest 的画布尺寸无效，请重新烘焙。")
    patches = payload.get("patches")
    if not isinstance(patches, dict) or not patches:
        raise RenderError(404, "manifest 不完整：缺少 patches，请重新烘焙。")
    _require_media(payload["base"].get("url"), "base")
    for key, patch in patches.items():
        if not isinstance(patch, dict):
            raise RenderError(404, f"manifest 补丁无效：{key}，请重新烘焙。")
        _require_media(patch.get("url"), f"补丁 {key}")
    payload["width"] = source_width
    payload["height"] = source_height
    return payload


@dataclass
class PreparedAssets:
    width: int
    height: int
    base: Image.Image
    patches: dict[str, tuple[Image.Image, tuple[int, int]]]
    zorder: list[str]
    default_state: dict[str, str]
    source_width: int
    source_height: int
    baked_at: str = ""
    layers: dict[str, tuple[Image.Image, tuple[int, int], int]] = field(default_factory=dict)
    patch_z: dict[str, int] = field(default_factory=dict)


def _channel_states(patches: Mapping[str, Any], channel: str) -> set[str]:
    prefix = channel + "."
    return {key[len(prefix):] for key in patches if key.startswith(prefix)}


def prepare_assets(psd_asset_id: str, out_width: int) -> PreparedAssets:
    """Load the baked base + patches and scale them to the requested width."""
    manifest = load_manifest(psd_asset_id)
    source_width = int(manifest["width"])
    source_height = int(manifest["height"])
    width, height = even_size(source_width, source_height, out_width)
    scale_x = width / float(source_width)
    scale_y = height / float(source_height)

    base_path = _require_media(manifest["base"]["url"], "base")
    try:
        with Image.open(base_path) as image:
            base = image.convert("RGBA")
    except OSError as exc:  # pragma: no cover - corrupt cache
        raise RenderError(404, f"base 图无法读取：{exc}") from exc
    if base.size != (width, height):
        base = base.resize((width, height), Image.Resampling.LANCZOS)

    patches: dict[str, tuple[Image.Image, tuple[int, int]]] = {}
    patch_z: dict[str, int] = {}
    for key, patch in manifest["patches"].items():
        path = _require_media(patch.get("url"), f"补丁 {key}")
        try:
            with Image.open(path) as image:
                layer = image.convert("RGBA")
        except OSError as exc:  # pragma: no cover - corrupt cache
            raise RenderError(404, f"补丁 {key} 无法读取：{exc}") from exc
        patch_width = max(1, round(layer.width * scale_x))
        patch_height = max(1, round(layer.height * scale_y))
        if layer.size != (patch_width, patch_height):
            layer = layer.resize((patch_width, patch_height), Image.Resampling.LANCZOS)
        offset = patch.get("offset") or [0, 0]
        try:
            offset_x = int(round(float(offset[0]) * scale_x))
            offset_y = int(round(float(offset[1]) * scale_y))
        except (TypeError, ValueError, IndexError):
            offset_x = offset_y = 0
        patches[key] = (layer, (offset_x, offset_y))
        try:
            patch_z[key] = int(patch.get("z") or 0)
        except (TypeError, ValueError):
            patch_z[key] = 0

    layers: dict[str, tuple[Image.Image, tuple[int, int], int]] = {}
    for layer_id, entry in (manifest.get("layers") or {}).items():
        if not isinstance(entry, Mapping):
            continue
        path = _require_media(entry.get("url"), f"静态图层 {layer_id}")
        try:
            with Image.open(path) as image:
                layer = image.convert("RGBA")
        except OSError as exc:  # pragma: no cover - corrupt cache
            raise RenderError(404, f"静态图层 {layer_id} 无法读取：{exc}") from exc
        layer_width = max(1, round(layer.width * scale_x))
        layer_height = max(1, round(layer.height * scale_y))
        if layer.size != (layer_width, layer_height):
            layer = layer.resize((layer_width, layer_height), Image.Resampling.LANCZOS)
        offset = entry.get("offset") or [0, 0]
        try:
            offset_x = int(round(float(offset[0]) * scale_x))
            offset_y = int(round(float(offset[1]) * scale_y))
        except (TypeError, ValueError, IndexError):
            offset_x = offset_y = 0
        try:
            z = int(entry.get("z") or 0)
        except (TypeError, ValueError):
            z = 0
        layers[str(layer_id)] = (layer, (offset_x, offset_y), z)

    manifest_zorder = [str(channel) for channel in (manifest.get("zorder") or [])] or list(DEFAULT_ZORDER)
    zorder: list[str] = []
    for channel in manifest_zorder + list(DEFAULT_ZORDER):
        if channel in zorder:
            continue
        if _channel_states(patches, channel):
            zorder.append(channel)

    missing_channels = [channel for channel in ("mouth", "eyes")
                        if not _channel_states(patches, channel)]
    if missing_channels:
        raise RenderError(
            400,
            f"烘焙 manifest 缺少 {'/'.join(missing_channels)} 补丁，无法导出。请重新烘焙。",
        )

    raw_defaults = manifest.get("defaultState")
    if not isinstance(raw_defaults, dict):
        raw_defaults = {}
    default_state: dict[str, str] = {}
    for channel in zorder:
        states = _channel_states(patches, channel)
        if not states:
            continue
        candidate = str(raw_defaults.get(channel) or "")
        if candidate == "off":
            # Optional overlay channel (sweat / eyeEffect ...) explicitly off.
            default_state[channel] = "off"
            continue
        if candidate not in states:
            preferred = DEFAULT_STATE.get(channel)
            if preferred is None:
                # No core default and no manifest hint: stay off.  Picking an
                # arbitrary state here is what made exports show sweat / tears
                # that the preview never drew.
                default_state[channel] = "off"
                continue
            candidate = preferred if preferred in states else sorted(states)[0]
        default_state[channel] = candidate

    return PreparedAssets(
        width=width,
        height=height,
        base=base,
        patches=patches,
        zorder=zorder,
        default_state=default_state,
        source_width=source_width,
        source_height=source_height,
        baked_at=str(manifest.get("bakedAt") or ""),
        layers=layers,
        patch_z=patch_z,
    )


# ---------------------------------------------------------------------------
# frame-state selection + composition
# ---------------------------------------------------------------------------


def _alpha_paste(canvas: Image.Image, image: Image.Image, position: tuple[int, int]) -> None:
    """``alpha_composite`` with clipping for negative / off-canvas offsets."""
    x, y = int(position[0]), int(position[1])
    width, height = canvas.size
    source_left = source_top = 0
    if x < 0:
        source_left = -x
        x = 0
    if y < 0:
        source_top = -y
        y = 0
    if x >= width or y >= height:
        return
    paste_width = min(image.width - source_left, width - x)
    paste_height = min(image.height - source_top, height - y)
    if paste_width <= 0 or paste_height <= 0:
        return
    if (source_left or source_top
            or paste_width != image.width or paste_height != image.height):
        image = image.crop((source_left, source_top,
                            source_left + paste_width, source_top + paste_height))
    canvas.alpha_composite(image, (x, y))


def _blink_active(blinks: list[tuple[float, float]], t: float) -> bool:
    """True when any blink interval covers ``t`` (handles overlapping blinks)."""
    for start, duration in blinks:
        if start <= t < start + duration:
            return True
    return False


class FrameSource:
    """Resolve a viseme/blink/expression state per frame and compose it."""

    def __init__(self, timeline: Mapping[str, Any] | None, blinks: list[Any],
                 assets: PreparedAssets, brow: str | None = None,
                 cheek: str | None = None, sway: Mapping[str, Any] | None = None,
                 hidden_layers: Iterable[str] | None = None) -> None:
        frames: list[tuple[float, str, str | None]] = []
        for item in (timeline or {}).get("frames") or []:
            if isinstance(item, Mapping):
                t = float(item.get("t") or 0.0)
                viseme = str(item.get("viseme") or "closed")
                mouth_pose = str(item["mouthPose"]) if item.get("mouthPose") else None
            else:
                t = float(item[0])
                viseme = str(item[1])
                mouth_pose = None
            frames.append((t, viseme, mouth_pose))
        frames.sort(key=lambda pair: pair[0])
        self._times = [pair[0] for pair in frames]
        self._visemes = [pair[1] for pair in frames]
        self._mouth_poses = [pair[2] for pair in frames]

        self._track_times: dict[str, list[float]] = {}
        self._track_states: dict[str, list[str]] = {}
        for channel, items in ((timeline or {}).get("tracks") or {}).items():
            events = sorted(
                (float(item.get("t") or 0.0), str(item.get("state")))
                for item in items
                if isinstance(item, Mapping) and item.get("state") is not None
            )
            self._track_times[str(channel)] = [event[0] for event in events]
            self._track_states[str(channel)] = [event[1] for event in events]

        normalized_blinks: list[tuple[float, float]] = []
        for item in blinks or []:
            if isinstance(item, Mapping):
                start = float(item.get("t") or 0.0)
                duration = float(item.get("duration") or 0.15)
            else:
                start = float(item[0])
                duration = float(item[1]) if len(item) > 1 else 0.15
            if math.isfinite(start) and math.isfinite(duration) and duration > 0:
                normalized_blinks.append((start, duration))
        normalized_blinks.sort()
        self._blinks = normalized_blinks

        self.assets = assets
        self._states = {channel: _channel_states(assets.patches, channel)
                        for channel in assets.zorder}
        self.brow = brow
        self.cheek = cheek
        self._hidden_layers = {str(item) for item in (hidden_layers or [])}
        sway = sway or {}
        self.sway_enabled = bool(sway.get("enabled")) and float(sway.get("bpm") or 0) > 0
        self.sway_amplitude = max(0.0, min(1.0, float(sway.get("amplitude") or 0.0)))
        self.sway_frequency = max(0.125, min(4.0, float(sway.get("frequency") or 0.5)))
        self.sway_offset_ms = max(-2000.0, min(2000.0, float(sway.get("offsetMs") or 0.0)))
        self.sway_bpm = max(0.0, float(sway.get("bpm") or 0.0))
        self.sway_audio_start = max(-300.0, min(300.0, float(sway.get("audioStart") or 0.0)))
        # Composed (pre-sway) frames are deterministic per state, so 10s of
        # "closed" or one held viseme only composes once.  Bounded by bytes.
        self._state_cache: "OrderedDict[tuple[tuple[str, str], ...], Image.Image]" = OrderedDict()
        self._state_cache_bytes = 0
        self._state_cache_lock = threading.Lock()

    # -- canvas --------------------------------------------------------
    @property
    def width(self) -> int:
        return self.assets.width

    @property
    def height(self) -> int:
        return self.assets.height

    # -- state ---------------------------------------------------------
    def _mouth_at(self, t: float) -> tuple[str | None, str]:
        if not self._times:
            return None, "closed"
        index = bisect.bisect_right(self._times, t + 1e-9) - 1
        if index < 0:
            index = 0
        return self._mouth_poses[index], self._visemes[index]

    def _track_at(self, channel: str, t: float) -> str | None:
        times = self._track_times.get(channel) or []
        index = bisect.bisect_right(times, t + 1e-9) - 1
        return self._track_states[channel][index] if index >= 0 else None

    def _resolve(self, channel: str, wanted: str | None) -> str | None:
        states = self._states.get(channel) or set()
        if not states:
            return None
        if wanted == "off":
            return None
        if wanted in states:
            return wanted
        fallback = self.assets.default_state.get(channel)
        if fallback == "off":
            return None
        if fallback in states:
            return fallback
        return sorted(states)[0]

    def state_at(self, t: float) -> dict[str, str]:
        blinking = _blink_active(self._blinks, t)
        mouth_pose, viseme = self._mouth_at(t)
        wanted = {
            channel: self._track_at(channel, t)
            for channel in self.assets.zorder
        }
        wanted["eyes"] = "blink" if blinking else wanted.get("eyes")
        if self.brow is not None:
            wanted["brow"] = self.brow
        if self.cheek is not None:
            wanted["cheek"] = self.cheek
        state: dict[str, str] = {}
        for channel in self.assets.zorder:
            if channel == "mouth":
                states = self._states.get(channel) or set()
                choice = mouth_pose if mouth_pose in states else self._resolve(channel, viseme)
            else:
                choice = self._resolve(channel, wanted.get(channel))
            if choice:
                state[channel] = f"{channel}.{choice}"
        return state

    # -- composition ---------------------------------------------------
    def _cached_state(self, key: tuple[tuple[str, str], ...]) -> Image.Image | None:
        with self._state_cache_lock:
            cached = self._state_cache.get(key)
            if cached is not None:
                self._state_cache.move_to_end(key)
            return cached

    def _store_state(self, key: tuple[tuple[str, str], ...], frame: Image.Image) -> None:
        size = frame.size[0] * frame.size[1] * 4
        if size > STATE_CACHE_BYTES // 2:
            return  # single frame already eats half the budget: not worth caching
        with self._state_cache_lock:
            if key in self._state_cache:
                return
            self._state_cache[key] = frame
            self._state_cache_bytes += size
            while self._state_cache_bytes > STATE_CACHE_BYTES and len(self._state_cache) > 1:
                _, stale = self._state_cache.popitem(last=False)
                self._state_cache_bytes -= stale.size[0] * stale.size[1] * 4

    def compose_state(self, state: Mapping[str, str]) -> Image.Image:
        """Compose the patches for one state.  Returned images are cache-shared:
        callers must treat them as read-only."""
        cache_key = tuple(sorted(state.items()))
        cached = self._cached_state(cache_key)
        if cached is not None:
            return cached
        frame = self.assets.base.copy()
        drawables: list[tuple[int, Image.Image, tuple[int, int]]] = []
        for layer_id, entry in self.assets.layers.items():
            if layer_id in self._hidden_layers:
                continue
            image, position, z = entry
            drawables.append((z, image, position))
        for channel in self.assets.zorder:
            key = state.get(channel)
            if not key:
                continue
            patch = self.assets.patches.get(key)
            if patch is None:
                continue
            layer, position = patch
            drawables.append((self.assets.patch_z.get(key, 10**6), layer, position))
        drawables.sort(key=lambda item: item[0])
        for _, layer, position in drawables:
            _alpha_paste(frame, layer, position)
        self._store_state(cache_key, frame)
        return frame

    def compose(self, t: float) -> Image.Image:
        frame = self.compose_state(self.state_at(t))
        if not self.sway_enabled or self.sway_amplitude <= 0:
            return frame
        width, height = frame.size
        safe_scale = 1.0 - 0.12 * self.sway_amplitude
        safe_w = max(1, round(width * safe_scale))
        safe_h = max(1, round(height * safe_scale))
        safe_x = (width - safe_w) // 2
        safe_y = (height - safe_h) // 2
        beat = (t - self.sway_audio_start + self.sway_offset_ms / 1000.0) * self.sway_bpm / 60.0
        phase = math.tau * (beat * self.sway_frequency)
        angle = math.radians(4.0) * self.sway_amplitude * math.sin(phase)
        scale_y = 1.0 + 0.02 * self.sway_amplitude * math.cos(phase * 2.0)
        cosine, sine = math.cos(angle), math.sin(angle)

        # Two steps in one affine transform: shrink into the safety margin and
        # then rotate + stretch about the bottom-centre pivot.  Doing the shrink
        # as a separate LANCZOS resize cost about half of every exported frame.
        pivot_x, pivot_y = width / 2.0, float(safe_y + safe_h)
        step_x = safe_w / float(width)
        step_y = safe_h / float(height)
        a = cosine * step_x
        b = -sine * scale_y * step_y
        d = sine * step_x
        e = cosine * scale_y * step_y
        # q = (safe_x, safe_y) + S*p   (scaled image pasted at the safe offset)
        # F(p) = P + M*(q - P)        (rotate + stretch about the pivot)
        offset_x = (
            pivot_x
            + cosine * (safe_x - pivot_x)
            - sine * scale_y * (safe_y - pivot_y)
        )
        offset_y = (
            pivot_y
            + sine * (safe_x - pivot_x)
            + cosine * scale_y * (safe_y - pivot_y)
        )
        det = a * e - b * d
        if abs(det) < 1e-12:  # pragma: no cover - degenerate parameters
            return frame
        inv_a, inv_b = e / det, -b / det
        inv_d, inv_e = -d / det, a / det
        inverse = (
            inv_a,
            inv_b,
            -(inv_a * offset_x + inv_b * offset_y),
            inv_d,
            inv_e,
            -(inv_d * offset_x + inv_e * offset_y),
        )
        return frame.transform(
            frame.size,
            Image.Transform.AFFINE,
            inverse,
            resample=Image.Resampling.BICUBIC,
        )


# ---------------------------------------------------------------------------
# job persistence / progress
# ---------------------------------------------------------------------------


_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.RLock()
_QUEUE: "queue.Queue[str]" = queue.Queue()
_WORKER: threading.Thread | None = None
_WORKER_LOCK = threading.Lock()


def _strip_internal(job: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if not key.startswith("_")}


def _write_job_file(job_id: str, payload: Mapping[str, Any]) -> bool:
    """Atomically persist job.json (a GET must never read a half-written file)."""
    path = _job_file(job_id)
    temp = path.with_name(path.name + ".part")
    try:
        storage.write_json(temp, dict(payload))
        os.replace(temp, path)
        return True
    except OSError:  # pragma: no cover - disk full / permissions
        log.warning("could not persist render job %s", job_id)
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _persist(job_id: str, force: bool = False) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        now = time.monotonic()
        if not force and now - float(job.get("_lastPersist") or 0.0) < 0.5:
            return
        job["_lastPersist"] = now
        payload = _strip_internal(job)
    _write_job_file(job_id, payload)


def _set_job(job_id: str, **changes: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(changes)


def _public_job(job: Mapping[str, Any]) -> RenderJobInfo:
    with _JOBS_LOCK:
        snapshot = dict(job)
    elapsed = snapshot.get("elapsedSec")
    if not elapsed:
        if snapshot.get("status") == "running" and snapshot.get("_startedEpoch"):
            elapsed = time.time() - float(snapshot["_startedEpoch"])
        else:
            elapsed = 0.0
    return RenderJobInfo(
        jobId=str(snapshot.get("jobId") or ""),
        status=snapshot.get("status") or "queued",  # type: ignore[arg-type]
        progress=float(snapshot.get("progress") or 0.0),
        format=snapshot.get("format") or "png_zip",  # type: ignore[arg-type]
        fps=float(snapshot.get("fps") or 24.0),
        width=int(snapshot.get("width") or 0),
        height=int(snapshot.get("height") or 0),
        frameCount=int(snapshot.get("frameCount") or 0),
        doneFrames=int(snapshot.get("doneFrames") or 0),
        fileUrl=snapshot.get("fileUrl"),
        fileName=snapshot.get("fileName"),
        error=snapshot.get("error"),
        elapsedSec=round(float(elapsed), 2),
        createdAt=str(snapshot.get("createdAt") or ""),
    )


def _load_job(job_id: str) -> dict[str, Any] | None:
    """In-memory job, or the on-disk job.json (restart-safe)."""
    if not _valid_job_id(job_id):
        return None
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is not None:
        return job
    stored = storage.read_json(_job_file(job_id))
    if not isinstance(stored, dict):
        return None
    stored.setdefault("jobId", job_id)
    if stored.get("status") in ("queued", "running"):
        # The worker only lives in this process; a persisted unfinished job
        # means the backend was restarted mid-export.
        stored.update(
            status="failed",
            progress=0.0,
            error="后端服务重启导致任务中断，请重新导出。",
            finishedAt=_now_iso(),
        )
        _write_job_file(job_id, _strip_internal(stored))
    with _JOBS_LOCK:
        _JOBS[job_id] = stored
    return stored


# ---------------------------------------------------------------------------
# encoders
# ---------------------------------------------------------------------------


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RenderError(500, f"未找到 {name}，请确认 ffmpeg 已加入 PATH。")
    return path


def _fps_text(fps: float) -> str:
    return f"{float(fps):g}"


def build_ffmpeg_command(fmt: str, width: int, height: int, fps: float,
                         out_path: Path) -> list[str]:
    """Raw-video pipe -> ffmpeg command for one of the video formats."""
    ffmpeg = _tool("ffmpeg")
    input_pix_fmt = "rgb24" if fmt == "mp4" else "rgba"
    command = [
        ffmpeg, "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", input_pix_fmt,
        "-s", f"{width}x{height}", "-r", _fps_text(fps), "-i", "-",
        "-an",
    ]
    if fmt == "prores4444":
        command += [
            "-c:v", "prores_ks", "-profile:v", "4",
            "-pix_fmt", "yuva444p10le", "-vendor", "apl0",
            str(out_path),
        ]
    elif fmt == "webm_alpha":
        command += [
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
            "-b:v", "0", "-crf", "30", "-row-mt", "1",
            "-auto-alt-ref", "0", "-speed", "4",
            str(out_path),
        ]
    elif fmt == "mp4":
        command += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out_path),
        ]
    else:  # pragma: no cover - guarded by pydantic
        raise RenderError(400, f"不支持的导出格式：{fmt}")
    return command


def _tail(path: Path, lines: int = 3) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return "未知错误"
    parts = [line.strip() for line in text.splitlines() if line.strip()]
    return " | ".join(parts[-lines:])[:800] or "未知错误"


def _frame_workers(frame_count: int) -> int:
    """Threads used to compose + encode frames (all cores by default)."""
    configured = int(getattr(config, "RENDER_WORKERS", 0) or 0)
    cpu = os.cpu_count() or 2
    workers = configured if configured > 0 else cpu
    return max(1, min(workers, max(1, frame_count)))


def _render_png_zip(job_id: str, source: FrameSource, start: float, fps: float,
                    frame_count: int, out_path: Path) -> None:
    temp_path = out_path.with_name(out_path.name + ".part")
    cache: "OrderedDict[tuple[tuple[str, str], ...], bytes]" = OrderedDict()
    cache_lock = threading.Lock()
    cache_bytes = 0
    digits = max(4, len(str(max(0, frame_count - 1))))
    workers = _frame_workers(frame_count)
    log.info("png_zip %s: %d frames on %d worker(s)", job_id, frame_count, workers)

    def encode(t: float, state: dict[str, str], key: tuple[tuple[str, str], ...]) -> bytes:
        """Compose one frame and encode it as PNG (runs on a worker thread)."""
        nonlocal cache_bytes
        with cache_lock:
            cached = cache.get(key)
            if cached is not None:
                cache.move_to_end(key)
                return cached
        image = source.compose(t) if source.sway_enabled else source.compose_state(state)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", compress_level=3)
        data = buffer.getvalue()
        with cache_lock:
            if key not in cache:
                cache[key] = data
                cache_bytes += len(data)
                while cache_bytes > PNG_CACHE_BYTES and len(cache) > 1:
                    _, stale = cache.popitem(last=False)
                    cache_bytes -= len(stale)
        return data

    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_STORED,
                             allowZip64=True) as archive, ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="mocadiff-png") as pool:
            # Compose ahead in parallel, write the archive strictly in order so
            # frame numbering and progress stay monotonic.  The window is capped
            # because every in-flight frame holds a full-size PNG in memory.
            window = max(2, min(workers + 2, 32))
            pending: "deque[tuple[int, Future[bytes]]]" = deque()
            submitted = 0
            previous_key: tuple[tuple[str, str], ...] | None = None
            previous_future: Future[bytes] | None = None
            for index in range(frame_count):
                while submitted < frame_count and len(pending) < window:
                    t = start + submitted / fps
                    state = source.state_at(t)
                    key = (tuple(sorted(state.items())),
                           submitted if source.sway_enabled else -1)
                    # Runs of identical pose reuse one task instead of queueing
                    # the same PNG over and over.
                    if key == previous_key and previous_future is not None:
                        future = previous_future
                    else:
                        future = pool.submit(encode, t, state, key)
                    previous_key, previous_future = key, future
                    pending.append((submitted, future))
                    submitted += 1
                frame_index, future = pending.popleft()
                archive.writestr(f"frame_{frame_index:0{digits}d}.png", future.result())
                _set_job(job_id, doneFrames=frame_index + 1,
                         progress=min(0.99, (frame_index + 1) / frame_count))
                _persist(job_id)
        os.replace(temp_path, out_path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best effort
            pass


def _encode_video(job_id: str, source: FrameSource, start: float, fps: float,
                  frame_count: int, fmt: str, out_path: Path,
                  background: tuple[int, int, int]) -> None:
    workers = _frame_workers(frame_count)
    log.info("%s %s: %d frames on %d worker(s)", fmt, job_id, frame_count, workers)

    def encode_frame(t: float, state: Mapping[str, str]) -> bytes:
        """Compose one frame into raw bytes (runs on a worker thread)."""
        image = source.compose(t) if source.sway_enabled else source.compose_state(state)
        if fmt == "mp4":
            canvas = Image.new("RGB", image.size, background)
            canvas.paste(image, (0, 0), image)
            return canvas.tobytes()
        return image.tobytes()

    with open(job_dir(job_id) / "ffmpeg.log", "wb") as stderr_file:
        process = subprocess.Popen(
            build_ffmpeg_command(fmt, source.width, source.height, fps, out_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            bufsize=0,
        )
        assert process.stdin is not None
        written = 0
        window = max(2, min(workers + 2, 32))
        pending: "deque[tuple[int, Future[bytes]]]" = deque()
        submitted = 0
        previous_key: tuple[tuple[str, str], ...] | None = None
        previous_future: Future[bytes] | None = None
        try:
            with ThreadPoolExecutor(max_workers=workers,
                                    thread_name_prefix="mocadiff-video") as pool:
                # Compose frames in parallel but feed ffmpeg strictly in order:
                # the pipe is sequential, the expensive part is not.
                while written < frame_count:
                    while submitted < frame_count and len(pending) < window:
                        t = start + submitted / fps
                        state = source.state_at(t)
                        key = (tuple(sorted(state.items())),
                               submitted if source.sway_enabled else -1)
                        if key == previous_key and previous_future is not None:
                            future = previous_future
                        else:
                            future = pool.submit(encode_frame, t, state)
                        previous_key, previous_future = key, future
                        pending.append((submitted, future))
                        submitted += 1
                    index, future = pending.popleft()
                    try:
                        process.stdin.write(future.result())
                    except (BrokenPipeError, OSError):
                        break
                    written = index + 1
                    _set_job(job_id, doneFrames=written,
                             progress=min(0.99, written / frame_count))
                    _persist(job_id)
        except BaseException:
            try:
                process.stdin.close()
            except OSError:
                pass
            process.kill()
            process.wait(timeout=30)
            raise
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            code = process.wait(timeout=900)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=30)
            raise RenderError(500, "ffmpeg 编码超时。") from None

    if written != frame_count:
        raise RenderError(
            500,
            f"ffmpeg 管道提前结束（写入 {written}/{frame_count} 帧）：{_tail(out_path.parent / 'ffmpeg.log')}",
        )
    if code != 0:
        raise RenderError(
            500,
            f"ffmpeg 编码失败（{code}）：{_tail(out_path.parent / 'ffmpeg.log')}",
        )
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise RenderError(500, "ffmpeg 未生成输出文件。")


# ---------------------------------------------------------------------------
# validation + job execution
# ---------------------------------------------------------------------------


def _validate(req: RenderRequest) -> tuple[float, float, int]:
    timeline = req.timeline
    start = max(0.0, float(req.startSec))
    if not math.isfinite(start):
        raise RenderError(400, "startSec 无效。")
    if req.durationSec is not None:
        duration = float(req.durationSec)
    else:
        duration = float(timeline.duration) - start
    if not math.isfinite(duration) or duration <= 0:
        raise RenderError(400, "durationSec 必须大于 0（或 timeline.duration 大于 startSec）。")
    if duration > MAX_DURATION_SEC + 1e-9:
        raise RenderError(400, f"单次导出最多 {MAX_DURATION_SEC:.0f} 秒（当前 {duration:.2f}s）。")
    if req.outFps < 1 or req.outFps > MAX_OUT_FPS:
        raise RenderError(400, f"outFps 必须在 1–{MAX_OUT_FPS:.0f} 之间。")
    frame_count = max(1, int(round(duration * float(req.outFps))))
    if frame_count > MAX_FRAMES:
        raise RenderError(
            400,
            f"单次最多 {MAX_FRAMES} 帧（当前 {frame_count}），请缩短 durationSec 或降低 outFps。",
        )
    return start, duration, frame_count


def _slice_timeline(timeline: Mapping[str, Any], start: float,
                    duration: float) -> list[dict[str, Any]]:
    """Keep only the frames needed for [start, start+duration) (+1 look-behind)."""
    frames: list[dict[str, Any]] = []
    for index, item in enumerate(timeline.get("frames") or []):
        if isinstance(item, Mapping):
            try:
                t = float(item.get("t") or 0.0)
                viseme = str(item.get("viseme") or "closed")
                frame = {"t": t, "viseme": viseme}
                if item.get("mouthPose") is not None:
                    frame["mouthPose"] = str(item["mouthPose"])
            except (TypeError, ValueError):
                raise RenderError(400, f"timeline.frames[{index}] 格式无效。") from None
        else:
            try:
                t = float(item[0])
                viseme = str(item[1])
                frame = {"t": t, "viseme": viseme}
            except (TypeError, ValueError, IndexError):
                raise RenderError(400, f"timeline.frames[{index}] 格式无效。") from None
        if not math.isfinite(t):
            raise RenderError(400, f"timeline.frames[{index}].t 无效。")
        frames.append(frame)
    frames.sort(key=lambda value: value["t"])
    if not frames:
        return []
    end = start + duration
    times = [frame["t"] for frame in frames]
    first = max(0, bisect.bisect_right(times, start + 1e-9) - 1)
    selected = [frames[first]]
    for frame in frames[first + 1:]:
        if frame["t"] > end + 1e-9:
            break
        selected.append(frame)
    return selected


def _slice_tracks(timeline: Mapping[str, Any], start: float,
                  duration: float) -> dict[str, list[dict[str, Any]]]:
    end = start + duration
    result: dict[str, list[dict[str, Any]]] = {}
    for channel, raw_items in (timeline.get("tracks") or {}).items():
        items = sorted(
            (dict(item) for item in raw_items if isinstance(item, Mapping)),
            key=lambda item: float(item.get("t") or 0.0),
        )
        if not items:
            continue
        times = [float(item.get("t") or 0.0) for item in items]
        first = max(0, bisect.bisect_right(times, start + 1e-9) - 1)
        selected = [items[first]]
        selected.extend(item for item in items[first + 1:]
                        if float(item.get("t") or 0.0) <= end + 1e-9)
        result[str(channel)] = selected
    return result


def _slice_blinks(blinks: list[Any], start: float, duration: float) -> list[list[float]]:
    end = start + duration
    result: list[list[float]] = []
    for item in blinks or []:
        if isinstance(item, Mapping):
            t = float(item.get("t") or 0.0)
            blink_duration = float(item.get("duration") or 0.15)
        else:
            t = float(item[0])
            blink_duration = float(item[1]) if len(item) > 1 else 0.15
        if not math.isfinite(t) or not math.isfinite(blink_duration) or blink_duration <= 0:
            continue
        if t < end + 1e-9 and t + blink_duration > start - 1e-9:
            result.append([t, blink_duration])
    result.sort(key=lambda pair: pair[0])
    return result


def _fail(job_id: str, detail: str, out_path: Path, started: float) -> None:
    for path in (out_path, out_path.with_name(out_path.name + ".part")):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    _set_job(
        job_id,
        status="failed",
        error=str(detail)[:2000],
        elapsedSec=round(time.time() - started, 2),
        finishedAt=_now_iso(),
    )
    _persist(job_id, force=True)


def _run_job(job_id: str) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        return
    params = job.get("params") or {}
    assets = job.get("_assets")
    started = time.time()
    _set_job(
        job_id,
        status="running",
        progress=0.0,
        doneFrames=0,
        error=None,
        startedAt=_now_iso(),
        _startedEpoch=started,
    )
    _persist(job_id, force=True)

    out_path = job_dir(job_id) / OUTPUT_NAMES[str(job["format"])]
    try:
        if not isinstance(assets, PreparedAssets):
            assets = prepare_assets(str(params["psdAssetId"]), int(job["width"]))
        source = FrameSource(
            timeline={
                "frames": params.get("frames") or [],
                "tracks": params.get("tracks") or {},
            },
            blinks=params.get("blinks") or [],
            assets=assets,
            brow=params.get("brow"),
            cheek=params.get("cheek"),
            sway=params.get("sway"),
            hidden_layers=params.get("hiddenLayers") or [],
        )
        if job["format"] == "png_zip":
            _render_png_zip(job_id, source, float(params["startSec"]),
                            float(params["outFps"]), int(job["frameCount"]), out_path)
        else:
            background = tuple(int(value) for value in (params.get("background") or (0, 0, 0)))
            _encode_video(job_id, source, float(params["startSec"]),
                          float(params["outFps"]), int(job["frameCount"]),
                          str(job["format"]), out_path, background)  # type: ignore[arg-type]
        _set_job(
            job_id,
            status="done",
            progress=1.0,
            doneFrames=int(job["frameCount"]),
            fileUrl=f"/api/render/{job_id}/download",
            fileName=out_path.name,
            finishedAt=_now_iso(),
            elapsedSec=round(time.time() - started, 2),
        )
        _persist(job_id, force=True)
        log.info("render job %s done in %.1fs (%s)", job_id,
                 time.time() - started, out_path.name)
    except RenderError as exc:
        _fail(job_id, exc.detail, out_path, started)
    except Exception as exc:  # noqa: BLE001 - surfaced to the client
        log.exception("render job %s failed", job_id)
        _fail(job_id, f"渲染失败：{exc}", out_path, started)
    finally:
        # The prepared PIL images are only needed while rendering; dropping
        # them keeps a long-lived backend from accumulating ~50 MB per job.
        _set_job(job_id, _assets=None)


def _worker_loop() -> None:
    while True:
        job_id = _QUEUE.get()
        try:
            _run_job(job_id)
        except Exception:  # pragma: no cover - defensive
            log.exception("render worker crashed on %s", job_id)
        finally:
            _QUEUE.task_done()


def _ensure_worker() -> None:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_worker_loop, name="mocadiff-render",
                                       daemon=True)
            _WORKER.start()


# ---------------------------------------------------------------------------
# public API used by the router (and tests)
# ---------------------------------------------------------------------------


def submit(req: RenderRequest) -> RenderJobInfo:
    """Validate + queue one render job; returns the initial job state."""
    assets = prepare_assets(req.psdAssetId, req.width)
    start, duration, frame_count = _validate(req)

    for channel, state in (("brow", req.brow), ("cheek", req.cheek)):
        if not state:
            continue
        available = _channel_states(assets.patches, channel)
        if not available:
            raise RenderError(400, f"烘焙 manifest 没有 {channel} 通道，无法使用 {state}。")
        if state not in available:
            raise RenderError(
                400,
                f"{channel} 状态不可用：{state}（可用：{', '.join(sorted(available))}）。",
            )

    fmt = str(req.format)
    if fmt not in OUTPUT_NAMES:
        raise RenderError(400, f"不支持的导出格式：{fmt}")
    if fmt != "png_zip" and shutil.which("ffmpeg") is None:
        raise RenderError(500, "未找到 ffmpeg，无法导出视频格式。")

    background = (0, 0, 0)
    if fmt == "mp4":
        try:
            rgb = ImageColor.getrgb(req.background or "#101010")
        except (ValueError, TypeError):
            raise RenderError(400, f"无效的背景色：{req.background}") from None
        background = tuple(int(value) for value in rgb[:3])

    job_id = "r_" + uuid.uuid4().hex[:12]
    while job_dir(job_id).exists():  # pragma: no cover - astronomically unlikely
        job_id = "r_" + uuid.uuid4().hex[:12]

    timeline = req.timeline
    timeline_data = timeline.model_dump()
    frames = _slice_timeline(timeline_data, start, duration)
    tracks = _slice_tracks(timeline_data, start, duration)
    blinks = _slice_blinks([blink.model_dump() for blink in req.blinks], start, duration)

    job: dict[str, Any] = {
        "jobId": job_id,
        "status": "queued",
        "progress": 0.0,
        "format": fmt,
        "fps": float(req.outFps),
        "width": assets.width,
        "height": assets.height,
        "frameCount": frame_count,
        "doneFrames": 0,
        "fileUrl": None,
        "fileName": None,
        "error": None,
        "elapsedSec": 0.0,
        "createdAt": _now_iso(),
        "finishedAt": None,
        "params": {
            "psdAssetId": req.psdAssetId,
            "frames": frames,
            "tracks": tracks,
            "blinks": blinks,
            "startSec": start,
            "durationSec": duration,
            "outFps": float(req.outFps),
            "background": list(background),
            "brow": req.brow,
            "cheek": req.cheek,
            "sway": req.sway.model_dump() if req.sway else None,
            "hiddenLayers": list(req.hiddenLayers),
        },
        "_assets": assets,
        "_lastPersist": time.monotonic(),
    }
    job_dir(job_id).mkdir(parents=True, exist_ok=True)
    with _JOBS_LOCK:
        _JOBS[job_id] = job
    _persist(job_id, force=True)
    info = _public_job(job)
    _ensure_worker()
    _QUEUE.put(job_id)
    return info


def get_job(job_id: str) -> RenderJobInfo | None:
    job = _load_job(job_id)
    if job is None:
        return None
    return _public_job(job)


def output_path(job_id: str) -> Path | None:
    job = _load_job(job_id)
    if job is None or job.get("status") != "done":
        return None
    file_name = job.get("fileName")
    if not file_name:
        return None
    path = job_dir(job_id) / str(file_name)
    return path if path.is_file() else None


# ---------------------------------------------------------------------------
# export history: list / delete / clean
# ---------------------------------------------------------------------------


def _dir_bytes(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _artifact(job_id: str, payload: Mapping[str, Any]) -> Path | None:
    name = payload.get("fileName")
    if not isinstance(name, str) or not name:
        return None
    # Only files we created ourselves live in the job dir; take the basename so
    # a tampered job.json can never escape it.
    path = job_dir(job_id) / Path(name).name
    return path if path.is_file() else None


def export_entry(job_id: str) -> dict[str, Any] | None:
    """Summary of one ``data/renders/<jobId>/`` directory (or None)."""
    if not _valid_job_id(job_id):
        return None
    payload = storage.read_json(_job_file(job_id))
    if not isinstance(payload, dict):
        return None
    status = str(payload.get("status") or "failed")
    if status not in ("queued", "running", "done", "failed"):
        status = "failed"
    error = payload.get("error")
    with _JOBS_LOCK:
        live = _JOBS.get(job_id)
    if status in ("queued", "running") and live is None:
        # The worker only exists in this process: a persisted unfinished job
        # means the backend restarted mid-export.
        status = "failed"
        error = error or "后端服务重启导致任务中断，请重新导出。"
    artifact = _artifact(job_id, payload)
    finished = payload.get("finishedAt")
    return {
        "jobId": job_id,
        "status": status,
        "format": payload.get("format") or "png_zip",
        "fps": float(payload.get("fps") or 24.0),
        "width": int(payload.get("width") or 0),
        "height": int(payload.get("height") or 0),
        "frameCount": int(payload.get("frameCount") or 0),
        "doneFrames": int(payload.get("doneFrames") or 0),
        "fileName": artifact.name if artifact is not None else None,
        "fileUrl": f"/api/render/{job_id}/download" if artifact is not None else None,
        "sizeBytes": artifact.stat().st_size if artifact is not None else _dir_bytes(job_dir(job_id)),
        "createdAt": str(payload.get("createdAt") or ""),
        "finishedAt": str(finished) if isinstance(finished, str) and finished else None,
        "elapsedSec": float(payload.get("elapsedSec") or 0.0),
        "error": error,
    }


def list_exports(limit: int = 100) -> list[dict[str, Any]]:
    """Export history, newest first.  Reads job.json so it survives restarts."""
    entries: list[dict[str, Any]] = []
    try:
        children = list(renders_dir().iterdir())
    except OSError:  # pragma: no cover - unreadable data dir
        return entries
    for child in children:
        if not child.is_dir() or not _valid_job_id(child.name):
            continue
        entry = export_entry(child.name)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda item: (item["finishedAt"] or item["createdAt"] or ""), reverse=True)
    return entries[: max(1, int(limit))]


def cleanup_stale_parts(max_age_sec: float = 60.0) -> int:
    """Delete leftover ``*.part`` files from killed/interrupted jobs."""
    removed = 0
    now = time.time()
    try:
        paths = list(renders_dir().rglob("*.part"))
    except OSError:  # pragma: no cover
        return 0
    for path in paths:
        try:
            if now - path.stat().st_mtime >= max_age_sec:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def delete_job(job_id: str) -> tuple[bool, int]:
    """Remove one export directory.  Running jobs are protected."""
    if not _valid_job_id(job_id):
        return False, 0
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is not None and job.get("status") in ("queued", "running"):
        raise RenderError(409, "任务正在渲染中，完成后才能删除。")
    directory = job_dir(job_id)
    if not directory.is_dir():
        with _JOBS_LOCK:
            _JOBS.pop(job_id, None)
        return False, 0
    freed = _dir_bytes(directory)
    try:
        shutil.rmtree(directory)
    except OSError as exc:  # pragma: no cover - windows file lock
        raise RenderError(500, f"删除导出文件失败：{exc}") from exc
    with _JOBS_LOCK:
        _JOBS.pop(job_id, None)
    return True, freed


def cleanup_exports(scope: str = "finished") -> dict[str, int]:
    """Bulk-delete exports: ``finished`` / ``failed`` / ``all`` (and stray parts)."""
    if scope not in ("finished", "failed", "all"):
        raise RenderError(400, f"未知的清理范围：{scope}")
    removed = 0
    freed = 0
    for entry in list_exports(limit=100_000):
        status = entry["status"]
        if scope == "finished" and status != "done":
            continue
        if scope == "failed" and status not in ("failed",):
            continue
        if scope == "all" and status in ("queued", "running"):
            continue
        try:
            ok, size = delete_job(entry["jobId"])
        except RenderError:
            continue
        if ok:
            removed += 1
            freed += size
    parts = cleanup_stale_parts(max_age_sec=0.0)
    return {"removed": removed, "freedBytes": int(freed), "partFiles": parts}


def wait_until_idle(timeout: float = 30.0) -> bool:
    """Test/debug helper: wait until no queued or running jobs remain."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _JOBS_LOCK:
            busy = any(job.get("status") in ("queued", "running")
                       for job in _JOBS.values())
        if not busy and _QUEUE.unfinished_tasks == 0:
            return True
        time.sleep(0.05)
    return False
