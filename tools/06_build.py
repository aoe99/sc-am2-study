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
import datetime as dt, json, re, sys, unicodedata
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (SESSIONS, SESSION_IDS, SECTIONS, CHOICE_KEYS, PM_PAPERS, ROOT,
                   DATA, BUILD, build_dir, clean, exam_name, pdf_path,
                   pm_papers_of, read_json, write_json)
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "pm_figures", Path(__file__).resolve().parent / "15_pm_figures.py")
pm_figures = _ilu.module_from_spec(_spec)
_argv, sys.argv = sys.argv, ["15_pm_figures.py"]
_spec.loader.exec_module(pm_figures)
sys.argv = _argv
import statistics

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
# The right-hand rule of a 空欄 frame comes through twice now and then, the
# second time as a closing bracket: "本文中の［b］，［c］に入れる" reads as
# "本文中の［b］［c］】に入れる". 84 of these across the corpus; the one real
# quotation among them — 「［f］」 in an event log — has its opening bracket
# earlier in the line, which is what tells the two apart.
PM_DOUBLE_CLOSE = re.compile(r"］\s*([】」〕])")
OPENER = {"】": "【", "」": "「", "〕": "〔"}


# A 空欄 frame is set inline in Japanese, with no space either side of it. The
# spaces that show up there are the frame's own width, read as one.
PM_BOX_SPACE = [(re.compile(r"(?<=[^\x00-\x7f])[ 　]+(?=［)"), ""),
                (re.compile(r"(?<=］)[ 　]+(?=[^\x00-\x7f])"), "")]


def pm_close_up(text: str) -> str:
    for rx, repl in PM_BOX_SPACE:
        text = rx.sub(repl, text)
    return text


# The same doubling with the closing rule read as a katakana コ. Only between a
# closed frame and the "に入れる" that follows it: everywhere else "［a］コマンド"
# and "［a］コインジェクション" are what the booklet really prints.
PM_TAIL_KO = re.compile(r"(?<=］)\s*コ(?=に入れる)")
# The frame's own right-hand rule, read twice as itself.
PM_TWICE = re.compile(r"］\s*］")


def pm_drop_double_close(text: str) -> str:
    return PM_DOUBLE_CLOSE.sub(
        lambda m: m.group(0) if OPENER[m.group(1)] in text[:m.start()] else "］",
        text)


# The scan reads a full-size kana as its small form often enough to matter, and
# IPA never labels a 空欄 ァ or ィ, so the two are the same letter here.
SMALL_KANA = str.maketrans("ァィゥェォヵヶッャュョ", "アイウエオカケツヤユヨ")


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold().translate(SMALL_KANA)


def _same(a: str, b: str) -> bool:
    return _norm(a) == _norm(b)


def _wordish(ch: str) -> bool:
    """Part of a Latin word — so `isalnum`, which says yes to every kana."""
    return bool(ch) and ch.isascii() and ch.isalnum()


# The digit Vision returns for a letter set small inside a 空欄 frame.
STRAY_DIGIT = {"g": "9", "i": "1", "l": "1", "o": "0", "b": "6"}


def _stray(ch: str, label: str) -> bool:
    return bool(ch) and (_same(ch, label) or STRAY_DIGIT.get(_norm(label)) == ch)


BOX = r"(?:［[^］]{0,3}］|■)"
BOXISH = rf"(?:{BOX}|[A-Za-zａ-ｚ]{{1,2}})"
# All that survives of a frame the scan lost is sometimes its right-hand rule,
# read as a closing bracket: "表4中の［e］～［g］に入れる" comes back as
# "表4中の 」～［ ］に入れる". Only a bracket counts on that side — a letter would
# take in "XX-XX-XX-23-46-4a" in a 解答群 of MAC addresses.
WRECK = r"[」］】〕]"
PM_RANGE = re.compile(rf"(?:{BOX}\s*){{1,3}}[~～ー−\-]\s*(?:{BOXISH}\s*){{1,3}}"
                      rf"|{WRECK}\s*[~～]\s*(?:{BOX}\s*){{1,3}}")
# The letter of a frame, left outside it and against the range's own dash.
PM_LEAKED = re.compile(rf"({BOX})\s*[A-Za-z0-9]\s*(?=[~～])")


# IPA sets two blanks side by side and three or more as a range, so two frames
# with nothing but a separator between them, in a 設問 the 解答例 gives three or
# more labels, are the ends of a range whatever the letters in them read as.
# What sits between is the tilde and the frames' own rules, and the scan makes
# ロ, コ, ｜ and _ of those as readily as it keeps them.
PM_PAIR = re.compile(rf"{BOX}[\s　～~ー−\-,，、ロコ｜_.]{{0,4}}{BOX}")


# a…z / あ…こ / ア…ン / α…ω / ①…⑳: a 設問 names its blanks from one of these
# alphabets and never mixes two.
ALPHABETS = [re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]$"), re.compile(r"[ぁ-ん]$"),
             re.compile(r"[ァ-ヶ]$"), re.compile(r"[α-ωΑ-Ω]$"),
             re.compile(r"[①-⑳]$")]


def _blank_labels(parts: list[dict]) -> list[str]:
    """The labels that name 空欄, in order.

    A 記述 answer written in two columns is labelled by a phrase — "必要な全ての
    コード", "作成時" — and those are rows of the 解答例, not blanks in the
    wording; a range never ends in one. Nor does a 設問 draw from two alphabets
    at once: 令5秋 問4's 設問2 comes back labelled ① and あ because the ① numbers
    one of three worked examples in the 解答例, and only あ is a blank.
    """
    labels = [p["label"] for p in parts if p["label"]]
    if not all(len(l) <= 2 for l in labels):
        return []
    return labels if any(all(a.match(l) for l in labels) for a in ALPHABETS) else []


def pm_fix_range(text: str, parts: list[dict]) -> str:
    labels = _blank_labels(parts)
    if not text or len(labels) < 2:
        return text
    text = PM_LEAKED.sub(r"\1", text)
    shown = f"［{labels[0]}］～［{labels[-1]}］"
    out = PM_RANGE.sub(shown, text, count=1)
    if out == text and len(labels) > 2:
        out = PM_PAIR.sub(shown, text, count=1)
    return out


# A 空欄 frame the scan swallowed whole. "設問1 表1中の a ～ e に入れる" comes back
# as "表1中の［e］に入れる": the gap from the end of "表1中の" to the letter e is
# one wide space, and everything printed inside it — the box round a, the tilde —
# is a drawing. The answer key names every 空欄 the 設問 has, so when the one
# marker that survived is the first or the last of them, what was printed is
# recoverable. IPA sets two blanks side by side and three or more as a range.
PM_ONE_BLANK = re.compile(r"［\s*([^］\s]{1,3})\s*］")


def pm_fix_ends(text: str, parts: list[dict]) -> str:
    labels = _blank_labels(parts)
    if not text or len(labels) < 2:
        return text
    found = PM_ONE_BLANK.findall(text)
    ends = (labels[0], labels[-1])
    if len(found) != 1 or not any(_same(found[0], l) for l in ends):
        return text
    shown = (f"［{labels[0]}］［{labels[1]}］" if len(labels) == 2
             else f"［{labels[0]}］～［{labels[-1]}］")
    return PM_ONE_BLANK.sub(shown, text, count=1)


# Every 空欄 in a 設問文, whatever the scan made of the letter inside its frame.
PM_BOX = re.compile(r"［\s*([^］\s]{0,3})\s*］")


# A frame whose letter Vision read but set outside it: the gap shows on both
# sides of the letter, so the frame comes back as two empty ones with the
# letter loose between them — "本文中の［l］" reads as "本文中の［ ］1［ ］".
PM_SPLIT_BOX = re.compile(r"［\s*］\s*(\S)\s*［\s*］")


def pm_join_split_box(text: str, parts: list[dict]) -> str:
    labels = [p["label"] for p in parts if p["label"]]

    def one(m: re.Match) -> str:
        hits = [l for l in labels if _stray(m.group(1), l)]
        return f"［{hits[0]}］" if len(hits) == 1 else m.group(0)

    return PM_SPLIT_BOX.sub(one, text) if labels else text


# A frame read as a quotation: its left rule lost or taken for 「, its right one
# for 」 or 】 or コ. "本文中の［f］に入れる" comes back as "本文中のf」に入れる".
# Only the wording is looked at, never the 解答群 under it, and only latin and
# hiragana count — katakana would take the ア of a 解答群's own markers.
PM_QUOTED_LABEL = re.compile(
    r"[「【〔]?\s*([A-Za-zＡ-Ｚａ-ｚあ-んα-ωァ-ヶ])\s*[」】〕コ]")


def pm_quoted_label(text: str, parts: list[dict]) -> str:
    by = {_norm(p["label"]): p["label"] for p in parts if p["label"]}
    if not by:
        return text
    head, sep, rest = text.partition("\n")
    head = PM_QUOTED_LABEL.sub(
        lambda m: f"［{by[_norm(m.group(1))]}］" if _norm(m.group(1)) in by
        else m.group(0), head)
    return head + sep + rest


# The same two misplacements as in the 事例, on the 設問 side: the letter set
# beside its frame instead of inside it, and — where the frame did not survive
# at all — the letter left standing on its own. Katakana counts here, unlike in
# the 事例: a 設問 names two or three blanks, so a letter that is one of them is
# very unlikely to be anything else.
PM_ASIDE = re.compile(
    r"(?<![-ー−0-9A-Za-z])([0-9A-Za-zＡ-Ｚａ-ｚあ-んα-ωァ-ヶ])\s*［[\s　]*］")


def pm_wording_labels(text: str, parts: list[dict]) -> str:
    by = {_norm(p["label"]): p["label"] for p in parts
          if p["label"] and len(p["label"]) == 1}
    if not by:
        return text
    head, sep, rest = text.partition("\n")
    def aside(m: re.Match) -> str:
        hits = [l for l in by.values() if _stray(m.group(1), l)]
        return f"［{hits[0]}］" if len(hits) == 1 else m.group(0)

    head = PM_ASIDE.sub(aside, head)
    # Nothing framed at all, and the one blank's letter standing loose in the
    # wording exactly once: "本文中のc に入れる" for "本文中の［c］に入れる".
    if len(by) == 1 and not PM_BOX.search(head):
        label = next(iter(by.values()))
        loose = re.compile(rf"(?<![0-9A-Za-z]){re.escape(label)}(?![0-9A-Za-z])")
        if len(loose.findall(head)) == 1:
            head = loose.sub(f"［{label}］", head)
    return head + sep + rest


def pm_fix_labels(text: str, parts: list[dict]) -> str:
    """Name each 空欄 of a 設問文 the way the 解答例 names it.

    The letter inside a frame is set small, and Vision returns a lower-case c in
    a box as C about a fifth of the time: the 設問 then reads "図2中の［C］［d］に
    入れる" while the boxes to write in are labelled c and d. The 解答例 is the
    authority on which blanks a 設問 has and what they are called, so where the
    frames line up with its labels they are given the labels' own form.

    Two shapes are safe to act on, and only these. When there are as many frames
    as labels and every frame that kept a letter agrees with the label in its
    place, each frame takes that label — which also fills in the frames whose
    letter the scan lost. When instead the frames that kept a letter already
    account for every label, a frame left over is one the gap-finder invented:
    there is nothing to put in it, so it goes.
    """
    labels = [p["label"] for p in parts if p["label"]]
    if not text or not labels:
        return text
    boxes = list(PM_BOX.finditer(text))
    named = [m for m in boxes if m.group(1)]
    wording = [m for m in boxes if m.start() < len(text.partition("\n")[0])]
    if len(labels) == 1 and len(wording) == 1:
        # One blank, one frame in the wording: that frame is that blank whatever
        # the scan made of the letter inside it, and the 解答例 outranks the scan.
        # 204 of these agree already; the 3 that do not read ［α］ for d, ［a］ for
        # α and ［d］ for p — misreadings, not blanks the 解答例 forgot.
        fill = {wording[0].start(): labels[0]}
    elif len(boxes) == len(labels):
        if not all(_same(m.group(1), l)
                   for m, l in zip(boxes, labels) if m.group(1)):
            return text
        fill = dict(zip((m.start() for m in boxes), labels))
    elif len(named) == len(labels) and all(
            _same(m.group(1), l) for m, l in zip(named, labels)):
        fill = dict(zip((m.start() for m in named), labels))
    elif (len(labels) > 2 and len(boxes) == 2 and len(named) == 2
          and _same(named[0].group(1), labels[0])
          and _same(named[1].group(1), labels[-1])):
        # "［c］～［h］" — a range. The two frames are the first and last labels
        # and the ones between them are not printed at all.
        fill = {named[0].start(): labels[0], named[1].start(): labels[-1]}
    else:
        return text
    out, last = [], 0
    for m in boxes:
        head, label, skip = text[last:m.start()], fill.get(m.start()), 0
        # The letter belongs inside the frame, and where Vision read it as a
        # neighbour instead the 設問 comes out as "図1中の［ ］eに入れる". Once the
        # frame carries its label, that loose copy is a leftover. Only a letter
        # standing on its own counts — never one cut out of a word.
        if label:
            left = head.rstrip(" ")
            if _stray(left[-1:], label) and not _wordish(left[-2:-1]):
                head = left[:-1].rstrip(" ")
            tail = text[m.end():]
            at = len(tail) - len(tail.lstrip(" "))
            if _stray(tail[at:at + 1], label) and not _wordish(tail[at + 1:at + 2]):
                after = tail[at + 1:]
                skip = at + 1 + len(after) - len(after.lstrip(" "))
        out.append(head)
        out.append(f"［{label}］" if label else "")
        last = m.end() + skip
    out.append(text[last:])
    return clean("".join(out))


# Vision reads the 下線⑥ marker as a copyright sign often enough to matter. The
# substitution is only made where it is certain: the 設問 ask about ⑥, the 事例
# has no ⑥, and exactly one © stands in the prose. Three 事例 qualify; the other
# two that contain a © have their ⑥ already and the sign is really printed.
LOOKALIKE = {"⑥": "©"}


# The letter belongs inside the frame, and where the page read set it just
# outside the 事例 loses the blank a 設問 points at: "d［ ］の対策と併せて" is
# printed "［d］の対策と併せて". Not after a hyphen or katakana, though —
# "SaaS-a", "DNS-K" and "サイトA" are names, and their last letter is no more a
# 空欄 label than the "B" of "B コイン" was.
PM_LOOSE_LABEL = re.compile(
    r"(?<![-ー−0-9A-Za-zァ-ヶ])([A-Za-zＡ-Ｚａ-ｚあ-んα-ω])\s*［[\s　]*］")


def pm_pull_in_label(text: str, by: dict) -> str:
    return PM_LOOSE_LABEL.sub(
        lambda m: f"［{by[_norm(m.group(1))]}］" if _norm(m.group(1)) in by
        else m.group(0), text)


def pm_fix_body_blanks(body: list[dict], labels: set) -> None:
    """Give the 空欄 of the 事例 the letters the 設問 call them by.

    Same misreading as in the 設問文, on the other side of the link: a lower-case
    c set small inside its frame comes back as C, 58 times across the corpus.
    IPA never mixes the cases, so a frame whose letter differs from one of this
    大問's labels only in case is that label — and until it says so, the 設問
    that reads "［c］に入れる" has no ［c］ in the 事例 to send the reader to.
    """
    by = {_norm(l): l for l in labels}
    for b in body:
        b["text"] = PM_ONE_BLANK.sub(
            lambda m: f"［{by.get(_norm(m.group(1)), m.group(1))}］",
            pm_pull_in_label(pm_close_up(pm_drop_double_close(b["text"])), by))


# A space between two Japanese characters, which sets nothing on its own.
PM_GAP = re.compile(r"(?<=\S)[ 　](?=\S)")


def pm_put_back_blank(text: str, parts: list[dict]) -> str:
    """Put back the one 空欄 frame a 設問文 lost outright.

    "本文中の［f］に入れる適切な字句を" comes back as "本文中の に入れる…" when the
    frame is faint enough that the ink test calls the gap blank paper: all that
    survives is the space it stood in. Where the 解答例 says the 設問 has exactly
    one blank, the wording shows none, and exactly one space in it separates two
    Japanese characters — Latin keeps its own spaces, so those are skipped —
    there is nowhere else the frame can have been. 50 設問 read this way.
    """
    labels = [p["label"] for p in parts if p["label"]]
    if len(labels) != 1 or not text:
        return text
    head, sep, rest = text.partition("\n")
    if PM_BOX.search(head):
        return text
    gaps = [m for m in PM_GAP.finditer(head)
            if not head[m.start() - 1].isascii() and not head[m.end()].isascii()]
    if len(gaps) != 1:
        return text
    at = gaps[0]
    return head[:at.start()] + f"［{labels[0]}］" + head[at.end():] + sep + rest


# Every frame in the 事例, labelled or not, in reading order.
PM_ANY_BOX = re.compile(r"［[^］]{0,3}］")
PM_IN_PROSE = re.compile(r"本文中")


# A 空欄 in running text has a particle on one side of it. A frame between two
# nouns is a table's column gap or a drawing's spacing, whatever the row was
# classified as, and an arrow anywhere in the row says the same.
PM_KANA = re.compile(r"[ぁ-ん、，]")
PM_ARROW = re.compile(r"[→⇒←↑↓]")


def pm_place_missing_blank(body: list[dict], order: list[str],
                           prose: set) -> None:
    """Put a 空欄 back where the labels either side of it say it must be.

    IPA labels the blanks of a 大問 a, b, c… down the 事例, so blanks the 設問 ask
    about that never came out of the scan are pinned by their neighbours: they
    lie after the last ［k］ and before the first ［n］, in that order. The frames
    still empty in that stretch take them, first to first.

    Everything here is inference, so it is fenced in hard. Only single-letter
    labels, only 設問 that say 本文中 (a blank in a 表 is inside a picture, and
    the 設問 would have said 表2中), only frames in the prose with a particle
    beside them, and never where the brackets belong to the text itself —
    "char *argv［］" is C, not a blank to fill in. What is left over is a frame
    that could hardly be anything else.
    """
    seq = [(i, m.start(), m.end(), m.group(0)[1:-1].strip(), b["kind"])
           for i, b in enumerate(body) for m in PM_ANY_BOX.finditer(b["text"])]
    if not seq:
        return
    have = {v for _, _, _, v, _ in seq}
    missing = [(n, l) for n, l in enumerate(order)
               if l not in have and len(l) == 1 and l in prose]
    for run in _runs(missing):
        first_n, last_n = run[0][0], run[-1][0]
        if first_n == 0 or order[first_n - 1] not in have:
            continue
        start = max(k for k, s in enumerate(seq) if s[3] == order[first_n - 1])
        if last_n == len(order) - 1:
            end = len(seq)
        elif order[last_n + 1] in have:
            end = min(k for k, s in enumerate(seq) if s[3] == order[last_n + 1])
        else:
            continue
        here = [k for k in range(start + 1, end) if _placeable(body, seq[k])]
        for k, (_, label) in zip(here, run):
            i, at, to, _, _ = seq[k]
            text = body[i]["text"]
            body[i]["text"] = text[:at] + f"［{label}］" + text[to:]
        left = [l for _, l in run[len(here):]]
        left = [l for l in left if not _frame_loose(body, l)]
        if left:
            stop = seq[end][0] if end < len(seq) else len(body)
            _insert_missing(body, left, seq[start][0], stop)


# The letter is in the 事例 but its frame is not: "が b コ 応弱性" for
# "が［b］脆弱性", "「f として" for "［f］として". Taken only for a blank that is
# missing altogether, only where the letter stands on its own with a particle
# beside it and appears just once in the whole 事例 — and never a circled
# number, which in these booklets marks a 下線 and not a blank.
PM_LOOSE_CLOSE = "」】〕コ"


def _frame_loose(body: list[dict], label: str) -> bool:
    if not re.match(r"[A-Za-zａ-ｚあ-んα-ωァ-ヶ]$", label):
        return False
    found = []
    for i, b in enumerate(body):
        if b["kind"] != "para":
            continue
        for m in re.finditer(rf"(?<![0-9A-Za-z]){re.escape(label)}(?![0-9A-Za-z])",
                             b["text"]):
            left, right = b["text"][m.start() - 1:m.start()], b["text"][m.end():m.end() + 1]
            if PM_KANA.match(left or " ") or PM_KANA.match(right or " "):
                found.append((i, m.start(), m.end()))
    if len(found) != 1:
        return False
    i, at, to = found[0]
    text = body[i]["text"]
    # The frame's own rules come through as 「 and 」 as often as they vanish.
    if text[at - 1:at] in "「【〔":
        at -= 1
    if text[to:to + 1] in PM_LOOSE_CLOSE:
        to += 1
    body[i]["text"] = text[:at] + f"［{label}］" + text[to:]
    return True


# A line the scan lost outright leaves a hole in the page: the 事例 skips from
# one line to the next but the paper has room between them for one more. That is
# how "・［j］" disappears — a bullet and an empty frame, with no text on the line
# for Vision to catch hold of. Where a blank is still missing and the stretch it
# has to be in has exactly one such hole, the frame goes there on a line of its
# own. Two and a half times the page's own line pitch: a paragraph break is
# under two, a 節 heading about two.
PM_HOLE = 2.5
PM_PAGE_NO = re.compile(r"^[-–—ー−ｰ=＝~〜_]?\s*\d{1,3}\s*[-–—ー−ｰ=＝~〜_]?$")


def _insert_missing(body: list[dict], labels: list[str],
                    first: int, last: int) -> None:
    pitch = _pitch(body)
    holes = []
    for i in range(first, min(last, len(body)) - 1):
        a, b = body[i], body[i + 1]
        step = pitch.get(a["page"])
        if (not step or b["page"] != a["page"] or b.get("y", 1) > 0.88
                or PM_PAGE_NO.match(a["text"].strip())
                or PM_PAGE_NO.match(b["text"].strip())):
            continue
        if b.get("y", 0) - a.get("y", 0) >= step * PM_HOLE:
            holes.append(i)
    if len(holes) != 1 or len(labels) != 1:
        return
    at = holes[0]
    body.insert(at + 1, {"kind": "para", "text": f"［{labels[0]}］",
                         "page": body[at]["page"],
                         "y": (body[at]["y"] + body[at + 1]["y"]) / 2,
                         "x": body[at]["x"], "w": 0.0, "h": 0.0, "lines": 1})


def _pitch(body: list[dict]) -> dict:
    """How far apart this page sets its lines, page by page."""
    by: dict = {}
    for i in range(len(body) - 1):
        if body[i + 1]["page"] == body[i]["page"]:
            by.setdefault(body[i]["page"], []).append(
                body[i + 1].get("y", 0) - body[i].get("y", 0))
    return {p: statistics.median(v) for p, v in by.items() if v}


def _runs(missing: list) -> list[list]:
    """The missing labels grouped into consecutive stretches."""
    out: list[list] = []
    for x in missing:
        if out and x[0] == out[-1][-1][0] + 1:
            out[-1].append(x)
        else:
            out.append([x])
    return out


def _placeable(body: list[dict], span: tuple) -> bool:
    i, at, to, letter, kind = span
    if letter or kind != "para":
        return False
    text = body[i]["text"]
    left, right = text[at - 1:at], text[to:to + 1]
    return (not _wordish(left)
            and (PM_KANA.match(left or " ") or PM_KANA.match(right or " "))
            and not PM_ARROW.search(text))


PM_MARK = re.compile(r"[①-⑳]")


def pm_repair_markers(body: list[dict], asked: set) -> None:
    text = "".join(b["text"] for b in body)
    for mark, stand_in in LOOKALIKE.items():
        if mark not in asked or mark in text or text.count(stand_in) != 1:
            continue
        for b in body:
            if stand_in in b["text"]:
                b["text"] = b["text"].replace(stand_in, mark, 1)
                break
    pm_reorder_markers(body, asked)


def pm_reorder_markers(body: list[dict], asked: set) -> None:
    """Put back a 下線 marker the scan read as a different circled number.

    The markers of a 事例 are printed ①②③… down the page in order, and the 設問
    name every one of them.  So a marker the 設問 ask about that is nowhere in
    the 事例 can be placed whenever exactly one of the numbers that *are* there
    sits where it belongs — after the marker below it, before the marker above
    it — and is out of order where it stands.  下線⑦ of 令5秋 問3 came back as a
    second ②, three lines under ⑥ and two above ⑧; nothing else in the 事例
    could have been it, and without the marker the 設問 asking about it had
    nowhere in the 事例 to point.
    """
    seen = [(i, m.start(), ord(m.group()) - 0x245F)
            for i, b in enumerate(body) for m in PM_MARK.finditer(b["text"])]
    if not seen:
        return
    seq = [v for _, _, v in seen]
    for mark in sorted(asked):
        want = ord(mark) - 0x245F
        if want in seq:
            continue
        hits = [k for k in range(len(seq))
                if (k == 0 or seq[k - 1] < want)
                and (k == len(seq) - 1 or seq[k + 1] > want)
                and ((k and seq[k] <= seq[k - 1])
                     or (k + 1 < len(seq) and seq[k] >= seq[k + 1]))]
        if len(hits) != 1:
            continue
        i, at, _ = seen[hits[0]]
        body[i]["text"] = body[i]["text"][:at] + mark + body[i]["text"][at + 1:]
        seq[hits[0]] = want


# A 事例 says the same words over and over — 平30秋 午後II 問1 prints サーバ 132
# times — so a katakana word that turns up once, and differs from a common one
# in that same 事例 by a single character, is the scan misreading that word and
# not a word of its own.  サーノ, サニバ, リーバ, ナーバ are all サーバ.
#
# The danger is the opposite case: a real word that happens to sit one character
# from a common one.  化学メーカ is not メール, DNS シンクホール is not ツール,
# キーボード入力 is not モード.  Four conditions keep those out.
KATA_WORD = re.compile(r"[ァ-ヶ][ァ-ヶー]{2,}")
VOTE_IN_CASE = 2      # times the odd spelling may appear in its own 事例
VOTE_IN_PM = 5        # times it may appear across the whole 午後 corpus
VOTE_RATIO = 10       # how much oftener the common spelling has to appear


def text_layer() -> str:
    """Every 午後 word that reached us without going through OCR.

    The 教科書解説 of both 区分, IPA's own 解答例 and the 採点講評 all have a text
    layer — 60万字 of this exact vocabulary, spelled correctly by construction.
    A katakana run that appears nowhere in it is not a word of the domain.
    """
    out = []
    for sec in ("pm", "am1", "am2"):
        path = build_dir(sec) / "explanations.json"
        if path.exists():
            out.append(json.dumps(read_json(path), ensure_ascii=False))
    for name in ("commentary.json", "answers.json"):
        path = build_dir("pm") / name
        if path.exists():
            out.append(json.dumps(read_json(path), ensure_ascii=False))
    return "".join(out)


def pm_vote_terms(cases: list[dict], questions: list[dict]) -> list[tuple]:
    """Correct a katakana word against the way its own 事例 spells it."""
    lex = text_layer()
    said: dict[str, list[str]] = {}
    for c in cases:
        said[c["id"]] = [b["text"] for b in c["body"]]
    for q in questions:
        if q.get("section") == "pm" and q.get("text"):
            said.setdefault(q["caseId"], []).append(q["text"])
    corpus = Counter(w for parts in said.values()
                     for s in parts for w in KATA_WORD.findall(s))

    fixed = []
    for cid, parts in said.items():
        here = Counter(w for s in parts for w in KATA_WORD.findall(s))
        words = list(here)
        cand: dict[str, set] = {}
        for i, a in enumerate(words):
            for b in words[i + 1:]:
                if len(a) != len(b) or sum(x != y for x, y in zip(a, b)) != 1:
                    continue
                odd, common = (a, b) if here[a] < here[b] else (b, a)
                if (here[odd] > VOTE_IN_CASE or corpus[odd] > VOTE_IN_PM
                        or here[common] < here[odd] * VOTE_RATIO):
                    continue
                if odd in lex:
                    continue          # a real word, however rare here
                # ファイア is the head of ファイアウォール, not a misread ファイル.
                if any(w != odd and odd in w and corpus[w] >= 3 for w in corpus):
                    continue
                cand.setdefault(odd, set()).add(common)
        for odd, commons in cand.items():
            # シンクホール sits one character from both メール and ツール. When the
            # 事例 offers two answers it has not told us which, so leave it.
            if len(commons) != 1:
                continue
            common = commons.pop()
            n = 0
            for c in cases:
                if c["id"] != cid:
                    continue
                for b in c["body"]:
                    if odd in b["text"]:
                        b["text"] = b["text"].replace(odd, common)
                        n += 1
            for q in questions:
                if q.get("caseId") == cid and q.get("text") and odd in q["text"]:
                    q["text"] = q["text"].replace(odd, common)
                    n += 1
            if n:
                fixed.append((cid, odd, common, n))
    return fixed


# The page number is printed on its own line at the foot of every page, and a
# 設問 that runs to the bottom of one takes it along: "70字以内で述べよ。 - 12 =".
# The rule has to want the rule — a bare number is a 字数 or a 項番, and 解答群
# option "ケ SHA-512" is a hyphen with a number after it. So a dash-like glyph
# has to sit against the digits, and what comes before has to be a break rather
# than a letter.
PM_PAGE = r"[-–—ー−ｰ―=＝~〜_]"
PM_PAGE_TAIL = re.compile(
    rf"(?:(?<=[\s。．）)」』])|^)(?:{PM_PAGE}{{1,2}}\s*\d{{1,3}}\s*{PM_PAGE}{{0,2}}"
    rf"|\d{{1,3}}\s*{PM_PAGE}{{1,2}})\s*$")
PM_PAGE_ROW = re.compile(
    rf"^\s*(?:{PM_PAGE}{{1,2}}\s*\d{{1,3}}\s*{PM_PAGE}{{0,2}}"
    rf"|\d{{1,3}}\s*{PM_PAGE}{{1,2}})\s*$")


def pm_drop_page_no(text: str) -> str:
    """Drop the foot-of-page number a 設問 picked up at a page break."""
    lines = [l for l in text.split("\n") if not PM_PAGE_ROW.match(l)]
    out = "\n".join(lines).rstrip()
    for _ in range(3):
        cut = PM_PAGE_TAIL.sub("", out).rstrip()
        if cut == out:
            break
        out = cut
    return out


# The rows a 図/表 crop replaces. The app shows the picture, so printing these
# again beside it says everything twice — and a table read in reading order is
# unreadable ("フェーズ32さんとB社での診断A 社グループである…").
#
# Three things decide it. The run goes in the caption's own direction (a 表
# caption sits above its table, a 図 caption below its figure). It stops at a
# row that is not inside the picture, because a row that is not in the crop
# would vanish altogether. And it survives a single row that reads like prose,
# because a table row whose cells the scan ran together looks exactly like one —
# two in a row end it, which is what keeps the sentence that introduces a 図
# from being swallowed.
DRAW_PAD = 0.004
DRAW_SKIP = 1


def _in_rect(row: dict, page: int, rect: list) -> bool:
    x, y, w, h = rect
    return (row["page"] == page
            and x <= row["x"] + DRAW_PAD
            and row["x"] + row.get("w", 0) <= x + w + DRAW_PAD
            and y <= row["y"] + DRAW_PAD
            and row["y"] + row.get("h", 0) <= y + h + DRAW_PAD)


def pm_drawing_rows(body: list[dict], regions: list[dict]) -> set:
    by_caption = {r["caption"]: r for r in regions}
    out: set = set()
    for i, row in enumerate(body):
        if row["kind"] != "caption":
            continue
        reg = by_caption.get(row["text"])
        if not reg:
            continue
        step = 1 if row["text"].startswith("表") else -1
        pend: list = []
        j = i + step
        while 0 <= j < len(body):
            b = body[j]
            if (b["kind"] in ("heading", "caption")
                    or not _in_rect(b, reg["page"], reg["rect"])):
                break
            if b["kind"] != "figure":
                pend.append(j)
                if len(pend) > DRAW_SKIP:
                    break
                j += step
                continue
            out.update(pend)
            pend = []
            out.add(j)
            j += step
    return out


def pm_wording(text: str, parts: list[dict]) -> str:
    """A 設問文 with its 空欄 put back the way the 解答例 names them."""
    text = pm_drop_page_no(text)
    text = pm_drop_double_close(PM_TWICE.sub("］", PM_TAIL_KO.sub("", text)))
    text = pm_join_split_box(pm_quoted_label(text, parts), parts)
    text = pm_wording_labels(text, parts)
    text = pm_fix_ends(pm_fix_range(text, parts), parts)
    return pm_close_up(pm_fix_labels(pm_put_back_blank(text, parts), parts))


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
                drawn = pm_drawing_rows(body["body"], pm_figures.regions(body["body"]))
                case_id = f"{sid}-{paper}-{no}"
                asked = set(re.findall(
                    r"下線\s*([①-⑳])",
                    " ".join(i.get("text", "") + " " + (i.get("lead") or "")
                             for i in body["items"])))
                pm_repair_markers(body["body"], asked)
                blanks = {p["label"] for i in key.get("items", [])
                          for p in i["parts"] if p["label"]}
                pm_fix_body_blanks(body["body"], blanks)
                # The 設問 say where each blank of theirs is; the ones in the
                # prose can be placed from the labels either side of them.
                texts = {(i["setsu"], i["sub"]): i for i in body["items"]}
                order, prose = [], set()
                for item in key.get("items", []):
                    wording = texts.get((item["setsu"], item["sub"]), {}).get(
                        "text", "").split("\n")[0]
                    for part in item["parts"]:
                        if not part["label"]:
                            continue
                        if part["label"] not in order:
                            order.append(part["label"])
                        if PM_IN_PROSE.search(wording):
                            prose.add(part["label"])
                pm_place_missing_blank(body["body"], order, prose)
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
                    # The foot-of-page number is not part of the 事例.
                    "body": [dict({"kind": b["kind"], "text": b["text"],
                                   "page": b["page"]},
                                  **({"drawn": True} if n in drawn else {}))
                             for n, b in enumerate(body["body"])
                             if not PM_PAGE_ROW.match(b["text"])],
                    # What ［…］ in this 事例 is a 空欄 rather than something the
                    # booklet really prints in brackets: "argv［1］" in a listing,
                    # "［チョコ］" as a search term, a particle the scan cut out of
                    # a line. 133 of the 755 framed letters in the 事例 are one of
                    # those, and calling them all 空欄 sends the reader hunting.
                    "blanks": sorted(blanks),
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
                for n, item in enumerate(key.get("items", []), 1):
                    setsu, sub = item["setsu"], item["sub"]
                    ask = texts.get((setsu, sub), {})
                    if not ask and sub is None:
                        # 令5秋 問4 の設問2 は、解答例が三つの記入例を①②③で
                        # 並べるので小問の番号が見えず、鍵の側だけ「設問2」に
                        # なる。冊子に素の設問2が無く(1)があるなら、それ。
                        ask = texts.get((setsu, 1), {})
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
                        "text": pm_wording(ask.get("text", ""), item["parts"]),
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
    voted = pm_vote_terms(cases, questions)
    if voted:
        print(f"  事例の多数決で直したカタカナ語 {len(voted)} 語 / "
              f"{sum(v[3] for v in voted)} 箇所")
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
