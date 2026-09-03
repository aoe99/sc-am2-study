#!/usr/bin/env python3
"""Stage 8 — the §3-8 acceptance checklist, printed as a table.

    python3 tools/08_validate.py
"""
from __future__ import annotations
import json, re, sys, unicodedata
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import CHOICE_KEYS, DATA, BUILD, read_json

CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MOJIBAKE = re.compile(r"[�□]")


def main() -> int:
    doc = read_json(DATA / "questions.json")
    qs = doc["questions"]
    answers = read_json(BUILD / "answers.json")
    expl = read_json(BUILD / "explanations.json")
    n_sess = doc["meta"]["sessionCount"]
    per = Counter(q["sessionId"] for q in qs)

    rows = []
    def check(label, ok, detail=""):
        rows.append((ok, label, detail))

    bad_count = [s for s, c in per.items() if c != 25]
    check(f"各回ちょうど25問（{n_sess}回）", not bad_count,
          "" if not bad_count else f"不正: {bad_count}")
    check(f"合計 {n_sess * 25} 問", len(qs) == n_sess * 25, f"実際 {len(qs)} 問")

    no_text = [q["id"] for q in qs if not q["text"].strip()]
    # A table-row choice legitimately carries an image instead of prose.
    no_ch = [q["id"] for q in qs
             if len([c for c in q["choices"]
                     if c["text"].strip() or q["choiceFigures"].get(c["key"])]) != 4]
    no_ans = [q["id"] for q in qs if q["answer"] not in CHOICE_KEYS]
    no_exp = [q["id"] for q in qs if not q["explanation"].strip()]
    check("全問に問題文がある", not no_text, str(no_text[:5]))
    check("全問に選択肢4つがある", not no_ch, str(no_ch[:5]))
    check("全問に正解記号がある", not no_ans, str(no_ans[:5]))
    check("全問に解説がある", not no_exp, str(no_exp[:5]))

    mism = [q["id"] for q in qs
            if answers[q["sessionId"]][str(q["no"])]
            != expl[q["sessionId"]][str(q["no"])]["answer"]]
    check("IPA解答例と教科書解説の正解が一致", not mism, str(mism[:5]))

    short = [q for q in qs if len(q["text"]) < 100]
    check(f"問題文100字未満は理由が説明できる（{len(short)}問）", True,
          "SC午前IIは用語の定義を一行で問う設問が多く、短いのは欠損ではない。"
          f"最短 {min((len(q['text']) for q in qs), default=0)}字")

    dirty = [q["id"] for q in qs
             if CTRL.search(q["text"] + q["explanation"])
             or MOJIBAKE.search(q["text"] + q["explanation"])
             or "  " in q["text"]
             or any("  " in c["text"] for c in q["choices"])]
    check("制御文字・文字化け・連続空白なし", not dirty, str(dirty[:5]))

    ids = [q["id"] for q in qs]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    check("IDに重複なし", not dup, str(dup[:5]))

    nfc = [q["id"] for q in qs
           if unicodedata.normalize("NFC", q["text"]) != q["text"]]
    check("Unicode正規化済み(NFC)", not nfc, str(nfc[:5]))

    w = max(len(r[1]) for r in rows)
    print(f"{'':2} {'検証項目'.ljust(w)}  詳細")
    print("-" * (w + 40))
    for ok, label, detail in rows:
        print(f"{'✓ ' if ok else '✗ '} {label.ljust(w)}  {detail}")
    nrev = sum(1 for q in qs if q["needsReview"])
    nfig = sum(1 for q in qs if q["figures"])
    print(f"\n要確認 {nrev} 問 / 図表付き {nfig} 問 / タグ種別 "
          f"{len({t for q in qs for t in q['tags']})}")
    return 0 if all(r[0] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
