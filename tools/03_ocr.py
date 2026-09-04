#!/usr/bin/env python3
"""Stage 3 — render the scanned 問題 booklets and OCR them with Vision.

The 問題 PDFs carry no text layer (0 chars), only 200dpi JPEG scans, so every
page is re-rendered at 400dpi and passed through VNRecognizeTextRequest.
Results are cached per session; pass --force to redo them.

    python3 tools/03_ocr.py [--section am1|am2|pm] [--force] [--tesseract] [session ...]

午後 shipped two booklets per sitting until 令和5年度春期, so its cache is keyed by
booklet (R05haru-pm1.json) rather than by sitting.
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (build_dir, pdf_path, pm_papers_of, run_tool, section_of,
                   targets_of)

DPI = 400


def tesseract_page(png: Path) -> str | None:
    """Secondary engine, used only to cross-check Vision (see review report)."""
    exe = Path("/opt/homebrew/bin/tesseract")
    if not exe.exists():
        return None
    r = subprocess.run([str(exe), str(png), "stdout", "-l", "jpn+eng", "--psm", "6"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def process(sid: str, section: str, force: bool, with_tess: bool,
            paper: str | None = None) -> None:
    root = build_dir(section)
    key = f"{sid}-{paper}" if paper else sid
    out = root / "ocr" / f"{key}.json"
    if out.exists() and not force:
        print(f"{key:14} cached")
        return
    pdf = pdf_path(sid, "1問題", section, paper)
    pdir = root / "pages" / key
    pdir.mkdir(parents=True, exist_ok=True)
    if force or not any(pdir.glob("*.png")):
        run_tool("render", pdf, pdir, "--dpi", str(DPI), "--prefix", f"{key}-p")
    pngs = sorted(pdir.glob("*.png"))
    data = json.loads(run_tool("ocr", *pngs, "--json"))
    for page in data:
        page["file"] = Path(page["file"]).name
        if with_tess:
            page["tesseract"] = tesseract_page(pdir / page["file"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"{key:14} {len(pngs):2}ページ  {sum(len(p['lines']) for p in data):5}行")


def main() -> None:
    args = sys.argv[1:]
    section = section_of(args)
    for sid in targets_of(args):
        papers = pm_papers_of(sid) if section == "pm" else [None]
        for paper in papers:
            process(sid, section, "--force" in args, "--tesseract" in args, paper)


if __name__ == "__main__":
    main()
