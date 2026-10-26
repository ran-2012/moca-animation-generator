"""Tests for backend session persistence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import config  # noqa: E402
from app.models.session import SessionState  # noqa: E402
from app.services import session_service  # noqa: E402


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _restore(path: Path, payload: bytes | None) -> None:
    if payload is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(payload)


def test_session_roundtrip_and_clear():
    original = _read(session_service.session_path())
    original_previous = _read(session_service.previous_path())
    original_projects = _read(session_service.projects_path())
    try:
        state = SessionState(
            projectName="测试项目",
            mockMode=False,
            time=27.5,
            psd={"assetId": "abc123", "filename": "moca.psd", "width": 2480, "height": 3500},
            profile={"psdAssetId": "abc123", "channels": {"mouth": {"a": "63"}}},
            hiddenGroups=["0.3.1"],
            hiddenLayers=["0.3.2"],
            exclusiveGroups=["3"],
            selectedLayerId="63",
            svp={"assetId": "svp123", "tracks": [{"index": 5, "name": "未命名音轨"}]},
            selectedTrack=5,
            mappingSetId="soft",
            animationModeId="expressive",
            timelineView={"start": 0.25, "span": 0.5},
            audio={"assetId": "aud123", "durationSec": 242.6},
            bpm=76.0,
            offset=0.25,
            sway={"enabled": True, "amplitude": 0.4, "frequency": 0.5, "offsetMs": 250},
            manifestStale=True,
        )
        saved_at = session_service.save(state)
        assert saved_at

        loaded, read_at = session_service.load()
        assert loaded is not None
        assert read_at == saved_at
        assert loaded.projectName == "测试项目"
        assert loaded.psd and loaded.psd["assetId"] == "abc123"
        assert loaded.selectedTrack == 5
        assert loaded.mappingSetId == "soft"
        assert loaded.animationModeId == "expressive"
        assert loaded.timelineView == {"start": 0.25, "span": 0.5}
        assert loaded.bpm == 76.0
        assert loaded.offset == 0.25
        assert loaded.sway is not None
        assert loaded.sway.model_dump() == {"enabled": True, "amplitude": 0.4, "frequency": 0.5, "offsetMs": 250}
        assert loaded.manifestStale is True
        assert loaded.hiddenGroups == ["0.3.1"]
        assert loaded.exclusiveGroups == ["3"]
        assert loaded.updatedAt == saved_at

        # raw file is valid JSON with the saved envelope
        payload = json.loads(session_service.session_path().read_text(encoding="utf-8"))
        assert payload["savedAt"] == saved_at
        assert payload["session"]["projectName"] == "测试项目"

        session_service.clear()
        assert session_service.load() == (None, None)
        assert session_service.load_previous() == (None, None)
    finally:
        _restore(session_service.session_path(), original)
        _restore(session_service.previous_path(), original_previous)
        _restore(session_service.projects_path(), original_projects)


def test_previous_session_kept_when_mode_switch_saves_empty_state():
    original = _read(session_service.session_path())
    original_previous = _read(session_service.previous_path())
    original_projects = _read(session_service.projects_path())
    try:
        session_service.clear()
        live = SessionState(
            projectName="LIVE 项目",
            mockMode=False,
            psd={"assetId": "psd-live"},
            audio={"assetId": "aud-live"},
            bpm=113.64,
            offset=-0.736,
        )
        session_service.save(live)

        # Switching to MOCK resets the workspace and saves an empty snapshot.
        session_service.save(SessionState(projectName="未命名项目", mockMode=True))

        current, _ = session_service.load()
        assert current is not None and current.mockMode is True
        assert not (current.psd or current.svp or current.audio)

        previous, _ = session_service.load_previous()
        assert previous is not None
        assert previous.psd and previous.psd["assetId"] == "psd-live"
        assert previous.audio and previous.audio["assetId"] == "aud-live"
        assert previous.offset == -0.736

        session_service.clear()
        assert session_service.load_previous() == (None, None)
    finally:
        _restore(session_service.session_path(), original)
        _restore(session_service.previous_path(), original_previous)
        _restore(session_service.projects_path(), original_projects)


def test_project_history_upserts_and_deletes():
    original = _read(session_service.session_path())
    original_previous = _read(session_service.previous_path())
    original_projects = _read(session_service.projects_path())
    try:
        session_service.projects_path().unlink(missing_ok=True)
        first = SessionState(
            projectName="项目 A",
            mockMode=False,
            psd={"assetId": "psd1", "filename": "a.psd"},
            svp={"assetId": "svp1", "filename": "a.svp"},
            audio={"assetId": "aud1", "filename": "a.wav"},
        )
        session_service.save(first)
        items = session_service.list_projects()
        assert len(items) == 1
        assert items[0]["name"] == "项目 A"
        assert items[0]["psd"] == "a.psd"
        assert "session" not in items[0]

        # Autosaves of the same assets update one entry instead of growing.
        session_service.save(SessionState(
            projectName="项目 A2",
            mockMode=False,
            psd={"assetId": "psd1", "filename": "a.psd"},
            svp={"assetId": "svp1", "filename": "a.svp"},
            audio={"assetId": "aud1", "filename": "a.wav"},
        ))
        items = session_service.list_projects()
        assert len(items) == 1
        assert items[0]["name"] == "项目 A2"

        state, _ = session_service.load_project(items[0]["id"])
        assert state is not None and state.projectName == "项目 A2"
        assert state.psd == {"assetId": "psd1", "filename": "a.psd"}
        assert session_service.delete_project(items[0]["id"]) is True
        # Listing re-seeds from the current session on disk, so assert on the id.
        assert session_service.load_project(items[0]["id"])[0] is None
        assert session_service.delete_project("missing") is False
    finally:
        _restore(session_service.session_path(), original)
        _restore(session_service.previous_path(), original_previous)
        _restore(session_service.projects_path(), original_projects)


if __name__ == "__main__":
    test_session_roundtrip_and_clear()
    test_previous_session_kept_when_mode_switch_saves_empty_state()
    test_project_history_upserts_and_deletes()
    print("session tests passed")
