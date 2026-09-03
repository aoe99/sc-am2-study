#!/usr/bin/env python3
"""Stage 6 — merge every stage into data/questions.json and the review report.

    python3 tools/06_build.py [session ...]
"""
from __future__ import annotations
import datetime as dt, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (SESSIONS, SESSION_IDS, CHOICE_KEYS, ROOT, DATA, BUILD,
                   exam_name, pdf_path, read_json, write_json)

SCHEMA_VERSION = 1
TAGS = read_json(Path(__file__).resolve().parent / "tags.json")
# Latin look-alikes and stray glyphs Vision leaves behind; each needs an eyeball.
SUSPECT = [
    (re.compile(r"[Ａ-Ｚａ-ｚ０-９]"), "全角英数字"),
    (re.compile(r"[０-９]"), "全角数字"),
    (re.compile(r"[ｱ-ﾝ]"), "半角カナ"),
    (re.compile(r"[〇◯Ｏ]\s*[0-9]"), "O/0 の混同疑い"),
    (re.compile(r"[a-zA-Z]{2,}\s+[a-z]{1,3}\b(?![a-zA-Z])"), "英単語の分断疑い"),
    (re.compile(r"[　]"), "全角スペース"),
    (re.compile(r"(.)\1{4,}"), "同一文字の連続"),
    (re.compile(r"[”“][^”“]{0,3}[，,]\s*[”“]"), "引用符内が短すぎる"),
    (re.compile(r"[口।।]"), "ロ/口 の混同疑い"),
]


def known_chars() -> set:
    """Every character the 読者特典 explanations use.

    That text comes out of the PDF losslessly, so it is a clean 13万字 sample of
    exactly this domain's vocabulary.  A kanji in the OCR'd 問題文 that never
    appears there, and appears almost nowhere else in the corpus either, is
    nearly always a misread (擎 for 撃, 発 for 殆).
    """
    expl = read_json(BUILD / "explanations.json")
    return {c for sess in expl.values() for q in sess.values()
            for c in q["explanation"]}


def tesseract_pages(sid: str) -> dict[int, str]:
    path = BUILD / "ocr" / f"{sid}.json"
    if not path.exists():
        return {}
    pages = json.loads(path.read_text(encoding="utf-8"))
    return {n: (p.get("tesseract") or "") for n, p in enumerate(pages, 1)}


def rare_chars(sid: str, questions: list[dict], known: set) -> dict[str, list[str]]:
    """Kanji that are absent from the explanations *and* that the second OCR
    engine did not see either.  Either signal alone is far too noisy; together
    they land almost exclusively on real misreads."""
    from collections import Counter
    freq = Counter(c for q in questions
                   for c in q["text"] + "".join(q["choices"].values()))
    tess = tesseract_pages(sid)
    out: dict[str, list[str]] = {}
    for q in questions:
        hay = q["text"] + "\n" + "\n".join(q["choices"].values())
        second = "".join(tess.get(p, "") for p in q["pages"])
        odd = sorted({c for c in hay
                      if c not in known and freq[c] <= 3
                      and "\u4e00" <= c <= "\u9fff"
                      and (not second or c not in second)})
        if odd:
            out[str(q["no"])] = odd
    return out


def _matcher(keyword: str):
    """Latin acronyms need word boundaries — plain substring matching puts
    "SPF" (メール) inside "OSPF" (ルーティング)."""
    if keyword.isascii() and re.fullmatch(r"[A-Za-z0-9/&.\-]{2,8}", keyword):
        rx = re.compile(rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])")
        return rx.search
    return lambda hay, k=keyword: k in hay


MATCH = {t["name"]: [_matcher(k) for k in t["keywords"]] for t in TAGS["tags"]}


def tags_for(text: str) -> list[str]:
    found = [t["name"] for t in TAGS["tags"]
             if any(m(text) for m in MATCH[t["name"]])]
    return found or [TAGS["fallback"]]


def suspects(q: dict) -> list[str]:
    hay = q["text"] + "\n" + "\n".join(q["choices"].values())
    return [label for rx, label in SUSPECT if rx.search(hay)]


def build(targets: list[str]) -> dict:
    answers = read_json(BUILD / "answers.json")
    expl = read_json(BUILD / "explanations.json")
    parsed = read_json(BUILD / "parsed.json")
    figs = read_json(BUILD / "figures.json") if (BUILD / "figures.json").exists() else {}
    meta = {s[0]: s for s in SESSIONS}

    known = known_chars()
    questions, review = [], []
    for sid in targets:
        odd_by_no = rare_chars(sid, parsed[sid], known)
        for q in parsed[sid]:
            no = q["no"]
            qid = f"{sid}-am2-{no:02d}"
            ans = answers[sid][str(no)]
            ex = expl[sid][str(no)]
            fig = figs.get(sid, {}).get(str(no)) or {}
            cfigs = fig.get("choiceFigures", {})
            notes = list(q["flags"])
            odd = odd_by_no.get(str(no))
            if odd:
                notes.append("解説に存在しない漢字: " + " ".join(odd))
            if len(q["choices"]) != 4:
                notes.append(f"選択肢が{len(q['choices'])}個")
            if q["mentionsFigure"] and not fig.get("file"):
                notes.append("図表に言及しているが画像なし")
            if ans != ex["answer"]:
                notes.append(f"正解不一致 IPA={ans} 解説={ex['answer']}")
            short = len(q["text"]) < 100
            questions.append({
                "id": qid, "sessionId": sid, "no": no,
                "text": q["text"],
                "choices": [{"key": k, "text": q["choices"].get(k, "")} for k in CHOICE_KEYS],
                "answer": ans,
                "explanation": ex["explanation"],
                "explanationSource": "情報処理教科書 安全確保支援士 読者特典",
                "figures": [fig["file"]] if fig.get("file") else [],
                "choiceFigures": cfigs,
                "tags": tags_for(q["text"] + "\n" + ex["explanation"]),
                "duplicateGroupId": None,
                "needsReview": bool(notes),
                "shortText": short,
                "source": {
                    "questionPdf": f"{sid}/{pdf_path(sid, '1問題').name}",
                    "page": q["pages"][0],
                    "pageImage": f"build/pages/{sid}/{sid}-p{q['pages'][0]:03d}.png",
                },
            })
            if notes:
                review.append((qid, notes, q))

    sessions = [{"id": s, "label": meta[s][1], "year": meta[s][2],
                 "term": meta[s][3], "examName": exam_name(s)} for s in targets]
    doc = {
        "meta": {
            "generatedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "schemaVersion": SCHEMA_VERSION,
            "sessionCount": len(sessions),
            "questionCount": len(questions),
        },
        "sessions": sessions,
        "questions": questions,
    }
    return doc, review


def write_review(doc: dict, review: list) -> None:
    lines = ["# 要確認リスト", "",
             f"生成: {doc['meta']['generatedAt']}  /  対象 {doc['meta']['questionCount']} 問中 "
             f"{len(review)} 問", "",
             "OCR は必ず誤認識するため、下の各問はページ画像と読み比べて直すこと。",
             "画像パスは `data/` からの相対。", ""]
    for qid, notes, q in review:
        page = q["pages"][0]
        sid = qid.split("-")[0]
        lines += [f"## {qid}", "",
                  f"- 指摘: {' / '.join(notes)}",
                  f"- ページ画像: `build/pages/{sid}/{sid}-p{page:03d}.png`", "",
                  "```", q["text"], ""]
        for k in CHOICE_KEYS:
            lines.append(f"{k}  {q['choices'].get(k, '(なし)')}")
        lines += ["```", ""]
    (BUILD / "review.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  → data/build/review.md ({len(review)} 問)")


def main() -> None:
    targets = sys.argv[1:] or SESSION_IDS
    doc, review = build(targets)
    write_json(DATA / "questions.json", doc)
    write_review(doc, review)
    from collections import Counter
    tc = Counter(t for q in doc["questions"] for t in q["tags"])
    print(f"\n{doc['meta']['questionCount']} 問 / {doc['meta']['sessionCount']} 回"
          f"  要確認 {len(review)} 問  図表 "
          f"{sum(1 for q in doc['questions'] if q['figures'])} 問")
    print("分野タグ:", "  ".join(f"{k}={v}" for k, v in tc.most_common()))


if __name__ == "__main__":
    main()
