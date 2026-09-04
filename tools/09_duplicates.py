#!/usr/bin/env python3
"""Phase 2 — group questions that IPA has re-used across sittings.

Exact matches (after normalisation) are grouped automatically and written back
into questions.json as `duplicateGroupId`.  Near-matches are only *reported*,
to data/build/duplicates.md, because deciding whether a reworded question is
"the same question" is a judgement call, not a threshold.

    python3 tools/09_duplicates.py [--apply]
"""
from __future__ import annotations
import difflib, hashlib, re, sys, unicodedata
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import DATA, BUILD, SECTIONS, read_json, write_json

NEAR = 0.82          # report as a near-duplicate at or above this ratio
PREFILTER = 0.55     # cheap 3-gram gate before the expensive comparison


SMALL = str.maketrans("ァィゥェォッャュョヮヵヶ", "アイウエオツヤユヨワカケ")


def canon(s: str) -> str:
    """Fold away everything that varies between reprints of one question.

    Small kana are folded too: IPA prints the same sentence in both sittings,
    so a ィ/イ difference is the OCR disagreeing with itself, not the exam.
    """
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    s = s.translate(SMALL)
    s = re.sub(r"[，、,]", "，", s)
    s = re.sub(r"[。．.]", "。", s)
    s = re.sub(r"[“”\"'`´‘’]", "", s)
    s = re.sub(r"[（）()〔〕\[\]「」【】]", "", s)
    s = re.sub(r"[-–—ー−~〜]", "", s)
    s = re.sub(r"\s+", "", s)
    return s


def key_of(q: dict) -> str:
    body = canon(q["text"]) + "|" + "|".join(canon(c["text"]) for c in q["choices"])
    return hashlib.sha1(body.encode()).hexdigest()[:12]


def grams(s: str) -> set:
    return {s[i:i + 3] for i in range(max(0, len(s) - 2))}


def choice_sim(qa: dict, qb: dict) -> float:
    sims = [difflib.SequenceMatcher(None, canon(ca["text"]), canon(cb["text"])).ratio()
            for ca, cb in zip(qa["choices"], qb["choices"])]
    return sum(sims) / len(sims) if sims else 1.0


def main() -> None:
    doc = read_json(DATA / "questions.json")
    # 午後 is out of scope: IPA writes a fresh case study every sitting, and a
    # 設問 like "本文中の下線①について答えよ" is worded almost identically across
    # ten years without being the same question at all.
    qs = [q for q in doc["questions"]
          if SECTIONS.get(q.get("section", "am2"), {}).get("style") == "choice"]
    order = {s["id"]: n for n, s in enumerate(doc["sessions"])}
    byid = {q["id"]: q for q in qs}

    # Group on the question text, then confirm with the choices.  Keying on the
    # choices as well would split real re-runs apart, because a single ィ/イ that
    # the OCR read differently in two sittings is enough to break a hash.
    # 午前I and 午前II are different papers; only group within a section.
    bytext: dict[tuple, list[dict]] = defaultdict(list)
    for q in qs:
        bytext[(q.get("section", "am2"), canon(q["text"]))].append(q)

    parent: dict[str, str] = {q["id"]: q["id"] for q in qs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    restems = []          # same stem, different options — a different question
    for members in bytext.values():
        if len(members) < 2:
            continue
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                qa, qb = members[a], members[b]
                if choice_sim(qa, qb) >= 0.9 and qa["answer"] == qb["answer"]:
                    union(qa["id"], qb["id"])
                else:
                    restems.append((qa["id"], qb["id"]))

    clusters: dict[str, list[dict]] = defaultdict(list)
    for q in qs:
        clusters[find(q["id"])].append(q)
    reused = {k: v for k, v in clusters.items() if len(v) > 1}

    gid = {}
    for n, (k, members) in enumerate(sorted(reused.items(),
                                            key=lambda kv: (-len(kv[1]), kv[0])), 1):
        members.sort(key=lambda q: order[q["sessionId"]])
        for q in members:
            gid[q["id"]] = f"grp-{n:04d}"

    # Near-duplicates: same question, reworded or with a choice swapped out.
    texts = {q["id"]: canon(q["text"]) for q in qs}
    gset = {qid: grams(t) for qid, t in texts.items()}
    ids = [q["id"] for q in qs]
    byid = {q["id"]: q for q in qs}
    near = []
    for a in range(len(ids)):
        ia = ids[a]
        for b in range(a + 1, len(ids)):
            ib = ids[b]
            if byid[ia].get("section") != byid[ib].get("section"):
                continue
            if gid.get(ia) and gid.get(ia) == gid.get(ib):
                continue
            ga, gb = gset[ia], gset[ib]
            if not ga or not gb:
                continue
            j = len(ga & gb) / len(ga | gb)
            if j < PREFILTER:
                continue
            r = difflib.SequenceMatcher(None, texts[ia], texts[ib]).ratio()
            if r >= NEAR:
                near.append((round(r, 3), ia, ib))
    near.sort(reverse=True)

    # Two sittings printing the same question is a free proofreading pass: where
    # the extracted choices disagree, one of the two readings is an OCR error.
    same_text = defaultdict(list)
    for q in qs:
        same_text[(q.get("section", "am2"), canon(q["text"]))].append(q)
    conflicts = []
    for members in same_text.values():
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                qa, qb = members[a], members[b]
                for ca, cb in zip(qa["choices"], qb["choices"]):
                    xa, xb = canon(ca["text"]), canon(cb["text"])
                    if xa == xb or not xa or not xb:
                        continue
                    r = difflib.SequenceMatcher(None, xa, xb).ratio()
                    if r < 0.85:
                        continue
                    sm = difflib.SequenceMatcher(None, ca["text"], cb["text"])
                    for tag, i1, i2, j1, j2 in sm.get_opcodes():
                        if tag == "equal":
                            continue
                        conflicts.append((qa["id"], qb["id"], ca["key"],
                                          ca["text"][i1:i2], cb["text"][j1:j2],
                                          ca["text"][max(0, i1 - 12):i2 + 12]))
    cl = ["# 回をまたいだ突き合わせ（OCR校正用）", "",
          "同じ問題が複数の回に出題されているため、抽出結果が食い違う箇所は"
          "**どちらかが誤読**。ページ画像を見てどちらが正しいか決めること。", "",
          f"- 検出 {len(conflicts)} 箇所", ""]
    for ida, idb, key, xa, xb, ctx in conflicts:
        cl.append(f"- `{ida}` 選択肢{key}: **{xa or '(なし)'}** ↔ "
                  f"**{xb or '(なし)'}**  （`{idb}` と比較）  … {ctx} …")
    (BUILD / "cross-check.md").write_text("\n".join(cl), encoding="utf-8")
    print(f"回またぎの不一致: {len(conflicts)} 箇所  → data/build/cross-check.md")

    counts = sorted((len(v) for v in reused.values()), reverse=True)
    uniq = len(qs) - sum(len(v) - 1 for v in reused.values())
    print(f"{len(qs)} 問中、再出題 {len(reused)} グループ / 実質 {uniq} 問")
    print(f"同じ設問文で選択肢が異なる（別問題として扱う）: {len(restems)} 組")
    print(f"最多再出題: {counts[0] if counts else 0} 回")
    print(f"2回={counts.count(2)}  3回={counts.count(3)}  4回以上={sum(1 for c in counts if c >= 4)}")
    print(f"類似候補（{NEAR}以上・要判断）: {len(near)} 組")

    lines = ["# 重複問題の検出結果", "",
             f"- 全 {len(qs)} 問 / 完全一致グループ {len(reused)} / 実質 {uniq} 問",
             f"- 類似候補 {len(near)} 組（下記）。**同一問題とみなすかは判断が要るので自動統合していない。**", ""]
    if restems:
        lines += ["## 同じ設問文だが選択肢が異なる（統合していない）", "",
                  "IPA が設問文を流用して選択肢を差し替えた例。正解が変わるので"
                  "別問題として扱っている。", ""]
        for ia, ib in restems:
            lines.append(f"- `{ia}`（正解{byid[ia]['answer']}） ↔ "
                         f"`{ib}`（正解{byid[ib]['answer']}）  {byid[ia]['text'][:70]}")
        lines.append("")
    if reused:
        lines += ["## 再出題（自動でグループ化済み）", ""]
        for k, members in sorted(reused.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            g = gid[members[0]["id"]]
            first, *again = members
            lines.append(f"### {g}  ×{len(members)}")
            back = ", ".join("{} 問{}".format(m["sessionId"], m["no"]) for m in again)
            lines.append("初出: **{} 問{}**  /  再出題: {}".format(
                first["sessionId"], first["no"], back))
            lines += ["", "```", first["text"][:200], "```", ""]
    if near:
        lines += ["## 類似候補（人間の判断待ち）", "",
                  "同一とみなすなら `tools/duplicate_overrides.json` の `merge` に、"
                  "別問題なら `split` に id 組を書き足すこと。", ""]
        for r, ia, ib in near:
            qa, qb = byid[ia], byid[ib]
            lines += [f"### 類似度 {r}  —  {ia} ↔ {ib}", "",
                      f"- {ia}: {qa['text'][:120]}",
                      f"- {ib}: {qb['text'][:120]}",
                      f"- 正解: {qa['answer']} / {qb['answer']}", ""]
    (BUILD / "duplicates.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  → data/build/duplicates.md")

    if "--apply" in sys.argv:
        for q in qs:
            q["duplicateGroupId"] = gid.get(q["id"])
        write_json(DATA / "questions.json", doc)


if __name__ == "__main__":
    main()
