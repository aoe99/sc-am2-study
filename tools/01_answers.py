#!/usr/bin/env python3
"""Stage 1 — pull the official IPA answer key (問1..問25 → ア/イ/ウ/エ).

    python3 tools/01_answers.py [session ...]     # default: all 19
"""
from __future__ import annotations
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (SESSIONS, SESSION_IDS, CHOICE_KEYS, BUILD, pdf_path,
                   pdf_text, clean, write_json)

# PDFKit returns the key table in reading order, one "問 N 記号" per line.
PAIR = re.compile(r"[問間]\s*(\d{1,2})\s*[\s:：]*\s*(ア|イ|ウ|エ)")


def extract(sid: str) -> dict[int, str]:
    txt = clean(pdf_text(pdf_path(sid, "2解答例")))
    found: dict[int, str] = {}
    dupes: list[str] = []
    for m in PAIR.finditer(txt):
        no, key = int(m.group(1)), m.group(2)
        if not 1 <= no <= 25:
            continue
        if no in found and found[no] != key:
            dupes.append(f"問{no}: {found[no]} vs {key}")
        found[no] = key
    if dupes:
        raise SystemExit(f"{sid}: conflicting answers → {dupes}")
    return found


def main() -> None:
    targets = sys.argv[1:] or SESSION_IDS
    out, bad = {}, []
    for sid in targets:
        ans = extract(sid)
        missing = [n for n in range(1, 26) if n not in ans]
        if missing:
            bad.append(f"{sid}: missing 問{missing}")
        out[sid] = {str(n): ans[n] for n in sorted(ans)}
        dist = "".join(f"{k}{sum(1 for v in ans.values() if v == k)} " for k in CHOICE_KEYS)
        print(f"{sid:9} {len(ans):2}/25  分布: {dist}")
    total = sum(len(v) for v in out.values())
    print(f"\n合計 {total} 件 / 期待 {len(targets) * 25} 件"
          f"  {'✓ OK' if total == len(targets) * 25 and not bad else '✗ NG'}")
    for b in bad:
        print("  !", b)
    write_json(BUILD / "answers.json", out)
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
