#!/usr/bin/env python3
"""Stage 1 — pull the official IPA answer key (問1..問25 → ア/イ/ウ/エ).

    python3 tools/01_answers.py [--section am1|am2] [session ...]
"""
from __future__ import annotations
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import json, subprocess, tempfile
from sclib import (CHOICE_KEYS, SECTIONS, PDFTOOL, build_dir, pdf_path, pdf_text,
                   clean, question_count, read_json, run_tool, section_of,
                   targets_of, write_json)

# PDFKit returns the key table in reading order, one "問 N 記号" per line.
PAIR = re.compile(r"[問間]\s*(\d{1,2})\s*[\s:：]*\s*(ア|イ|ウ|エ)")


# Vision's confusions for the four markers. "1"/"l" stand in for イ only in a
# cell of their own: next to the question number they would swallow a digit —
# "問11" would read as 問1 answered "1" — so the inline form excludes them.
KEY_ALIAS = {"ア": "アァ", "イ": "イィ1lＩ", "ウ": "ウゥワヮ", "エ": "エェ工ヱ"}
UNALIAS = {c: k for k, v in KEY_ALIAS.items() for c in v}
SAFE = "".join(c for c in UNALIAS if not c.isdigit() and c not in "lＩ")
ONLY_NO = re.compile(r"^[問間]\s*(\d{1,2})\s*$")
NO_AND_KEY = re.compile(r"[問間]\s*(\d{1,2})(?!\d)\s*[\s:：]*([" + SAFE + r"])")


def ocr_key(pdf, n_max: int) -> dict:
    """Read an answer key that was scanned instead of typeset.

    Every sitting but one ships the key with a text layer; R04haru's 午前I is a
    bare image.  The key is a three-column table, and Vision emits each cell as
    its own observation in an order that sometimes skips one, so the number and
    its answer are paired by position — same baseline, next box to the right —
    rather than by reading order.
    """
    with tempfile.TemporaryDirectory() as td:
        run_tool("render", pdf, td, "--dpi", "600", "--prefix", "k-")
        pngs = sorted(Path(td).glob("*.png"))
        pages = json.loads(run_tool("ocr", *pngs, "--json"))

    found: dict[int, str] = {}
    unresolved: list[tuple] = []
    for pi, page in enumerate(pages, 1):
        lines = [l for l in page["lines"] if l["text"].strip()]
        numbered = [l for l in lines if ONLY_NO.match(l["text"].strip())
                    or NO_AND_KEY.search(l["text"].strip())]
        for l in lines:
            t = l["text"].strip()
            m = NO_AND_KEY.search(t)
            if m:                                   # cell read as "問1 ア"
                no = int(m.group(1))
                if 1 <= no <= n_max:
                    found[no] = UNALIAS[m.group(2)]
                continue
            m = ONLY_NO.match(t)
            if not m:
                continue
            no = int(m.group(1))
            if not 1 <= no <= n_max or no in found:
                continue
            mid = l["y"] + l["h"] / 2
            band = max(l["h"], 0.008)
            same_row = [o for o in lines
                        if o is not l and o["x"] > l["x"]
                        and abs((o["y"] + o["h"] / 2) - mid) < band]
            # The table has three 問N columns side by side, so the answer must
            # be found before the next question number — otherwise 問19 would
            # happily adopt 問29's answer.
            wall = min((o["x"] for o in same_row if o in numbered), default=1.0)
            keys = [o for o in same_row
                    if o["x"] < wall and o["text"].strip()[:1] in UNALIAS]
            if keys:
                found[no] = UNALIAS[min(keys, key=lambda o: o["x"])["text"].strip()[0]]
            else:
                unresolved.append((pi, no, l, wall))

    # Whatever is still blank gets its own cell rendered large and read again.
    if unresolved:
        for pi, no, l, wall in unresolved:
            key = _read_cell(pdf, pi, l, wall)
            if key:
                found[no] = key
    return found


# Insetting the crop matters more than resolution: a lone character boxed by
# table rules reads as blank, and pulling the frame off the rules fixes it.
CELL_TRIES = ((600, 0.02, 0.35), (1200, 0.03, 0.25), (900, 0.02, 0.35),
              (900, 0.0, 0.6))


def _read_cell(pdf, page: int, num_line: dict, wall: float) -> str | None:
    """Render just the answer cell of one row and read it on its own.

    A cell Vision skipped at page scale is legible when it fills the frame;
    cropping it is what keeps a blank from turning into a guess."""
    left = num_line["x"] + num_line["w"] + 0.005
    right = wall if wall < 1.0 else left + 0.12
    if right - left < 0.02:
        return None
    for dpi, px, py in CELL_TRIES:
        x0, x1 = left + px, right - px
        y0 = max(0.0, num_line["y"] - num_line["h"] * py)
        h = num_line["h"] * (1 + 2 * py)
        if x1 - x0 < 0.01:
            continue
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "cell.png"
            try:
                run_tool("crop", pdf, page, f"{x0:.5f}", f"{y0:.5f}",
                         f"{x1 - x0:.5f}", f"{h:.5f}", out, "--dpi", str(dpi))
                txt = run_tool("ocr", out).strip()
            except Exception:
                continue
        for ch in txt:
            if ch in UNALIAS:
                return UNALIAS[ch]
    return None


def extract(sid: str, section: str) -> dict[int, str]:
    n_max = question_count(section)
    pdf = pdf_path(sid, "2解答例", section)
    txt = clean(pdf_text(pdf))
    if not PAIR.search(txt):
        return ocr_key(pdf, n_max)
    found: dict[int, str] = {}
    dupes: list[str] = []
    for m in PAIR.finditer(txt):
        no, key = int(m.group(1)), m.group(2)
        if not 1 <= no <= n_max:
            continue
        if no in found and found[no] != key:
            dupes.append(f"問{no}: {found[no]} vs {key}")
        found[no] = key
    if dupes:
        raise SystemExit(f"{sid}: conflicting answers → {dupes}")
    return found


def main() -> None:
    section = section_of(sys.argv[1:])
    targets = targets_of(sys.argv[1:])
    n = question_count(section)
    out, bad = {}, []
    for sid in targets:
        ans = extract(sid, section)
        missing = [x for x in range(1, n + 1) if x not in ans]
        if missing:
            bad.append(f"{sid}: missing 問{missing}")
        out[sid] = {str(n): ans[n] for n in sorted(ans)}
        dist = "".join(f"{k}{sum(1 for v in ans.values() if v == k)} " for k in CHOICE_KEYS)
        print(f"{sid:9} {len(ans):2}/{n}  分布: {dist}")
    total = sum(len(v) for v in out.values())
    want = len(targets) * n
    print(f"\n[{SECTIONS[section]['label']}] 合計 {total} 件 / 期待 {want} 件"
          f"  {'✓ OK' if total == want and not bad else '✗ NG'}")
    for b in bad:
        print("  !", b)
    # Merge, so running a single session does not wipe the other eighteen.
    path = build_dir(section) / "answers.json"
    merged = read_json(path) if path.exists() else {}
    merged.update(out)
    write_json(path, merged)
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
