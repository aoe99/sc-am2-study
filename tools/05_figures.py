#!/usr/bin/env python3
"""Stage 5 — crop the figure/table artwork of questions that need it.

Regions come from stage 4: the OCR lines that belong to neither the question
prose nor a choice, plus any hole in the page too tall to be line spacing.
Crops are re-rendered straight from the PDF at 300dpi rather than cut out of
the page PNG, so nothing is resampled twice.

    python3 tools/05_figures.py [--section am1|am2] [session ...]
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sclib import (DATA, build_dir, pdf_path, read_json, run_tool, section_of,
                   targets_of, write_json)

FIGDIR = DATA / "figures"
# OCR boxes sit inside the cell borders, so the pad has to clear the rules
# of a table as well as the glyphs.
PAD_X, PAD_Y = 0.08, 0.018
# A band shorter than one printed line above the first choice is not a header.
MIN_HEADER = 0.02
# Artwork often runs wider than the text column, so allow more margin
# than the prose uses before clamping.
MIN_X, MAX_X = 0.035, 0.965


def region(q: dict, with_choices: bool = False) -> tuple[int, float, float, float, float] | None:
    boxes = [(l["page"], l["x"], l["y"], l["x"] + l["w"], l["y"] + l["h"])
             for l in q["figureLines"]]
    if with_choices:
        boxes += [(b["page"], b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
                  for v in q["choiceBoxes"].values() for b in v]
    for pg, top, bot in q["holes"]:
        boxes.append((pg, MIN_X, top, MAX_X, bot))
    if not boxes:
        return None
    page = min(b[0] for b in boxes)
    on = [b for b in boxes if b[0] == page]
    x0 = max(MIN_X, min(b[1] for b in on) - PAD_X)
    y0 = max(0.0, min(b[2] for b in on) - PAD_Y)
    x1 = min(MAX_X, max(b[3] for b in on) + PAD_X)
    y1 = min(1.0, max(b[4] for b in on) + PAD_Y)
    return page, x0, y0, x1 - x0, y1 - y0


def _bands(centres, pad_lo, pad_hi):
    """Split an axis at the midpoints between neighbouring marker centres."""
    edges = [(x + y) / 2 for x, y in zip(centres, centres[1:])]
    lo = [centres[0] - pad_lo] + edges
    hi = edges + [centres[-1] + pad_hi]
    return list(zip(lo, hi))


def choice_rows(q: dict) -> dict:
    """One crop rectangle per choice, for choices that are drawn, not typeset.

    Reading order cannot delimit them: a marker printed in the middle of its
    table cell is emitted *after* the first line of its own row, so grouping by
    the lines a choice owns crops one row too low.  The markers' own centres are
    stable, so the choices are cut at the midpoints between them — down the page
    for stacked rows, across it for four-in-a-line, and both for a 2×2 grid.
    """
    marks = q.get("markerBoxes") or {}
    keys = [k for k in ("ア", "イ", "ウ", "エ") if k in marks]
    if len(keys) < 2:
        return {}
    page = marks[keys[0]]["page"]
    if any(marks[k]["page"] != page for k in keys):
        return {}

    pos = {k: (marks[k]["x"], marks[k]["y"] + marks[k]["h"] / 2) for k in keys}

    # Cluster into visual rows.
    rows = []
    for k in sorted(keys, key=lambda k: pos[k][1]):
        if rows and abs(pos[rows[-1][0]][1] - pos[k][1]) <= 0.012:
            rows[-1].append(k)
        else:
            rows.append([k])
    widths = {len(r) for r in rows}
    if len(widths) != 1:
        return {}          # ragged: a marker was recovered in the wrong place

    def row_boxes(row):
        return [b for k in row for b in q["choiceBoxes"].get(k, [])
                if b["page"] == page]

    boxes = row_boxes(keys)
    ys = [pos[r[0]][1] for r in rows]
    if len(rows) == 1:
        top = min([b["y"] for b in boxes] + ys) - 0.012
        bot = max([b["y"] + b["h"] for b in boxes] + ys) + 0.012
        ybands = [(top, bot)]
    else:
        gap = min(b - a for a, b in zip(ys, ys[1:]))
        content = sorted(
            ([b for k in keys for b in q["choiceBoxes"].get(k, []) if b["page"] == page]
             + [l for l in q["figureLines"] if l["page"] == page]),
            key=lambda b: b["y"])
        if gap > 0.10:
            # Tall cells: the marker labels the top-left of a drawing, so each
            # band runs from its own marker down to the next one. Splitting at
            # the midpoint would cut every diagram in half.
            ybands = [(a - 0.014, b - 0.014) for a, b in zip(ys, ys[1:])]
            ybands.append((ys[-1] - 0.014, min(1.0, ys[-1] + gap - 0.014)))
        else:
            # Short rows of a table. The marker is centred in its row, but the
            # rows are not the same height — 選択肢エ may run to four lines while
            # 選択肢イ is one — so halving the distance between two markers lands
            # inside the taller row and clips its first line. Cut instead at the
            # widest blank band between the two markers, which is the rule the
            # printed table is drawn on.
            edges = []
            for a, b in zip(ys, ys[1:]):
                between = [c for c in content if a < c["y"] + c["h"] / 2 < b]
                best, best_gap = (a + b) / 2, -1.0
                for lo_box, hi_box in zip(between, between[1:]):
                    space = hi_box["y"] - (lo_box["y"] + lo_box["h"])
                    if space > best_gap:
                        best_gap, best = space, (lo_box["y"] + lo_box["h"] + hi_box["y"]) / 2
                edges.append(best)
            def outer_edge(boxes, fallback):
                """Blank band separating this row from the header above it."""
                boxes = sorted(boxes, key=lambda b: b["y"])
                if not boxes:
                    return fallback
                best, best_gap = boxes[0]["y"] - 0.008, 0.0
                for lo_box, hi_box in zip(boxes, boxes[1:]):
                    space = hi_box["y"] - (lo_box["y"] + lo_box["h"])
                    if space > best_gap and space > 0.004:
                        best_gap = space
                        best = (lo_box["y"] + lo_box["h"] + hi_box["y"]) / 2
                return best

            head = edges[0] if edges else ys[-1] + gap
            tail = edges[-1] if edges else ys[0] - gap
            top0 = outer_edge([c for c in content if c["y"] + c["h"] / 2 < head],
                              ys[0] - gap / 2)
            below = [c for c in content if c["y"] + c["h"] / 2 > tail]
            last = max([c["y"] + c["h"] for c in below] or [ys[-1]])
            ybands = list(zip([top0] + edges, edges + [last + 0.008]))

    spread = [b for k in keys for b in q["choiceBoxes"].get(k, []) if b["page"] == page]
    spread += [marks[k] for k in keys]
    spread += [l for l in q["figureLines"] if l["page"] == page]
    table_x = ((max(MIN_X, min(b["x"] for b in spread) - 0.02),
                min(MAX_X, max(b["x"] + b["w"] for b in spread) + 0.02))
               if spread else (MIN_X, MAX_X))

    out = {}
    for row, (top, bot) in zip(rows, ybands):
        ordered = sorted(row, key=lambda k: pos[k][0])
        xs = [pos[k][0] for k in ordered]
        if len(ordered) == 1:
            # One choice per row. A row's own right-hand cells are often
            # absorbed into a neighbouring choice by reading order, so the
            # width comes from every row together — collectively they do cover
            # the table, and a narrow table stays readable instead of being
            # padded out to the full page.
            xbands = [table_x]
        else:
            span = min(b - a for a, b in zip(xs, xs[1:]))
            # Start each crop just left of its own marker, not halfway back,
            # or every choice carries a slab of empty margin.
            xbands = [(x - 0.014, y - 0.014) for x, y in zip(xs, xs[1:])]
            xbands.append((xs[-1] - 0.014, min(MAX_X, xs[-1] + span)))
        for k, (left, right) in zip(ordered, xbands):
            x0, y0 = max(0.0, left), max(0.0, top - 0.004)
            # The band already stops at the midpoint to the next row; padding it
            # further only lets the following row peek in under the crop.
            x1, y1 = min(1.0, right), min(1.0, bot)
            if x1 - x0 <= 0.01 or y1 - y0 <= 0.005:
                return {}
            out[k] = (page, x0, y0, x1 - x0, y1 - y0)
    return out


def main() -> None:
    section = section_of(sys.argv[1:])
    targets = targets_of(sys.argv[1:])
    parsed = read_json(build_dir(section) / "parsed.json")
    index: dict[str, dict] = {}
    for sid in targets:
        pdf = pdf_path(sid, "1問題", section)
        outdir = FIGDIR / sid
        made = 0
        for q in parsed[sid]:
            rows = choice_rows(q) if q.get("tableChoices") else {}
            # The choices are drawn but their rows could not be delimited, so no
            # per-choice crop will exist. One image has to carry all four, or the
            # question cannot be answered at all.
            whole = bool(q.get("tableChoices")) and not rows
            r = region(q, with_choices=whole)
            if r is None:
                continue
            page, x, y, w, h = r
            if rows:
                # Whatever sits inside the choice band is part of a choice, not
                # a separate exhibit: a stray "m" from the denominator of 選択肢ア
                # must not be published again as the question's own figure.
                on_page = [v for v in rows.values() if v[0] == page]
                first = min((v[2] for v in on_page), default=None)
                if first is None:
                    pass                          # rows live elsewhere; keep as is
                elif first - y < MIN_HEADER:
                    continue                      # nothing above the choices
                else:
                    h = min(h, first - y)         # header only; rows crop below
            outdir.mkdir(parents=True, exist_ok=True)
            name = f"{sid}-{section}-{q['no']:02d}.png"
            run_tool("crop", pdf, page, f"{x:.5f}", f"{y:.5f}",
                     f"{w:.5f}", f"{h:.5f}", outdir / name, "--dpi", "300")
            index.setdefault(sid, {})[str(q["no"])] = {
                "choiceFigures": {},
                "file": f"figures/{sid}/{name}",
                "page": page, "rect": [round(v, 5) for v in (x, y, w, h)],
                "ocr": [l["text"] for l in q["figureLines"]],
            }
            made += 1
        # Choices printed as table rows cannot survive as plain text; crop each row.
        tables = 0
        for q in parsed[sid]:
            if not q.get("tableChoices"):
                continue
            outdir.mkdir(parents=True, exist_ok=True)
            entry = index.setdefault(sid, {}).setdefault(
                str(q["no"]), {"choiceFigures": {}})
            entry.setdefault("choiceFigures", {})
            for key, (page, x, y, w, h) in choice_rows(q).items():
                name = f"{sid}-{section}-{q['no']:02d}-{'アイウエ'.index(key)}.png"
                run_tool("crop", pdf, page, f"{x:.5f}", f"{y:.5f}",
                         f"{w:.5f}", f"{h:.5f}", outdir / name, "--dpi", "300")
                entry["choiceFigures"][key] = f"figures/{sid}/{name}"
            tables += 1
        print(f"{sid:9} 図表 {made} 件  表形式選択肢 {tables} 問")
    # Merge, so running a single session does not wipe the other eighteen.
    path = build_dir(section) / "figures.json"
    merged = read_json(path) if path.exists() else {}
    merged.update(index)
    write_json(path, merged)


if __name__ == "__main__":
    main()
