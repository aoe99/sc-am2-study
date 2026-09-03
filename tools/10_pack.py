#!/usr/bin/env python3
"""Stage 10 — build the single file the web app imports.

The app is served without any question data (§copyright), so everything it
needs has to arrive through one file picked by hand: questions, sessions and
the figure images, the last as data: URIs.  Figures are re-encoded down from
the 300dpi crops — at 1200px wide and JPEG q65 a table scan drops from 220KB
to 45KB with no loss of legibility, which is what keeps the pack openable on
a phone.

    python3 tools/10_pack.py [--width 1200] [--quality 65]
"""
from __future__ import annotations
import base64, json, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import DATA, ROOT, read_json

WIDTH, QUALITY = 1200, 65


def encode(png: Path, width: int, quality: int) -> str:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "f.jpg"
        r = subprocess.run(["sips", "-Z", str(width), "-s", "format", "jpeg",
                            "-s", "formatOptions", str(quality),
                            str(png), "--out", str(out)],
                           capture_output=True)
        if r.returncode != 0 or not out.exists():
            raise RuntimeError(f"sips failed on {png}")
        b64 = base64.b64encode(out.read_bytes()).decode()
    return "data:image/jpeg;base64," + b64


def main() -> None:
    args = sys.argv[1:]
    width = int(args[args.index("--width") + 1]) if "--width" in args else WIDTH
    quality = int(args[args.index("--quality") + 1]) if "--quality" in args else QUALITY

    doc = read_json(DATA / "questions.json")
    wanted: list[str] = []
    for q in doc["questions"]:
        wanted += q["figures"]
        wanted += list(q["choiceFigures"].values())
    wanted = sorted(set(wanted))

    assets, missing, raw = {}, [], 0
    for n, rel in enumerate(wanted, 1):
        png = DATA / rel
        if not png.exists():
            missing.append(rel)
            continue
        raw += png.stat().st_size
        assets[rel] = encode(png, width, quality)
        if n % 40 == 0:
            print(f"  {n}/{len(wanted)} …")
    if missing:
        print(f"  ! 画像が見つからない: {len(missing)} 件 {missing[:3]}")

    doc["assets"] = assets
    doc["meta"]["figureCount"] = len(assets)
    doc["meta"]["packBuiltAt"] = doc["meta"]["generatedAt"]
    out = DATA / "sc-data.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    size = out.stat().st_size
    print(f"\n図表 {len(assets)} 枚  元 {raw/1024/1024:.1f}MB → "
          f"埋め込み後 {sum(len(v) for v in assets.values())/1024/1024:.1f}MB")
    print(f"→ {out.relative_to(ROOT)}  {size/1024/1024:.1f}MB")


if __name__ == "__main__":
    main()
