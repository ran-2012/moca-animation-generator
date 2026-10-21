"""PSD / project API tests (CONTRACT.md §7).

Pure pytest-style tests with no fixtures on purpose: they also run with
``python tests/test_psd.py`` when pytest is unavailable in the environment.
Run from ``moca-diff/backend``:

    python -m pytest tests/test_psd.py -q
    python tests/test_psd.py

The suite reuses the read-only ``moca.psd`` in the workspace root and redirects
``config``'s runtime directories to a throw-away folder under ``backend/tests``
so the real ``data/`` tree is untouched.
"""

from __future__ import annotations

import atexit
import gc
# (hashlib not needed)
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
MOCA_PSD = WORKSPACE / "moca.psd"

from PIL import Image  # noqa: E402

from app import config, storage  # noqa: E402
from app.services import project_service, psd_service  # noqa: E402

# Keep the workspace clean: only the /media URL layer depends on these paths.
_ORIGINAL_PATHS = {
    "DATA_DIR": config.DATA_DIR,
    "ASSETS_DIR": config.ASSETS_DIR,
    "PROJECTS_DIR": config.PROJECTS_DIR,
    "SETTINGS_FILE": config.SETTINGS_FILE,
}

_ENV: dict | None = None
_BAKED: dict | None = None


def _make_env() -> dict:
    # Keep the throw-away runtime tree outside `tests/` so pytest does not scan
    # it, and create it with the default mode: Python's `tempfile` uses mode
    # 0o700, which this Windows sandbox turns into an unreadable explicit ACL.
    root = BACKEND_DIR / f".test_data_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True)
    config.DATA_DIR = root / "data"
    config.ASSETS_DIR = root / "data" / "assets"
    config.PROJECTS_DIR = root / "data" / "projects"
    config.SETTINGS_FILE = root / "data" / "settings.json"
    config.ensure_dirs()
    assert MOCA_PSD.is_file(), f"找不到测试素材: {MOCA_PSD}"
    info = psd_service.upload_psd(MOCA_PSD.name, MOCA_PSD.read_bytes())
    return {"root": root, "info": info, "assetId": info["assetId"]}


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
    # psd-tools / Pillow may still hold handles; drop the caches before rmtree.
    psd_service._PSD_CACHE.clear()
    psd_service._TREE_CACHE.clear()
    gc.collect()
    root = _ENV["root"]
    for _ in range(10):
        try:
            shutil.rmtree(root)
            return
        except OSError:
            time.sleep(0.2)
    print(f"[test_psd] 警告：临时目录未能删除，可手动清理 {root}")


atexit.register(_cleanup)


def _asset_id() -> str:
    return _env()["assetId"]


def _walk_tree(node: dict):
    yield node
    for child in node.get("children", []):
        yield from _walk_tree(child)


def _find_node(asset_id: str, node_id: str) -> dict:
    for node in _walk_tree(psd_service.layer_tree(asset_id)):
        if node["id"] == node_id:
            return node
    raise AssertionError(f"图层树里找不到 id={node_id}")


def _media_file(url: str) -> Path:
    assert url.startswith("/media/"), f"不是 /media URL: {url}"
    return config.ASSETS_DIR / Path(url[len("/media/"):])


def _ensure_baked() -> dict:
    global _BAKED
    if _BAKED is None:
        asset_id = _asset_id()
        profile = psd_service.automap(asset_id)["profile"]
        psd_service.save_profile(asset_id, profile)
        _BAKED = psd_service.bake(asset_id)
    return _BAKED


# ---------------------------------------------------------------------------
# upload / tree
# ---------------------------------------------------------------------------

def test_upload_info() -> None:
    env = _env()
    info = env["info"]
    assert info["assetId"] == env["assetId"]
    assert len(info["assetId"]) == 12
    assert info["filename"] == "moca.psd"
    assert info["width"] == 2480
    assert info["height"] == 3500
    assert isinstance(info["dpi"], (int, float)) and 300 <= info["dpi"] <= 400
    assert info["layerCount"] == 190
    assert info["groupCount"] == 31
    # meta.json written next to the persisted source file
    meta = storage.read_json(storage.asset_meta_path("psd", env["assetId"]), {})
    assert meta.get("filename") == "moca.psd"
    assert meta.get("width") == 2480
    source = storage.find_source("psd", env["assetId"])
    assert source is not None and source.name == "source.psd"


def test_tree_contract() -> None:
    asset_id = _asset_id()
    tree = psd_service.layer_tree(asset_id)
    assert tree["id"] == "root"
    assert tree["kind"] == "group"
    assert [tree["width"], tree["height"]] == [2480, 3500]
    assert len(tree["children"]) >= 2
    all_nodes = list(_walk_tree(tree))
    assert len(all_nodes) == 191  # root + 190 layers

    mouth_a = _find_node(asset_id, "63")
    assert mouth_a["path"] == "0.3.1.19.4"
    assert mouth_a["name"] == "あ"
    assert mouth_a["kind"] == "pixel"
    assert mouth_a["bbox"] == [1171, 727, 1324, 859]
    assert [mouth_a["width"], mouth_a["height"]] == [153, 132]
    assert mouth_a["opacity"] == 255
    assert mouth_a["blendMode"] == "normal"
    assert mouth_a["visible"] is True
    # parent group あいうえお is hidden in the PSD, so it is not effectively visible
    assert mouth_a["effectiveVisible"] is False
    assert mouth_a["children"] == []

    face = _find_node(asset_id, "146")
    assert face["name"] == "顔パーツ"
    assert face["kind"] == "group"
    assert len(face["children"]) >= 4
    assert face["bbox"] == [1016, 449, 1544, 780]


def test_missing_asset_errors() -> None:
    for call in (
        lambda: psd_service.layer_tree("doesnotexist"),
        lambda: psd_service.thumbnail_png("doesnotexist", "1"),
    ):
        try:
            call()
        except psd_service.PsdError as exc:
            assert exc.status_code == 404
        else:  # pragma: no cover
            raise AssertionError("未知资产应返回 404")
    try:
        psd_service.upload_psd("broken.psd", b"not a psd at all")
    except psd_service.PsdError as exc:
        assert exc.status_code == 400
    else:  # pragma: no cover
        raise AssertionError("损坏的 PSD 应返回 400")


# ---------------------------------------------------------------------------
# automap
# ---------------------------------------------------------------------------

def test_automap_identifies_moca_channels() -> None:
    asset_id = _asset_id()
    result = psd_service.automap(asset_id)
    profile = result["profile"]
    channels = profile["channels"]

    assert channels["mouth"] == {
        "a": "63",
        "i": "62",
        "u": "61",
        "e": "60",
        "o": "59",
        "n": "42",
        "closed": "44",
    }
    assert channels["eyes"] == {"open": "119", "blink": "137", "smile": "136", "cry": "134"}
    assert channels["brow"] == {
        "neutral": "140",
        "angry": "141",
        "question": "142",
        "surprise": "143",
        "sad": "144",
    }
    assert channels["cheek"] == {"normal": "32", "blush": "33", "deep": "34"}

    # names of the mapped layers, looked up through the tree (guard against id drift)
    expected_names = {
        "63": "あ", "62": "い", "61": "う", "60": "え", "59": "お",
        "42": "ん", "44": "ω", "119": "通常", "137": "ーー",
        "136": "にっこり", "134": "うるうる",
    }
    for layer_id, name in expected_names.items():
        assert _find_node(asset_id, layer_id)["name"] == name

    assert profile["canvas"] == [2480, 3500]
    assert profile["base"]["defaultState"] == {
        "cheek": "normal",
        "mouth": "closed",
        "eyes": "open",
        "brow": "neutral",
    }
    assert set(profile["base"]["hiddenGroups"]) == {"0.3.1", "0.3.2", "0.3.3", "0.3.0.0"}
    assert profile["zorder"] == ["cheek", "mouth", "eyes", "brow"]
    assert profile["meta"]["auto"] is True
    assert set(profile["meta"]["confidence"]) == {"mouth", "eyes", "brow", "cheek"}
    assert result["warnings"] == []


# ---------------------------------------------------------------------------
# thumbnails / profile
# ---------------------------------------------------------------------------

def test_thumbnails_are_png() -> None:
    asset_id = _asset_id()
    raw = psd_service.thumbnail_png(asset_id, "63", 160)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    import io

    with Image.open(io.BytesIO(raw)) as image:
        assert image.mode == "RGBA"
        assert image.size == (153, 132)  # smaller than size -> no upscale
        assert image.getchannel("A").getextrema()[1] > 0

    group_raw = psd_service.thumbnail_png(asset_id, "0.3.2", 160)
    with Image.open(io.BytesIO(group_raw)) as image:
        assert image.mode == "RGBA"
        assert max(image.size) <= 160
        assert image.getchannel("A").getextrema()[1] > 0  # group rendered by hand

    root_raw = psd_service.thumbnail_png(asset_id, "root", 96)
    with Image.open(io.BytesIO(root_raw)) as image:
        assert max(image.size) <= 96

    try:
        psd_service.thumbnail_png(asset_id, "99.99", 64)
    except psd_service.PsdError as exc:
        assert exc.status_code == 404
    else:  # pragma: no cover
        raise AssertionError("不存在的图层应返回 404")


def test_profile_roundtrip() -> None:
    asset_id = _asset_id()
    profile = psd_service.automap(asset_id)["profile"]
    saved = psd_service.save_profile(asset_id, profile)
    assert saved["psdAssetId"] == asset_id
    loaded = psd_service.load_profile(asset_id)
    assert loaded is not None
    assert loaded["channels"]["mouth"]["a"] == "63"
    assert loaded["canvas"] == [2480, 3500]
    profile_path = config.ASSETS_DIR / "psd" / asset_id / "profile.json"
    assert profile_path.is_file()
    on_disk = json.loads(profile_path.read_text(encoding="utf-8"))
    assert on_disk["channels"]["eyes"]["blink"] == "137"
    # manifest endpoint is a cached artifact: absent until bake.  Use a freshly
    # uploaded asset so the assertion is independent of test execution order.
    fresh = psd_service.upload_psd(MOCA_PSD.name, MOCA_PSD.read_bytes())
    assert psd_service.get_manifest(fresh["assetId"]) is None
    assert psd_service.load_profile(fresh["assetId"]) is None


# ---------------------------------------------------------------------------
# bake
# ---------------------------------------------------------------------------

def test_bake_creates_base_and_patches() -> None:
    asset_id = _asset_id()
    started = time.perf_counter()
    manifest = _ensure_baked()
    elapsed = time.perf_counter() - started
    assert elapsed < 60, f"烘焙过慢: {elapsed:.1f}s"
    assert manifest["assetId"] == asset_id
    assert manifest["width"] == 2480 and manifest["height"] == 3500
    assert manifest["base"]["url"] == f"/media/psd/{asset_id}/cache/base.png"
    assert manifest["zorder"] == ["cheek", "mouth", "eyes", "brow"]
    assert len(manifest["profileVersion"]) == 40
    int(manifest["profileVersion"], 16)
    assert manifest["bakedAt"].endswith("Z")

    expected_keys = {
        f"{channel}.{state}"
        for channel, states in psd_service.automap(asset_id)["profile"]["channels"].items()
        for state in states
    }
    assert expected_keys <= set(manifest["patches"])
    assert set(manifest["patches"]) == expected_keys

    base_file = _media_file(manifest["base"]["url"])
    assert base_file.is_file() and base_file.stat().st_size > 10000
    with Image.open(base_file) as base:
        assert base.mode == "RGBA" and base.size == (2480, 3500)
        # The character is a cut-out: transparent background, opaque body.
        assert base.getchannel("A").getextrema() == (0, 255)

    mouth_a = manifest["patches"]["mouth.a"]
    assert mouth_a["offset"] == [1171, 727]
    assert [mouth_a["width"], mouth_a["height"]] == [153, 132]
    patch_file = _media_file(mouth_a["url"])
    assert patch_file.is_file()
    with Image.open(patch_file) as patch:
        assert patch.mode == "RGBA" and patch.size == (153, 132)
        assert patch.getchannel("A").getextrema()[1] > 0

    eyes_open = manifest["patches"]["eyes.open"]
    assert eyes_open["offset"] == [1016, 512]
    assert _media_file(eyes_open["url"]).is_file()
    assert _media_file(manifest["patches"]["eyes.blink"]["url"]).is_file()
    assert psd_service.get_manifest(asset_id) is not None


def test_bake_second_call_is_cached() -> None:
    asset_id = _asset_id()
    first = _ensure_baked()
    started = time.perf_counter()
    second = psd_service.bake(asset_id)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"缓存命中仍然耗时 {elapsed:.2f}s"
    assert second.get("cached") is True
    assert second["bakedAt"] == first["bakedAt"]
    assert second["profileVersion"] == first["profileVersion"]

    # changing the profile invalidates the cache and produces a new version hash
    profile = psd_service.load_profile(asset_id)
    if profile is None:
        profile = psd_service.automap(asset_id)["profile"]
        psd_service.save_profile(asset_id, profile)
    mutated = json.loads(json.dumps(profile))
    mutated["channels"]["mouth"]["closed"] = "59"  # o instead of ω: intentionally wrong
    started = time.perf_counter()
    rebaked = psd_service.bake(asset_id, mutated)
    assert rebaked.get("cached") is False
    assert rebaked["profileVersion"] != first["profileVersion"]
    assert time.perf_counter() - started < 60
    # restore the correct profile for the remaining tests
    corrected = psd_service.load_profile(asset_id)
    assert corrected is not None
    corrected["channels"]["mouth"]["closed"] = "44"
    psd_service.save_profile(asset_id, corrected)


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------

def test_preview_png() -> None:
    asset_id = _asset_id()
    _ensure_baked()
    payload = psd_service.preview_png(asset_id, 900)
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    import io

    with Image.open(io.BytesIO(payload)) as image:
        assert image.size[0] == 900
        assert image.size[1] == round(3500 * (900 / 2480))
        assert image.mode == "RGBA"
        assert image.getchannel("A").getextrema()[1] > 0

    started = time.perf_counter()
    cached = psd_service.preview_png(asset_id, 900)
    assert time.perf_counter() - started < 1.0
    assert cached == payload


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------

def test_project_crud() -> None:
    created = project_service.create_project({"name": "测试项目", "fps": 24, "width": 1080, "height": 1524})
    project_id = created["id"]
    assert project_id.startswith("p_")
    assert created["name"] == "测试项目"
    assert created["fps"] == 24
    assert created["characters"] == []
    assert created["timeline"] == {}
    assert created["createdAt"] and created["updatedAt"]

    listing = project_service.list_projects()
    assert any(item["id"] == project_id and item["name"] == "测试项目" for item in listing)

    fetched = project_service.get_project(project_id)
    assert fetched["id"] == project_id
    assert fetched["width"] == 1080

    updated = project_service.update_project(
        project_id,
        {
            "name": "改名项目",
            "fps": 60,
            "timeline": {
                "characterId": "c_1",
                "blinks": [{"t": 2.0, "duration": 0.15}],
                "emotions": [],
                "effects": [],
            },
            "characters": [{"id": "c_1", "name": "moca", "psdAssetId": _asset_id()}],
        },
    )
    assert updated["name"] == "改名项目"
    assert updated["fps"] == 60
    assert updated["timeline"]["blinks"][0]["t"] == 2.0
    assert updated["createdAt"] == created["createdAt"]
    assert updated["updatedAt"] >= created["updatedAt"]

    stored = config.PROJECTS_DIR / project_id / "project.json"
    assert stored.is_file()
    payload = json.loads(stored.read_text(encoding="utf-8"))
    assert payload["name"] == "改名项目"
    assert payload["timeline"]["characterId"] == "c_1"

    assert project_service.delete_project(project_id) == {"ok": True}
    assert not stored.exists()
    try:
        project_service.get_project(project_id)
    except project_service.ProjectError as exc:
        assert exc.status_code == 404
    else:  # pragma: no cover
        raise AssertionError("删除后应返回 404")

    for bad_id in ("../evil", "a/b", "", "x" * 65):
        try:
            project_service.get_project(bad_id)
        except project_service.ProjectError as exc:
            assert exc.status_code in (400, 404)
        else:  # pragma: no cover
            raise AssertionError(f"非法项目 ID 应被拒绝: {bad_id!r}")


# ---------------------------------------------------------------------------
# bare-python runner (pytest is not installed in this environment)
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
    print(f"\n{len(tests) - failures} passed, {failures} failed in {time.perf_counter() - started:.2f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
