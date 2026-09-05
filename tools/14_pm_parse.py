#!/usr/bin/env python3
"""Stage 14 — 午後の問題冊子OCR を事例本文と設問文に組み立てる。

The booklet is laid out plainly enough to read by position:

    x≈0.12  問1…に関する次の記述を読んで、設問に答えよ。   大問の見出し
    x≈0.14  〔S サービスの概要〕                          節の見出し
    x≈0.18  段落の1行目（字下げ）
    x≈0.16  段落の続き
    x≈0.30  図1 …／表1 …                                図表のキャプション（中央）
    x≈0.13  設問1 …
    x≈0.18  （1）…

The 空欄 boxes do not survive OCR — the frame is a drawing and the letter inside
is often too small for Vision — so they are found the other way round, as a gap
between two fragments of the same line that is too wide to be spacing.  Where
the letter did come through it goes into the marker (［a］) and where it did not
the box is left empty (［　］) rather than guessed at.

    python3 tools/14_pm_parse.py [session ...]
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (PDFTOOL, PM_PAPERS, build_dir, clean, pdf_path, pm_papers_of,
                   read_json, targets_of, write_json)
import json as _json, subprocess

# A 空欄 is a drawn frame, so something is printed where it sits. A gap between
# two columns of a table, or between the parts of a diagram, is bare paper. The
# text alone cannot tell them apart, so each candidate is measured against the
# page: below this much ink the gap is white space, not a box. Calibrated on the
# 758 frames whose letter survived — 0.02 leaves all but a dozen of them (and
# those look like mis-placed rectangles) while dropping a tenth of the rest.
INK_MIN = 0.02
# A gap awaiting that measurement, held in the text until the answer comes back.
MARK_OPEN, MARK_CLOSE = "\ue000", "\ue001"
PENDING = re.compile(MARK_OPEN + r"(\d+)" + MARK_CLOSE)


def ink_of(pdf, rects: list[dict]) -> list[float]:
    """Ask the Swift tool how much of each rectangle is printed on."""
    if not rects:
        return []
    r = subprocess.run([str(PDFTOOL), "ink", str(pdf)],
                       input=_json.dumps(rects), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"pdfkit-tool ink failed: {r.stderr.strip()}")
    return _json.loads(r.stdout)

# The same known Vision misreads 午前 corrects: ロ/口, HITP for HTTP, and so on.
CORR = read_json(Path(__file__).resolve().parent / "corrections.json")
FIXES = [(re.compile(r["pattern"], re.M), r["repl"]) for r in CORR["replacements"]]


# The frame of a 空欄 is found from the gap around it, and a box whose letter
# Vision also read shows up as a gap on both sides — two boxes where one was
# printed. Nothing in these booklets sets two empty boxes side by side.
DOUBLE_BOX = re.compile(r"(?:［\s*］\s*){2,}")


def fix(s: str) -> str:
    for rx, repl in FIXES:
        s = rx.sub(repl, s)
    return DOUBLE_BOX.sub("［　］", s)

# Every booklet opens a 大問 the same way; only the tail varies — "設問に答えよ"
# in the merged 午後, "設問1～4に答えよ" in the older 午後I / 午後II, and sometimes
# it wraps onto the next line. The invariant is what comes before it.
CASE_HEAD = re.compile(r"^[問間]\s*([0-9０-９]{1,2})\s*(.*?)に関する次の記述を読んで")
SETSU = re.compile(r"^設問\s*([0-9０-９]{1,2})\s*")
# "設問1～3に答えよ。" is the tail of a 問N heading that wrapped, not a 設問 of its
# own — counted as one it closes the 大問 a page early and swallows the 事例.
SETSU_RANGE = re.compile(r"^設問\s*[0-9０-９]{1,2}\s*[〜~～ー−-]")


def is_setsu_head(row: dict) -> bool:
    t = row["text"]
    return bool(SETSU.match(t)) and not SETSU_RANGE.match(t) and row["x"] < 0.17
SUB = re.compile(r"^[（(]\s*([0-9０-９]{1,2})\s*[）)]\s*")
SECTION = re.compile(r"^[〔［\[【]")
CAPTION = re.compile(r"^([図表])\s*([0-9０-９]{1,2})\s*[^0-9０-９]")
BLANK_CHAR = re.compile(r"^[a-zA-Zあ-んア-ンα-ωΑ-Ω①-⑳]$")
# Vision reads the 空欄 frame itself as a filled square often enough to matter
# (98 times in this corpus). It is a box, so it is shown as one.
BOX_GLYPH = re.compile(r"[■□▪▫◼◻▢▣◾◽]+")

# The booklet is printed to be read from both ends: 注意事項 on the front cover
# *and* on the back. The back one falls after the last 設問, so without this the
# whole of "答案用紙は、いかなる場合でも提出してください" ends up appended to the
# last 設問文.
#
# The markers are only ones that belong to running the exam. "答案用紙" is
# deliberately not among them: 設問 say things like "答案用紙の大・中・小のいずれ
# かの文字を○で囲んで示せ", and keying on it threw away a whole page of R05秋 問4.
# A page carrying a 設問 is never dropped, whatever else is on it.
NOTICE = re.compile(r"監督員|退室可能時間|問題冊子|試験開始の合図"
                    r"|試験問題に記載されている会社名|受験番号欄")

# The rule either side of a page number is set as a dash, and Vision reads it
# as any of these. Leaving one unlisted put "- 12 =" on the end of a 設問文.
DASH = r"[-–—ー−ｰ=＝~〜_]"
PAGE_NO = re.compile(rf"^{DASH}?\s*\d{{1,3}}\s*{DASH}?$")

# Furniture: running heads, page numbers, and the sheets between 大問.
FURNITURE = [
    re.compile(r"^問題は次のページに続く"),
    re.compile(r"^このページは白紙"),
    re.compile(r"^次のページに続く"),
    # Blank sheets for working out, bound between the 大問.
    re.compile(r"^[〔［\[【（(]?\s*[メxXｘ×]モ用紙\s*[〕］\]】）)]?$"),
]

# A gap wider than this between two fragments of one line is a 空欄 box, not
# word spacing — a full-width character is about 0.021 of the text column.
BLANK_GAP = 0.030
FW = str.maketrans("０１２３４５６７８９", "0123456789")


def digits(s: str) -> int:
    return int(s.translate(FW))


# Gaps at the same x on three or more lines of a page are the rules between a
# table's columns, not 空欄 frames. 0.015 of the page width is about half a
# character, which is as far as OCR moves a column edge between rows.
COLUMN_TOL = 0.015
COLUMN_MIN = 3


def column_edges(rows: list[dict]) -> list[float]:
    """Where this page's table columns sit, from the gaps that line up."""
    xs = sorted(f["x"] for r in rows for f in r["gaps"])
    edges, run = [], []
    for x in xs:
        if run and x - run[0] > COLUMN_TOL:
            if len(run) >= COLUMN_MIN:
                edges.append(sum(run) / len(run))
            run = []
        run.append(x)
    if len(run) >= COLUMN_MIN:
        edges.append(sum(run) / len(run))
    return edges


def rows_of(page: dict, page_no: int, pending: list | None = None) -> list[dict]:
    """OCR fragments regrouped into the lines a reader would see.

    Vision emits a run of text per box, so one printed line arrives in pieces
    whenever a 空欄 frame interrupts it.  Pieces that share a baseline are put
    back together, and the space they were separated by is what betrays the box.

    Most of those spaces are not boxes, though.  A table's columns are separated
    by the same kind of gap, and there are far more tables than 空欄 in these
    booklets — 5,154 empty frames against 537 that carry a letter.  Printed as
    boxes they made the 事例 unreadable: every 設問 that says "本文中の［ ］" sent
    the reader hunting through a page of identical empty brackets.  So the gaps
    are collected first, the ones that line up down the page are taken for
    column rules, and only the rest become boxes.
    """
    lines: list[list[dict]] = []
    cur: list[dict] = []
    for f in page["lines"]:
        if not f["text"].strip():
            continue
        if cur:
            band = max(cur[-1]["h"], f["h"]) * 0.6
            if abs(f["y"] - cur[-1]["y"]) > band:
                lines.append(cur); cur = []
        cur.append(f)
    if cur:
        lines.append(cur)

    rows = []
    for frags in lines:
        frags.sort(key=lambda f: f["x"])
        gaps = []
        for i in range(1, len(frags)):
            space = frags[i]["x"] - (frags[i - 1]["x"] + frags[i - 1]["w"])
            if space > BLANK_GAP:
                gaps.append({"i": i, "x": frags[i]["x"]})
        rows.append({"frags": frags, "gaps": gaps})

    edges = column_edges(rows)
    is_column = lambda x: any(abs(x - e) <= COLUMN_TOL for e in edges)

    out: list[dict] = []
    for r in rows:
        frags, boxed = r["frags"], {g["i"] for g in r["gaps"]}
        columns = {g["i"] for g in r["gaps"] if is_column(g["x"])}
        parts = []
        just_boxed = False
        for i, f in enumerate(frags):
            body = f["text"].strip()
            if i in boxed:
                # The letter naming the box is set small and centred inside it,
                # so the frame shows up as a gap on *both* sides; emitting a box
                # for the trailing one too would double every blank.
                if BLANK_CHAR.match(body):
                    parts.append(f"［{body}］")
                    just_boxed = True
                    continue
                if i in columns:
                    parts.append(" ")          # a column rule, not a 空欄
                elif not just_boxed:
                    if pending is None:
                        parts.append("［　］")
                    else:
                        # Held until the page says whether anything is printed
                        # in the gap.
                        pending.append({
                            "page": page_no, "x": frags[i - 1]["x"] + frags[i - 1]["w"],
                            "y": max(0.0, min(f["y"] for f in frags)
                                     - (max(f["y"] + f["h"] for f in frags)
                                        - min(f["y"] for f in frags)) * 0.6),
                            "w": frags[i]["x"] - (frags[i - 1]["x"] + frags[i - 1]["w"]),
                            "h": (max(f["y"] + f["h"] for f in frags)
                                  - min(f["y"] for f in frags)) * 2.2,
                        })
                        parts.append(f"{MARK_OPEN}{len(pending) - 1}{MARK_CLOSE}")
            just_boxed = False
            parts.append(body)
        text = BOX_GLYPH.sub("［　］", fix(clean("".join(parts))))
        if not text:
            continue
        # The row's own frame is kept: stage 15 crops 図表 by the box the lines
        # around a caption occupy, and nothing else knows where the drawing on
        # the page actually is.
        out.append({"x": frags[0]["x"], "y": min(f["y"] for f in frags),
                    "w": max(f["x"] + f["w"] for f in frags) - frags[0]["x"],
                    "h": max(f["y"] + f["h"] for f in frags)
                         - min(f["y"] for f in frags),
                    "page": page_no, "text": text})
    return out


def load_rows(sid: str, paper: str) -> list[dict]:
    path = build_dir("pm") / "ocr" / f"{sid}-{paper}.json"
    pages = json.loads(path.read_text(encoding="utf-8"))
    pending: list[dict] = []
    rows: list[dict] = []
    for n, page in enumerate(pages, 1):
        got = rows_of(page, n, pending)
        if (sum(1 for r in got if NOTICE.search(r["text"])) >= 2
                and not any(is_setsu_head(r) for r in got)):
            continue                       # 注意事項のページ（表紙・裏表紙）
        for r in got:
            # The page number sits in the bottom margin on every sheet. Anchor
            # on that: a bare number elsewhere on the page is content.
            if r["y"] > 0.88 and PAGE_NO.match(r["text"]):
                continue
            if any(p.match(r["text"]) for p in FURNITURE):
                continue
            rows.append(r)

    # One question to the page for every gap in the booklet, then each held
    # marker becomes a box or a space.
    inked = ink_of(pdf_path(sid, "1問題", "pm", paper), pending)
    for r in rows:
        r["text"] = fix(PENDING.sub(
            lambda m: "［　］" if inked[int(m.group(1))] >= INK_MIN else " ",
            r["text"]))
    return [r for r in rows if r["text"].strip()]


def split_cases(rows: list[dict], want: int) -> list[tuple[int, str, list[dict]]]:
    starts = [(i, CASE_HEAD.match(r["text"]))
              for i, r in enumerate(rows) if CASE_HEAD.match(r["text"])]
    if len(starts) == want:
        cases = []
        for k, (i, m) in enumerate(starts):
            end = starts[k + 1][0] if k + 1 < len(starts) else len(rows)
            cases.append((digits(m.group(1)), clean(m.group(2)), rows[i + 1:end]))
        return cases
    return split_by_setsu(rows, want)


# Two 設問 of one 大問 are never more than a page or two apart; the gap to the
# next 大問's block is the rest of a case study.
SETSU_GAP = 2


def split_by_setsu(rows: list[dict], want: int) -> list[tuple[int, str, list[dict]]]:
    """Split on the 設問 blocks when the 問N headings are not in the scan.

    Nine of the older booklets were scanned with the top margin cropped off,
    which took the "問1 …に関する次の記述を読んで" line with it — it is not in the
    PDF at all, so nothing can read it back.  Some of those scans lost the first
    line of a 設問 block the same way, so the split cannot key on 設問1 either.

    What survives is that every 大問 closes with a run of 設問 lines and IPA
    always starts the next one on a fresh page.  So the runs are found by the
    page gap between 設問 lines, the 事例 is what precedes its own run, and the
    title comes from the 教科書解説, which names every 大問 anyway.
    """
    marks = [i for i, r in enumerate(rows) if is_setsu_head(r)]
    if not marks:
        return []
    runs = [[marks[0]]]
    for i in marks[1:]:
        if rows[i]["page"] - rows[runs[-1][-1]]["page"] > SETSU_GAP:
            runs.append([i])
        else:
            runs[-1].append(i)
    if len(runs) != want:
        return []

    cases, body_from = [], 0
    for k, run in enumerate(runs):
        last_page = rows[run[-1]]["page"]
        nxt = runs[k + 1][0] if k + 1 < len(runs) else len(rows)
        end = nxt
        for j in range(run[0], nxt):
            if rows[j]["page"] > last_page:
                end = j
                break
        cases.append((k + 1, "", rows[body_from:end]))
        body_from = end
    return cases


def base_indent(rows: list[dict]) -> float:
    """The left edge of running text, as the most common one."""
    xs = sorted(round(r["x"], 2) for r in rows)
    if not xs:
        return 0.16
    best, run, cur, prev = xs[0], 0, 0, None
    for x in xs:
        cur = cur + 1 if x == prev else 1
        if cur > run:
            run, best = cur, x
        prev = x
    return best


# Two or more empty boxes on one line are the gaps between a table's columns,
# not blanks to fill in: prose never has that many.
COLUMNS = re.compile(r"(?:［　］.*){2,}")
EMPTY_BOX = re.compile(r"［\s*］")


def drop_layout_boxes(text: str) -> str:
    """Empty boxes that are really the spacing of a diagram or a table row.

    A 設問 points at one 空欄 at a time, so a line of the 事例 carrying two or
    more unlabelled frames is laying out a drawing — "サーバ［ ］サーバ［ ］サーバ"
    is the row of boxes in a network diagram, not three things to fill in. Left
    in, they are indistinguishable from the blank the 設問 is asking about.
    Labelled frames (［c］) are never touched.
    """
    return EMPTY_BOX.sub(" ", text) if len(EMPTY_BOX.findall(text)) >= 2 else text


def build_body(rows: list[dict]) -> list[dict]:
    """Prose, headings and captions, with everything inside a 図/表 set apart.

    A 図 or 表 breaks the left margin the whole page otherwise keeps, so the
    parse runs as a small state machine: a caption or a row carrying column gaps
    opens a drawing, and the next properly indented paragraph closes it.  Cell
    text that drifted back to the paragraph indent would otherwise be glued into
    the sentence above it, which is how a table ends up mid-paragraph.
    """
    base = base_indent(rows)
    out: list[dict] = []
    in_figure = False
    for r in rows:
        text, x = r["text"], r["x"]
        caption = bool(CAPTION.match(text)) and x > base + 0.04
        opens = caption or bool(COLUMNS.match(text))
        indented = base + 0.012 <= x <= base + 0.045
        if opens:
            in_figure = True
        elif in_figure and indented and "［　］" not in text:
            in_figure = False

        if caption:
            kind = "caption"
        elif in_figure:
            kind = "figure"
        elif SECTION.match(text) and x <= base + 0.01:
            kind = "heading"
        elif indented or x > base + 0.045:
            kind = "para"
        elif (out and out[-1]["kind"] == "para"
              and out[-1]["page"] == r["page"]):
            # Not across a page break. A paragraph does continue over one, but
            # merging there throws away the geometry of everything on the new
            # page, and stage 15 needs it: 図4 of 令7秋 問2 is printed at the top
            # of a page with its caption below, and its rows had been swallowed
            # by the paragraph that ended the page before.
            prev = out[-1]
            prev["text"] += text
            # How many printed lines went into this paragraph. Stage 15 uses it
            # to tell a wrapped sentence from a line of a listing: prose wraps,
            # a 図's labels and a code block's lines each stand alone.
            prev["lines"] = prev.get("lines", 1) + 1
            # Keep the block's real extent. Without this a paragraph's frame is
            # its first line's, and a 図 cropped from those rows comes out cut
            # off down the left-hand side.
            left = min(prev["x"], x)
            right = max(prev["x"] + prev["w"], x + r.get("w", 0))
            prev["w"] = round(right - left, 4)
            prev["x"] = round(left, 3)
            prev["h"] = round(max(prev["y"] + prev["h"],
                                  r["y"] + r.get("h", 0)) - prev["y"], 4)
            continue
        else:
            kind = "figure"
        out.append({"kind": kind, "text": text, "page": r["page"], "lines": 1,
                    "x": round(x, 3), "y": round(r["y"], 4),
                    "w": round(r.get("w", 0), 4), "h": round(r.get("h", 0), 4)})
    # Corrections are applied per row as it is read, but a pattern that straddles
    # a line break ("施" ending one line, "弱" opening the next) only becomes
    # visible once the paragraph is joined.
    return [dict(b, text=drop_layout_boxes(fix(clean(b["text"]))))
            for b in out if clean(b["text"])]


# A 解答群 is printed as a lettered list, often in two or three columns, and it
# arrives as one unbroken run: "解答群アシステム運用担当者イシステム運用担当者と
# システム開発者ウ…". Unreadable. The markers run in a fixed order, which is what
# makes them findable: each is searched for only after the one before it.
GROUP_MARKS = "アイウエオカキクケコサシスセソタチツテト"
# Kanji and kana Vision returns in place of a marker.
MARK_ALIAS = {"エ": "工", "オ": "才", "カ": "力", "ロ": "口", "ニ": "二",
              "タ": "夕", "ハ": "八", "ト": "卜", "ク": "ワ"}
GROUP_HEAD = re.compile(r"解答群")


def format_group(text: str) -> str:
    """Put each choice of a 解答群 on its own line.

    The word appears twice: once in the question ("解答群の中から選び") and again
    as the heading of the list itself. The heading is the later one, so the
    occurrences are tried from the back, and one is only accepted when what
    follows it really is a list — three markers in order, opening promptly, with
    no question wording in between.
    """
    for i in reversed([m.start() for m in re.finditer("解答群", text)]):
        head, body = text[:i], text[i + len("解答群"):]
        hits: list[tuple[int, str]] = []
        pos = 0
        for mark in GROUP_MARKS:
            alts = [mark] + ([MARK_ALIAS[mark]] if mark in MARK_ALIAS else [])
            at = min((body.find(a, pos) for a in alts if body.find(a, pos) >= 0),
                     default=-1)
            if at < 0:
                break
            hits.append((at, mark))
            pos = at + 1
        if len(hits) < 3:
            continue
        # What sits between the heading and ア is the list's own column header
        # ("記号 第1引数 第2引数"), never more of the question.
        lead = body[:hits[0][0]]
        if len(lead) > 30 or re.search(r"答えよ|選び|述べよ|入れる", lead):
            continue
        items = []
        for k, (at, mark) in enumerate(hits):
            end = hits[k + 1][0] if k + 1 < len(hits) else len(body)
            # The gaps between the list's columns come through as empty boxes.
            seg = clean(body[at + 1:end].replace("［　］", " ").replace("［ ］", " "))
            if len(seg) < 2:
                items = []
                break                      # a marker matched inside a word
            items.append(f"{mark} {seg}")
        if not items:
            continue
        return "\n".join([clean(head), "解答群" + (" " + clean(lead) if lead.strip() else "")]
                         + items)
    return text


def widen_cut(rows: list[dict], cut: int) -> int:
    """Take in the 小問 that sit above the first surviving 設問 heading.

    Nine of the older booklets lost their top margin to the scan, and with it
    the "設問1" line.  Its (1)(2)… then read as part of the 事例 and their
    wording was dropped.  They are recognisable by where they start: a 設問's
    小問 are indented further than the 事例's own lists — 0.135 against 0.086 in
    平成28年春 — so the indent used by the 小問 *after* the heading says which
    rows above it belong to the block. Only the same page is considered, since
    IPA always starts the 設問 on a fresh one.
    """
    subs = [r["x"] for r in rows[cut:] if SUB.match(r["text"])]
    if not subs or cut == 0:
        return cut
    indent = min(subs)
    page = rows[cut]["page"]
    i = cut
    while i > 0:
        r = rows[i - 1]
        if r["page"] != page or r["x"] < indent - 0.02:
            break
        i -= 1
    return i


def build_items(rows: list[dict]) -> list[dict]:
    items: list[dict] = []
    setsu = 0
    for r in rows:
        text = r["text"]
        if SETSU_RANGE.match(text):
            continue
        m = SETSU.match(text)
        if m:
            setsu = digits(m.group(1))
            rest = text[m.end():].strip()
            m2 = SUB.match(rest)
            items.append({"setsu": setsu,
                          "sub": digits(m2.group(1)) if m2 else None,
                          "text": rest[m2.end():].strip() if m2 else rest,
                          "page": r["page"], "lead": "" if m2 else None})
            continue
        m2 = SUB.match(text)
        if m2 and not setsu:
            # The 設問 block opens with (1) because the "設問1" line above it was
            # cropped off with the top margin — nine of the older booklets were
            # scanned that way. The 小問 before the first surviving 設問 heading
            # belong to 設問1; dropping them lost 54 設問文.
            setsu = 1
        if m2 and setsu:
            # A 設問 that opens with a preamble ("〔…〕について答えよ。") keeps it
            # as the lead-in every one of its 小問 is read under.
            lead = ""
            if items and items[-1]["setsu"] == setsu and items[-1]["sub"] is None:
                lead = items.pop()["text"]
            elif items and items[-1]["setsu"] == setsu:
                lead = items[-1].get("lead") or ""
            items.append({"setsu": setsu, "sub": digits(m2.group(1)),
                          "text": text[m2.end():].strip(), "page": r["page"],
                          "lead": lead})
            continue
        if items:
            items[-1]["text"] += text
    for it in items:
        it["text"] = format_group(fix(clean(it["text"])))
        it["lead"] = fix(clean(it.get("lead") or ""))
    return [i for i in items if i["text"]]


def parse_paper(sid: str, paper: str) -> dict:
    rows = load_rows(sid, paper)
    cases = {}
    for no, title, body_rows in split_cases(rows, PM_PAPERS[paper]["cases"]):
        cut = next((i for i, r in enumerate(body_rows) if is_setsu_head(r)),
                   len(body_rows))
        cut = widen_cut(body_rows, cut)
        pages = sorted({r["page"] for r in body_rows})
        cases[str(no)] = {
            "no": no, "paper": paper, "title": title,
            "pages": [pages[0], pages[-1]] if pages else [],
            "body": build_body(body_rows[:cut]),
            "items": build_items(body_rows[cut:]),
        }
    return cases


def main() -> None:
    targets = targets_of(sys.argv[1:])
    answers = read_json(build_dir("pm") / "answers.json")
    out, bad, note = {}, [], []
    for sid in targets:
        out[sid] = {}
        for paper in pm_papers_of(sid):
            if not (build_dir("pm") / "ocr" / f"{sid}-{paper}.json").exists():
                bad.append(f"{sid}/{paper}: OCR結果がない（03_ocr.py --section pm）")
                continue
            cases = parse_paper(sid, paper)
            want = PM_PAPERS[paper]["cases"]
            if len(cases) != want:
                bad.append(f"{sid}/{paper}: 大問 {len(cases)}/{want}")
            chars = 0
            for no, c in cases.items():
                chars += sum(len(b["text"]) for b in c["body"])
                if not c["body"]:
                    bad.append(f"{sid}/{paper} 問{no}: 本文が空")
                # The answer key already knows every 設問 this 大問 has; anything
                # it lists that the booklet parse did not find is a real gap.
                key = answers.get(sid, {}).get(paper, {}).get(no)
                if key:
                    want_ids = {(i["setsu"], i["sub"]) for i in key["items"]}
                    got_ids = {(i["setsu"], i["sub"]) for i in c["items"]}
                    # sub is None for a 設問 with no 小問; sort on that too.
                    missing = sorted(want_ids - got_ids,
                                     key=lambda x: (x[0], x[1] or 0))
                    if missing:
                        note.append(f"{sid}/{paper} 問{no}: 設問文が取れない "
                                    + " ".join(f"設問{a}({b})" if b else f"設問{a}"
                                               for a, b in missing))
            out[sid][paper] = cases
            n_items = sum(len(c["items"]) for c in cases.values())
            n_fig = sum(1 for c in cases.values() for b in c["body"]
                        if b["kind"] == "caption")
            print(f"{sid:9} {PM_PAPERS[paper]['label']:5} 大問{len(cases)}  "
                  f"本文{chars//1000:3}千字  設問文{n_items:3}  図表{n_fig:3}")
    for x in note[:15]:
        print("  *", x)
    if len(note) > 15:
        print(f"  * …ほか {len(note) - 15} 件")
    for b in bad:
        print("  !", b)
    path = build_dir("pm") / "parsed.json"
    merged = read_json(path) if path.exists() else {}
    merged.update(out)
    write_json(path, merged)
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
