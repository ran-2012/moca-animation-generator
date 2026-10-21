"""End-to-end smoke test for the MocaDiff backend.

Usage (backend must be running on http://127.0.0.1:8787):
    python scripts/e2e_smoke.py
    python scripts/e2e_smoke.py --base http://127.0.0.1:8787 --skip-bake

Only uses the Python standard library so it works regardless of httpx version.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent  # 工作区根目录（仓库上一级，放 moca.psd 等示例素材）


def _request(method: str, url: str, data: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read()
            ctype = resp.headers.get("content-type", "")
            if "application/json" in ctype:
                return resp.status, json.loads(body)
            return resp.status, body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc


def upload(base: str, route: str, path: Path) -> dict:
    boundary = "----mocadiff" + uuid.uuid4().hex
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    body = head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
    status, payload = _request(
        "POST",
        base + route,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert status == 200, (route, status)
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--psd", default=str(WORKSPACE / "moca.psd"))
    ap.add_argument("--svp", default=str(WORKSPACE / "流沙.svp"))
    ap.add_argument("--track", type=int, default=5)
    ap.add_argument("--skip-audio", action="store_true")
    ap.add_argument("--skip-bake", action="store_true")
    ap.add_argument("--skip-svp", action="store_true")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    report: dict = {}

    print("== health ==")
    status, health = _request("GET", base + "/api/health")
    print(health)
    report["health"] = health

    print("== upload PSD ==")
    t0 = time.time()
    psd = upload(base, "/api/psd/upload", Path(args.psd))
    report["psd"] = psd
    print(json.dumps(psd, ensure_ascii=False))
    print(f"upload+parse: {time.time() - t0:.1f}s")
    asset = psd["assetId"]

    print("== tree ==")
    _, tree = _request("GET", f"{base}/api/psd/{asset}/tree")
    report["treeRoot"] = {"id": tree.get("id"), "children": len(tree.get("children", []))}
    print(report["treeRoot"])

    print("== automap ==")
    _, automap = _request("POST", f"{base}/api/psd/{asset}/automap")
    profile = automap["profile"]
    report["automap"] = {
        "warnings": automap.get("warnings", []),
        "mouth": profile.get("channels", {}).get("mouth", {}),
        "eyes": profile.get("channels", {}).get("eyes", {}),
        "brow": profile.get("channels", {}).get("brow", {}),
        "cheek": profile.get("channels", {}).get("cheek", {}),
    }
    print(json.dumps(report["automap"], ensure_ascii=False, indent=1))

    if not args.skip_bake:
        print("== bake ==")
        t0 = time.time()
        _, bake = _request(
            "POST",
            f"{base}/api/psd/{asset}/bake",
            data=json.dumps({"profile": profile}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        report["bake"] = {
            "elapsedClient": round(time.time() - t0, 2),
            "base": bake.get("base"),
            "patchCount": len(bake.get("patches", {})),
            "patchKeys": sorted(bake.get("patches", {})),
        }
        print(json.dumps(report["bake"], ensure_ascii=False, indent=1))
        base_url = bake["base"]["url"]
        # verify one image is actually downloadable
        _, image = _request("GET", base + base_url)
        report["bake"]["baseBytes"] = len(image)

    if not args.skip_svp:
        print("== upload SVP ==")
        svp = upload(base, "/api/svp/upload", Path(args.svp))
        report["svp"] = {
            "assetId": svp["assetId"],
            "tracks": [
                {
                    "index": t["index"],
                    "name": t["name"],
                    "isInstrumental": t["isInstrumental"],
                    "noteCount": t["noteCount"],
                    "range": [t.get("rangeStartSec"), t.get("rangeEndSec")],
                }
                for t in svp["tracks"]
            ],
        }
        print(json.dumps(report["svp"], ensure_ascii=False, indent=1))
        svp_asset = svp["assetId"]

        print(f"== timeline track {args.track} ==")
        t0 = time.time()
        _, tl = _request(
            "POST",
            f"{base}/api/svp/{svp_asset}/timeline",
            data=json.dumps({"trackIndex": args.track, "fps": 60}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        timeline = tl.get("timeline", {})
        frames = timeline.get("frames", [])
        report["timeline"] = {
            "elapsed": round(time.time() - t0, 2),
            "fps": timeline.get("fps"),
            "duration": timeline.get("duration"),
            "frameCount": len(frames),
            "blinks": len(tl.get("blinks", [])),
            "warnings": tl.get("warnings", []),
            "firstFrames": frames[:3],
        }
        print(json.dumps(report["timeline"], ensure_ascii=False, indent=1))

    if not args.skip_audio:
        print("== audio (generated 6s sine) ==")
        import subprocess
        import tempfile

        wav = Path(tempfile.gettempdir()) / "smoke_6s.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=6", str(wav)],
            check=True,
        )
        audio = upload(base, "/api/audio/upload", wav)
        report["audio"] = audio
        print(json.dumps(audio, ensure_ascii=False))
        _, peaks = _request("GET", f"{base}/api/audio/{audio['assetId']}/peaks?points=100")
        report["audio"]["peakCount"] = len(peaks.get("peaks", []))

    print("== create project ==")
    status, project = _request(
        "POST",
        base + "/api/projects",
        data=json.dumps({"name": "smoke"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    report["project"] = {"id": project["id"], "name": project["name"]}
    print(report["project"])

    out = ROOT / "data" / "e2e_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport -> {out}")
    print("E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
