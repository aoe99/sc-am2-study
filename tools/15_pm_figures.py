#!/usr/bin/env python3
"""Stage 15 — 午後の図表を問題冊子PDFから切り出す。

午後 leans on its drawings far more than 午前 does: a network diagram, a table of
機器, a listing of HTML — the 設問 are unanswerable without them, and their OCR
text is fragments, not prose.  So they are cropped as images.

Where they are is read off the captions.  Japanese typesetting puts a 表 caption
above its table and a 図 caption below its figure, and stage 14 has already
marked every row that is inside a drawing rather than in the prose, so the crop
is the run of those rows on the caption's own page — below it for a 表, above it
for a 図.

Crops come straight from the PDF at 300dpi rather than out of the 400dpi page
PNG, so nothing is resampled twice.

    python3 tools/15_pm_figures.py [session ...]
"""
from __future__ import annotations
import importlib.util, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (DATA, PM_PAPERS, build_dir, pdf_path, pm_papers_of, read_json,
                   run_tool, targets_of, write_json)

_spec = importlib.util.spec_from_file_location(
    "pm_parse", Path(__file__).resolve().parent / "14_pm_parse.py")
pm_parse = importlib.util.module_from_spec(_spec)
_argv, sys.argv = sys.argv, ["14_pm_parse.py"]
_spec.loader.exec_module(pm_parse)
sys.argv = _argv

FIGDIR = DATA / "figures"
CAPTION = re.compile(r"^([図表])\s*([0-9０-９]{1,2})")
# Artwork runs wider than the text column, and the OCR box sits inside the
# table rules, so the pad has to clear both the glyphs and the frame.
PAD_X, PAD_Y = 0.05, 0.012
MIN_X, MAX_X = 0.045, 0.955
# A crop shorter than two printed lines is a stray caption, not a drawing.
MIN_H = 0.035


# Text set to the full measure of the column is body copy, not a caption or a
# label inside a drawing, which are indented by their frame.
PROSE_W = 0.60
# The tallest a 図 gets in these booklets, as a fraction of the page.
MAX_FIG_H = 0.62


def is_prose(row: dict) -> bool:
    """Body copy: it wrapped across lines *and* runs the full column width.

    Neither test works alone. Lines inside a 図 wrap too — a boxed list of steps
    is still a drawing — and a single 図 label can be wide. Requiring both is
    what separates the paragraph that introduces 図2 from 図2's own contents."""
    return row.get("lines", 1) > 1 and row.get("w", 0) > PROSE_W
FW = str.maketrans("０１２３４５６７８９", "0123456789")


def regions(body: list[dict]) -> list[dict]:
    """One rectangle per caption, from the drawing rows it belongs to."""
    out = []
    for i, row in enumerate(body):
        if row["kind"] != "caption":
            continue
        m = CAPTION.match(row["text"])
        if not m:
            continue
        kind, no = m.group(1), m.group(2).translate(FW)
        page = row["page"]
        # 表 captions sit above their table, 図 captions below their figure.
        step = 1 if kind == "表" else -1
        rows = []
        j = i + step
        while 0 <= j < len(body):
            b = body[j]
            if b["page"] != page or b["kind"] in ("heading", "caption"):
                break
            if kind == "表":
                # Walking down from the caption, the table ends where prose
                # resumes, and that is easy to see.
                if b["kind"] != "figure" and is_prose(b):
                    break
            else:
                # Walking *up* from a 図's caption there is no such marker: the
                # boxed HTML listing of 図2 and the boxed step list of 図4 are
                # wrapped Japanese paragraphs by every test that separates them
                # from the sentence introducing them. So the run is taken back
                # to the previous caption, heading or page top, capped at the
                # height a figure can plausibly be. Reaching too far puts one
                # extra sentence above the drawing; stopping short cuts the
                # drawing itself in half, which is the one thing the crop
                # exists to prevent.
                if row["y"] + row["h"] - b["y"] > MAX_FIG_H:
                    break
            rows.append(b)
            j += step
        if not rows:
            continue
        boxes = rows + [row]
        x0 = max(MIN_X, min(b["x"] for b in boxes) - PAD_X)
        x1 = min(MAX_X, max(b["x"] + b["w"] for b in boxes) + PAD_X)
        y0 = max(0.0, min(b["y"] for b in boxes) - PAD_Y)
        y1 = min(1.0, max(b["y"] + b["h"] for b in boxes) + PAD_Y)
        if y1 - y0 < MIN_H or x1 - x0 < 0.05:
            continue
        out.append({"label": f"{kind}{no}", "caption": row["text"], "page": page,
                    "rect": [round(x0, 4), round(y0, 4),
                             round(x1 - x0, 4), round(y1 - y0, 4)]})
    return out


def crop_case(sid: str, paper: str, no: int, body: list[dict]) -> list[dict]:
    pdf = pdf_path(sid, "1問題", "pm", paper)
    outdir = FIGDIR / sid / paper
    outdir.mkdir(parents=True, exist_ok=True)
    figs = []
    for n, r in enumerate(regions(body), 1):
        name = f"{sid}-{paper}-{no}-{n:02d}.png"
        out = outdir / name
        x, y, w, h = r["rect"]
        run_tool("crop", pdf, r["page"], f"{x}", f"{y}", f"{w}", f"{h}",
                 out, "--dpi", "300")
        figs.append({"label": r["label"], "caption": r["caption"],
                     "page": r["page"],
                     "file": str(out.relative_to(DATA))})
    return figs


def main() -> None:
    targets = targets_of(sys.argv[1:])
    parsed = read_json(build_dir("pm") / "parsed.json")
    out, bad, note = {}, [], []
    for sid in targets:
        if sid not in parsed:
            continue
        out[sid] = {}
        for paper in pm_papers_of(sid):
            cases = parsed[sid].get(paper, {})
            if not cases:
                continue
            out[sid][paper] = {}
            total = 0
            for no_s, c in sorted(cases.items(), key=lambda kv: int(kv[0])):
                figs = crop_case(sid, paper, int(no_s), c["body"])
                out[sid][paper][no_s] = {"figures": figs}
                total += len(figs)
                # Every 図N the prose refers to should have been cropped.
                named = {f["label"] for f in figs}
                # Only real captions count: prose says "図4に示す" all the time.
                wanted = {f"{m.group(1)}{m.group(2).translate(FW)}"
                          for b in c["body"] if b["kind"] == "caption"
                          for m in [CAPTION.match(b["text"])] if m}
                missing = sorted(wanted - named)
                if missing:
                    note.append(f"{sid}/{paper} 問{no_s}: 切り出せない {missing}")
            print(f"{sid:9} {PM_PAPERS[paper]['label']:5} 図表 {total:3} 枚")
    for x in note[:12]:
        print("  *", x)
    if len(note) > 12:
        print(f"  * …ほか {len(note) - 12} 件")
    path = build_dir("pm") / "figures.json"
    merged = read_json(path) if path.exists() else {}
    for sid, papers in out.items():
        merged.setdefault(sid, {}).update(papers)
    write_json(path, merged)
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
