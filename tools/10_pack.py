#!/usr/bin/env python3
"""Stage 10 — build the files the web app imports, two per 区分.

The app is served without any question data (§copyright), so everything it needs
has to arrive through files picked by hand.  Each 区分 ships as a pair:

    sc-data-am.json  /  sc-data-am-figures.bin
    sc-data-pm.json  /  sc-data-pm-figures.bin

**Text and pictures are separated, and the pictures are not base64.**  Both
choices are forced by the phone.  午後 has 668 figures — full-width network
diagrams and tables, not the small crops 午前 needs — which come to 63MB of
JPEG.  As data: URIs inside the JSON that is 84MB, and reading it means holding
an 84MB string, then a parsed object containing the same 84MB again: Safari on
an iPhone does not survive it.  As a length-indexed binary the app reads one
ArrayBuffer and slices Blobs straight out of it, with no string and no parse.

The .bin layout is deliberately trivial — no library to depend on in five years:

    SCFIG1\n                     magic
    <uint32 LE>                  length of the header that follows
    <header>                     JSON: {"group", "entries":[{p,o,l,t}]}
    <payload>                    the JPEGs, back to back, at those offsets

Figures are re-encoded down from the 300dpi crops.  At 1000px wide and JPEG q60
the densest table in the corpus drops from 1.0MB to 123KB and stays readable.

    python3 tools/10_pack.py [--width 1200] [--quality 65] [--section am|pm]
"""
from __future__ import annotations
import json, struct, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import DATA, ROOT, SECTIONS, read_json

WIDTH, QUALITY = 1000, 60

# Which 区分 travel together. 午前Ⅰ and 午前Ⅱ are one sitting's worth of
# multiple choice and are always studied side by side; 午後 is its own paper.
GROUPS = {
    "am": [s for s, v in SECTIONS.items() if v["style"] == "choice"],
    "pm": [s for s, v in SECTIONS.items() if v["style"] == "written"],
}


MAGIC = b"SCFIG1\n"


def encode(png: Path, width: int, quality: int) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "f.jpg"
        r = subprocess.run(["sips", "-Z", str(width), "-s", "format", "jpeg",
                            "-s", "formatOptions", str(quality),
                            str(png), "--out", str(out)],
                           capture_output=True)
        if r.returncode != 0 or not out.exists():
            raise RuntimeError(f"sips failed on {png}")
        return out.read_bytes()


def write_figures(path: Path, group: str, blobs: dict[str, bytes]) -> None:
    entries, offset = [], 0
    for rel, data in blobs.items():
        entries.append({"p": rel, "o": offset, "l": len(data), "t": "image/jpeg"})
        offset += len(data)
    header = json.dumps({"group": group, "entries": entries},
                        ensure_ascii=False, separators=(",", ":")).encode()
    with path.open("wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<I", len(header)))
        f.write(header)
        for data in blobs.values():
            f.write(data)


def pack(doc: dict, group: str, width: int, quality: int) -> Path | None:
    secs = [s for s in GROUPS[group]
            if any(q.get("section", "am2") == s for q in doc["questions"])]
    if not secs:
        return None
    questions = [q for q in doc["questions"] if q.get("section", "am2") in secs]
    cases = [c for c in doc.get("cases", []) if c.get("section") in secs]
    used = {q["sessionId"] for q in questions}
    sessions = [s for s in doc["sessions"] if s["id"] in used]

    wanted: list[str] = []
    for q in questions:
        wanted += q.get("figures", [])
        wanted += list(q.get("choiceFigures", {}).values())
    for c in cases:
        wanted += [f["file"] for f in c.get("figures", []) if f.get("file")]
    wanted = sorted(set(wanted))

    blobs, missing, raw = {}, [], 0
    for n, rel in enumerate(wanted, 1):
        png = DATA / rel
        if not png.exists():
            missing.append(rel)
            continue
        raw += png.stat().st_size
        blobs[rel] = encode(png, width, quality)
        if n % 40 == 0:
            print(f"  {n}/{len(wanted)} …")
    if missing:
        print(f"  ! 画像が見つからない: {len(missing)} 件 {missing[:3]}")

    meta = dict(doc["meta"])
    meta["sections"] = [s for s in doc["meta"]["sections"] if s["id"] in secs]
    meta["questionCount"] = len(questions)
    meta["caseCount"] = len(cases)
    meta["sessionCount"] = len(sessions)
    meta["figureCount"] = len(blobs)
    meta["packBuiltAt"] = meta["generatedAt"]
    meta["packGroup"] = group
    meta["figureFile"] = f"sc-data-{group}-figures.bin" if blobs else None

    out = DATA / f"sc-data-{group}.json"
    payload = {"meta": meta, "sessions": sessions, "questions": questions}
    if cases:
        payload["cases"] = cases
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"[{group}] {len(questions)} 問"
          + (f" / {len(cases)} 事例" if cases else "")
          + f"  図表 {len(blobs)} 枚  元 {raw/1024/1024:.1f}MB")
    print(f"  → {out.relative_to(ROOT)}  {out.stat().st_size/1024/1024:.1f}MB")
    if blobs:
        fig = DATA / f"sc-data-{group}-figures.bin"
        write_figures(fig, group, blobs)
        print(f"  → {fig.relative_to(ROOT)}  {fig.stat().st_size/1024/1024:.1f}MB")
    return out


def main() -> None:
    args = sys.argv[1:]
    width = int(args[args.index("--width") + 1]) if "--width" in args else WIDTH
    quality = int(args[args.index("--quality") + 1]) if "--quality" in args else QUALITY
    groups = ([args[args.index("--section") + 1]] if "--section" in args
              else list(GROUPS))
    for g in groups:
        if g not in GROUPS:
            raise SystemExit(f"unknown group: {g} (expected {list(GROUPS)})")

    doc = read_json(DATA / "questions.json")
    for g in groups:
        pack(doc, g, width, quality)


if __name__ == "__main__":
    main()
