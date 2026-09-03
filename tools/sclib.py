"""Shared helpers for the SC 午前II extraction pipeline."""
from __future__ import annotations
import json, os, re, subprocess, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDFTOOL = ROOT / "bin" / "pdfkit-tool"
DATA = ROOT / "data"
BUILD = DATA / "build"

# Where the IPA/翔泳社 PDFs live. Override with SC_PDF_ROOT.
PDF_ROOT = Path(os.environ.get(
    "SC_PDF_ROOT", Path.home() / "Desktop" / "情報セキュリティSP過去問"))

# id, 和暦ラベル, 西暦, 期, ファイル接頭辞
SESSIONS = [
    ("H28haru", "平成28年度 春期", 2016, "haru", "H28h"),
    ("H28aki",  "平成28年度 秋期", 2016, "aki",  "H28a"),
    ("H29haru", "平成29年度 春期", 2017, "haru", "H29h"),
    ("H29aki",  "平成29年度 秋期", 2017, "aki",  "H29a"),
    ("H30haru", "平成30年度 春期", 2018, "haru", "H30h"),
    ("H30aki",  "平成30年度 秋期", 2018, "aki",  "H30a"),
    ("H31haru", "平成31年度 春期", 2019, "haru", "H31h"),
    ("R01aki",  "令和元年度 秋期",  2019, "aki",  "R01a"),
    ("R02aki",  "令和2年度 秋期",   2020, "aki",  "R02a"),
    ("R03haru", "令和3年度 春期",   2021, "haru", "R03h"),
    ("R03aki",  "令和3年度 秋期",   2021, "aki",  "R03a"),
    ("R04haru", "令和4年度 春期",   2022, "haru", "R04h"),
    ("R04aki",  "令和4年度 秋期",   2022, "aki",  "R04a"),
    ("R05haru", "令和5年度 春期",   2023, "haru", "R05h"),
    ("R05aki",  "令和5年度 秋期",   2023, "aki",  "R05a"),
    ("R06haru", "令和6年度 春期",   2024, "haru", "R06h"),
    ("R06aki",  "令和6年度 秋期",   2024, "aki",  "R06a"),
    ("R07haru", "令和7年度 春期",   2025, "haru", "R07h"),
    ("R07aki",  "令和7年度 秋期",   2025, "aki",  "R07a"),
]
SESSION_IDS = [s[0] for s in SESSIONS]
CHOICE_KEYS = ["ア", "イ", "ウ", "エ"]

# 午前I is the 高度共通 paper (30問50分); 午前II is the SC-specific one (25問40分).
# Both are 4-choice multiple choice with the same booklet layout, so the whole
# pipeline is shared and only these numbers differ.
SECTIONS = {
    "am1": {"code": "1", "dir": "午前I", "label": "午前Ⅰ", "count": 30, "minutes": 50},
    "am2": {"code": "2", "dir": "午前II", "label": "午前Ⅱ", "count": 25, "minutes": 40},
}
DEFAULT_SECTION = "am2"


def section_of(argv) -> str:
    """Pull --section from a stage's argv (default 午前II)."""
    if "--section" in argv:
        v = argv[argv.index("--section") + 1]
        if v not in SECTIONS:
            raise SystemExit(f"unknown section: {v} (expected {list(SECTIONS)})")
        return v
    return DEFAULT_SECTION


def targets_of(argv) -> list:
    """Session ids given on the command line, minus flags and their values."""
    out, i = [], 0
    while i < len(argv):
        if argv[i].startswith("--"):
            i += 2 if argv[i] == "--section" else 1
        else:
            out.append(argv[i]); i += 1
    return out or SESSION_IDS


def build_dir(section: str) -> Path:
    return BUILD / section


def question_count(section: str) -> int:
    return SECTIONS[section]["count"]

# 情報処理安全確保支援士 started 平成29年度春期; before that it was 情報セキュリティスペシャリスト.
def exam_name(sid: str) -> str:
    return ("情報セキュリティスペシャリスト試験"
            if sid in ("H28haru", "H28aki") else "情報処理安全確保支援士試験")


def pdf_path(sid: str, kind: str, section: str = DEFAULT_SECTION) -> Path:
    """kind: '1問題' | '2解答例' | '4教科書解説'"""
    prefix = dict((s[0], s[4]) for s in SESSIONS)[sid]
    sec = SECTIONS[section]
    return PDF_ROOT / sid / f"{prefix}_{sec['code']}_{sec['dir']}_{kind}.pdf"


def run_tool(*args: str) -> str:
    r = subprocess.run([str(PDFTOOL), *map(str, args)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"pdfkit-tool {args[:2]} failed: {r.stderr.strip()}")
    return r.stdout


def pdf_text(path: Path) -> str:
    return run_tool("text", path)


# --- text normalisation -------------------------------------------------

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

def clean(s: str) -> str:
    """Strip control chars and collapse stray whitespace, keeping newlines."""
    s = unicodedata.normalize("NFC", s)
    s = _CTRL.sub("", s)
    s = s.replace("　", " ").replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return s.strip()


def dwidth(s: str) -> int:
    """Display width in columns: full-width glyphs count as two."""
    return sum(2 if unicodedata.east_asian_width(c) in "WFA" else 1 for c in s)


_BLOCK = re.compile(r"^\s*(?:[・●○◆■□▪]|[-–—]\s|\(\d+\)|（\d+）|[0-9０-９]+[\.．]"
                    r"|[ア-ン][\.．)）]|[①-⑳]|[❶-❿]|[㋐-㋾]|[ⅰ-ⅹⅠ-Ⅹ][\.．)）]"
                    r"|【|＜|\[|注\d*[）)]?)")


def unwrap(s: str) -> str:
    """Join PDF hard-wrapped lines, keeping real paragraph breaks.

    A wrapped line runs to the right margin, so any line noticeably shorter
    than the column width ends its paragraph.  Lines opening a bullet or a
    numbered item always start a new one.
    """
    lines = [l.strip() for l in s.split("\n")]
    widths = [dwidth(l) for l in lines if l]
    if not widths:
        return s.strip()
    full = sorted(widths)[int(len(widths) * 0.9)]
    out: list[str] = []
    prev_wrapped = False
    ends_sentence = re.compile(r"[。！？!?：:]\s*$")
    for ln in lines:
        if not ln:
            prev_wrapped = False
            continue
        if out and prev_wrapped and not _BLOCK.match(ln):
            prev = out[-1]
            joiner = " " if (prev[-1].isascii() and prev[-1].isalnum()
                             and ln[0].isascii() and ln[0].isalnum()) else ""
            out[-1] = prev + joiner + ln
        else:
            out.append(ln)
        # A wrapped line runs to the margin and stops mid-sentence.
        prev_wrapped = (dwidth(ln) >= full * 0.8
                        and not ends_sentence.search(ln))
    return "\n".join(out).strip()


def read_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path, obj) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    print(f"  → {p.relative_to(ROOT)}")
