#!/usr/bin/env python3
"""Stage 13 — 午後の教科書解説PDF から事例のタイトルと設問ごとの解説を取り出す。

翔泳社's 読者特典 is the only place the 大問 has a name — IPA's booklet just says
問1 — and it is the only per-設問 walkthrough of *why* the 解答例 is the 解答例.

The layout moved around over the ten years this covers: 設問 headings are ■ in
the older books and ● in the newer ones, the 解答例 block is bracketed 〔〕 or
［］, and R03 春 prints the whole answer block above the first 設問 instead of
inside it.  So the split is by 設問 heading and everything else is taken where it
falls; what could not be placed is reported rather than guessed at.

    python3 tools/13_pm_explanations.py [session ...]
"""
from __future__ import annotations
import json, re, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (PM_PAPERS, build_dir, clean, pdf_path, pdf_text, pm_papers_of,
                   read_json, run_tool, strip_ruby, targets_of, unwrap, write_json)

# Three headings for the same thing across ten years of 読者特典: ＜問１＞ with
# angle brackets (usual), and a bare "問 1 API セキュリティ" from R06 春 on.  The
# bracketed form is distinctive enough to match anywhere — H31 春 has one that
# PDFKit dropped into the middle of a sentence — but the bare form has to start
# its line and carry a title, or "問1 の設問3で解説した" would open a 大問.
CASE = re.compile(
    r"[＜<〈\[［]\s*[問間]\s*([0-9０-９]{1,2})\s*[＞>〉\]］]\s*([^\n]*)"
    r"|^[問間]\s*([0-9０-９]{1,2})\s*([^\s\d０-９。、，][^\n。、，]{1,40})$", re.M)


def case_head(m: re.Match) -> tuple[int, str]:
    no = m.group(1) or m.group(3)
    return int(no.translate(FW)), clean(m.group(2) if m.group(1) else m.group(4))
SETSU = re.compile(r"^[■●◆▲○□]?\s*設問\s*([0-9０-９]{1,2})\s*$")
ANSWER_HEAD = re.compile(r"^[［〔\[]\s*試験センターによる解答例\s*[］〕\]]\s*$")
EXPL_HEAD = re.compile(r"^[＜<]\s*解説\s*[＞>]\s*$")

NOISE = [
    re.compile(r"^情報処理教科書\s*安全確保支援士.*読者特典\s*$"),
    re.compile(r"^[［\[].{0,24}午後[ⅠⅡI]*\s*解答・解説[］\]]\s*$"),
    re.compile(r"^[-–—]\s*\d+\s*[-–—]\s*$"),
    re.compile(r"^©\s*\d{4}.*$"),
    re.compile(r"^(令和|平成).*(支援士|スペシャリスト)\s*$"),
    re.compile(r"^＜午後[ⅠⅡI]*\s*解答・解説＞\s*$"),
    re.compile(r"^\d+\s*/\s*\d+$"),
]

# "(2) c：タスク名" — the 解答例 block labels its blanks with a full-width colon,
# which is the one thing the IPA table does not do.
SUB = re.compile(r"^[(（]\s*([0-9０-９]{1,2})\s*[)）]\s*")
LABELLED = re.compile(r"^([a-zA-Zａ-ｚＡ-Ｚあ-んア-ンａ-ｚ①-⑳α-ωΑ-Ω]{1,2})\s*[：:]\s*(.*)$")
# 翔泳社 prints the length IPA counted, which the booklet only gives as a limit.
CHARS = re.compile(r"[（(]\s*[0-9０-９]{1,3}\s*字\s*[）)]\s*$")

# Full-width digits and latin letters both appear as 空欄 labels; normalising
# them is what lets "ａ：ア" line up with the IPA table's "a".
FW = str.maketrans(
    "０１２３４５６７８９" + "".join(chr(0xFF21 + i) for i in range(26))
    + "".join(chr(0xFF41 + i) for i in range(26)),
    "0123456789" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + "abcdefghijklmnopqrstuvwxyz")


def source_text(pdf: Path) -> tuple[str, str]:
    """The 読者特典 text, OCR'd if the book shipped that year as a scan.

    Every other sitting's explanation PDF carries a text layer.  R07 春 does not
    — all eight pages are images — so it goes through Vision like the 問題冊子,
    and says so, because OCR'd prose is not as trustworthy as the real thing.
    """
    text = pdf_text(pdf)
    if len(clean(text)) > 500:
        return text, "text"
    info = json.loads(run_tool("info", pdf))
    with tempfile.TemporaryDirectory() as td:
        shots = []
        for page in info["pages"]:
            n = page["page"]
            # R07 春 was scanned two book pages to a landscape sheet.  OCR sorts
            # by baseline, so reading a whole sheet at once interleaves the two
            # columns and shuffles 設問2 into 設問3; each half is read on its own.
            halves = ([(0.0, 0.5), (0.5, 0.5)] if page["w"] > page["h"]
                      else [(0.0, 1.0)])
            for k, (x, w) in enumerate(halves):
                out = Path(td) / f"e-{n:03d}{chr(97 + k)}.png"
                run_tool("crop", pdf, n, f"{x}", "0", f"{w}", "1", out, "--dpi", "400")
                shots.append(out)
        pages = json.loads(run_tool("ocr", *shots, "--json"))
    return "\n".join(l["text"] for pg in pages for l in pg["lines"]), "ocr"


def strip_noise(lines: list[str]) -> list[str]:
    return [l for l in (x.strip() for x in lines)
            if l and not any(p.match(l) for p in NOISE)]


def parse_answers(lines: list[str]) -> list[dict]:
    """The 解答例 block, as {sub, label, answer} rows."""
    out: list[dict] = []
    sub: int | None = None
    for ln in lines:
        m = SUB.match(ln)
        if m:
            sub = int(m.group(1).translate(FW))
            ln = ln[m.end():].strip()
            if not ln:
                continue
        m = LABELLED.match(ln)
        if m:
            out.append({"sub": sub, "label": m.group(1).translate(FW),
                        "answer": CHARS.sub("", m.group(2)).strip()})
        elif out and not SUB.match(ln) and out[-1]["sub"] == sub and not m:
            out[-1]["answer"] = (out[-1]["answer"] + ln).strip()
        else:
            out.append({"sub": sub, "label": None,
                        "answer": CHARS.sub("", ln).strip()})
    return [r for r in out if r["answer"]]


def parse_paper(sid: str, paper: str) -> dict:
    raw, origin = source_text(pdf_path(sid, "4教科書解説", "pm", paper))
    text = strip_ruby(clean(raw))
    heads = list(CASE.finditer(text))
    if not heads:
        raise SystemExit(f"{sid}/{paper}: ＜問N＞ の見出しが見つからない")
    # The older books print the walkthrough straight after the 解答例 with no
    # ＜解説＞ heading of its own, so there is nothing to close the answer block
    # on.  Where the marker is never used, the whole 設問 block is the解説.
    split_answers = bool(EXPL_HEAD.search(text.replace("\n", "\n")) or
                         any(EXPL_HEAD.match(l.strip()) for l in text.split("\n")))
    cases = {}
    for i, m in enumerate(heads):
        no, title = case_head(m)
        block = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        lines = strip_noise(block.split("\n"))

        by: dict[str, dict] = {}
        key, where = None, "pre"
        pre: list[str] = []
        for ln in lines:
            ms = SETSU.match(ln)
            if ms:
                key = str(int(ms.group(1).translate(FW)))
                by.setdefault(key, {"answers": [], "explanation": []})
                where = "expl"
                continue
            if ANSWER_HEAD.match(ln):
                where = "ans" if split_answers else "expl"
                continue
            if EXPL_HEAD.match(ln):
                where = "expl"
                continue
            if key is None:
                pre.append(ln)
            elif where == "ans":
                by[key]["answers"].append(ln)
            else:
                by[key]["explanation"].append(ln)

        cases[str(no)] = {
            "no": no, "paper": paper, "origin": origin,
            "title": title,
            "preamble": unwrap("\n".join(pre)),
            "bySetsu": {k: {"answers": parse_answers(v["answers"]),
                            "explanation": unwrap("\n".join(v["explanation"]))}
                        for k, v in by.items()},
        }
    return cases


def main() -> None:
    targets = targets_of(sys.argv[1:])
    out, bad, note = {}, [], []
    for sid in targets:
        out[sid] = {}
        for paper in pm_papers_of(sid):
            cases = parse_paper(sid, paper)
            if any(c["origin"] == "ocr" for c in cases.values()):
                note.append(f"{sid}/{paper}: 解説PDFにテキスト層がないためOCR")
            want = PM_PAPERS[paper]["cases"]
            if len(cases) != want:
                bad.append(f"{sid}/{paper}: 大問 {len(cases)}/{want}")
            for no, c in cases.items():
                if not c["title"]:
                    bad.append(f"{sid}/{paper} 問{no}: 事例タイトルなし")
                if not c["bySetsu"]:
                    bad.append(f"{sid}/{paper} 問{no}: 設問の見出しが取れない")
                short = [k for k, v in c["bySetsu"].items()
                         if len(v["explanation"]) < 60]
                if short:
                    note.append(f"{sid}/{paper} 問{no}: 解説が短い 設問{short}")
            out[sid][paper] = cases
            n_ex = sum(len(c["bySetsu"]) for c in cases.values())
            n_an = sum(len(v["answers"]) for c in cases.values()
                       for v in c["bySetsu"].values())
            chars = sum(len(v["explanation"]) for c in cases.values()
                        for v in c["bySetsu"].values())
            print(f"{sid:9} {PM_PAPERS[paper]['label']:5} 大問{len(cases)}  "
                  f"設問{n_ex:3}  解答例行{n_an:3}  解説{chars//1000:3}千字")
    for x in note[:12]:
        print("  *", x)
    if len(note) > 12:
        print(f"  * …ほか {len(note) - 12} 件")
    for b in bad:
        print("  !", b)
    path = build_dir("pm") / "explanations.json"
    merged = read_json(path) if path.exists() else {}
    merged.update(out)
    write_json(path, merged)
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
