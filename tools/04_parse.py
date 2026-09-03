#!/usr/bin/env python3
"""Stage 4 — split OCR lines into 問1..25, each with its four choices.

Vision returns one observation per printed line with a normalised box, so the
split is driven by geometry as much as by text: 問N headings sit in the
leftmost column, choice markers one indent in, and continuation lines one
indent further still.  Anything inside a question that belongs to none of
those is figure/table artwork, which gets flagged and cropped in stage 5.

    python3 tools/04_parse.py [--section am1|am2] [session ...]
"""
from __future__ import annotations
import difflib, json, re, sys, unicodedata
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (CHOICE_KEYS, SECTIONS, PDFTOOL, build_dir, clean, pdf_path,
                   question_count, read_json, run_tool, section_of, targets_of,
                   write_json)
import tempfile

SECTION = section_of(sys.argv[1:])
N_MAX = question_count(SECTION)
CORR = json.loads((Path(__file__).resolve().parent / "corrections.json")
                  .read_text(encoding="utf-8"))
FIXES = [(re.compile(r["pattern"], re.M), r["repl"], r["why"])
         for r in CORR["replacements"]]
FLAGS = [(re.compile(f["pattern"], re.M), f["label"]) for f in CORR["flagPatterns"]]
applied: dict[str, int] = {}


def _vocab() -> set:
    """English words as the 読者特典 explanations spell them.

    Those come out of the PDF with no OCR involved, so they are a free
    domain dictionary — enough to tell "Authent ication" (a glyph gap Vision
    read as a space) from "Pass the" (a real one)."""
    path = build_dir(SECTION) / "explanations.json"
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    out = set()
    for sess in data.values():
        for q in sess.values():
            out |= {w.lower() for w in
                    re.findall(r"[A-Za-z][A-Za-z0-9]{4,}", q["explanation"])}
    return out


VOCAB = _vocab()
rejoined: dict[str, int] = {}


def rejoin_split_words(s: str) -> str:
    def fix(m):
        parts = m.group(0).split(" ")
        out, i = [], 0
        while i < len(parts):
            hit = next((j for j in range(len(parts), i + 1, -1)
                        if "".join(parts[i:j]).lower() in VOCAB), None)
            if hit:
                joined = "".join(parts[i:hit])
                rejoined[joined] = rejoined.get(joined, 0) + 1
                out.append(joined); i = hit
            else:
                out.append(parts[i]); i += 1
        return " ".join(out)
    return re.sub(r"[A-Za-z]{2,}(?: [A-Za-z]{1,7}){1,3}", fix, s)

# The number runs straight into the sentence often enough ("問18" + "1台の
# サーバ…" → 問181台) that no digit boundary can be trusted here; capture the
# whole run and let the 1..25 sequence decide where the number ends.
HEAD = re.compile(r"^[問間]\s*(\d{1,3})")
# "− 12 −" and also the bare rules left when the digits are not recognised.
PAGE_NO = re.compile(r"^[\s\-–—ー−=_]*\d{1,3}[\s\-–—ー−=_]*$|^[\s\-–—ー−=_･・.,]+$")
# Vision confuses these with the choice markers: エ/工 (katakana vs kanji) and
# イ/1 are the two that actually bite.
ALIAS = {"ア": "アァ", "イ": "イィ1lＩ", "ウ": "ウゥワヮ", "エ": "エェ工ヱ"}
# "1"/"l" stand in for イ only as a last resort. A four-across row of binary
# strings ("ア0110011  ィ  1010011 …") offers the digit as a rival marker, and
# taking it would eat the first bit of the answer.
STRONG = {"ア": "アァ", "イ": "イィ", "ウ": "ウゥワヮ", "エ": "エェ工ヱ"}
# Figure and table blocks are introduced by a bracketed caption when they have one.
CAPTION = re.compile(r"^[〔［【\[（(]")
ENDS_SENTENCE = re.compile(r"[。．！？]\s*$")
# "図" and "表" occur inside ordinary words (地図, 発表, 表示); only count them
# when the sentence is pointing at an actual exhibit.
FIGREF = re.compile(r"(?:次の[図表]|[下上左右本]図|図中|(?<![地海系意合構星版縮])図[のにはを]|[図表]\s?\d"
                    r"|[下上]表|表中|(?<![発公代年別])表[のにはを]|〔[^〕]*〕|次に示す)")

CJK = r"　-〿぀-ヿ㐀-䶿一-鿿＀-￯"

# Letters, digits and Japanese are content; anything else at the head of a
# choice whose marker was inferred is OCR debris.
KEEPS_FIRST = re.compile(rf"[0-9A-Za-z{CJK}]")


def norm(s: str) -> str:
    """Normalise OCR output of an IPA booklet.

    IPA typesets 読点 as "，" throughout; Vision reads many of them as "、"
    (tesseract independently read every one of them as a comma glyph, which
    is what settles it).  Latin runs are printed with padding spaces that
    Vision keeps only sometimes, so those are dropped for consistency.
    """
    s = clean(s)
    s = s.replace("、", "，").replace("｡", "。").replace("､", "，")
    s = s.replace("―", "—").replace("~", "〜")
    s = re.sub(rf"(?<=[{CJK}]) +", "", s)
    s = re.sub(rf" +(?=[{CJK}])", "", s)
    return s.strip()


def apply_fixes(s: str) -> str:
    """Run the correction dictionary over a whole run of prose.

    It has to see the joined text, not each OCR line: a misread term is as
    likely as not to straddle a line wrap ("エクスプロイ" / "ド"), and a
    per-line pass would never see it whole.
    """
    if VOCAB:
        s = rejoin_split_words(s)
    for rx, repl, why in FIXES:
        s, n = rx.subn(repl, s)
        if n:
            applied[why] = applied.get(why, 0) + n
    return s


DROP_SKIP = re.compile(r"[\s，,、。．.・:：]")
recovered: list[str] = []
rejected: list[str] = []


def _confirm(pdf, page: int, line: dict, seg: str) -> bool:
    """Re-read one line at 600dpi to arbitrate a Vision/tesseract disagreement.

    tesseract hallucinates too, so a character it alone reports is not enough.
    Cropping just the line makes the glyph far larger relative to the frame,
    and Vision reliably picks up what it skipped at full-page scale.
    """
    x = max(0.0, line["x"] - 0.02)
    y = max(0.0, line["y"] - 0.012)
    w = min(1.0 - x, line["w"] + 0.05)
    h = min(1.0 - y, line["h"] + 0.024)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "line.png"
        try:
            run_tool("crop", pdf, page, f"{x:.5f}", f"{y:.5f}",
                     f"{w:.5f}", f"{h:.5f}", out, "--dpi", "600")
            return seg in run_tool("ocr", out)
        except Exception:
            return False


def repair_dropped(pages: list[dict], pdf) -> None:
    """Put back characters Vision lost that the second engine did read.

    Vision occasionally swallows a glyph — 「信」 in 通信/受信 especially — and
    nothing about the surviving text looks wrong, so the only way to notice is a
    second opinion.  Every candidate is then confirmed by re-reading the line.
    """
    for pn, page in enumerate(pages, 1):
        second = page.get("tesseract")
        if not second:
            continue
        chars, owner = [], []
        for li, l in enumerate(page["lines"]):
            for ci, c in enumerate(l["text"]):
                if not DROP_SKIP.match(c):
                    chars.append(unicodedata.normalize("NFC", c))
                    owner.append((li, ci))
        ref = [c for c in unicodedata.normalize("NFC", second) if not DROP_SKIP.match(c)]
        if len(chars) < 200:
            continue
        edits = []
        sm = difflib.SequenceMatcher(None, chars, ref, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "insert" or not 1 <= j2 - j1 <= 2 or i1 >= len(owner):
                continue
            seg = "".join(ref[j1:j2])
            if not all("\u4e00" <= c <= "\u9fff" for c in seg):
                continue
            li, ci = owner[i1]
            if _confirm(pdf, pn, page["lines"][li], seg):
                edits.append(((li, ci), seg))
            else:
                rejected.append(f"p{pn} 『{seg}』（再読取で確認できず・不採用）")
        for (li, ci), seg in sorted(edits, reverse=True):
            t = page["lines"][li]["text"]
            page["lines"][li]["text"] = t[:ci] + seg + t[ci:]
            recovered.append(f"p{pn} 『{seg}』 → …{t[max(0, ci - 10):ci]}[{seg}]{t[ci:ci + 10]}…")


# In a four-across choice row Vision sometimes emits two cells as one
# observation ("イEIGamal暗号 ウ RSA"). The successor marker plus the space
# in front of it is the seam.
MERGED = re.compile(r"^(?P<a>[アイウエ])\s*(?P<at>.{2,}?)[ 　]*(?P<b>[アイウエ])[ 　]*(?P<bt>.{2,})$")
NEXT_KEY = {"ア": "イ", "イ": "ウ", "ウ": "エ"}
# A split is only real if the second cell starts a word. Small kana and the
# long-vowel mark mean the marker was the middle of one ("アクセスウィンドウ").
NOT_A_START = "ァィゥェォッャュョヮーぁぃぅぇぉっゃゅょ"


def split_merged(lines: list[dict]) -> list[dict]:
    out = []
    for l in lines:
        t = l["text"].strip()
        m = MERGED.match(t) if len(t) <= 64 else None
        if (not m or NEXT_KEY.get(m.group("a")) != m.group("b")
                or m.group("bt")[0] in NOT_A_START):
            out.append(l)
            continue
        # Estimate where the second cell starts from its offset in the line.
        cut = m.start("b") / max(1, len(t))
        first = dict(l)
        first["text"] = m.group("a") + m.group("at")
        first["w"] = l["w"] * cut
        second = dict(l)
        second["text"] = m.group("b") + m.group("bt")
        second["x"] = l["x"] + l["w"] * cut
        second["w"] = l["w"] * (1 - cut)
        out += [first, second]
    return out


def load(sid: str) -> list[dict]:
    pages = json.loads((build_dir(SECTION) / "ocr" / f"{sid}.json")
                       .read_text(encoding="utf-8"))
    repair_dropped(pages, pdf_path(sid, "1問題", SECTION))
    out = []
    for pi, page in enumerate(pages, 1):
        for li, l in enumerate(page["lines"]):
            t = l["text"].strip()
            if not t or PAGE_NO.match(t):
                continue
            out.append({"page": pi, "i": li, "text": t,
                        "x": l["x"], "y": l["y"], "w": l["w"], "h": l["h"]})
    return split_merged(out)


def find_headings(lines: list[dict]) -> dict[int, int]:
    """Map 問番号 → line index for the 25 headings.

    The heading number is the one spot where a single bad glyph costs a whole
    question, so the scan tolerates two kinds of damage: a number that picked up
    a stray digit ("問9 3層…" reads as 問93), and a heading OCR missed entirely,
    which is recovered afterwards from the space it left in the left column.
    """
    cands = [(i, HEAD.match(l["text"]).group(1))
             for i, l in enumerate(lines) if HEAD.match(l["text"])]
    if not cands:
        return {}
    left = min(lines[i]["x"] for i, _ in cands)
    # Headings share the leftmost column; body text sits a full indent further in.
    margin = left + 0.06
    cands = [(i, n) for i, n in cands if lines[i]["x"] <= margin]
    # The gap-filler must not reach past the heading column into wrapped body
    # text, so bound it by the headings actually seen rather than by `margin`.
    head_x = max((lines[i]["x"] for i, _ in cands), default=margin) + 0.008

    def scan(pool, loose):
        got: dict[int, int] = {}
        want = 1
        for i, ds in pool:
            if want > N_MAX:
                break
            if ds == str(want):
                got[want] = i; want += 1
            elif loose and ds.startswith(str(want)):
                got[want] = i; want += 1
            elif loose and ds.isdigit() and want < int(ds) <= N_MAX:
                got[int(ds)] = i; want = int(ds) + 1   # a heading was missed
        return got

    # A "問1～問25" line on the cover can steal the first slot; if the run comes
    # up short, drop whichever candidate it grabbed first and try again.
    best: dict[int, int] = {}
    for loose in (False, True):
        pool = cands
        for _ in range(4):
            got = scan(pool, loose)
            if len(got) == N_MAX:
                return got
            if len(got) > len(best):
                best = got
            if not got:
                break
            pool = [(i, n) for i, n in pool if i != min(got.values())]

    # Whatever is still missing lost its 問N to OCR, but the heading itself is
    # still the only line sitting alone in the left column between its neighbours.
    taken = set(best.values())
    for miss in [n for n in range(1, N_MAX + 1) if n not in best]:
        lo = max((best[n] for n in range(miss - 1, 0, -1) if n in best), default=-1)
        hi = min((best[n] for n in range(miss + 1, N_MAX + 1) if n in best),
                 default=len(lines))
        slot = next((j for j in range(lo + 1, hi)
                     if lines[j]["x"] <= head_x and j not in taken), None)
        if slot is not None:
            best[miss] = slot; taken.add(slot)
    return best


def _marker(line: dict, key: str, table=None) -> bool:
    """Does this line open a choice?  Bare markers count: when the choices are
    laid out as a table the ア sits alone in its own cell."""
    t = line["text"].strip()
    return bool(t) and t[0] in (table or ALIAS)[key]


def _multicolumn(body: list[dict]) -> bool:
    """Does this choice's text sit in two separate columns of a table?"""
    xs = [l["x"] for l in body[1:]]
    return bool(xs) and max(xs) - min(xs) > 0.15


def _bare(line: dict) -> bool:
    """A marker alone on its line — the choice body is table artwork."""
    return len(line["text"].strip()) == 1


def _consistent(block: list[dict], idx: list[int]) -> bool:
    xs = [block[j]["x"] for j in idx]
    ys = [block[j]["y"] for j in idx]
    base = min(xs)
    # Single column: every marker sits in the same 1.3%-of-page-wide gutter.
    # Continuation lines are indented about twice that, so they fall out here.
    if max(xs) - base < 0.013:
        return True
    # 2- or 4-across: markers share a baseline band and step to the right.
    rows = len({round(y / 0.02) for y in ys})
    return (rows < 4
            and all(b >= a - 0.012 for a, b in zip(ys, ys[1:]))
            and all(x >= base - 0.013 for x in xs))


def _assign(block: list[dict], cands: dict[str, list[int]]) -> list[int] | None:
    for e in reversed(cands["エ"]):
        for u in reversed([j for j in cands["ウ"] if j < e]):
            for i in reversed([j for j in cands["イ"] if j < u]):
                for a in reversed([j for j in cands["ア"] if j < i]):
                    if _consistent(block, [a, i, u, e]):
                        return [a, i, u, e]
    return None


def find_markers(block: list[dict], flags: list[str], inferred: set) -> list[int] | None:
    """Indices of the ア/イ/ウ/エ markers.

    Both a wrapped choice ("…マルウェ" / "ア感染を検知する。") and a figure label
    ("アプリケーション層") look exactly like an ア marker in the text alone, so
    candidates are searched as a whole assignment and kept only when the four
    line up in a column — or in a proper multi-column row.
    """
    def candidates(table):
        return {k: [j for j in range(1, len(block)) if _marker(block[j], k, table)]
                for k in CHOICE_KEYS}

    # Real marker glyphs win over the digit stand-ins; only fall back if the
    # strict reading cannot produce a consistent set of four.
    cands = candidates(ALIAS)
    for table in (STRONG, ALIAS):
        strict = candidates(table)
        if all(strict.values()):
            got = _assign(block, strict)
            if got:
                return got

    # Vision sometimes drops the marker glyph itself, leaving the choice text
    # starting one full-width character further in than a wrapped line would.
    for n, miss in enumerate(CHOICE_KEYS):
        others = {k: v for k, v in cands.items() if k != miss}
        if not all(others.values()):
            continue
        partial = _assign_partial(block, cands, miss)
        if partial:
            flags.append(f"選択肢{miss}のマーカーが読めず位置から補完")
            inferred.add(miss)
            return partial
    return None


def _assign_partial(block, cands, miss):
    keys = [k for k in CHOICE_KEYS if k != miss]
    n = CHOICE_KEYS.index(miss)
    combos = [[]]
    for k in keys:
        combos = [c + [j] for c in combos for j in reversed(cands[k])
                  if not c or j > c[-1]]
        if len(combos) > 400:
            combos = combos[:400]
    for combo in combos:
        cols = [block[j]["x"] for j in combo]
        lo = combo[n - 1] if n else 0
        hi = combo[n] if n < len(combo) else len(block)
        span = list(range(lo + 1, hi))
        # Three ways a marker goes missing, most specific first: the glyph was
        # dropped and the text starts a character further right; the glyph was
        # misread into something unrecognisable but still sits in the column;
        # or the whole line landed somewhere only its position can vouch for.
        slot = next((j for j in span
                     if any(c + 0.028 <= block[j]["x"] <= c + 0.052 for c in cols)), None)
        if slot is None:
            slot = next((j for j in span
                         if any(abs(block[j]["x"] - c) <= 0.013 for c in cols)), None)
        if slot is None:
            slot = next((j for j in span
                         if block[j]["x"] >= min(cols) - 0.013), None)
        if slot is None:
            continue
        idx = combo[:n] + [slot] + combo[n:]
        # Judge the layout on the markers actually seen — the recovered one is
        # a full glyph-width to their right by definition.
        if all(a < b for a, b in zip(idx, idx[1:])) and _consistent(block, combo):
            return idx
    return None


def _widest_gap(block: list[dict]) -> int:
    """Where the prose stops and the artwork starts: the tallest vertical hole
    in the first part of the block."""
    best, best_gap = len(block), 0.0
    limit = max(2, int(len(block) * 0.7))
    for i in range(1, limit):
        a, b = block[i - 1], block[i]
        if b["page"] != a["page"]:
            continue
        gap = b["y"] - (a["y"] + a["h"])
        if gap > best_gap:
            best, best_gap = i, gap
    return best if best_gap > 0.02 else min(3, len(block))


def split_figure(qblock: list[dict], base_x: float):
    """Peel a figure/table off the tail of the question-text lines.

    Two things mark the boundary, and whichever comes first wins: a line
    indented far past the prose column, or — once the prose has finished — one
    or two characters set at a different indent. The latter is a column label
    of the table below ("a b c d") or the numerator of 選択肢ア's fraction, and
    it always precedes the wide line that gives the artwork away.
    """
    for n in range(1, len(qblock)):
        prev, ln = qblock[n - 1], qblock[n]
        t = ln["text"].strip()
        if ln["x"] > base_x + 0.15 or CAPTION.match(ln["text"]):
            # The wide line may be the second cell of a header row whose first
            # cell is barely indented ("第1正規形 | 第2正規形 | …"). Back up over
            # anything sharing its baseline so the row is not cut in half.
            while (n > 1 and qblock[n - 1]["page"] == ln["page"]
                   and abs(qblock[n - 1]["y"] - ln["y"]) <= max(ln["h"], 0.008)):
                n -= 1
            return qblock[:n], qblock[n:]
        if (len(t) <= 2 and not ENDS_SENTENCE.search(t)
                and ENDS_SENTENCE.search(prev["text"])
                and abs(ln["x"] - prev["x"]) > 0.03):
            return qblock[:n], qblock[n:]
    return qblock, []


def split_choices(block: list[dict], flags: list[str], inferred: set):
    """Return (question_lines, {key: [lines]}, figure_lines)."""
    idx = find_markers(block, flags, inferred)
    if idx is None:
        # The choices are drawn (B+木, アローダイアグラム, ○ の表) and even the
        # markers did not survive OCR. Keep the prose, hand the whole choice
        # area over as one image, and let the reader pick ア〜エ from it.
        flags.append("選択肢を特定できず、選択肢領域を丸ごと画像化")
        cut = _widest_gap(block)
        return block[:cut], {}, block[cut:], [], False
    qlines, figure = split_figure(block[:idx[0]], block[0]["x"])
    choices: dict[str, list[dict]] = {}
    for n, key in enumerate(CHOICE_KEYS):
        start = idx[n]
        stop = idx[n + 1] if n + 1 < len(idx) else len(block)
        body = [block[start]]
        for j in range(start + 1, stop):
            ln = block[j]
            if ln["x"] < block[start]["x"] - 0.012:
                continue
            # Stop at a jump too large to be the next line of the same answer:
            # the page number at the foot of the sheet is indented like a
            # continuation and would otherwise be swallowed by 選択肢エ.
            prev = body[-1]
            if ln["page"] == prev["page"] and ln["y"] - (prev["y"] + prev["h"]) > 0.08:
                break
            body.append(ln)
        choices[key] = body
    used = {id(l) for ls in choices.values() for l in ls}
    used |= {id(l) for l in qlines} | {id(l) for l in figure}
    spare = [(n, l) for n, l in enumerate(block) if id(l) not in used]
    # Unclaimed lines still inside the choice run are artwork; anything past the
    # final choice is the booklet's back matter (メモ用紙, 注意事項, 商標表示).
    inter = [l for n, l in spare if idx[0] < n < idx[-1]]
    figure += [l for n, l in spare if n < idx[-1]]
    trailing = [l for n, l in spare if n > idx[-1]]
    return qlines, choices, figure, trailing, bool(inter)


def join(lines: list[dict]) -> str:
    """Concatenate wrapped OCR lines back into one run of prose."""
    parts = [norm(l["text"]) for l in lines]
    out = ""
    for part in parts:
        if not part:
            continue
        if out and out[-1].isascii() and out[-1].isalnum() \
                and part[0].isascii() and part[0].isalnum():
            out += " "
        out += part
    return apply_fixes(out.strip())


def parse(sid: str) -> list[dict]:
    lines = load(sid)
    heads = find_headings(lines)
    # メモ用紙 and the 注意事項 sheet sit after the last question; keeping them
    # would let the final choice swallow the whole back matter.
    if heads:
        idxs = list(heads.values())
        span = range(min(lines[i]["page"] for i in idxs),
                     max(lines[i]["page"] for i in idxs) + 1)
        keep = [n for n, l in enumerate(lines) if l["page"] in span]
        remap = {old: new for new, old in enumerate(keep)}
        lines = [lines[n] for n in keep]
        heads = {no: remap[i] for no, i in heads.items() if i in remap}
    if len(heads) != N_MAX:
        print(f"  ! {sid}: 見出し {len(heads)}/{N_MAX} 件しか検出できず")
    order = sorted(heads)
    out = []
    for k, no in enumerate(order):
        hi = heads[no]
        end = heads[order[k + 1]] if k + 1 < len(order) else len(lines)
        block = lines[hi:end]
        # Where the artwork is allowed to reach. A drawing carries almost no
        # text, so its true bottom is invisible to OCR; the next question is
        # the only hard stop there is.
        nxt = lines[end] if end < len(lines) else None
        limit = ({"page": nxt["page"], "y": nxt["y"] - 0.014}
                 if nxt and nxt["page"] == block[-1]["page"]
                 else {"page": block[-1]["page"], "y": 0.93})
        m = HEAD.match(block[0]["text"])
        flags: list[str] = []
        if m is None:
            flags.append("見出し行を認識できず位置から補完")
        elif not m.group(1).startswith(str(no)):
            flags.append(f"見出し番号の誤認識（『{m.group(1)}』と読めた）")
        stripped = dict(block[0])
        stripped["text"] = re.sub(rf"^[問間]\s*{no}\s*", "", block[0]["text"], count=1)
        block = [stripped] + block[1:]
        inferred: set = set()
        qlines, choices, figure, trailing, interleaved = split_choices(
            block, flags, inferred)
        # Artwork between the markers means the choices themselves are drawn.
        # A bare marker on its own proves nothing — OCR splits one off in an
        # ordinary four-across row too — so it only counts when the text that
        # came out is unusable: empty, or a table row whose cells collapsed
        # into one string with the columns lost.
        def body_text(key, v):
            raw = join(v)
            if key not in inferred:
                raw = raw[1:]                     # the marker was read; drop it
            elif raw[:1] and (raw[0] in ALIAS[key] or not KEEPS_FIRST.match(raw[0])):
                # The marker was recovered from position, so the text may or may
                # not still carry a glyph for it. Cut only a marker or a stray
                # symbol — a letter or digit there is the answer ("Java").
                raw = raw[1:]
            return norm(raw.lstrip(" 　"))

        bare = bool(choices) and any(_bare(v[0]) for v in choices.values())
        blank = [k for k, v in choices.items() if not body_text(k, v)]
        broken = bool(blank) or any(_multicolumn(v) for v in choices.values())
        table_choices = bool(choices) and (interleaved or (bare and broken))
        if blank and not table_choices:
            # An option came out empty and there are no per-choice crops, so the
            # reader has to work from the scan. Widen the figure to the whole
            # choice area — a crop that stops after 選択肢ア is unanswerable.
            seen = {id(l) for l in figure}
            figure = figure + [l for k in CHOICE_KEYS for l in choices.get(k, [])
                               if id(l) not in seen]

        text = join(qlines)
        # Strip the marker glyph only where one was actually read: a marker
        # recovered from position never appeared in the text, so cutting a
        # character there would eat the answer ("Java" → "ava").
        ch = ({key: body_text(key, v) for key, v in choices.items()}
              if choices else {})
        if choices and any(not v for v in ch.values()):
            flags.append("空の選択肢がある")
        if table_choices:
            flags.append("選択肢が表形式（画像化）")
        if len(text) < 10:
            flags.append(f"問題文が短すぎる({len(text)}字)")
        hay = text + "\n" + "\n".join(ch.values())
        flags += [label for rx, label in FLAGS if rx.search(hay)]
        mentions = bool(FIGREF.search(text))
        # A pure line drawing yields no OCR lines at all, only a hole in the page.
        holes = []
        seq = qlines + figure + [l for k in CHOICE_KEYS for l in choices.get(k, [])]
        for a, b in zip(seq, seq[1:]):
            if b["page"] == a["page"] and b["y"] - (a["y"] + a["h"]) > 0.05:
                holes.append([a["page"], round(a["y"] + a["h"], 4), round(b["y"], 4)])
        if mentions and not figure and not holes:
            flags.append("本文が図表に言及しているが図表領域を検出できず")
        out.append({
            "no": no, "text": text, "choices": ch,
            "pages": sorted({l["page"] for l in block}),
            "figureLines": [{k: l[k] for k in ("page", "x", "y", "w", "h", "text")}
                            for l in figure],
            "bottomLimit": limit,
            "wholeArea": not choices,
            "choiceBoxes": {k: [{kk: l[kk] for kk in ("page", "x", "y", "w", "h")}
                                for l in v] for k, v in choices.items()},
            # The marker's own box: in a table it sits vertically centred in its
            # row, which is the only reliable anchor for cropping that row.
            "markerBoxes": {k: {kk: v[0][kk] for kk in ("page", "x", "y", "w", "h")}
                            for k, v in choices.items() if v},
            "tableChoices": table_choices,
            "mentionsFigure": mentions,
            "holes": holes,
            "trailingDropped": len(trailing),
            "needsFigure": bool(figure) or bool(holes),
            "flags": flags,
        })
    return out


def main() -> None:
    targets = targets_of(sys.argv[1:])
    result = {}
    for sid in targets:
        qs = parse(sid)
        result[sid] = qs
        nf = sum(1 for q in qs if q["flags"])
        fig = sum(1 for q in qs if q["figureLines"])
        print(f"{sid:9} {len(qs):2}/{N_MAX}  要確認 {nf:2}  図表候補 {fig:2}")
        for q in qs:
            if q["flags"]:
                print(f"    問{q['no']}: {'; '.join(q['flags'])}")
    if rejoined:
        top = sorted(rejoined.items(), key=lambda kv: -kv[1])[:8]
        print(f"\n分断された英単語を解説の語彙で復元 {sum(rejoined.values())} 件: "
              + ", ".join(f"{w}×{n}" for w, n in top))
    if rejected:
        print(f"\n不採用（tesseractのみが読んだ文字）{len(rejected)} 件")
    if recovered:
        print(f"\n第2エンジン(tesseract)から補完した脱落文字 {len(recovered)} 件:")
        for r in recovered:
            print("  ", r)
    if applied:
        print("\n補正辞書の適用:")
        for why, n in sorted(applied.items(), key=lambda kv: -kv[1]):
            print(f"  {n:3} 件  {why}")
    # Merge, so running a single session does not wipe the other eighteen.
    path = build_dir(SECTION) / "parsed.json"
    merged = read_json(path) if path.exists() else {}
    merged.update(result)
    write_json(path, merged)


if __name__ == "__main__":
    main()
