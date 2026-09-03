#!/bin/bash
# 全ステージを順に実行する。引数に回ID（例: R07aki）を並べるとその回だけ処理する。
#   ./tools/run_all.sh              # 全19回
#   ./tools/run_all.sh R07aki       # 1回分だけ
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x bin/pdfkit-tool ] || [ tools/swift/pdfkit-tool.swift -nt bin/pdfkit-tool ]; then
  echo "== Swift ツールをビルド =="
  mkdir -p bin
  swiftc -O -o bin/pdfkit-tool tools/swift/pdfkit-tool.swift \
    -framework PDFKit -framework Vision -framework AppKit
fi

for stage in 01_answers 02_explanations 03_ocr 04_parse 05_figures 06_build 07_review_html; do
  echo; echo "== $stage =="
  if [ "$stage" = 03_ocr ]; then
    python3 "tools/$stage.py" --tesseract "$@"
  else
    python3 "tools/$stage.py" "$@"
  fi
done
# 重複の検出とアプリ用パックは全19回そろっているときだけ意味がある。
if [ $# -eq 0 ]; then
  echo; echo "== 09_duplicates =="; python3 tools/09_duplicates.py --apply
  echo; echo "== 10_pack =="; python3 tools/10_pack.py
fi

echo; echo "== 08_validate =="; python3 tools/08_validate.py || true
echo; echo "完了: data/questions.json / data/sc-data.json / data/build/review.md"
