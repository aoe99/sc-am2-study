#!/bin/bash
# 全ステージを順に実行する。
#   ./tools/run_all.sh                    # 午前I・午前II・午後 の全19回
#   ./tools/run_all.sh --section am1      # 午前Iだけ
#   ./tools/run_all.sh --section pm       # 午後だけ
#   ./tools/run_all.sh R07aki             # 全区分の R07aki だけ
#   ./tools/run_all.sh --section am2 R07aki
set -euo pipefail
cd "$(dirname "$0")/.."

SECTIONS=(am1 am2 pm)
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --section) SECTIONS=("$2"); shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

if [ ! -x bin/pdfkit-tool ] || [ tools/swift/pdfkit-tool.swift -nt bin/pdfkit-tool ]; then
  echo "== Swift ツールをビルド =="
  mkdir -p bin
  swiftc -O -o bin/pdfkit-tool tools/swift/pdfkit-tool.swift \
    -framework PDFKit -framework Vision -framework AppKit
fi

# 午前は 01〜05、午後は 11〜15。OCR(03) だけは共通。
for sec in "${SECTIONS[@]}"; do
  if [ "$sec" = pm ]; then
    STAGES=(11_pm_answers 12_pm_commentary 13_pm_explanations 03_ocr 14_pm_parse 15_pm_figures)
  else
    STAGES=(01_answers 02_explanations 03_ocr 04_parse 05_figures)
  fi
  for stage in "${STAGES[@]}"; do
    echo; echo "== [$sec] $stage =="
    case "$stage" in
      03_ocr)
        python3 "tools/$stage.py" --section "$sec" --tesseract ${ARGS[@]+"${ARGS[@]}"} ;;
      1[1-5]_pm_*)
        # 午後のステージは区分がひとつしかないので --section を取らない。
        python3 "tools/$stage.py" ${ARGS[@]+"${ARGS[@]}"} ;;
      *)
        python3 "tools/$stage.py" --section "$sec" ${ARGS[@]+"${ARGS[@]}"} ;;
    esac
  done
done

# 統合以降は区分をまたぐ。
echo; echo "== 06_build =="; python3 tools/06_build.py ${ARGS[@]+"${ARGS[@]}"}
echo; echo "== 07_review_html =="; python3 tools/07_review_html.py ${ARGS[@]+"${ARGS[@]}"}

# 重複検出とアプリ用パックは全19回そろっているときだけ意味がある。
if [ ${#ARGS[@]} -eq 0 ]; then
  echo; echo "== 09_duplicates =="; python3 tools/09_duplicates.py --apply
  echo; echo "== 10_pack =="; python3 tools/10_pack.py
fi

echo; echo "== 08_validate =="; python3 tools/08_validate.py || true
echo; echo "完了: data/questions.json / data/sc-data-am.json / data/sc-data-pm.json / data/build/review.md"
