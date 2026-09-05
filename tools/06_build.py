#!/usr/bin/env python3
"""Stage 6 — merge every stage into data/questions.json and the review report.

    python3 tools/06_build.py [--section am1|am2|pm] [session ...]
                                       # 省略時は生成済みの区分をすべて統合

午前 is one record per question.  午後 is two: a `case` holding the 事例本文 and
its 図表, and one `question` per 設問 pointing at it.  Keeping the questions flat
is what lets the Leitner boxes, the study record and the stats stay exactly as
they are — a 設問 is the thing you answer and the thing you come back to, not the
ten pages of scenario above it.
"""
from __future__ import annotations
import datetime as dt, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (SESSIONS, SESSION_IDS, SECTIONS, CHOICE_KEYS, PM_PAPERS, ROOT,
                   DATA, BUILD, build_dir, exam_name, pdf_path, pm_papers_of,
                   read_json, write_json)

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


def known_chars(section: str) -> set:
    """Every character the 読者特典 explanations use.

    That text comes out of the PDF losslessly, so it is a clean 13万字 sample of
    exactly this domain's vocabulary.  A kanji in the OCR'd 問題文 that never
    appears there, and appears almost nowhere else in the corpus either, is
    nearly always a misread (擎 for 撃, 発 for 殆).
    """
    expl = read_json(build_dir(section) / "explanations.json")
    return {c for sess in expl.values() for q in sess.values()
            for c in q["explanation"]}


def tesseract_pages(sid: str, section: str) -> dict[int, str]:
    path = build_dir(section) / "ocr" / f"{sid}.json"
    if not path.exists():
        return {}
    pages = json.loads(path.read_text(encoding="utf-8"))
    return {n: (p.get("tesseract") or "") for n, p in enumerate(pages, 1)}


def rare_chars(sid: str, section: str, questions: list[dict], known: set) -> dict[str, list[str]]:
    """Kanji that are absent from the explanations *and* that the second OCR
    engine did not see either.  Either signal alone is far too noisy; together
    they land almost exclusively on real misreads."""
    from collections import Counter
    freq = Counter(c for q in questions
                   for c in q["text"] + "".join(q["choices"].values()))
    tess = tesseract_pages(sid, section)
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


def available_sections() -> list[str]:
    return [sec for sec in SECTIONS if (build_dir(sec) / "parsed.json").exists()]


# --- 午後 ---------------------------------------------------------------

def pm_commentary(comm: dict, setsu: int, sub) -> tuple[str, str | None]:
    """IPA's remarks on this 設問, falling back to the whole 設問's paragraph.

    The 採点講評 sometimes addresses 設問3(1) and sometimes 設問3 as a whole, so a
    小問 reads the more specific one where it exists.
    """
    by = comm.get("bySetsu", {}) if comm else {}
    hit = by.get(f"{setsu}({sub})") if sub else None
    hit = hit or by.get(str(setsu))
    return ((hit or {}).get("text", ""), (hit or {}).get("rate"))


# "図8中の c ～ e に入れる" is a range over the blanks a 設問 has, and the answer
# key names every one of them. Where OCR lost the letter inside a frame or read
# it as something else (e as N), the ends of the range are still recoverable:
# a range runs from the first blank to the last. Four 設問 in the corpus are
# written this way, few enough to have checked each one by eye.
# The frame of a box is read as its own fragment often enough that one printed
# box arrives as two ("［c］［　］"), so both ends of the range absorb whatever
# run of boxes and stray letters sits there.
# The left of the range has to be a real frame. Letters alone are not enough:
# "XX-XX-XX-23-46-4a" in a 解答群 of MAC addresses is not a range of blanks, and
# reading it as one rewrote an answer choice.
BOX = r"(?:［[^］]{0,3}］|■)"
BOXISH = rf"(?:{BOX}|[A-Za-zａ-ｚ]{{1,2}})"
PM_RANGE = re.compile(rf"(?:{BOX}\s*){{1,3}}[~～ー−\-]\s*(?:{BOXISH}\s*){{1,3}}")


def pm_fix_range(text: str, parts: list[dict]) -> str:
    labels = [p["label"] for p in parts if p["label"]]
    if not text or len(labels) < 2:
        return text
    return PM_RANGE.sub(f"［{labels[0]}］～［{labels[-1]}］", text, count=1)


# A 空欄 frame the scan swallowed whole. "設問1 表1中の a ～ e に入れる" comes back
# as "表1中の［e］に入れる": the gap from the end of "表1中の" to the letter e is
# one wide space, and everything printed inside it — the box round a, the tilde —
# is a drawing. The answer key names every 空欄 the 設問 has, so when the one
# marker that survived is the first or the last of them, what was printed is
# recoverable. IPA sets two blanks side by side and three or more as a range.
PM_ONE_BLANK = re.compile(r"［\s*([^］\s]{1,3})\s*］")


def pm_fix_ends(text: str, parts: list[dict]) -> str:
    labels = [p["label"] for p in parts if p["label"]]
    if not text or len(labels) < 2:
        return text
    found = PM_ONE_BLANK.findall(text)
    if len(found) != 1 or found[0] not in (labels[0], labels[-1]):
        return text
    shown = (f"［{labels[0]}］［{labels[1]}］" if len(labels) == 2
             else f"［{labels[0]}］～［{labels[-1]}］")
    return PM_ONE_BLANK.sub(shown, text, count=1)


# Vision reads the 下線⑥ marker as a copyright sign often enough to matter. The
# substitution is only made where it is certain: the 設問 ask about ⑥, the 事例
# has no ⑥, and exactly one © stands in the prose. Three 事例 qualify; the other
# two that contain a © have their ⑥ already and the sign is really printed.
LOOKALIKE = {"⑥": "©"}


def pm_repair_markers(body: list[dict], asked: set) -> None:
    text = "".join(b["text"] for b in body)
    for mark, stand_in in LOOKALIKE.items():
        if mark not in asked or mark in text or text.count(stand_in) != 1:
            continue
        for b in body:
            if stand_in in b["text"]:
                b["text"] = b["text"].replace(stand_in, mark, 1)
                break


def build_pm(targets: list[str]) -> tuple[list, list, list]:
    root = build_dir("pm")
    answers = read_json(root / "answers.json")
    parsed = read_json(root / "parsed.json")
    expl = read_json(root / "explanations.json")
    comm = read_json(root / "commentary.json")
    figs = read_json(root / "figures.json") if (root / "figures.json").exists() else {}

    cases, questions, review = [], [], []
    for sid in targets:
        if sid not in parsed:
            continue
        for paper in pm_papers_of(sid):
            for no_s, body in sorted(parsed[sid].get(paper, {}).items(),
                                     key=lambda kv: int(kv[0])):
                no = int(no_s)
                key = answers.get(sid, {}).get(paper, {}).get(no_s, {})
                ex = expl.get(sid, {}).get(paper, {}).get(no_s, {})
                cm = comm.get(sid, {}).get(paper, {}).get(no_s, {})
                fg = figs.get(sid, {}).get(paper, {}).get(no_s, {})
                case_id = f"{sid}-{paper}-{no}"
                asked = set(re.findall(
                    r"下線\s*([①-⑳])",
                    " ".join(i.get("text", "") + " " + (i.get("lead") or "")
                             for i in body["items"])))
                pm_repair_markers(body["body"], asked)
                prose = "\n".join(b["text"] for b in body["body"]
                                   if b["kind"] in ("para", "heading"))
                # 翔泳社 is the only one of the four PDFs that names the 事例;
                # IPA's own heading is just 問N + the topic in passing.
                title = ex.get("title") or body.get("title") or f"問{no}"
                notes = []
                if not body["body"]:
                    notes.append("事例本文が空")
                if not ex.get("bySetsu"):
                    notes.append("解説なし")
                # The same OCR tells 午前 flags on: full-width latin, half-width
                # kana, ロ/口 and the rest. 午後 is 879 scanned pages of prose, so
                # it needs the review list at least as much.
                notes += [label for rx, label in SUSPECT if rx.search(prose)]
                cases.append({
                    "id": case_id, "sessionId": sid, "section": "pm",
                    "paper": paper, "no": no, "title": title,
                    "intent": key.get("intent", ""),
                    "overview": cm.get("overall", ""),
                    "overviewRate": cm.get("overallRate"),
                    "body": [{"kind": b["kind"], "text": b["text"], "page": b["page"]}
                             for b in body["body"]],
                    "figures": fg.get("figures", []),
                    "pages": body.get("pages", []),
                    "tags": tags_for(prose[:6000]),
                    "explanationSource": "情報処理教科書 安全確保支援士 読者特典",
                    "needsReview": bool(notes),
                    "source": {
                        "questionPdf": f"{sid}/{pdf_path(sid, '1問題', 'pm', paper).name}",
                        "pages": body.get("pages", []),
                    },
                })
                if notes:
                    review.append((case_id, notes, None))

                # The booklet supplies the wording, the 解答例 supplies the
                # answer; an item exists when the 解答例 has one, because that is
                # the authoritative list of what was actually asked.
                texts = {(i["setsu"], i["sub"]): i for i in body["items"]}
                for n, item in enumerate(key.get("items", []), 1):
                    setsu, sub = item["setsu"], item["sub"]
                    ask = texts.get((setsu, sub), {})
                    qid = f"{case_id}-{setsu}" + (f"-{sub}" if sub else "")
                    text, rate = pm_commentary(cm, setsu, sub)
                    inotes = list(item.get("flags", []))
                    if not ask.get("text"):
                        inotes.append("設問文が問題冊子から取れていない")
                    inotes += [label for rx, label in SUSPECT
                               if rx.search(ask.get("text", ""))]
                    # Leftover frame glyphs mean a 空欄 was not read cleanly, and
                    # the wording around it is usually damaged too.
                    asked = ask.get("text", "")
                    if re.search(r"[【】■□]", asked):
                        inotes.append("空欄の枠が読み取れていない")
                    if asked.count("［") != asked.count("］"):
                        inotes.append("空欄の括弧の数が合わない")
                    body_expl = ex.get("bySetsu", {}).get(str(setsu), {})
                    questions.append({
                        "id": qid, "sessionId": sid, "section": "pm",
                        "caseId": case_id,
                        "no": no * 100 + n,
                        "setsu": setsu, "sub": sub, "label": item["label"],
                        "text": pm_fix_ends(
                            pm_fix_range(ask.get("text", ""), item["parts"]),
                            item["parts"]),
                        "lead": ask.get("lead", ""),
                        "answerKind": item["kind"],
                        "parts": item["parts"],
                        "remarks": item.get("remarks", []),
                        "explanation": body_expl.get("explanation", ""),
                        "explanationSource": "情報処理教科書 安全確保支援士 読者特典",
                        "commentary": text,
                        "commentaryRate": rate,
                        "tags": tags_for(" ".join(
                            [ask.get("text", ""), body_expl.get("explanation", "")])),
                        "duplicateGroupId": None,
                        "needsReview": bool(inotes),
                        "source": {"page": ask.get("page"), "caseId": case_id},
                    })
                    if inotes:
                        review.append((qid, inotes, None))
    return cases, questions, review


def build(targets: list[str], sections: list[str]) -> tuple:
    meta = {s[0]: s for s in SESSIONS}
    questions, cases, review = [], [], []

    if "pm" in sections:
        cases, pm_questions, pm_review = build_pm(targets)
        questions += pm_questions
        review += pm_review

    for sec in sections:
        if SECTIONS[sec]["style"] != "choice":
            continue
        root = build_dir(sec)
        answers = read_json(root / "answers.json")
        expl = read_json(root / "explanations.json")
        parsed = read_json(root / "parsed.json")
        figs = read_json(root / "figures.json") if (root / "figures.json").exists() else {}
        known = known_chars(sec)

        for sid in targets:
            if sid not in parsed:
                continue
            odd_by_no = rare_chars(sid, sec, parsed[sid], known)
            for q in parsed[sid]:
                no = q["no"]
                qid = f"{sid}-{sec}-{no:02d}"
                ans = answers[sid][str(no)]
                ex = expl[sid][str(no)]
                fig = figs.get(sid, {}).get(str(no)) or {}
                cfigs = fig.get("choiceFigures", {})
                notes = list(q["flags"])
                odd = odd_by_no.get(str(no))
                if odd:
                    notes.append("解説に存在しない漢字: " + " ".join(odd))
                # An option is "in the drawing" when it has neither prose nor
                # a crop of its own, but the question carries artwork.
                blank = [k for k in CHOICE_KEYS
                         if not q["choices"].get(k, "").strip() and k not in cfigs]
                as_figure = bool(blank) and bool(fig.get("file"))
                if len(q["choices"]) != 4 and not as_figure:
                    notes.append(f"選択肢が{len(q['choices'])}個")
                if q["mentionsFigure"] and not fig.get("file"):
                    notes.append("図表に言及しているが画像なし")
                if ans != ex["answer"]:
                    notes.append(f"正解不一致 IPA={ans} 解説={ex['answer']}")
                questions.append({
                    "id": qid, "sessionId": sid, "section": sec, "no": no,
                    "text": q["text"],
                    "choices": [{"key": k, "text": q["choices"].get(k, "")}
                                for k in CHOICE_KEYS],
                    "answer": ans,
                    "explanation": ex["explanation"],
                    "explanationSource": "情報処理教科書 安全確保支援士 読者特典",
                    "figures": [fig["file"]] if fig.get("file") else [],
                    "choiceFigures": cfigs,
                    "tags": tags_for(q["text"] + "\n" + ex["explanation"]),
                    "duplicateGroupId": None,
                    "choicesInFigure": as_figure,
                    "needsReview": bool(notes),
                    "shortText": len(q["text"]) < 100,
                    "source": {
                        "questionPdf": f"{sid}/{pdf_path(sid, '1問題', sec).name}",
                        "page": q["pages"][0],
                        "pageImage": f"build/{sec}/pages/{sid}/{sid}-p{q['pages'][0]:03d}.png",
                    },
                })
                if notes:
                    review.append((qid, notes, q))

    order = {s: n for n, s in enumerate(SESSION_IDS)}
    used = sorted({q["sessionId"] for q in questions}, key=lambda s: order[s])
    cases.sort(key=lambda c: (order[c["sessionId"]], c["paper"], c["no"]))
    sessions = [{"id": s, "label": meta[s][1], "year": meta[s][2],
                 "term": meta[s][3], "examName": exam_name(s)} for s in used]
    questions.sort(key=lambda q: (order[q["sessionId"]], q["section"], q["no"]))
    doc = {
        "meta": {
            "generatedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "schemaVersion": SCHEMA_VERSION,
            "sessionCount": len(sessions),
            "questionCount": len(questions),
            "caseCount": len(cases),
            "sections": [section_meta(sec, questions, cases) for sec in sections],
        },
        "sessions": sessions,
        "cases": cases,
        "questions": questions,
    }
    return doc, review


def section_meta(sec: str, questions: list, cases: list) -> dict:
    info = SECTIONS[sec]
    out = {"id": sec, "label": info["label"], "count": info["count"],
           "minutes": info["minutes"], "style": info["style"],
           "questionCount": sum(1 for q in questions if q["section"] == sec)}
    if info["style"] == "written":
        # 本番モード needs the rules of the paper a 大問 came from, and those
        # changed when 午後I and 午後II were merged in 令和5年度秋期.
        used = [p for p in PM_PAPERS if any(c["paper"] == p for c in cases)]
        out["caseCount"] = sum(1 for c in cases if c["section"] == sec)
        out["papers"] = [{"id": p, "label": PM_PAPERS[p]["label"],
                          "minutes": PM_PAPERS[p]["minutes"],
                          "cases": PM_PAPERS[p]["cases"],
                          "choose": PM_PAPERS[p]["choose"]} for p in used]
    return out


def write_review(doc: dict, review: list) -> None:
    lines = ["# 要確認リスト", "",
             f"生成: {doc['meta']['generatedAt']}  /  対象 {doc['meta']['questionCount']} 問中 "
             f"{len(review)} 問", "",
             "OCR は必ず誤認識するため、下の各問はページ画像と読み比べて直すこと。",
             "画像パスは `data/` からの相対。", ""]
    for qid, notes, q in review:
        lines += [f"## {qid}", "", f"- 指摘: {' / '.join(notes)}"]
        if q is None:                       # 午後: the case carries the pages
            lines.append("")
            continue
        page = q["pages"][0]
        sid, sec = qid.split("-")[0], qid.split("-")[1]
        lines += [f"- ページ画像: `build/{sec}/pages/{sid}/{sid}-p{page:03d}.png`", "",
                  "```", q["text"], ""]
        for k in CHOICE_KEYS:
            lines.append(f"{k}  {q['choices'].get(k, '(なし)')}")
        lines += ["```", ""]
    (BUILD / "review.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  → data/build/review.md ({len(review)} 問)")


def main() -> None:
    from sclib import section_of, targets_of
    args = sys.argv[1:]
    sections = ([section_of(args)] if "--section" in args else available_sections())
    doc, review = build(targets_of(args), sections)
    write_json(DATA / "questions.json", doc)
    write_review(doc, review)
    from collections import Counter
    tc = Counter(t for q in doc["questions"] for t in q["tags"])
    for sec in doc["meta"]["sections"]:
        extra = f" / {sec['caseCount']} 事例" if sec.get("caseCount") else ""
        print(f"  {sec['label']}: {sec['questionCount']} 問{extra}")
    figs = (sum(1 for q in doc["questions"] if q.get("figures"))
            + sum(1 for c in doc["cases"] if c.get("figures")))
    print(f"\n{doc['meta']['questionCount']} 問 / {doc['meta']['sessionCount']} 回"
          f"  要確認 {len(review)} 件  図表 {figs} 件")
    print("分野タグ:", "  ".join(f"{k}={v}" for k, v in tc.most_common()))


if __name__ == "__main__":
    main()
