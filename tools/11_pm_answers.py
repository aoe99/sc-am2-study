#!/usr/bin/env python3
"""Stage 11 — 午後の解答例PDF から設問の骨格と解答例を取り出す。

This is the load-bearing stage of the whole 午後 pipeline.  The 問題冊子 is a
scan and has to be OCR'd, but the 解答例 has a text layer, and it is laid out as
a table whose rows *are* the question structure:

    設問 解答例・解答の要点 備考
    設問１ a できない
    b できない
    設問２ (1) ロール管理
    (2) c タスク名

So the skeleton — which 設問 exist, which 小問 each has, which 空欄 each of those
fills — is read from here first, and stage 14 then goes looking for those same
markers in the OCR'd 問題文.  Deriving the structure from clean text and matching
it into noisy text is far steadier than trying to parse the prose blind.

An item is one 設問+小問 pair, not one 空欄: 設問3(1) with six blanks c..h is one
thing you sit down and answer.  Its blanks are its `parts`, which is what lets a
half-right answer be graded △ rather than forced to ○ or ×.

    python3 tools/11_pm_answers.py [session ...]
"""
from __future__ import annotations
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (PM_PAPERS, build_dir, clean, pdf_path, pdf_text, pm_papers_of,
                   read_json, strip_ruby, targets_of, write_json)

# One 大問 per "問N" heading standing alone on its line.
CASE = re.compile(r"^[問間]\s*([0-9０-９]{1,2})\s*$", re.M)
TABLE_HEAD = re.compile(r"^設問\s*解答例・解答の要点\s*備考\s*$")
INTENT_HEAD = re.compile(r"^出題趣旨\s*$")

# Page furniture, repeated on every sheet.
NOISE = [
    re.compile(r"^\d+\s*/\s*\d+$"),
    re.compile(r"^©\s*\d{4}.*$"),
    re.compile(r"^(令和|平成).*(解答例|採点講評)\s*$"),
    re.compile(r"^午後[ⅠⅡI]*\s*試験\s*$"),
    re.compile(r"^設問\s*解答例・解答の要点\s*備考\s*$"),
]

SETSU = re.compile(r"^設問\s*([0-9０-９]{1,2})\s*")
SUB = re.compile(r"^[(（]\s*([0-9０-９]{1,2})\s*[)）]\s*")
BULLET = re.compile(r"^[・･]\s*")
# 空欄 labels: latin a..z, katakana ア..ン, circled ①..⑳, and hiragana — but only
# あ〜こ. IPA enumerates blanks あ, い, う…, never に or っ; allowing every kana
# turned a continuation line opening with a particle ("に入れる…") into a blank
# of its own and put an input box labelled "に" on the answer form.
# Spelled out rather than a range: [あ-こ] would also take が and ぐ.
KANA_LABEL = "あいうえおかきくけこ"
# Lower case only. IPA labels its blanks a, b, c…, never A or B, and a capital
# at the head of an answer is the first letter of a name the exam invented —
# "B コインを攻撃者に移転する" came out as blank B answered "コインを…", and the
# answer form then asked for a 空欄 B that does not exist. 30 labels were wrong
# this way (A社, L社, Sサービス, Xサービス…).
LABEL = re.compile(rf"^([a-zａ-ｚ{KANA_LABEL}ア-ン][)）]?|[①-⑳])\s+(?=\S)")
LABEL_ALONE = re.compile(rf"^([a-zａ-ｚ{KANA_LABEL}ア-ン]|[①-⑳])\s*$")
# A second 空欄 opening midway through a line: "d イ e カ".  Only latin and
# hiragana are split on — katakana in that position is usually the answer.
INLINE_LABEL = re.compile(rf"\s+([a-zａ-ｚ{KANA_LABEL}])\s+(?=\S)")
# The 備考 column carries these; PDFKit flattens them onto a line of their own.
REMARK = re.compile(r"^(順不同|全て順不同|各順不同|別解|.{0,12}も可|.{0,20}でも可)\s*$")

# An answer that already reads as complete: a 記号, a bare number, or a
# sentence that has reached its 。
FINISHED = re.compile(r"^(?:[ア-ン](?:\s*[，,、]\s*[ア-ン])*|[0-9０-９]{1,4}"
                      r"|.{4,}。)$")

# "利点 誤検知による…" — a short lead-in with no punctuation, then the answer.
PHRASE_LABEL = re.compile(r"^([^\s。，、]{1,10}(?:\s?[0-9０-９]{1,2})?)\s+(\S.*)$")

MARKER = r"[ア-ン]"
ONLY_MARKERS = re.compile(rf"^[（(]?{MARKER}[）)]?(?:\s*[，,、]\s*[（(]?{MARKER}[）)]?)*$")

FW = str.maketrans("０１２３４５６７８９", "0123456789")


def digits(s: str) -> int:
    return int(s.translate(FW))


def strip_noise(block: str) -> list[str]:
    out = []
    for ln in block.split("\n"):
        ln = ln.strip()
        if not ln or any(p.match(ln) for p in NOISE):
            continue
        out.append(ln)
    return out


def kind_of(answer: str) -> str:
    """How this answer can be marked.

    記号 can be compared outright; a short phrase survives normalising; anything
    with a sentence in it only a human can judge.
    """
    a = answer.strip()
    if ONLY_MARKERS.match(a):
        return "choice"
    if len(a) <= 20 and "。" not in a:
        return "term"
    return "essay"


class Item:
    def __init__(self, setsu: int, sub: int | None):
        self.setsu, self.sub = setsu, sub
        self.parts: list[dict] = []
        self.remarks: list[str] = []
        self.flags: list[str] = []

    def part(self, label: str | None) -> dict:
        p = {"label": label, "answer": "", "options": []}
        self.parts.append(p)
        return p

    def current(self) -> dict:
        return self.parts[-1] if self.parts else self.part(None)

    def as_dict(self) -> dict:
        parts = []
        for p in self.parts:
            ans = tidy(p["answer"])
            opts = [tidy(o) for o in p["options"] if tidy(o)]
            # A part written only as bullets has no answer line of its own.
            if not ans and opts:
                ans = opts[0]
            parts.append({"label": p["label"], "answer": ans,
                          "options": opts, "kind": kind_of(ans)})
        parts = [p for p in parts if p["answer"] or p["options"]]
        kinds = {p["kind"] for p in parts}
        kind = ("essay" if "essay" in kinds
                else "term" if "term" in kinds
                else "choice" if kinds else "essay")
        return {
            "setsu": self.setsu, "sub": self.sub,
            "label": f"設問{self.setsu}" + (f"({self.sub})" if self.sub else ""),
            "parts": parts, "kind": kind,
            "remarks": self.remarks, "flags": self.flags,
        }


def tidy(s: str) -> str:
    """Rejoin the answer's hard wraps; CJK takes no space at the seam."""
    return BULLET.sub("", clean(s).replace("\n", "").strip())


def join(prev: str, add: str) -> str:
    if not prev:
        return add
    sep = " " if (prev[-1].isascii() and prev[-1].isalnum()
                  and add[:1].isascii() and add[:1].isalnum()) else ""
    return prev + sep + add


def parse_table(lines: list[str]) -> list[dict]:
    items: list[Item] = []
    cur: Item | None = None
    setsu = 0

    def open_item(sub: int | None) -> None:
        nonlocal cur
        cur = Item(setsu, sub)
        items.append(cur)

    for raw in lines:
        line = raw
        opened = False
        m = SETSU.match(line)
        if m:
            setsu = digits(m.group(1))
            line = line[m.end():].strip()
            open_item(None)
            opened = True
        m = SUB.match(line)
        if m:
            sub = digits(m.group(1))
            if opened:
                cur.sub = sub
            else:
                open_item(sub)
                opened = True
            line = line[m.end():].strip()
        if cur is None:
            continue                       # stray text before the first 設問
        if not line:
            continue
        if REMARK.match(line) and cur.parts:
            cur.remarks.append(line)
            continue
        if BULLET.match(line):
            cur.current()["options"].append(BULLET.sub("", line))
            continue
        m = LABEL_ALONE.match(line)
        if m:
            # "①" on a line of its own opens a slot whose answers follow as
            # bullets underneath.
            cur.part(m.group(1))
            continue
        m = LABEL.match(line)
        if m and not ONLY_MARKERS.match(line):
            p = cur.part(m.group(1).rstrip(")）"))
            rest = line[m.end():].strip()
            # "d イ e カ" is two blanks flattened onto one row.
            while True:
                m2 = INLINE_LABEL.search(rest)
                if not m2:
                    break
                p["answer"] = join(p["answer"], rest[:m2.start()].strip())
                p = cur.part(m2.group(1))
                rest = rest[m2.end():].strip()
            p["answer"] = join(p["answer"], rest)
            continue
        p = cur.current()
        if p["options"]:
            p["options"][-1] = join(p["options"][-1], line)
        else:
            # A row whose label is a phrase rather than a letter ("利点 …" /
            # "内容 …", "作成時 …" / "更新時 …") is flattened onto the line below
            # its neighbour, and nothing in the text tells it apart from an
            # answer that simply wrapped — the columns that would have said so
            # are not in the text layer.  A line arriving after an answer that
            # already read as complete is far more often the next row than a
            # continuation, so it opens a part of its own and the item is
            # flagged for the 解説 to settle.
            if FINISHED.match(p["answer"]):
                cur.flags.append(
                    f"表の列を推定: 「{p['answer'][:18]}」の次に「{line[:18]}」")
                m3 = PHRASE_LABEL.match(line)
                # Two-column rows come in pairs, so the row above this one has a
                # lead-in of its own still glued to its answer.
                if m3 and p["label"] is None:
                    m4 = PHRASE_LABEL.match(p["answer"])
                    if m4:
                        p["label"], p["answer"] = m4.group(1), m4.group(2)
                p = cur.part(m3.group(1) if m3 else None)
                line = m3.group(2) if m3 else line
            p["answer"] = join(p["answer"], line)

    return [i.as_dict() for i in items if any(
        p["answer"] or p["options"] for p in i.parts)]


def parse_paper(sid: str, paper: str) -> dict:
    text = strip_ruby(clean(pdf_text(pdf_path(sid, "2解答例", "pm", paper))))
    heads = list(CASE.finditer(text))
    if not heads:
        raise SystemExit(f"{sid}/{paper}: 問N の見出しが見つからない")
    cases = {}
    for i, m in enumerate(heads):
        no = digits(m.group(1))
        block = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        lines = strip_noise(block)
        # 出題趣旨 runs from its heading to the answer table.
        intent, table = [], []
        where = "pre"
        for ln in lines:
            if INTENT_HEAD.match(ln):
                where = "intent"; continue
            if TABLE_HEAD.match(ln) or (where != "table" and ln.startswith("設問")
                                        and SETSU.match(ln)):
                where = "table"
            (table if where == "table" else intent if where == "intent" else []).append(ln)
        cases[str(no)] = {
            "no": no, "paper": paper,
            "intent": tidy(" ".join(intent)),
            "items": parse_table(table),
        }
    return cases


def main() -> None:
    targets = targets_of(sys.argv[1:])
    out, bad = {}, []
    for sid in targets:
        out[sid] = {}
        for paper in pm_papers_of(sid):
            cases = parse_paper(sid, paper)
            want = PM_PAPERS[paper]["cases"]
            if len(cases) != want:
                bad.append(f"{sid}/{paper}: 大問 {len(cases)}/{want}")
            for no, c in cases.items():
                if not c["items"]:
                    bad.append(f"{sid}/{paper} 問{no}: 設問が0件")
                if not c["intent"]:
                    bad.append(f"{sid}/{paper} 問{no}: 出題趣旨なし")
            out[sid][paper] = cases
            n_items = sum(len(c["items"]) for c in cases.values())
            n_parts = sum(len(i["parts"]) for c in cases.values() for i in c["items"])
            kinds = {}
            for c in cases.values():
                for i in c["items"]:
                    kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
            print(f"{sid:9} {PM_PAPERS[paper]['label']:5} 大問{len(cases)}  "
                  f"設問{n_items:3}  空欄{n_parts:3}  "
                  + " ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    total = sum(len(c["items"]) for s in out.values() for p in s.values()
                for c in p.values())
    print(f"\n設問 合計 {total} 件 / {len(targets)} 回")
    for b in bad:
        print("  !", b)
    path = build_dir("pm") / "answers.json"
    merged = read_json(path) if path.exists() else {}
    merged.update(out)
    write_json(path, merged)
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
