#!/bin/bash
# 全ステージを順に実行する。
#   ./tools/run_all.sh                    # 午前I・午前II の全19回
#   ./tools/run_all.sh --section am1      # 午前Iだけ
#   ./tools/run_all.sh R07aki             # 両区分の R07aki だけ
#   ./tools/run_all.sh --section am2 R07aki
set -euo pipefail
cd "$(dirname "$0")/.."

SECTIONS=(am1 am2)
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

for sec in "${SECTIONS[@]}"; do
  for stage in 01_answers 02_explanations 03_ocr 04_parse 05_figures; do
    echo; echo "== [$sec] $stage =="
    if [ "$stage" = 03_ocr ]; then
      python3 "tools/$stage.py" --section "$sec" --tesseract ${ARGS[@]+"${ARGS[@]}"}
    else
      python3 "tools/$stage.py" --section "$sec" ${ARGS[@]+"${ARGS[@]}"}
    fi
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
echo; echo "完了: data/questions.json / data/sc-data.json / data/build/review.md"
