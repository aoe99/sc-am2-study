#!/usr/bin/env python3
"""Stage 7 — a local proofreading page: extracted text beside the page scan.

Deliberately writes a plain local file (never published anywhere) because the
問題冊子 and the 読者特典 解説 are both copyrighted.

    python3 tools/07_review_html.py [session ...]
"""
from __future__ import annotations
import html, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import SESSION_IDS, DATA, BUILD, read_json

CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#e0e0e0;--warn:#b45309;--ok:#047857;--accent:#1d4ed8}
@media(prefers-color-scheme:dark){:root{--bg:#161616;--fg:#e8e8e8;--mut:#9a9a9a;--line:#333;--warn:#fbbf24;--ok:#34d399;--accent:#93c5fd}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.75 -apple-system,"Hiragino Sans","Noto Sans JP",sans-serif}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:14px 20px;z-index:5}
h1{font-size:17px;margin:0} .sub{color:var(--mut);font-size:13px;margin-top:4px}
main{max-width:1500px;margin:0 auto;padding:20px}
.q{display:grid;grid-template-columns:1fr 1fr;gap:24px;border-top:1px solid var(--line);padding:26px 0}
@media(max-width:1000px){.q{grid-template-columns:1fr}}
.no{font-weight:700;font-size:15px}
.badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--mut);margin-left:6px}
.warn{color:var(--warn);border-color:var(--warn)} .ok{color:var(--ok);border-color:var(--ok)}
.text{margin:10px 0 14px;white-space:pre-wrap}
ol.ch{list-style:none;padding:0;margin:0}
ol.ch li{display:flex;gap:10px;padding:5px 8px;border-radius:6px}
ol.ch li.correct{background:color-mix(in srgb,var(--ok) 14%,transparent);font-weight:600}
ol.ch li .k{flex:0 0 1.6em;color:var(--mut)}
.exp{margin-top:14px;padding:12px 14px;border-left:3px solid var(--accent);background:color-mix(in srgb,var(--accent) 7%,transparent);white-space:pre-wrap;font-size:14.5px}
.src{color:var(--mut);font-size:11.5px;margin-top:8px}
figure{margin:12px 0}figure img{max-width:100%;border:1px solid var(--line);border-radius:6px}
.scan img{width:100%;border:1px solid var(--line);border-radius:8px}
.tags span{font-size:11.5px;color:var(--mut);border:1px solid var(--line);border-radius:99px;padding:1px 8px;margin-right:5px}
"""


def render(sid: str) -> Path:
    doc = read_json(DATA / "questions.json")
    qs = [q for q in doc["questions"] if q["sessionId"] == sid]
    label = next(s["label"] for s in doc["sessions"] if s["id"] == sid)
    out = [f"<!doctype html><meta charset=utf-8><title>{sid} 校正</title>",
           f"<style>{CSS}</style>",
           f"<header><h1>{label} 午前II — 抽出結果の校正</h1>",
           f"<div class=sub>{len(qs)} 問  /  要確認 "
           f"{sum(1 for q in qs if q['needsReview'])} 問  /  左=抽出テキスト  右=元のページ画像</div></header><main>"]
    for q in qs:
        badges = ""
        if q["needsReview"]:
            badges += '<span class="badge warn">要確認</span>'
        if q["figures"]:
            badges += '<span class="badge">図表あり</span>'
        if q.get("shortText"):
            badges += '<span class="badge">短文</span>'
        out.append(f'<section class=q><div><div class=no>問{q["no"]}{badges}</div>')
        out.append(f'<div class=tags>{"".join(f"<span>{html.escape(t)}</span>" for t in q["tags"])}</div>')
        out.append(f'<div class=text>{html.escape(q["text"])}</div>')
        for f in q["figures"]:
            out.append(f'<figure><img src="../{f}" alt=""></figure>')
        out.append("<ol class=ch>")
        for c in q["choices"]:
            cls = " class=correct" if c["key"] == q["answer"] else ""
            cf = q["choiceFigures"].get(c["key"])
            body = (f'<img src="../{cf}" alt="" style="max-width:100%">' if cf
                    else html.escape(c["text"]))
            out.append(f'<li{cls}><span class=k>{c["key"]}</span>'
                       f'<span>{body}</span></li>')
        out.append("</ol>")
        out.append(f'<div class=exp>{html.escape(q["explanation"])}</div>')
        out.append(f'<div class=src>正解 {q["answer"]}  /  出典: {q["explanationSource"]}'
                   f'  /  {q["source"]["questionPdf"]} p.{q["source"]["page"]}</div>')
        out.append(f'</div><div class=scan><img src="../{q["source"]["pageImage"]}" alt=""></div></section>')
    out.append("</main>")
    path = BUILD / f"review-{sid}.html"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main() -> None:
    for sid in (sys.argv[1:] or SESSION_IDS):
        p = render(sid)
        print(f"  → {p.relative_to(Path(__file__).resolve().parent.parent)}")


if __name__ == "__main__":
    main()
