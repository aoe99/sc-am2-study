#!/usr/bin/env python3
"""Stage 12 — 午後の採点講評PDF から設問ごとの講評と正答率を取り出す。

午前 has no equivalent of this document and it is the most useful thing 午後
ships.  IPA says, per 設問, how well the cohort did and which wrong answers were
common:

    設問 3(2)は，正答率が低かった。“デジタル署名”という解答が多く見られた。

For a 記述 answer that is graded by the person who wrote it, that is the only
thing standing between "I'll call that close enough" and an honest ×.  The
正答率 also gives the corpus a difficulty signal 午前 never had.

    python3 tools/12_pm_commentary.py [session ...]
"""
from __future__ import annotations
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (PM_PAPERS, build_dir, clean, pdf_path, pdf_text, pm_papers_of,
                   read_json, strip_ruby, targets_of, unwrap, write_json)

CASE = re.compile(r"^[問間]\s*([0-9０-９]{1,2})\s*$", re.M)
# "設問 3(1)は，" / "設問4では，" — the paragraph for one 設問 starts its line.
SETSU = re.compile(r"^設問\s*([0-9０-９]{1,2})\s*(?:[(（]\s*([0-9０-９]{1,2})\s*[)）])?"
                   r"\s*(?=[はをでにのがと，,、（(～])")
NOISE = [
    re.compile(r"^\d+\s*/\s*\d+$"),
    re.compile(r"^©\s*\d{4}.*$"),
    re.compile(r"^(令和|平成).*採点講評\s*$"),
    re.compile(r"^午後[ⅠⅡI]*\s*試験\s*$"),
]

# IPA grades the cohort with a closed set of phrases; "やや" has to be tested
# before the plain form or every "やや低かった" reads as "低かった".
RATES = [
    ("やや低", re.compile(r"正答率[^。]{0,8}やや低")),
    ("やや高", re.compile(r"正答率[^。]{0,8}やや高")),
    ("平均",   re.compile(r"正答率[^。]{0,8}平均的")),
    ("低",     re.compile(r"正答率[^。]{0,8}(?:低|高くなかった)")),
    ("高",     re.compile(r"正答率[^。]{0,8}高")),
]

FW = str.maketrans("０１２３４５６７８９", "0123456789")


def rate_of(text: str) -> str | None:
    for name, rx in RATES:
        if rx.search(text):
            return name
    return None


def parse_paper(sid: str, paper: str) -> dict:
    text = strip_ruby(clean(pdf_text(pdf_path(sid, "3採点講評", "pm", paper))))
    heads = list(CASE.finditer(text))
    if not heads:
        raise SystemExit(f"{sid}/{paper}: 問N の見出しが見つからない")
    cases = {}
    for i, m in enumerate(heads):
        no = int(m.group(1).translate(FW))
        block = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        lines = [l for l in block.split("\n")
                 if l.strip() and not any(p.match(l.strip()) for p in NOISE)]
        paras = unwrap("\n".join(lines)).split("\n")

        overall: list[str] = []
        by: dict[str, list[str]] = {}
        key = None
        for para in paras:
            mm = SETSU.match(para)
            if mm:
                sub = mm.group(2)
                key = (mm.group(1).translate(FW)
                       + (f"({sub.translate(FW)})" if sub else ""))
                by.setdefault(key, [])
            (by[key] if key else overall).append(para)

        cases[str(no)] = {
            "no": no, "paper": paper,
            "overall": " ".join(overall).strip(),
            "overallRate": rate_of(" ".join(overall)),
            "bySetsu": {k: {"text": " ".join(v).strip(), "rate": rate_of(" ".join(v))}
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
            want = PM_PAPERS[paper]["cases"]
            if len(cases) != want:
                bad.append(f"{sid}/{paper}: 大問 {len(cases)}/{want}")
            for no, c in cases.items():
                if not c["bySetsu"] and not c["overall"]:
                    bad.append(f"{sid}/{paper} 問{no}: 講評が空")
                elif not c["bySetsu"]:
                    # Some sittings comment on the 大問 as a whole and never
                    # open a paragraph with 設問N — that is how IPA wrote it.
                    note.append(f"{sid}/{paper} 問{no}: 全体講評のみ（設問別なし）")
            out[sid][paper] = cases
            n = sum(len(c["bySetsu"]) for c in cases.values())
            rated = sum(1 for c in cases.values() for v in c["bySetsu"].values()
                        if v["rate"])
            print(f"{sid:9} {PM_PAPERS[paper]['label']:5} 大問{len(cases)}  "
                  f"設問別講評{n:3}  うち正答率あり{rated:3}")
    total = sum(len(c["bySetsu"]) for s in out.values() for p in s.values()
                for c in p.values())
    print(f"\n設問別の講評 合計 {total} 件 / {len(targets)} 回")
    for x in note:
        print("  *", x)
    for b in bad:
        print("  !", b)
    path = build_dir("pm") / "commentary.json"
    merged = read_json(path) if path.exists() else {}
    merged.update(out)
    write_json(path, merged)
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
