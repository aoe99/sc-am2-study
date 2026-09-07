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
between two fragments of the same line that is too wide to be spacing.  Each of
those is then rendered on its own at 600dpi and read again, and the letter is
taken only when the 解答例 of that 大問 has exactly one label it could be.  A
frame nothing certain can be said about is left empty (［　］) rather than
guessed at.

    python3 tools/14_pm_parse.py [session ...]
"""
from __future__ import annotations
import json, re, sys, unicodedata
from collections import Counter
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


def grown(r: dict, up: float, tall: float) -> dict:
    """A gap's rectangle opened out to take in the frame drawn around it.

    A 空欄 frame stands taller than the line of text it sits in, so the gap
    between two runs of OCR — which is only as tall as the text — has to be
    grown before either the ink or the letter inside can be looked at.
    """
    return {"page": r["page"], "x": r["x"], "w": r["w"],
            "y": max(0.0, r["y"] - r["h"] * up), "h": r["h"] * tall}


def ink_of(pdf, rects: list[dict]) -> list[float]:
    """Ask the Swift tool how much of each rectangle is printed on."""
    if not rects:
        return []
    r = subprocess.run([str(PDFTOOL), "ink", str(pdf)],
                       input=_json.dumps([grown(x, 0.6, 2.2) for x in rects]),
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"pdfkit-tool ink failed: {r.stderr.strip()}")
    return _json.loads(r.stdout)


# The letter naming a 空欄 is set inside the frame at about half the size of the
# body text. Read as part of a whole page it is lost more often than not — 994
# frames came back empty against 589 that kept their letter — so each frame is
# read again on its own, at 600dpi instead of 400.
FRAME_DPI = 600
# How far above and below the line to reach for the frame, as a multiple of the
# line's own height. Read three times: the crops see different letters, and
# putting all of the readings in front of the label test finds a fifth more
# frames than one alone without costing it any of its accuracy (97% either way,
# 63% of the legible frames recovered with one crop against 78% with three).
FRAME_CROPS = [0.2, 0.5, 0.8]


def frame_text(pdf, rects: list[dict]) -> list[list[list[str]]]:
    """What was read in each gap: one list of single-character readings per run
    of glyphs found in it, left to right.

    A gap is not always one frame. "［f］は［g］" is a single run of text that the
    page OCR lost whole, so it comes back as three runs in one rectangle and has
    to stay three. Runs at the same place in the two crops are the same glyph,
    and their readings are pooled.
    """
    passes = []
    for up in FRAME_CROPS:
        if not rects:
            return [[] for _ in rects]
        r = subprocess.run([str(PDFTOOL), "rectocr", str(pdf), "--dpi", str(FRAME_DPI)],
                           input=_json.dumps([grown(x, up, 1 + 2 * up) for x in rects]),
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"pdfkit-tool rectocr failed: {r.stderr.strip()}")
        passes.append(_json.loads(r.stdout))

    out: list[list[list[str]]] = []
    for i in range(len(rects)):
        runs: list[dict] = []
        for got in passes:
            for sp in got[i]["spans"]:
                seen = [norm_label(c.strip()) for c in sp["alts"]
                        if len(c.strip()) == 1]
                if not seen:
                    continue
                mid = sp["x"] + sp["w"] / 2
                same = next((g for g in runs
                             if g["x"] <= mid <= g["x"] + g["w"]), None)
                if same is None:
                    runs.append({"x": sp["x"], "w": sp["w"], "alts": seen})
                else:
                    same["alts"] += [c for c in seen if c not in same["alts"]]
        out.append([g["alts"] for g in sorted(runs, key=lambda g: g["x"])])
    return out


def norm_label(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()

# The same known Vision misreads 午前 corrects: ロ/口, HITP for HTTP, and so on.
CORR = read_json(Path(__file__).resolve().parent / "corrections.json")
FIXES = [(re.compile(r["pattern"], re.M), r["repl"]) for r in CORR["replacements"]]


# The frame of a 空欄 is found from the gap around it, and a box whose letter
# Vision also read shows up as a gap on both sides — two boxes where one was
# printed. Nothing in these booklets sets two empty boxes side by side.
DOUBLE_BOX = re.compile(r"(?:［\s*］\s*){2,}")


# IPA typesets 読点 as "，"; Vision reads most of them as "、".  What settles it
# is that the 解答例 and 採点講評 PDFs of these same booklets have a text layer —
# no OCR — and use "，" 1,604 times and "、" not once.  tesseract independently
# reads them as comma glyphs too.  04_parse does the same for 午前, where the
# corpus now has no "、" at all; the 午後 path never picked it up.  The 教科書解説
# is 翔泳社's own text layer and genuinely mixes both, so it is left alone.
PUNCT = str.maketrans({"、": "，", "､": "，", "｡": "。"})


def fix(s: str) -> str:
    s = s.translate(PUNCT)
    for rx, repl in FIXES:
        s = rx.sub(repl, s)
    return DOUBLE_BOX.sub("［　］", s)

# Every booklet opens a 大問 the same way; only the tail varies — "設問に答えよ"
# in the merged 午後, "設問1～4に答えよ" in the older 午後I / 午後II, and sometimes
# it wraps onto the next line. The invariant is what comes before it.
CASE_HEAD = re.compile(r"^[問間]\s*([0-9０-９]{1,2})\s*(.*?)に関する次の記述を読んで")
CASE_OPEN = re.compile(r"^[問間]\s*[0-9０-９]{1,2}\s*\S")
SETSU = re.compile(r"^設問\s*([0-9０-９]{1,2})\s*")
# "設問1～3に答えよ。" is the tail of a 問N heading that wrapped, not a 設問 of its
# own — counted as one it closes the 大問 a page early and swallows the 事例.
SETSU_RANGE = re.compile(r"^設問\s*[0-9０-９]{1,2}\s*[〜~～ー−-]")


def is_setsu_head(row: dict) -> bool:
    t = row["text"]
    return bool(SETSU.match(t)) and not SETSU_RANGE.match(t) and row["x"] < 0.17
# The 小問 number, as the scan hands it over. The closing paren is sometimes
# lost, "1" comes back as "I", and a circled ① stands in for (1) or for the
# whole "(4)" — 5 設問文 across the corpus were dropped for one of those. A
# number with neither its closing paren nor a space after it is prose.
SUB_N = r"(?:[0-9０-９]{1,2}|[IlＩｌ]|[①-⑳])"
SUB = re.compile(rf"^(?:[（(]\s*({SUB_N})\s*(?:[）)]|(?=\s))|([①-⑳])\s*[）)])\s*")
CIRCLED = {chr(0x2460 + i): i + 1 for i in range(20)}


def sub_no(m: re.Match) -> int:
    """The 小問 number a SUB match found, however it was printed."""
    s = m.group(1) or m.group(2)
    return CIRCLED.get(s) or (1 if s in "IlＩｌ" else digits(s))
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


# A 空欄 at the very start of a printed line has no fragment before it, so there
# is no gap between two runs to find it by. What gives it away is the indent:
# the line starts further in than the line above it, and the frame is what fills
# the difference. Most such lines are nothing of the kind — every 会話 wraps to a
# hanging indent — so these are inferred rather than seen, and unlike the other
# frames they only become a 空欄 when the ink test says something is printed
# there and exactly one letter is read out of it.
EDGE_MIN = 0.04
INDENT_TOL = 0.012


def indents(rows: list[dict]) -> list[float]:
    """The left edges this page sets text at, as the ones it uses twice."""
    seen = Counter(round(min(f["x"] for f in r["frags"]) / 0.005) * 0.005
                   for r in rows)
    return sorted(x for x, n in seen.items() if n >= 2)


def base_of(rows: list[dict]) -> float:
    """The left edge this page sets most of its text at."""
    seen = Counter(round(min(f["x"] for f in r["frags"]) / 0.005) * 0.005
                   for r in rows)
    return seen.most_common(1)[0][0] if seen else 0.0


# Japanese is justified to the measure, so a line of prose that stops short of
# it and is not the end of its paragraph is being held short by something, and
# in these booklets that is a 空欄 frame. Only prose: a table's rows and a
# drawing's labels stop wherever their cell does, which is why the line and the
# one under it must both be free of column gaps and sit at the page's own
# indent. And not after a 。 or a latin word, where the short end is the line
# breaking of its own accord.
TAIL_STOP = re.compile(r"[。．.、，,]$|[0-9A-Za-z]$")


def rows_of(page: dict, page_no: int, pending: list | None = None,
            edges: set | None = None) -> list[dict]:
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

    rules = column_edges(rows)
    is_column = lambda x: any(abs(x - e) <= COLUMN_TOL for e in rules)
    cols = indents(rows)
    measure = max((max(f["x"] + f["w"] for f in r["frags"]) for r in rows),
                  default=1.0)

    out: list[dict] = []
    for n_row, r in enumerate(rows):
        frags, boxed = r["frags"], {g["i"] for g in r["gaps"]}
        columns = {g["i"] for g in r["gaps"] if is_column(g["x"])}
        parts = []
        # A frame holding the line in from the left, if the indent says so.
        x0 = frags[0]["x"]
        base = base_of(rows)
        right = max(f["x"] + f["w"] for f in frags)
        above = rows[n_row - 1]["frags"] if n_row else []
        left = min((f["x"] for f in above), default=x0)
        # A line set in the middle of the measure — a caption, a page number —
        # is short at both ends because it is centred, not because a frame is
        # holding it in from the left.
        centred = abs((x0 - left) - (measure - right)) < 0.06
        # Lines that open something of their own are set where they are for a
        # reason, and a marker in front of them would hide what they open.
        raw = "".join(f["text"] for f in frags).strip()
        prev_raw = "".join(f["text"] for f in above).strip()
        opens = (CAPTION.match(raw) or SETSU.match(raw) or SUB.match(raw)
                 or CASE_HEAD.match(raw) or SECTION.match(raw)
                 # A 大問 heading that wraps: the line under it finishes
                 # "…に関する次の記述を読んで", and a marker in front of it hides
                 # the join that puts the heading back together.
                 or CASE_OPEN.match(prev_raw))
        if (pending is not None and edges is not None and n_row > 0
                and not centred and not opens
                and x0 - left >= EDGE_MIN):
            # The frame runs from where the line would have started — the left
            # edge of the line above, which is in the same block — to where it
            # actually does.
            top = min(f["y"] for f in frags)
            pending.append({"page": page_no, "x": left, "y": top,
                            "w": x0 - left,
                            "h": max(f["y"] + f["h"] for f in frags) - top})
            edges.add(len(pending) - 1)
            parts.append(f"{MARK_OPEN}{len(pending) - 1}{MARK_CLOSE}")
        just_boxed = False
        tail = None
        nxt = rows[n_row + 1] if n_row + 1 < len(rows) else None
        nxt_cols = ({g["i"] for g in nxt["gaps"] if is_column(g["x"])}
                    if nxt else set())
        # Prose, but a line of prose may still carry a 空欄 of its own: 平30春
        # 午後I 問1 sets "アドレス［c］番地に値［d］を" and the scan lost the tail
        # from ［d］ on, so the row has one gap and still stops short. What must
        # not be there is a *column rule* — that is a table, and a table's cells
        # end where they end.
        if (pending is not None and edges is not None and nxt
                and not columns and not nxt_cols
                and abs(x0 - base) <= INDENT_TOL
                and abs(min(f["x"] for f in nxt["frags"]) - base) <= INDENT_TOL
                and measure - right >= EDGE_MIN
                and not TAIL_STOP.search(raw)):
            top = min(f["y"] for f in frags)
            pending.append({"page": page_no, "x": right, "y": top,
                            "w": measure - right,
                            "h": max(f["y"] + f["h"] for f in frags) - top})
            edges.add(len(pending) - 1)
            tail = f"{MARK_OPEN}{len(pending) - 1}{MARK_CLOSE}"
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
                        top = min(g["y"] for g in frags)
                        pending.append({
                            "page": page_no,
                            "x": frags[i - 1]["x"] + frags[i - 1]["w"],
                            "y": top,
                            "w": frags[i]["x"] - (frags[i - 1]["x"] + frags[i - 1]["w"]),
                            "h": max(g["y"] + g["h"] for g in frags) - top,
                        })
                        parts.append(f"{MARK_OPEN}{len(pending) - 1}{MARK_CLOSE}")
            just_boxed = False
            parts.append(body)
        if tail:
            parts.append(tail)
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


def load_rows(sid: str, paper: str) -> tuple[list[dict], dict, set]:
    path = build_dir("pm") / "ocr" / f"{sid}-{paper}.json"
    pages = json.loads(path.read_text(encoding="utf-8"))
    pending: list[dict] = []
    edges: set[int] = set()
    rows: list[dict] = []
    for n, page in enumerate(pages, 1):
        got = rows_of(page, n, pending, edges)
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

    # One question to the page for every gap in the booklet: a gap with nothing
    # printed in it is white paper, not a frame, and becomes a space.
    pdf = pdf_path(sid, "1問題", "pm", paper)
    inked = ink_of(pdf, pending)
    frames = [i for i, v in enumerate(inked) if v >= INK_MIN]
    for r in rows:
        r["text"] = fix(PENDING.sub(
            lambda m: m.group(0) if inked[int(m.group(1))] >= INK_MIN else " ",
            r["text"]))
    # The frames that are left keep their marker until the 大問 they belong to
    # is known: which letters it can be naming is what tells a reading apart
    # from a misreading.
    read = dict(zip(frames, frame_text(pdf, [pending[i] for i in frames])))
    return [r for r in rows if r["text"].strip()], read, edges & set(frames)


# The letter in a frame is set at half the size of the body text, and at 200dpi
# 1/l/i, 9/g, 6/b, 0/o and 5/s are the same handful of pixels. Reading digits as
# letters everywhere costs more than it gains — measured at 97%→96% — so it is
# done only for a label the 大問 asks for and the 事例 does not have anywhere
# else, and only when the digit is the *first* reading and just one letter fits.
DIGIT_LOOKS = {"1": "li", "9": "g", "6": "b", "0": "o", "5": "s"}
BOXED_LETTER = re.compile(r"［([^］\s])］")


def resolve_frames(rows: list[dict], read: dict, edges: set, labels: set) -> None:
    """Give each 空欄 frame the label it holds, where that is beyond doubt.

    A frame is read as up to three single characters, and the 解答例 says which
    labels this 大問 has. Exactly one of the readings being one of those labels
    is the whole test: it is what separates an "a" from the "α" of the drawing
    beside it, and 0 or 2 matches means the frame stays empty rather than
    labelled wrongly. On the frames whose letter was legible on the page scan
    this picks the right one 97% of the time.
    """
    by = {norm_label(l): l for l in labels}

    def one(m: re.Match) -> str:
        at = int(m.group(1))
        runs = read.get(at, [])
        boxes, other = [], []
        for alts in runs:
            hits = [by[c] for c in alts if c in by]
            if len(hits) == 1:
                boxes.append(f"［{hits[0]}］")
            else:
                other.append(min(alts, key=len) if alts else "")
        # A frame only the measure spoke for stands or falls on what is in it.
        if at in edges:
            if len(boxes) == 1:
                return boxes[0]
            # Two is usually the crop catching the prose beside it — but a line
            # can open with a pair: 令7春 問2 sets "，［f］や［g］だった。" and the
            # scan lost the whole run, frames and connector alike. That case has
            # nothing in the rect but the labels and a one-character connector.
            if (len(boxes) >= 2 and len(set(boxes)) == len(boxes)
                    and len(runs) <= 4 and all(len(o) <= 2 for o in other)):
                return "".join(boxes)
            return ""
        return "".join(boxes) if boxes else "［　］"

    # What the ordinary reading finds, counting the letters the page scan itself
    # got. A fold is only ever allowed to supply a label that is nowhere else.
    found = set(BOXED_LETTER.findall("\n".join(r["text"] for r in rows)))
    for r in rows:
        for m in PENDING.finditer(r["text"]):
            found.update(BOXED_LETTER.findall(one(m)))
    missing = {l for l in labels if len(l) == 1 and l not in found}

    def sub(m: re.Match) -> str:
        got = one(m)
        if got not in ("", "［　］") or not missing:
            return got
        at = int(m.group(1))
        runs = read.get(at, [])
        if len(runs) != 1 or not runs[0] or any(c in by for c in runs[0]):
            return got
        hits = {by[t] for t in DIGIT_LOOKS.get(runs[0][0], "")
                if t in by and by[t] in missing}
        if len(hits) != 1:
            return got
        lab = hits.pop()
        missing.discard(lab)
        return f"［{lab}］"

    for r in rows:
        r["text"] = PENDING.sub(sub, r["text"])


def join_wrapped_heads(rows: list[dict]) -> list[dict]:
    """Put a 大問 heading that ran onto a second line back together.

    "問1 Webアプリケーションプログラム開発のセキュリティ対策に関する次の記述を読ん"
    breaks mid-word before "で、設問1～3に答えよ。", and the heading is what names
    the 大問 and says where its 事例 begins.  Two rows are only ever joined when
    the join is itself a heading, so nothing else in the booklet is touched.
    """
    out: list[dict] = []
    skip = False
    for i, r in enumerate(rows):
        if skip:
            skip = False
            continue
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        joined = PENDING.sub("", r["text"] + nxt["text"]) if nxt else ""
        if (nxt and not CASE_HEAD.match(r["text"]) and CASE_HEAD.match(joined)):
            r = dict(r, text=joined)
            skip = True
        out.append(r)
    return out


def split_cases(rows: list[dict], want: int) -> list[tuple[int, str, list[dict]]]:
    rows = join_wrapped_heads(rows)
    starts = [(i, CASE_HEAD.match(r["text"]))
              for i, r in enumerate(rows) if CASE_HEAD.match(r["text"])]
    if len(starts) == want:
        cases = []
        for k, (i, m) in enumerate(starts):
            end = starts[k + 1][0] if k + 1 < len(starts) else len(rows)
            cases.append((digits(m.group(1)), clean(m.group(2)), rows[i + 1:end]))
        return cases
    # Every booklet's 問N headings are in the scan; a count that does not match
    # is a parse that has gone wrong, and main() says so rather than guessing
    # the boundaries from somewhere else.
    return []


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


# Body copy runs the full measure and wraps; a drawing's labels and a table's
# cells stop where their frame does.
PROSE_W = 0.60
# Running text starts at the margin or one indent in. A drawing puts its labels
# wherever its frame does, which is anywhere else.
PROSE_INDENTS = (0.0, 0.02)
INDENT_EPS = 0.012
# The end of a sentence. A line at the margin that stops short of the measure
# is either the last line of a paragraph or a label inside a drawing; the full
# stop is what tells them apart.
SENTENCE_END = re.compile(r"[。．]\s*$")


def is_prose(row: dict) -> bool:
    """Body copy: it wrapped across lines *and* runs the full column width."""
    return row.get("lines", 1) > 1 and row.get("w", 0) > PROSE_W


# Telling running text from a drawing's labels by where the line starts only
# works when the 事例 has one margin, and plenty have three: 平30春 午後I 問1 sets
# its C++ listing at 0.115, its paragraphs at 0.15 and the continuation lines of
# its 会話 at 0.23, and the most common of those is not the text margin. So the
# line is read instead of measured. A drawing's labels come back with the gaps
# between their cells still in them; Japanese running text is set solid, and the
# only spaces in it are the ones around Latin words.
INNER_GAP = re.compile(r"(?<![0-9A-Za-z（(）)])\s(?![0-9A-Za-z（(）)])|\s{2,}")
JA_CHAR = re.compile(r"[ぁ-んァ-ヶ一-鿿]")
PROSE_MIN_LEN = 12
PROSE_MIN_JA = 8


def looks_prose(text: str) -> bool:
    """Running text — no cell gaps, and long enough to be a sentence."""
    text = text.strip()
    if len(text) < PROSE_MIN_LEN or INNER_GAP.search(text):
        return False
    return len(JA_CHAR.findall(text)) >= PROSE_MIN_JA


def mark_drawings(body: list[dict], base: float) -> None:
    """Set "figure" on the rows a 図 or 表 prints inside itself.

    Stage 15 crops the drawing and the app shows the picture, so those rows
    would otherwise be printed a second time — as fragments in reading order,
    beside the drawing they were read from. 令7春 問3 の 図9 is a page of
    "a を送" / "→" / "（5） 9" set next to the picture that already says it.

    The state machine above opens a drawing on a caption or on column gaps, and
    both can be missed: a 図's caption is printed *below* it, and gaps that the
    frame pass has not resolved yet do not look like gaps. So the run is taken
    again from each caption, outwards, and stops at the first row that is set
    like running text — at the margin, or wrapped across the full measure.
    """
    for i, row in enumerate(body):
        if row["kind"] != "caption" or not CAPTION.match(row["text"]):
            continue
        # 表 captions sit above their table, 図 captions below their figure.
        step = 1 if row["text"][0] == "表" else -1
        j = i + step
        while 0 <= j < len(body):
            b = body[j]
            if b["page"] != row["page"] or b["kind"] in ("heading", "caption"):
                break
            if looks_prose(b["text"]):
                break
            at_margin = any(abs(b["x"] - base - d) <= INDENT_EPS
                            for d in PROSE_INDENTS)
            # Starting at the margin is not enough on its own: a drawing's rows
            # wrap back to it too ("ハンズ、［ ］（2） Encrypted Extensions" in
            # 図9). Running text either fills the measure or ends a sentence.
            if is_prose(b) or (at_margin and (b["w"] > PROSE_W
                                              or SENTENCE_END.search(b["text"]))):
                break
            b["kind"] = "figure"
            j += step


def build_body(rows: list[dict]) -> list[dict]:
    """Prose, headings and captions, with everything inside a 図/表 set apart.

    A 図 or 表 breaks the left margin the whole page otherwise keeps, so the
    parse runs as a small state machine: a caption or a row carrying column gaps
    opens a drawing, and the next properly indented paragraph closes it.  Cell
    text that drifted back to the paragraph indent would otherwise be glued into
    the sentence above it, which is how a table ends up mid-paragraph.
    """
    base = base_indent(rows)
    # Where the text column ends. A caption is centred, so it stops short of it;
    # prose is set to the full measure.
    measure = max((r["x"] + r.get("w", 0) for r in rows), default=1.0)
    out: list[dict] = []
    in_figure = False
    for r in rows:
        text, x = r["text"], r["x"]
        # A caption sits in from both margins. Being well in from the left is
        # enough on its own; a long one that only just clears the indent — 表4 of
        # 平29秋 問1 starts 0.037 in — is told from prose by its right-hand end.
        caption = bool(CAPTION.match(text)) and (
            x > base + 0.04
            or (x > base + 0.02 and x + r.get("w", 0) < measure - 0.04))
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
              and out[-1]["page"] == r["page"]
              # ...and that paragraph is one. A "paragraph" that began well
              # right of the text margin is a drawing's label, and the line at
              # the margin under it is the drawing's 注記, not its continuation.
              and out[-1]["x"] <= base + 0.045):
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
    body = [dict(b, text=drop_layout_boxes(fix(clean(b["text"]))))
            for b in out if clean(b["text"])]
    # The state machine above decides from the left edge, so a 事例 with more
    # than one margin has whole paragraphs filed as drawing. 平30春 午後I 問1 lost
    # 140 of its 155 rows that way — the entire T主任/Uさん conversation was
    # replaced by the pictures beside it. Read the line to put those back.
    for b in body:
        if b["kind"] == "figure" and looks_prose(b["text"]):
            b["kind"] = "para"
    mark_drawings(body, base)
    return body


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


def build_items(rows: list[dict]) -> list[dict]:
    items: list[dict] = []
    setsu, nth = 0, 1
    for r in rows:
        text = r["text"]
        if SETSU_RANGE.match(text):
            continue
        m = SETSU.match(text)
        if m:
            setsu, nth = digits(m.group(1)), 1
            rest = text[m.end():].strip()
            m2 = SUB.match(rest)
            if m2:
                nth = sub_no(m2) + 1
            items.append({"setsu": setsu,
                          "sub": sub_no(m2) if m2 else None,
                          "text": rest[m2.end():].strip() if m2 else rest,
                          "page": r["page"], "lead": "" if m2 else None})
            continue
        m2 = SUB.match(text)
        # 小問 are numbered from (1) and run on without a gap, so a number that
        # goes backwards — or jumps — is not a heading but the line's own text.
        # 図9 of 令4春 問2 draws its message flow as "(1) スケジュール取得要求" and
        # the 小問 under it wraps onto "(10)から選び、番号で答えよ。"; both read as
        # headings until this was checked, and between them they cost the 大問
        # three 設問文. It also settles a 設問 heading that wraps: "設問2〔…〕に
        # ついて、(1)，" carries on as "(2)に答えよ。", and that (2) is the end of
        # the heading, not the second 小問 under it.
        if m2 and sub_no(m2) != nth:
            m2 = None
        if m2 and setsu:
            # A 設問 that opens with a preamble ("〔…〕について答えよ。") keeps it
            # as the lead-in every one of its 小問 is read under.
            lead = ""
            if items and items[-1]["setsu"] == setsu and items[-1]["sub"] is None:
                lead = items.pop()["text"]
            elif items and items[-1]["setsu"] == setsu:
                lead = items[-1].get("lead") or ""
            items.append({"setsu": setsu, "sub": sub_no(m2),
                          "text": text[m2.end():].strip(), "page": r["page"],
                          "lead": lead})
            nth = sub_no(m2) + 1
            continue
        if items:
            items[-1]["text"] += text
    for it in items:
        it["text"] = format_group(fix(clean(it["text"])))
        it["lead"] = fix(clean(it.get("lead") or ""))
    return [i for i in items if i["text"]]


def parse_paper(sid: str, paper: str, answers: dict | None = None) -> dict:
    rows, read, edges = load_rows(sid, paper)
    key = (answers or {}).get(sid, {}).get(paper, {})
    cases = {}
    for no, title, body_rows in split_cases(rows, PM_PAPERS[paper]["cases"]):
        resolve_frames(body_rows, read, edges,
                       {p["label"] for i in key.get(str(no), {}).get("items", [])
                        for p in i["parts"] if p["label"]})
        cut = next((i for i, r in enumerate(body_rows) if is_setsu_head(r)),
                   len(body_rows))
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
            cases = parse_paper(sid, paper, answers)
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
