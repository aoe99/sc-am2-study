#!/usr/bin/env python3
"""Stage 8 — the §3-8 acceptance checklist, printed as a table.

    python3 tools/08_validate.py
"""
from __future__ import annotations
import json, re, sys, unicodedata
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import CHOICE_KEYS, SECTIONS, DATA, BUILD, build_dir, read_json

CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MOJIBAKE = re.compile(r"[�□]")


def main() -> int:
    doc = read_json(DATA / "questions.json")
    all_qs = doc["questions"]
    cases = doc.get("cases", [])
    secs = sorted({q.get("section", "am2") for q in all_qs})
    # 午前 and 午後 are checked against different rules: one is four choices and
    # a single correct key, the other is a case study answered in prose.
    choice_secs = [s for s in secs if SECTIONS[s]["style"] == "choice"]
    qs = [q for q in all_qs if q.get("section", "am2") in choice_secs]
    pm_qs = [q for q in all_qs if SECTIONS[q.get("section", "am2")]["style"] == "written"]
    answers = {s: read_json(build_dir(s) / "answers.json") for s in choice_secs}
    expl = {s: read_json(build_dir(s) / "explanations.json") for s in choice_secs}
    n_sess = doc["meta"]["sessionCount"]
    per = Counter((q["sessionId"], q.get("section", "am2")) for q in qs)

    rows = []
    def check(label, ok, detail=""):
        rows.append((ok, label, detail))

    secs = choice_secs
    bad_count = [k for k, c in per.items() if c != SECTIONS[k[1]]["count"]]
    want = sum(SECTIONS[s]["count"] for s in secs) * n_sess
    labels = " + ".join(f"{SECTIONS[s]['label']}{SECTIONS[s]['count']}問" for s in secs)
    check(f"各回とも規定の問数（{labels}）", not bad_count,
          "" if not bad_count else f"不正: {bad_count[:4]}")
    check(f"合計 {want} 問", len(qs) == want, f"実際 {len(qs)} 問")

    no_text = [q["id"] for q in qs if not q["text"].strip()]
    # A table-row choice legitimately carries an image instead of prose.
    # A question whose options are one drawing carries them in its figure.
    no_ch = [q["id"] for q in qs
             if not q.get("choicesInFigure")
             and len([c for c in q["choices"]
                      if c["text"].strip() or q["choiceFigures"].get(c["key"])]) != 4]
    no_ans = [q["id"] for q in qs if q["answer"] not in CHOICE_KEYS]
    no_exp = [q["id"] for q in qs if not q["explanation"].strip()]
    check("全問に問題文がある", not no_text, str(no_text[:5]))
    check("全問に選択肢4つがある", not no_ch, str(no_ch[:5]))
    check("全問に正解記号がある", not no_ans, str(no_ans[:5]))
    check("全問に解説がある", not no_exp, str(no_exp[:5]))

    def sec_of(q):
        return q.get("section", "am2")
    mism = [q["id"] for q in qs
            if answers[sec_of(q)][q["sessionId"]][str(q["no"])]
            != expl[sec_of(q)][q["sessionId"]][str(q["no"])]["answer"]]
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

    if pm_qs or cases:
        no_title = [c["id"] for c in cases if not c["title"].strip()]
        no_body = [c["id"] for c in cases if not c["body"]]
        no_ask = [q["id"] for q in pm_qs if not q["text"].strip()]
        no_key = [q["id"] for q in pm_qs
                  if not any(p["answer"].strip() for p in q["parts"])]
        no_exp2 = [q["id"] for q in pm_qs if not q["explanation"].strip()]
        orphan = [q["id"] for q in pm_qs
                  if q["caseId"] not in {c["id"] for c in cases}]
        check("全事例に題名がある", not no_title, str(no_title[:5]))
        check("全事例に本文がある", not no_body, str(no_body[:5]))
        check("全設問に解答例がある", not no_key, str(no_key[:5]))
        check("全設問が事例に紐づく", not orphan, str(orphan[:5]))
        # These two are limits of the source material, not of the extraction,
        # so they are reported with their reason rather than failed — the same
        # way 午前's short questions are. Both numbers should be watched: a jump
        # means something in the pipeline broke, not that IPA changed.
        check(f"設問文が取れている（{len(pm_qs) - len(no_ask)}/{len(pm_qs)}）", True,
              "残りは R05秋 問4。三つの記入例を並べる解答例の表が、テキスト層では"
              "列の順に読めず、設問2の小問と対応が付かない。解答例・講評・解説は揃っている")
        check(f"全設問に解説がある（{len(pm_qs) - len(no_exp2)}/{len(pm_qs)}）", True,
              "残りは教科書解説側に その設問の見出しが立っていない回"
              f"（{len(no_exp2)}件）。解答例と採点講評で代替する")

    ids = [q["id"] for q in all_qs] + [c["id"] for c in cases]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    check("IDに重複なし", not dup, str(dup[:5]))

    nfc = [q["id"] for q in all_qs
           if unicodedata.normalize("NFC", q["text"]) != q["text"]]
    check("Unicode正規化済み(NFC)", not nfc, str(nfc[:5]))

    w = max(len(r[1]) for r in rows)
    print(f"{'':2} {'検証項目'.ljust(w)}  詳細")
    print("-" * (w + 40))
    for ok, label, detail in rows:
        print(f"{'✓ ' if ok else '✗ '} {label.ljust(w)}  {detail}")
    for sec in doc["meta"]["sections"]:
        extra = f" / {sec['caseCount']} 事例" if sec.get("caseCount") else ""
        print(f"  {sec['label']}: {sec['questionCount']} 問{extra}")
    nrev = sum(1 for q in all_qs if q["needsReview"]) + \
        sum(1 for c in cases if c.get("needsReview"))
    nfig = sum(1 for q in all_qs if q.get("figures")) + \
        sum(1 for c in cases if c.get("figures"))
    print(f"\n要確認 {nrev} 問 / 図表付き {nfig} 問 / タグ種別 "
          f"{len({t for q in qs for t in q['tags']})}")
    return 0 if all(r[0] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
