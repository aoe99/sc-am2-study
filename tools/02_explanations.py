#!/usr/bin/env python3
"""Stage 2 — pull 翔泳社 読者特典 explanations (正解記号 + 解説本文).

Some booklets embed a font whose opening bracket has no ToUnicode entry, so
PDFKit silently drops it (R07aki loses all 30 of its "（").  When the bracket
counts do not balance we render the page, OCR it, and diff-align the two texts
to put the missing brackets back at their exact positions.

    python3 tools/02_explanations.py [session ...]
"""
from __future__ import annotations
import difflib, json, re, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (SESSION_IDS, BUILD, PDFTOOL, pdf_path, pdf_text, clean,
                   unwrap, write_json)

HEAD = re.compile(r"[●○]\s*[問間]\s*(\d{1,2})\s*正解\s*[：:]\s*(ア|イ|ウ|エ)")
# Page furniture repeated on every sheet of the 読者特典 PDFs.
NOISE = [
    re.compile(r"^情報処理教科書\s*安全確保支援士.*読者特典\s*$"),
    re.compile(r"^［.{0,20}午前Ⅱ解答・解説］\s*$"),
    re.compile(r"^[-–—]\s*\d+\s*[-–—]\s*$"),
    re.compile(r"^©\s*\d{4}.*$"),
    re.compile(r"^令和.*年度.*情報処理安全確保支援士\s*$"),
    re.compile(r"^平成.*年度.*(情報処理安全確保支援士|情報セキュリティスペシャリスト)\s*$"),
    re.compile(r"^＜午前Ⅱ解答・解説＞\s*$"),
]
# Half- and full-width parens are one class: the source mixes them freely.
BRACKET_CLASSES = [("（(", "）)"), ("「", "」"), ("［", "］"), ("【", "】")]
# "a)" / "1)" / "①" clause labels quoted from JIS/ISO are not unclosed brackets.
LIST_MARK = re.compile(r"(?m)^\s*[a-zA-Z0-9０-９ⅰ-ⅹ]{1,3}[）)]")


def strip_noise(text: str) -> str:
    keep = [l for l in text.split("\n")
            if not any(p.match(l.strip()) for p in NOISE)]
    return "\n".join(keep)


def ocr_reference(pdf: Path) -> str:
    """Render + Vision-OCR the whole PDF, returned as one string."""
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([str(PDFTOOL), "render", str(pdf), td, "--dpi", "300"],
                       capture_output=True, text=True, check=True)
        pngs = sorted(Path(td).glob("*.png"))
        r = subprocess.run([str(PDFTOOL), "ocr", *map(str, pngs)],
                           capture_output=True, text=True, check=True)
        return r.stdout


def repair_brackets(text: str, pdf: Path, sid: str, log: list[str]) -> str:
    probe = LIST_MARK.sub("", text)
    deficits: dict[str, int] = {}
    for opens, closes in BRACKET_CLASSES:
        gap = (sum(probe.count(c) for c in closes)
               - sum(probe.count(o) for o in opens))
        if gap > 0:
            deficits[opens] = gap
    if not deficits:
        return text
    log.append(f"{sid}: 開き括弧の脱落を検出 {deficits} → OCR照合で復元")
    ocr = ocr_reference(pdf)

    # Compare both sides with whitespace removed; remember where each kept
    # character sat in the original so insertions can be mapped back.
    a, amap = [], []
    for i, ch in enumerate(text):
        if not ch.isspace():
            a.append(ch); amap.append(i)
    b = [ch for ch in ocr if not ch.isspace()]
    amap.append(len(text))

    inserts: list[tuple[int, str]] = []
    remaining = dict(deficits)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "insert":
            continue
        seg = "".join(b[j1:j2])
        for ch in seg:
            cls = next((o for o in remaining if ch in o), None)
            if cls and remaining[cls] > 0:
                inserts.append((amap[i1], ch))
                remaining[cls] -= 1
    for pos, ch in sorted(inserts, reverse=True):
        # The dropped glyph left a space (or wrap) behind: reuse that slot.
        if pos > 0 and text[pos - 1] in " \n":
            text = text[:pos - 1] + ch + text[pos:]
        else:
            text = text[:pos] + ch + text[pos:]
    done = {k: deficits[k] - v for k, v in remaining.items()}
    log.append(f"{sid}: 復元 {done} / 未解決 "
               f"{ {k: v for k, v in remaining.items() if v} }")
    return text


def split_questions(text: str, sid: str) -> dict[int, dict]:
    heads = list(HEAD.finditer(text))
    out: dict[int, dict] = {}
    for i, m in enumerate(heads):
        no = int(m.group(1))
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = unwrap(clean(strip_noise(text[m.end():end])))
        out[no] = {"answer": m.group(2), "explanation": body}
    return out


def main() -> None:
    targets = sys.argv[1:] or SESSION_IDS
    result, log, bad = {}, [], []
    for sid in targets:
        pdf = pdf_path(sid, "4教科書解説")
        text = clean(pdf_text(pdf))
        text = repair_brackets(text, pdf, sid, log)
        qs = split_questions(text, sid)
        missing = [n for n in range(1, 26) if n not in qs]
        short = [n for n, q in qs.items() if len(q["explanation"]) < 40]
        if missing:
            bad.append(f"{sid}: 解説なし 問{missing}")
        lens = [len(q["explanation"]) for q in qs.values()]
        result[sid] = {str(n): qs[n] for n in sorted(qs)}
        print(f"{sid:9} {len(qs):2}/25  解説長 min={min(lens)} med="
              f"{sorted(lens)[len(lens)//2]} max={max(lens)}"
              + (f"  短い:問{short}" if short else ""))
    for l in log:
        print("  *", l)
    for b in bad:
        print("  !", b)
    write_json(BUILD / "explanations.json", result)
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
