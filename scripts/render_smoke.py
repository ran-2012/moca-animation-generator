"""Submit a real render and wait for it (uses a baked PSD + a viseme timeline).

Usage:
    python scripts/render_smoke.py --psd-asset 2babe7e249c0 \
        --timeline _work/svp/viseme_timeline.json --format png_zip
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent


def request(method: str, url: str, payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--psd-asset", required=True)
    ap.add_argument("--timeline", default=str(WORKSPACE / "_work" / "svp" / "viseme_timeline.json"))
    ap.add_argument("--start", type=float, default=27.6)
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--format", default="png_zip",
                    choices=["png_zip", "prores4444", "webm_alpha", "mp4"])
    args = ap.parse_args()

    timeline = json.loads(Path(args.timeline).read_text(encoding="utf-8"))
    payload = {
        "psdAssetId": args.psd_asset,
        "timeline": {
            "fps": timeline.get("fps", 60),
            "duration": timeline.get("duration"),
            "frames": [{"t": f["t"], "viseme": f["viseme"]} for f in timeline["frames"]],
        },
        "blinks": [],
        "startSec": args.start,
        "durationSec": args.seconds,
        "outFps": args.fps,
        "width": args.width,
        "format": args.format,
    }
    print("submitting", args.format, f"{args.seconds}s @ {args.fps}fps", f"{args.width}px")
    t0 = time.time()
    job = request("POST", args.base + "/api/render", payload)
    print("job", job)

    while time.time() - t0 < 600:
        info = request("GET", f"{args.base}/api/render/{job['jobId']}")
        print(json.dumps(info, ensure_ascii=False))
        if info["status"] in ("done", "failed"):
            print(f"elapsed: {time.time() - t0:.1f}s")
            if info["status"] == "done":
                url = args.base + info["fileUrl"]
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=120) as response:
                    data = response.read()
                out = ROOT / "data" / "renders" / f"smoke_{info['jobId']}{Path(info['fileName']).suffix}"
                out.write_bytes(data)
                print(f"downloaded {len(data)} bytes -> {out}")
            return 0 if info["status"] == "done" else 1
        time.sleep(0.5)
    print("timeout")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
