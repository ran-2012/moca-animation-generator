"""PSD domain service: parsing, layer tree, thumbnails, automap, profile, bake.

The service is transport agnostic (no FastAPI imports) so the pytest suite can
call it directly.  All heavy work goes through a per-asset lock and the opened
``PSDImage`` is cached, because a single local user hits the same document many
times (one thumbnail request per tree row).

Key facts about psd-tools 1.25 that shape this module:

* ``layer.bbox`` / ``layer.offset`` are absolute canvas coordinates;
* ``Group.topil()`` returns ``None`` -- groups must be rasterized by hand;
* a group's own ``visible`` flag does *not* cascade on assignment, so to bake a
  "base without face parts" we explicitly hide the feature groups and then call
  ``psd.composite(ignore_preview=True)`` (the stored merged preview is stale).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from PIL import Image

from .. import config, storage

# config.py puts the vendored psd-tools on sys.path before this import runs.
from psd_tools import PSDImage  # noqa: E402
from psd_tools.constants import Resource  # noqa: E402


class PsdError(Exception):
    """Error with an HTTP status code and a human readable message."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = int(status_code)
        self.detail = str(detail)


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

_ASSET_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
_CANVAS_PAD = 0

# Channels and their priority order (bottom -> top) used when no profile says otherwise.
DEFAULT_ZORDER = ["cheek", "mouth", "eyes", "brow", "eyeEffect", "sweat"]
DEFAULT_STATE = {
    "mouth": "closed", "eyes": "open", "brow": "neutral", "cheek": "normal",
    "eyeEffect": "off", "sweat": "off",
}

# Group names that identify a semantic feature container.  Matching is done on a
# normalized name (spaces / separators removed, lower-cased).
FEATURE_ALIASES: dict[str, tuple[str, ...]] = {
    "mouth": ("口", "くち", "mouth", "mouthparts", "口元", "くちびる"),
    "eyes": ("目", "め", "eye", "eyes", "まなこ"),
    "brow": ("眉毛", "まゆ", "brow", "eyebrow", "eyebrows"),
    "cheek": ("頬", "ほお", "cheek", "blush", "チーク", "頬っぺた"),
    "sweat": ("汗", "sweat"),
    "eyeEffect": ("効果", "eye effect", "eyeeffect"),
}

# Per-state layer names.  Exact normalized matches win over prefix/contains matches.
STATE_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "mouth": {
        "a": ("あ", "ア", "a"),
        "i": ("い", "イ", "i"),
        "u": ("う", "ウ", "u"),
        "e": ("え", "エ", "e"),
        "o": ("お", "オ", "o"),
        "n": ("ん", "ン", "n"),
        "closed": ("ω", "Ω", "w", "ー", "--", "口閉じ", "口を閉じる", "とじ", "閉じ", "closed"),
        "narrow": ("ん",),
        "pressed": ("むむ",),
        "roundSmall": ("ぉ",),
        "aSoft": ("あー",),
        "wide": ("わー",),
        "openLarge": ("□",),
        "openXLarge": ("□大",),
        "scream": ("ぎゃー",),
    },
    "eyes": {
        "open": ("通常", "ノーマル", "open", "開き", "開眼", "おめめ"),
        "blink": ("ーー", "——", "--", "blink", "閉じ", "閉じ目", "まばたき", "まばたき目", "つぶり"),
        "smile": ("にっこり", "笑い目", "微笑み", "smile", "にこにこ"),
        "cry": ("うるうる", "涙目", "涙", "泣き", "cry", "うる目"),
    },
    "brow": {
        "neutral": ("通常", "ノーマル", "neutral", "normal", "普通"),
        "angry": ("怒り", "怒", "angry", "mad", "いかり"),
        "question": ("疑問", "はてな", "question", "？", "?"),
        "surprise": ("驚き", "驚", "びっくり", "surprise", "！"),
        "sad": ("悲しみ", "悲しい", "sad", "かなしい"),
    },
    "cheek": {
        "normal": ("通常", "ノーマル", "normal", "neutral"),
        "blush": ("赤面", "頬染め", "照れ", "blush", "赤らみ"),
        "deep": ("真っ赤", "真赤", "まっか", "deep", "激赤"),
    },
    "sweat": {
        "single": ("汗",),
        "double": ("汗汗",),
        "neck": ("首汗",),
    },
    "eyeEffect": {
        "tear": ("涙",),
        "cry": ("泣き",),
    },
}

# Which ancestors hint at the right closed/open variant of a channel.
PARENT_HINTS: dict[tuple[str, str], dict[str, tuple[str, ...]]] = {
    ("eyes", "open"): {"prefer": ("開き", "開", "open", "opened"), "avoid": ("閉じ", "閉", "closed")},
    ("eyes", "blink"): {"prefer": ("閉じ", "閉", "closed", "blink")},
    ("eyes", "smile"): {"prefer": ("閉じ", "閉", "smile")},
    ("eyes", "cry"): {"prefer": ("閉じ", "閉", "cry", "涙")},
    ("mouth", "a"): {"prefer": ("あいうえお", "母音", "vowel")},
    ("mouth", "i"): {"prefer": ("あいうえお", "母音", "vowel")},
    ("mouth", "u"): {"prefer": ("あいうえお", "母音", "vowel")},
    ("mouth", "e"): {"prefer": ("あいうえお", "母音", "vowel")},
    ("mouth", "o"): {"prefer": ("あいうえお", "母音", "vowel")},
}

REQUIRED_STATES: dict[str, tuple[str, ...]] = {
    "mouth": ("a", "i", "u", "e", "o", "n", "closed"),
    "eyes": ("open", "blink"),
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _norm_name(name: str | None) -> str:
    return re.sub(r"[\s_\-・/／|｜]+", "", (name or "").strip()).lower()


def _blend_name(layer: Any) -> str:
    blend = getattr(layer, "blend_mode", None)
    name = getattr(blend, "name", None)
    if not name:
        name = str(blend or "normal").split(".")[-1]
    return str(name).lower()


def _bbox(value: Any) -> list[int]:
    try:
        left, top, right, bottom = (int(v) for v in value)
    except (TypeError, ValueError):
        return [0, 0, 0, 0]
    return [left, top, right, bottom]


def _offset(value: Any) -> tuple[int, int]:
    try:
        values = list(value)
    except TypeError:
        return (0, 0)
    if len(values) < 2:
        return (0, 0)
    try:
        return (int(values[0]), int(values[1]))
    except (TypeError, ValueError):
        return (0, 0)


def _layer_id(layer: Any) -> str | None:
    value = getattr(layer, "layer_id", None)
    return None if value is None else str(value)


def _validate_asset_id(asset_id: str) -> str:
    if not isinstance(asset_id, str) or not _ASSET_ID_RE.match(asset_id):
        raise PsdError(404, f"未知 PSD 资产: {asset_id}")
    return asset_id


def _source_path(asset_id: str) -> Path:
    _validate_asset_id(asset_id)
    source = storage.find_source("psd", asset_id)
    if source is None:
        raise PsdError(404, f"未知 PSD 资产: {asset_id}")
    return source


def _cache_dir(asset_id: str) -> Path:
    directory = storage.asset_dir("psd", asset_id) / "cache"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _read_dpi(psd: Any) -> float | None:
    """Read the 16.16 fixed point resolution resource and convert it to DPI."""
    try:
        info = psd.image_resources.get_data(Resource.RESOLUTION_INFO)
    except Exception:  # pragma: no cover - defensive
        return None
    if info is None:
        return None
    raw = float(getattr(info, "horizontal", 0) or 0) / 65536.0
    if raw <= 0:
        return None
    if int(getattr(info, "horizontal_unit", 1) or 1) == 2:  # pixels per cm
        raw *= 2.54
    return round(raw, 1)


def _media_path(url: str) -> Path | None:
    """Resolve a /media URL back to a file under data/assets (kept traversal-safe)."""
    if not isinstance(url, str) or not url.startswith("/media/"):
        return None
    relative = url[len("/media/"):]
    parts = Path(relative).parts
    if not parts or any(part in ("..", ".", "") for part in parts):
        return None
    return config.ASSETS_DIR / Path(*parts)


# ---------------------------------------------------------------------------
# PSD object cache
# ---------------------------------------------------------------------------

_ASSET_LOCKS: dict[str, threading.RLock] = {}
_PSD_CACHE: "OrderedDict[str, PSDImage]" = OrderedDict()
_CACHE_LOCK = threading.RLock()
_TREE_CACHE: dict[str, dict[str, Any]] = {}


def _asset_lock(asset_id: str) -> threading.RLock:
    with _CACHE_LOCK:
        lock = _ASSET_LOCKS.get(asset_id)
        if lock is None:
            lock = threading.RLock()
            _ASSET_LOCKS[asset_id] = lock
        return lock


def _open_psd(asset_id: str) -> PSDImage:
    """Open (and memoize) the PSDImage for an asset."""
    source = _source_path(asset_id)
    with _CACHE_LOCK:
        cached = _PSD_CACHE.get(asset_id)
        if cached is not None:
            _PSD_CACHE.move_to_end(asset_id)
            return cached
    psd = PSDImage.open(str(source))
    with _CACHE_LOCK:
        _PSD_CACHE[asset_id] = psd
        while len(_PSD_CACHE) > 2:
            _PSD_CACHE.popitem(last=False)
    return psd


# ---------------------------------------------------------------------------
# layer tree
# ---------------------------------------------------------------------------

def _build_node(layer: Any, path: str, parent_effective: bool) -> dict[str, Any]:
    visible = bool(layer.visible)
    effective = visible and parent_effective
    bbox = _bbox(getattr(layer, "bbox", None))
    width = max(0, bbox[2] - bbox[0])
    height = max(0, bbox[3] - bbox[1])
    is_group = bool(layer.is_group())
    node: dict[str, Any] = {
        "id": _layer_id(layer) or path,
        "path": path,
        "name": layer.name or "",
        "kind": "group" if is_group else "pixel",
        "visible": visible,
        "effectiveVisible": effective,
        "bbox": bbox,
        "width": width,
        "height": height,
        "opacity": int(getattr(layer, "opacity", 255) or 255),
        "blendMode": _blend_name(layer),
        "offset": list(_offset(getattr(layer, "offset", None))),
        "children": [],
    }
    if is_group:
        for index, child in enumerate(layer):
            child_path = f"{path}.{index}" if path else str(index)
            node["children"].append(_build_node(child, child_path, effective))
    return node


def _dedupe_tree_ids(root: dict[str, Any]) -> None:
    """psd-tools layer ids are unique in practice; guard against weird files."""
    seen: set[str] = set()

    def walk(node: dict[str, Any]) -> None:
        node_id = str(node.get("id") or node["path"])
        if node_id in seen:
            node_id = f"{node_id}@{node['path']}"
            node["id"] = node_id
        seen.add(node_id)
        for child in node.get("children", []):
            walk(child)

    walk(root)


def _iter_nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    for child in node.get("children", []):
        yield from _iter_nodes(child)


def _build_root(psd: PSDImage, source: Path, display_name: str | None = None) -> dict[str, Any]:
    stem = Path(display_name).stem if display_name else source.stem
    root: dict[str, Any] = {
        "id": "root",
        "path": "",
        "name": stem or "root",
        "kind": "group",
        "visible": True,
        "effectiveVisible": True,
        "bbox": [0, 0, int(psd.width), int(psd.height)],
        "width": int(psd.width),
        "height": int(psd.height),
        "opacity": 255,
        "blendMode": "normal",
        "offset": [0, 0],
        "children": [],
    }
    for index, layer in enumerate(psd):
        root["children"].append(_build_node(layer, str(index), True))
    _dedupe_tree_ids(root)
    return root


def _tree_stats(root: dict[str, Any]) -> dict[str, int]:
    layer_count = 0
    group_count = 0
    for node in _iter_nodes(root):
        if node.get("path", "") == "":
            continue
        layer_count += 1
        if node.get("kind") == "group":
            group_count += 1
    return {"layerCount": layer_count, "groupCount": group_count}


def _tree_data(asset_id: str) -> dict[str, Any]:
    """Return ``{root, canvas, meta, _index}`` with an on-disk cache."""
    source = _source_path(asset_id)
    stat = source.stat()
    signature = {"mtime": float(stat.st_mtime), "size": int(stat.st_size)}
    cached = _TREE_CACHE.get(asset_id)
    if cached is not None and cached.get("signature") == signature:
        return cached["data"]

    cache_path = storage.asset_dir("psd", asset_id) / "tree.json"
    data: dict[str, Any] | None = storage.read_json(cache_path)
    if not data or data.get("signature") != signature or not data.get("root"):
        psd = _open_psd(asset_id)
        meta = storage.read_json(storage.asset_meta_path("psd", asset_id), {}) or {}
        with _asset_lock(asset_id):
            root = _build_root(psd, source, meta.get("filename"))
            stats = _tree_stats(root)
            canvas = [int(psd.width), int(psd.height)]
            meta = {
                "width": canvas[0],
                "height": canvas[1],
                "dpi": _read_dpi(psd),
                **stats,
            }
        data = {
            "signature": signature,
            "canvas": canvas,
            "meta": meta,
            "root": root,
        }
        storage.write_json(cache_path, data)

    index: dict[str, dict[str, Any]] = {}
    for node in _iter_nodes(data["root"]):
        index[str(node["id"])] = node
    data["_index"] = index
    _TREE_CACHE[asset_id] = {"signature": signature, "data": data}
    return data


def layer_tree(asset_id: str) -> dict[str, Any]:
    """LayerNode tree (root node) for ``GET /api/psd/{id}/tree``."""
    return _tree_data(asset_id)["root"]


def asset_summary(asset_id: str) -> dict[str, Any]:
    """Best-effort summary for an existing asset (upload response shape)."""
    data = _tree_data(asset_id)
    meta = storage.read_json(storage.asset_meta_path("psd", asset_id), {}) or {}
    return {
        "assetId": asset_id,
        "filename": meta.get("filename") or f"{asset_id}.psd",
        "width": int(data["meta"]["width"]),
        "height": int(data["meta"]["height"]),
        "dpi": data["meta"].get("dpi"),
        "layerCount": int(data["meta"].get("layerCount", 0)),
        "groupCount": int(data["meta"].get("groupCount", 0)),
    }


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------

def upload_psd(filename: str, data: bytes) -> dict[str, Any]:
    """Persist an uploaded PSD, parse it, and prime the layer-tree cache."""
    if not data:
        raise PsdError(400, "上传文件为空")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise PsdError(413, f"PSD 超过大小限制（{config.MAX_UPLOAD_BYTES // (1024 * 1024)}MB）")

    original_name = Path(filename or "upload.psd").name
    asset_id = storage.new_id()
    asset_dir = storage.asset_dir("psd", asset_id)
    try:
        source = storage.save_upload("psd", asset_id, original_name, data)
        psd = PSDImage.open(str(source))
        width, height = int(psd.width), int(psd.height)
        root = _build_root(psd, source, original_name)
        stats = _tree_stats(root)
        dpi = _read_dpi(psd)
        stat = source.stat()
        signature = {"mtime": float(stat.st_mtime), "size": int(stat.st_size)}
        tree_payload = {
            "signature": signature,
            "canvas": [width, height],
            "meta": {"width": width, "height": height, "dpi": dpi, **stats},
            "root": root,
        }
        storage.write_json(asset_dir / "tree.json", tree_payload)
        meta = {
            "assetId": asset_id,
            "kind": "psd",
            "filename": original_name,
            "storedName": source.name,
            "width": width,
            "height": height,
            "dpi": dpi,
            "layerCount": stats["layerCount"],
            "groupCount": stats["groupCount"],
            "sizeBytes": len(data),
            "uploadedAt": _iso_now(),
        }
        storage.write_json(storage.asset_meta_path("psd", asset_id), meta)
        with _CACHE_LOCK:
            _PSD_CACHE[asset_id] = psd
            while len(_PSD_CACHE) > 2:
                _PSD_CACHE.popitem(last=False)
        _TREE_CACHE.pop(asset_id, None)
    except PsdError:
        raise
    except Exception as exc:  # corrupt / unsupported PSD
        shutil.rmtree(asset_dir, ignore_errors=True)
        raise PsdError(400, f"无法解析 PSD：{exc}") from exc

    return {
        "assetId": asset_id,
        "filename": original_name,
        "width": width,
        "height": height,
        "dpi": dpi,
        "layerCount": stats["layerCount"],
        "groupCount": stats["groupCount"],
    }


# ---------------------------------------------------------------------------
# layer lookup + rasterization
# ---------------------------------------------------------------------------

def _layer_by_path(psd: Any, path: str) -> Any:
    if not path:
        return psd
    node: Any = psd
    for part in path.split("."):
        node = node[int(part)]
    return node


def _find_layer(psd: Any, layer_id: str) -> Any:
    """Resolve a layer by stable layer id, dotted path, or "root"."""
    if not layer_id:
        return None
    if layer_id in ("root", "psd"):
        return psd
    for layer in psd.descendants():
        if _layer_id(layer) == layer_id:
            return layer
    if re.fullmatch(r"\d+(\.\d+)*", layer_id):
        try:
            return _layer_by_path(psd, layer_id)
        except (IndexError, KeyError, TypeError, ValueError):
            return None
    return None


def _content_bbox(layer: Any) -> tuple[int, int, int, int] | None:
    """Union bbox of every pixel descendant (groups often report an empty bbox)."""
    left = top = right = bottom = None
    stack = [layer]
    while stack:
        node = stack.pop()
        if node.is_group():
            stack.extend(list(node))
            continue
        bbox = _bbox(getattr(node, "bbox", None))
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        left = bbox[0] if left is None else min(left, bbox[0])
        top = bbox[1] if top is None else min(top, bbox[1])
        right = bbox[2] if right is None else max(right, bbox[2])
        bottom = bbox[3] if bottom is None else max(bottom, bbox[3])
    if left is None or right is None or top is None or bottom is None:
        return None
    return int(left), int(top), int(right), int(bottom)


def _alpha_paste(canvas: Image.Image, image: Image.Image, x: int, y: int) -> None:
    """alpha_composite ``image`` at (x, y), clipping negative / out-of-canvas parts."""
    width, height = canvas.size
    source_left = 0
    source_top = 0
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
    if source_left or source_top or paste_width != image.width or paste_height != image.height:
        image = image.crop((source_left, source_top, source_left + paste_width, source_top + paste_height))
    if image.size != (paste_width, paste_height):  # pragma: no cover - defensive
        return
    canvas.alpha_composite(image, (x, y))


def _rasterize_group(group: Any) -> Image.Image | None:
    bbox = _content_bbox(group)
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    canvas = Image.new("RGBA", (max(1, right - left), max(1, bottom - top)), (0, 0, 0, 0))

    def walk(node: Any) -> None:
        for child in node:
            if child.is_group():
                if child.visible:
                    walk(child)
                continue
            if not child.visible:
                continue
            image = child.topil()
            if image is None:
                continue
            offset = _offset(getattr(child, "offset", None))
            _alpha_paste(canvas, image.convert("RGBA"), offset[0] - left, offset[1] - top)

    walk(group)
    return canvas


def _rasterize_layer(layer: Any) -> tuple[Image.Image | None, tuple[int, int]]:
    """Return (RGBA image, absolute canvas offset) for a pixel *or* group layer."""
    if layer is None:
        return None, (0, 0)
    if layer.is_group():
        bbox = _content_bbox(layer)
        image = _rasterize_group(layer)
        if image is None or bbox is None:
            return None, (0, 0)
        return image, (bbox[0], bbox[1])
    image = layer.topil()
    if image is None:
        return None, (0, 0)
    offset = _offset(getattr(layer, "offset", None))
    return image.convert("RGBA"), (offset[0], offset[1])


def _rasterize_root(psd: Any) -> Image.Image | None:
    image = psd.topil()
    if image is not None:
        return image.convert("RGBA")
    try:
        return psd.composite(ignore_preview=True).convert("RGBA")
    except Exception:  # pragma: no cover - defensive
        return None


# ---------------------------------------------------------------------------
# thumbnails
# ---------------------------------------------------------------------------

def thumbnail_png(asset_id: str, layer_id: str, size: int = 160) -> bytes:
    size = max(8, min(int(size or 160), 1024))
    cache_dir = _cache_dir(asset_id) / "thumbs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(str(layer_id).encode("utf-8")).hexdigest()[:16]
    target = cache_dir / f"{digest}_{size}.png"
    if target.is_file():
        return target.read_bytes()

    psd = _open_psd(asset_id)
    with _asset_lock(asset_id):
        layer = _find_layer(psd, layer_id)
        if layer is None:
            raise PsdError(404, f"未找到图层: {layer_id}")
        if layer is psd:
            image = _rasterize_root(psd)
        else:
            image, _offset = _rasterize_layer(layer)
        if image is None:
            raise PsdError(404, f"图层无法栅格化: {layer_id}")
        image = image.convert("RGBA")
        image.thumbnail((size, size), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", compress_level=3)
    payload = buffer.getvalue()
    try:
        target.write_bytes(payload)
    except OSError:  # pragma: no cover - cache is best effort
        pass
    return payload


# ---------------------------------------------------------------------------
# automap
# ---------------------------------------------------------------------------

def _name_score(name: str, aliases: tuple[str, ...]) -> int:
    normalized = _norm_name(name)
    if not normalized:
        return 0
    best = 0
    for alias in aliases:
        candidate = _norm_name(alias)
        if not candidate:
            continue
        if len(candidate) == 1 and candidate.isascii():
            # A bare latin letter should only match exactly ("a" never matches "あー").
            if normalized == candidate:
                best = max(best, 100)
            continue
        if normalized == candidate:
            best = max(best, 100)
        elif normalized.startswith(candidate) or normalized.endswith(candidate):
            best = max(best, 60)
        elif candidate in normalized:
            best = max(best, 35)
    return best


def _detect_feature_groups(root: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Find the semantic feature containers (口 / 目 / 眉毛 / 頬) by name."""
    warnings: list[str] = []
    candidates: dict[str, list[tuple[float, dict[str, Any]]]] = {name: [] for name in FEATURE_ALIASES}
    for node in _iter_nodes(root):
        if node.get("kind") != "group" or not node.get("path"):
            continue
        depth = len(str(node["path"]).split("."))
        normalized = _norm_name(node.get("name"))
        for channel, aliases in FEATURE_ALIASES.items():
            score = 0.0
            for alias in aliases:
                candidate = _norm_name(alias)
                if not candidate:
                    continue
                if normalized == candidate:
                    score = max(score, 100.0)
                elif candidate in normalized:
                    score = max(score, 55.0)
            if score:
                # Same-name groups: prefer the outermost (least specific nesting
                # is not wanted, so reward exact matches and slightly prefer
                # shallower containers only as a tie breaker).
                candidates[channel].append((score - depth * 0.5, node))

    found: dict[str, dict[str, Any]] = {}
    for channel, entries in candidates.items():
        if not entries:
            continue
        entries.sort(key=lambda item: (-item[0], len(str(item[1]["path"]).split(".")), item[1]["path"]))
        best_score = entries[0][0]
        best_node = entries[0][1]
        tied = [node for score, node in entries if abs(score - best_score) < 1e-6]
        if len(tied) > 1:
            warnings.append(
                f"通道 {channel} 有多个候选组："
                + "、".join(f"{node['name']}({node['path']})" for node in tied[:4])
                + f"，已选择 {best_node['name']}({best_node['path']})"
            )
        found[channel] = best_node
    return found, warnings


def _ancestor_names(by_path: dict[str, dict[str, Any]], path: str) -> list[str]:
    names: list[str] = []
    parts = str(path).split(".")
    for end in range(1, len(parts)):
        ancestor = by_path.get(".".join(parts[:end]))
        if ancestor:
            names.append(str(ancestor.get("name") or ""))
    return names


def _descendant_nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for child in node.get("children", []):
        yield child
        yield from _descendant_nodes(child)


def _automap_profile(asset_id: str) -> dict[str, Any]:
    data = _tree_data(asset_id)
    root = data["root"]
    by_path = {str(node["path"]): node for node in _iter_nodes(root)}
    warnings: list[str] = []
    groups, group_warnings = _detect_feature_groups(root)
    warnings.extend(group_warnings)

    channels: dict[str, dict[str, str]] = {}
    confidence: dict[str, float] = {}
    best_nodes: dict[str, list[dict[str, Any]]] = {}
    hidden_groups: list[str] = []

    for channel, aliases_by_state in STATE_ALIASES.items():
        feature_group = groups.get(channel)
        if feature_group is None:
            warnings.append(f"未找到 {channel} 组，跳过该通道")
            continue
        hidden_groups.append(str(feature_group["path"]))
        pool = list(_descendant_nodes(feature_group))
        pixel_pool = [node for node in pool if node.get("kind") == "pixel"]
        group_pool = [node for node in pool if node.get("kind") == "group"]
        # Full-state patches tend to be the biggest layer of a group; pupils etc.
        # are much smaller and should not win the area heuristic.
        max_area = 0
        for node in pixel_pool:
            area = int(node.get("width", 0)) * int(node.get("height", 0))
            max_area = max(max_area, area)

        mapping: dict[str, str] = {}
        scores: list[float] = []
        node_hits: list[dict[str, Any]] = []
        for state, aliases in aliases_by_state.items():
            scored: list[tuple[float, dict[str, Any]]] = []
            for node in pixel_pool:
                score = _name_score(node.get("name", ""), aliases)
                if score <= 0:
                    continue
                if node.get("effectiveVisible"):
                    score += 25
                parent_names = _ancestor_names(by_path, node.get("path", ""))
                hints = PARENT_HINTS.get((channel, state), {})
                normalized_parents = [_norm_name(name) for name in parent_names]
                if any(any(_norm_name(hint) in parent for hint in hints.get("prefer", ())) for parent in normalized_parents):
                    score += 20
                if any(any(_norm_name(hint) in parent for hint in hints.get("avoid", ())) for parent in normalized_parents):
                    score -= 15
                area = int(node.get("width", 0)) * int(node.get("height", 0))
                if max_area > 0:
                    score += 25.0 * (area / max_area)
                score -= 0.5 * len(str(node["path"]).split("."))
                scored.append((score, node))
            if not scored:
                # Fall back to group nodes (whole sub-tree replacement).
                for node in group_pool:
                    score = _name_score(node.get("name", ""), aliases) - 15
                    if score <= 0:
                        continue
                    if node.get("effectiveVisible"):
                        score += 25
                    scored.append((score, node))
            if not scored:
                continue
            scored.sort(key=lambda item: (-item[0], item[1]["path"]))
            best_score, best = scored[0]
            mapping[state] = str(best["id"])
            scores.append(best_score)
            node_hits.append(best)
            if best_score < 80:
                warnings.append(
                    f"{channel}.{state} 匹配置信度较低：{best.get('name')}（{best.get('path')}，score={best_score:.1f}）"
                )

        if not mapping:
            warnings.append(f"{channel} 组内没有匹配到任何状态层")
            hidden_groups.pop()
            continue

        channels[channel] = mapping
        confidence[channel] = round(min(0.99, (sum(scores) / len(scores)) / 160.0), 3)
        best_nodes[channel] = node_hits

    for channel, states in REQUIRED_STATES.items():
        mapping = channels.get(channel, {})
        missing = [state for state in states if state not in mapping]
        if missing:
            warnings.append(f"必需通道状态缺失：{channel}.{'/'.join(missing)}（前端将降级）")

    # Default state: required base states when mapped, otherwise the first entry.
    default_state: dict[str, str] = {}
    for channel in DEFAULT_ZORDER:
        mapping = channels.get(channel)
        if not mapping:
            continue
        preferred = DEFAULT_STATE.get(channel)
        if channel in ("sweat", "eyeEffect"):
            default_state[channel] = "off"
        else:
            default_state[channel] = preferred if preferred in mapping else next(iter(mapping))

    zorder = [channel for channel in DEFAULT_ZORDER if channel in channels]
    zorder += [channel for channel in channels if channel not in zorder]
    profile = {
        "psdAssetId": asset_id,
        "canvas": [int(data["canvas"][0]), int(data["canvas"][1])],
        "base": {
            "hiddenGroups": hidden_groups,
            "hiddenLayers": [],
            "defaultState": default_state,
        },
        "channels": channels,
        "mappingSets": {
            "standard": {"label": "标准", "channels": channels},
        },
        "defaultMappingSetId": "standard",
        "channelDefinitions": {
            channel: {
                "behavior": "overlay" if channel in ("sweat", "eyeEffect") else "exclusive",
                "defaultState": DEFAULT_STATE.get(channel, next(iter(mapping))),
            }
            for channel, mapping in channels.items()
        },
        "zorder": zorder,
        "meta": {
            "auto": True,
            "confidence": confidence,
            "warnings": warnings,
        },
    }
    return profile


def automap(asset_id: str) -> dict[str, Any]:
    """Heuristic MappingProfile for an uploaded PSD (never hardcodes an asset id)."""
    profile = _automap_profile(asset_id)
    return {"profile": profile, "warnings": list(profile["meta"]["warnings"])}


# ---------------------------------------------------------------------------
# profile persistence
# ---------------------------------------------------------------------------

def _prepare_profile(asset_id: str, profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise PsdError(400, "profile 必须是 JSON 对象")
    data = _tree_data(asset_id)
    base_raw = profile.get("base") if isinstance(profile.get("base"), dict) else {}
    hidden_groups = [str(path) for path in (base_raw.get("hiddenGroups") or []) if str(path)]
    hidden_layers = [str(layer) for layer in (base_raw.get("hiddenLayers") or []) if str(layer)]
    default_raw = base_raw.get("defaultState") if isinstance(base_raw.get("defaultState"), dict) else {}
    mapping_sets_raw = profile.get("mappingSets") if isinstance(profile.get("mappingSets"), dict) else {}
    default_mapping_set_id = str(profile.get("defaultMappingSetId") or "standard")
    selected_set = mapping_sets_raw.get(default_mapping_set_id)
    selected_channels = selected_set.get("channels") if isinstance(selected_set, dict) else None
    channels_raw = profile.get("channels") if isinstance(profile.get("channels"), dict) else (
        selected_channels if isinstance(selected_channels, dict) else {}
    )
    channels: dict[str, dict[str, str]] = {}
    for channel, states in channels_raw.items():
        if not isinstance(states, dict):
            continue
        cleaned = {str(state): str(layer) for state, layer in states.items() if layer not in (None, "")}
        if cleaned:
            channels[str(channel)] = cleaned
    zorder = [str(channel) for channel in (profile.get("zorder") or []) if str(channel)]
    if not zorder:
        zorder = [channel for channel in DEFAULT_ZORDER if channel in channels]
    zorder += [channel for channel in channels if channel not in zorder]

    default_state: dict[str, str] = {str(key): str(value) for key, value in default_raw.items() if value}
    for channel, states in channels.items():
        if channel in ("sweat", "eyeEffect") and default_state.get(channel, "off") == "off":
            default_state[channel] = "off"
            continue
        if default_state.get(channel) not in states:
            default_state[channel] = DEFAULT_STATE.get(channel) if DEFAULT_STATE.get(channel) in states else next(iter(states))

    cleaned_sets: dict[str, dict[str, Any]] = {}
    for set_id, mapping_set in mapping_sets_raw.items():
        if not isinstance(mapping_set, dict):
            continue
        set_channels: dict[str, dict[str, str]] = {}
        for channel, states in (mapping_set.get("channels") or {}).items():
            if not isinstance(states, dict):
                continue
            set_channels[str(channel)] = {
                str(state): str(layer) for state, layer in states.items() if layer not in (None, "")
            }
        cleaned_sets[str(set_id)] = {
            "label": str(mapping_set.get("label") or set_id),
            "channels": set_channels,
        }
    if not cleaned_sets:
        cleaned_sets["standard"] = {"label": "标准", "channels": channels}
        default_mapping_set_id = "standard"
    if default_mapping_set_id not in cleaned_sets:
        default_mapping_set_id = next(iter(cleaned_sets))
    cleaned_sets[default_mapping_set_id]["channels"] = channels

    channel_definitions = profile.get("channelDefinitions") if isinstance(profile.get("channelDefinitions"), dict) else {}
    definitions = {
        channel: {
            "behavior": "overlay" if channel in ("sweat", "eyeEffect") else "exclusive",
            "defaultState": DEFAULT_STATE.get(channel, next(iter(states), "off")),
            **(channel_definitions.get(channel) if isinstance(channel_definitions.get(channel), dict) else {}),
        }
        for channel, states in channels.items()
    }
    meta = profile.get("meta") if isinstance(profile.get("meta"), dict) else {}
    return {
        "psdAssetId": asset_id,
        "canvas": [int(data["canvas"][0]), int(data["canvas"][1])],
        "base": {
            "hiddenGroups": hidden_groups,
            "hiddenLayers": hidden_layers,
            "defaultState": default_state,
        },
        "channels": channels,
        "mappingSets": cleaned_sets,
        "defaultMappingSetId": default_mapping_set_id,
        "channelDefinitions": definitions,
        "zorder": zorder,
        "meta": meta,
    }


def _profile_path(asset_id: str) -> Path:
    return storage.asset_dir("psd", asset_id) / "profile.json"


def load_profile(asset_id: str) -> dict[str, Any] | None:
    _source_path(asset_id)
    payload = storage.read_json(_profile_path(asset_id))
    if not isinstance(payload, dict):
        return None
    return _prepare_profile(asset_id, payload)


def save_profile(asset_id: str, payload: Any) -> dict[str, Any]:
    _source_path(asset_id)
    profile = _prepare_profile(asset_id, payload)
    storage.write_json(_profile_path(asset_id), profile)
    return profile


def _profile_hash(profile: dict[str, Any]) -> str:
    canonical = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def current_profile(asset_id: str) -> dict[str, Any]:
    """Saved profile if any, else the automap proposal (used by bake/preview)."""
    profile = load_profile(asset_id)
    if profile is not None:
        return profile
    return _prepare_profile(asset_id, _automap_profile(asset_id))


# ---------------------------------------------------------------------------
# bake
# ---------------------------------------------------------------------------

def _manifest_files_ok(manifest: dict[str, Any]) -> bool:
    if not isinstance(manifest, dict):
        return False
    base_url = ((manifest.get("base") or {}).get("url")) if isinstance(manifest.get("base"), dict) else None
    base_path = _media_path(base_url) if base_url else None
    if base_path is None or not base_path.is_file():
        return False
    patches = manifest.get("patches")
    if not isinstance(patches, dict):
        return False
    for patch in patches.values():
        if not isinstance(patch, dict):
            return False
        url = patch.get("url")
        path = _media_path(url) if url else None
        if path is None or not path.is_file():
            return False
    return True


def _manifest_path(asset_id: str) -> Path:
    return _cache_dir(asset_id) / "manifest.json"


def get_manifest(asset_id: str) -> dict[str, Any] | None:
    """Cached BakeManifest, or None (HTTP 404 upstream)."""
    _source_path(asset_id)
    manifest = storage.read_json(_manifest_path(asset_id))
    if not isinstance(manifest, dict) or not _manifest_files_ok(manifest):
        return None
    return manifest


def _hide_for_base(psd: Any, profile: dict[str, Any], warnings: list[str]) -> list[Any]:
    """Hide the profile's feature groups/layers; returns the layers to restore."""
    touched: list[Any] = []
    for path in profile["base"].get("hiddenGroups") or []:
        try:
            layer = _layer_by_path(psd, path)
        except (IndexError, KeyError, TypeError, ValueError):
            warnings.append(f"隐藏组路径无效：{path}")
            continue
        if layer is psd:
            continue
        if layer.visible:
            layer.visible = False
            touched.append(layer)
    for layer_id in profile["base"].get("hiddenLayers") or []:
        layer = _find_layer(psd, layer_id)
        if layer is None or layer is psd:
            warnings.append(f"隐藏图层无效：{layer_id}")
            continue
        if layer.visible:
            layer.visible = False
            touched.append(layer)
    return touched


def _restore_visibility(layers: list[Any]) -> None:
    for layer in layers:
        try:
            layer.visible = True
        except Exception:  # pragma: no cover - defensive
            pass


def _bake_patches(
    psd: Any,
    profile: dict[str, Any],
    cache_dir: Path,
    warnings: list[str],
) -> dict[str, dict[str, Any]]:
    patches: dict[str, dict[str, Any]] = {}
    for channel in profile["zorder"]:
        mapping = profile["channels"].get(channel) or {}
        for state, layer_id in mapping.items():
            layer = _find_layer(psd, layer_id)
            if layer is None:
                warnings.append(f"图层不存在：{channel}.{state} -> {layer_id}")
                continue
            image, offset = _rasterize_layer(layer)
            if image is None:
                warnings.append(f"图层无法栅格化：{channel}.{state} -> {layer_id}")
                continue
            filename = f"patch_{channel}_{state}.png"
            target = cache_dir / filename
            image.save(target, format="PNG", compress_level=3)
            patches[f"{channel}.{state}"] = {
                "url": storage.media_url(target),
                "offset": [int(offset[0]), int(offset[1])],
                "width": int(image.width),
                "height": int(image.height),
            }
    return patches


def _clean_cache(cache_dir: Path, keep: set[str]) -> None:
    for path in cache_dir.glob("patch_*.png"):
        if path.name not in keep:
            try:
                path.unlink()
            except OSError:  # pragma: no cover - best effort
                pass


def bake(asset_id: str, profile: Any = None) -> dict[str, Any]:
    """Bake base + differential patches.

    Synchronous and intentionally heavy on the first run (~10-30s for a
    2480x3500 PSD).  The result is cached by profile hash: the same profile
    returns the stored manifest without touching psd-tools again.
    """
    _source_path(asset_id)
    if profile is None:
        profile = current_profile(asset_id)
    else:
        profile = _prepare_profile(asset_id, profile)
    profile_hash = _profile_hash(profile)
    cache_dir = _cache_dir(asset_id)
    manifest_path = cache_dir / "manifest.json"

    cached = storage.read_json(manifest_path)
    if isinstance(cached, dict) and cached.get("profileVersion") == profile_hash and _manifest_files_ok(cached):
        result = dict(cached)
        result["cached"] = True
        return result

    started = time.perf_counter()
    warnings: list[str] = []
    psd = _open_psd(asset_id)
    with _asset_lock(asset_id):
        t0 = time.perf_counter()
        patches = _bake_patches(psd, profile, cache_dir, warnings)
        patches_seconds = time.perf_counter() - t0

        touched: list[Any] = []
        try:
            touched = _hide_for_base(psd, profile, warnings)
            t0 = time.perf_counter()
            base = psd.composite(ignore_preview=True).convert("RGBA")
            base_seconds = time.perf_counter() - t0
        finally:
            _restore_visibility(touched)

        base_path = cache_dir / "base.png"
        t0 = time.perf_counter()
        base.save(base_path, format="PNG", compress_level=3)
        save_seconds = time.perf_counter() - t0

    elapsed = time.perf_counter() - started
    manifest: dict[str, Any] = {
        "assetId": asset_id,
        "width": int(psd.width),
        "height": int(psd.height),
        "base": {"url": storage.media_url(base_path)},
        "patches": patches,
        "zorder": list(profile["zorder"]),
        "profileVersion": profile_hash,
        "bakedAt": _iso_now(),
        # Extra (non-contract) metadata: useful for debugging / preview reuse.
        "defaultState": dict(profile["base"].get("defaultState") or {}),
        "hiddenGroups": list(profile["base"].get("hiddenGroups") or []),
        "hiddenLayers": list(profile["base"].get("hiddenLayers") or []),
        "warnings": warnings,
        "timings": {
            "patches": round(patches_seconds, 3),
            "baseComposite": round(base_seconds, 3),
            "baseSave": round(save_seconds, 3),
            "total": round(elapsed, 3),
        },
    }
    storage.write_json(manifest_path, manifest)
    keep = {Path(patch["url"]).name for patch in patches.values()} | {"base.png", "manifest.json"}
    _clean_cache(cache_dir, keep)
    result = dict(manifest)
    result["cached"] = False
    return result


# ---------------------------------------------------------------------------
# preview (base + default-state patches, no full PSD composite when possible)
# ---------------------------------------------------------------------------

def _load_rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def _overlay_defaults(
    base: Image.Image,
    profile: dict[str, Any],
    patch_images: dict[str, tuple[Image.Image, tuple[int, int]]],
) -> Image.Image:
    composed = base.copy()
    defaults = profile["base"].get("defaultState") or {}
    for channel in profile["zorder"]:
        state = defaults.get(channel)
        if not state:
            continue
        entry = patch_images.get(f"{channel}.{state}")
        if entry is None:
            continue
        image, offset = entry
        _alpha_paste(composed, image, int(offset[0]), int(offset[1]))
    return composed


def _rasterize_default_patches(
    psd: Any, profile: dict[str, Any]
) -> dict[str, tuple[Image.Image, tuple[int, int]]]:
    defaults = profile["base"].get("defaultState") or {}
    result: dict[str, tuple[Image.Image, tuple[int, int]]] = {}
    for channel in profile["zorder"]:
        state = defaults.get(channel)
        if not state:
            continue
        layer_id = (profile["channels"].get(channel) or {}).get(state)
        if not layer_id:
            continue
        layer = _find_layer(psd, layer_id)
        if layer is None:
            continue
        image, offset = _rasterize_layer(layer)
        if image is not None:
            result[f"{channel}.{state}"] = (image, offset)
    return result


def preview_png(asset_id: str, width: int = 900) -> bytes:
    """PNG of the current profile's default state, composed from base + patches."""
    width = max(64, min(int(width or 900), 4096))
    _source_path(asset_id)
    profile = current_profile(asset_id)
    profile_hash = _profile_hash(profile)
    cache_dir = _cache_dir(asset_id)
    target = cache_dir / f"preview_{width}_{profile_hash[:12]}.png"
    if target.is_file():
        return target.read_bytes()

    manifest = storage.read_json(_manifest_path(asset_id))
    base_image: Image.Image | None = None
    patch_images: dict[str, tuple[Image.Image, tuple[int, int]]] = {}

    if (
        isinstance(manifest, dict)
        and manifest.get("profileVersion") == profile_hash
        and _manifest_files_ok(manifest)
    ):
        base_path = _media_path(manifest["base"]["url"])
        if base_path is not None:
            base_image = _load_rgba(base_path)
        for key, patch in (manifest.get("patches") or {}).items():
            patch = patch or {}
            path = _media_path(patch.get("url"))
            if path is not None and path.is_file():
                patch_images[key] = (_load_rgba(path), _offset(patch.get("offset")))
    elif (
        isinstance(manifest, dict)
        and manifest.get("hiddenGroups") == list(profile["base"].get("hiddenGroups") or [])
        and _manifest_files_ok(manifest)
    ):
        # Only channel/state mapping changed: the baked base is still valid.
        base_path = _media_path(manifest["base"]["url"])
        if base_path is not None:
            base_image = _load_rgba(base_path)

    psd = _open_psd(asset_id)
    with _asset_lock(asset_id):
        if base_image is None:
            patch_images = _rasterize_default_patches(psd, profile)
            touched: list[Any] = []
            try:
                touched = _hide_for_base(psd, profile, [])
                base_image = psd.composite(ignore_preview=True).convert("RGBA")
            finally:
                _restore_visibility(touched)
        else:
            patch_images = _rasterize_default_patches(psd, profile)

    composed = _overlay_defaults(base_image, profile, patch_images)
    if composed.width > width:
        target_width = width
        target_height = max(1, round(composed.height * (width / composed.width)))
        composed = composed.resize((target_width, target_height), Image.LANCZOS)
    buffer = io.BytesIO()
    composed.save(buffer, format="PNG", compress_level=3)
    payload = buffer.getvalue()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        for stale in cache_dir.glob(f"preview_{width}_*.png"):
            if stale.name != target.name:
                stale.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - cache is best effort
        pass
    return payload
