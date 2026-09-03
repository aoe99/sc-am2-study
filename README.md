# SC試験対策 — 情報処理安全確保支援士 午前I / 午前II

情報処理安全確保支援士試験（SC）の過去問19回分を、手元のPDFから抽出して学習アプリで
使える形にするためのリポジトリ。**午前I（高度共通・30問50分）と午前II（25問40分）**の
両方を扱う。

> **著作権について。** 抽出元のうち IPA の問題冊子と翔泳社『情報処理教科書 安全確保
> 支援士』読者特典の解説は、いずれも著作物。`data/` 以下（`questions.json`・
> `figures/`・`build/`）は**公開リポジトリ・公開URL・公開ストレージに置かない**。
> `.gitignore` でも除外している。

---

## 1. 必要なもの

| | |
|---|---|
| macOS | PDFKit と Vision を使うため必須。Apple Silicon / Intel どちらでも可 |
| Xcode Command Line Tools | `xcode-select --install`（`swiftc` が要る） |
| Python | 3.9 以上。macOS 標準の `/usr/bin/python3` でよい（追加パッケージ不要） |
| tesseract | **任意**。あると OCR のクロスチェックが有効になり、要確認リストの精度が上がる。`brew install tesseract tesseract-lang` |

Homebrew の poppler（`pdftotext` / `pdfimages`）は**不要**。理由は §5 を参照。

## 2. 過去問PDFの置き場所

既定では `~/Desktop/情報セキュリティSP過去問/` を見に行く。別の場所なら環境変数で指定する。

```bash
export SC_PDF_ROOT=/path/to/情報セキュリティSP過去問
```

各回のフォルダに区分ごとの3ファイルがある前提。

```
R07aki/R07a_1_午前I_1問題.pdf         IPA公式の問題冊子（スキャン画像・テキスト層なし）
R07aki/R07a_1_午前I_2解答例.pdf       IPA公式の解答例
R07aki/R07a_1_午前I_4教科書解説.pdf   翔泳社 読者特典の解答・解説
R07aki/R07a_2_午前II_1問題.pdf        （午前IIも同じ構成）
…
```

問題冊子は**全19回・両区分ともテキスト層がない**ためOCRが要る。解答例は R04haru の
午前Iだけ画像で、そこもOCRに回る。

iCloud Drive 上にあってローカル未ダウンロードだと読めない。事前に Finder で開いて実体を落としておくこと。

## 3. 実行

```bash
./tools/run_all.sh                  # 午前I・午前II の全19回
./tools/run_all.sh --section am1    # 午前Iだけ
./tools/run_all.sh R07aki           # 両区分の R07aki だけ
```

各ステージは `--section am1|am2` を受け取り、中間生成物は `data/build/<区分>/` に
分かれる。統合（`06_build`）以降は両区分を1つの `questions.json` にまとめ、各問に
`section` を持たせる。

各ステージは単体でも動く。冪等なので何度流し直してもよい。

| ステージ | 役割 | 出力 |
|---|---|---|
| `01_answers.py` | 解答例PDF → 正解記号 | `data/build/answers.json` |
| `02_explanations.py` | 教科書解説PDF → 正解＋解説本文 | `data/build/explanations.json` |
| `03_ocr.py` | 問題冊子を400dpiで描画し Vision でOCR | `data/build/pages/`, `data/build/ocr/` |
| `04_parse.py` | OCR行を 問1〜25 と選択肢ア〜エに分割 | `data/build/parsed.json` |
| `05_figures.py` | 図表領域をPDFから直接切り出し | `data/figures/` |
| `06_build.py` | 全部を統合、分野タグ付与、要確認リスト生成 | `data/questions.json`, `data/build/review.md` |
| `07_review_html.py` | 抽出結果とページ画像を左右に並べた校正ページ | `data/build/review-<回>.html` |
| `08_validate.py` | 受け入れ基準のチェック表 | 標準出力 |
| `09_duplicates.py` | 再出題の検出とグループ化、回またぎの突き合わせ | `data/build/duplicates.md`, `cross-check.md` |
| `10_pack.py` | アプリが読み込む単一ファイルを生成 | `data/sc-data.json` |

`03_ocr.py` は結果をキャッシュする。やり直すときは `--force` を付ける。

### 校正のしかた

```bash
open data/build/review-R07aki.html
```

左に抽出テキスト、右に元のページ画像が並ぶ。`data/build/review.md` には自動検出した
要確認箇所だけが集まっている。

## 4. 手で直せる設定ファイル

| ファイル | 中身 |
|---|---|
| `tools/tags.json` | 分野タグの定義。キーワードを足し引きすれば分類が変わる |
| `tools/corrections.json` | OCR の既知の誤認識と、その置換規則。`flagPatterns` は「自動で直さず人間に見せる」パターン |

どちらも編集後に `04_parse.py` 以降を流し直せば反映される。

## 5. 設計上の判断

**PDFの読み取りに poppler ではなく PDFKit を使っている。** この環境に poppler が
入っておらず、また `pdftotext -layout` よりも PDFKit のリーディング順のほうが解答例
PDFの3段組を正しく1行1件で返した。macOS 標準フレームワークだけで完結するので、
数年後に再実行しても壊れにくい。実体は `tools/swift/pdfkit-tool.swift`（`bin/pdfkit-tool`
に自動ビルドされる）。

**OCR は Vision を採用した。** 同一ページで tesseract と比較した結果:

| 指標 | Vision | tesseract |
|---|---|---|
| 問N見出しの認識 | 24/25 | 14/25 |
| 行頭の選択肢マーカー | **100/100** | 77/100 |
| 全角括弧・全角読点の保持 | 保持する | すべて半角化 |
| 1ページあたり | 約0.6秒 | 約1.5秒 |

選択肢マーカーの取りこぼしは構造の破壊に直結するため、この差は決定的。ただし
tesseract のほうが正しく読む字もある（`危殆化` など）ので、**入れてあれば第2エンジン
として突き合わせに使い**、両者が食い違った文字を要確認リストに載せる。

**誤認識の検出に解説テキストを辞書として使っている。** 教科書解説PDFはテキスト層が
あり、OCRを通していない約13万字のきれいな同分野コーパスになる。OCRした問題文に
「解説側に一度も現れない漢字」があり、かつ tesseract もその字を読んでいなければ、
ほぼ誤読（`擎`←`撃`、`億`←`偽` など実例あり）。

## 6. 出力データ

`data/questions.json` のスキーマは `schemaVersion: 1`。1問は次の形。

```jsonc
{
  "id": "R07aki-am2-01",
  "sessionId": "R07aki",
  "no": 1,
  "text": "…",
  "choices": [{ "key": "ア", "text": "…" }, …],
  "answer": "ウ",
  "explanation": "…",
  "explanationSource": "情報処理教科書 安全確保支援士 読者特典",
  "figures": ["figures/R07aki/R07aki-am2-22.png"],
  "choiceFigures": {},
  "tags": ["暗号"],
  "duplicateGroupId": null,
  "needsReview": false,
  "shortText": true,
  "source": { "questionPdf": "…", "page": 3, "pageImage": "…" }
}
```

将来 午前I や午後を足せるよう、`id` には区分（`am2`）を入れてある。

---

## 7. Webアプリ

`app/` がアプリ本体。ビルド工程はなく、HTML + CSS + ES modules だけで動く。

### 公開先

**https://aoe99.github.io/sc-am2-study/app/**（アプリ名: SC試験対策）

Service Worker がアプリ本体（21ファイル）をキャッシュするので、一度開けば
オフラインで動く。iPhone は共有 →「ホーム画面に追加」。

### ローカルで動かす

```bash
python3 tools/serve.py        # → http://localhost:8765/
```

または `起動.command` をダブルクリック。インターネットは不要
（127.0.0.1 にしか listen しない）。

初回に「ファイルを選ぶ」から `data/sc-data.json` を読み込む。以降は IndexedDB
から読むので、オフラインでも動く。

### なぜ「ファイルを選ぶ」なのか

問題文も解説も著作物なので、**アプリと一緒に配信しない**。`app/` だけなら
GitHub Pages などの HTTPS に置ける（Service Worker は HTTPS か localhost でしか
動かないため、iPhone で PWA として使うには HTTPS 配信が要る）。問題データは
利用者が自分の手元のファイルから読み込む。`.gitignore` で `data/` を除外済み。

### iPhone

1. `data/sc-data.json`（約10MB）を iCloud Drive に置く
2. Safari でアプリを開き、「ファイルを選ぶ」から読み込む
3. 共有 →「ホーム画面に追加」

Safari の「サイトデータを消去」で学習記録が消えるので、設定画面から
**書き出し**ておくこと。同期機能ではなく手動バックアップ。

### モード

| | |
|---|---|
| 練習 | 出題数・年度・分野・未着手/誤答で絞る。即時判定 or まとめて採点 |
| 本番 | 25問40分。実時刻ベースのタイマー、合格ライン60%判定、分野別内訳 |
| 復習 | ライトナー5箱（当日 / 1日 / 3日 / 7日 / 16日、箱5正解で35日） |
| 年度別 | 回を選んで25問を通しで |

### 操作

- `1`〜`4` / `A`〜`D` で選択、`Enter` で次へ、`S` で解説の開閉
- スワイプで前後の問題へ
- ダークモード（OS追従＋手動）、文字サイズ3段階

### 選択肢のシャッフル

既定でON。**解説を開くと元のア/イ/ウ/エ順に戻る** — 解説本文が「したがってウが
正解」と印刷上の記号で書かれているため。並びが動いて迷わないよう、位置が変わった
選択肢には「解答時は ウ」と併記する。

### 表・図が選択肢になっている問題

38問ある。テキストにすると意味が壊れるので選択肢ごとに画像を出す
（`choiceFigures`）。うち33問は自動で切り出せている。残り5問はマーカー位置の
推定が不確かなため画像がなく、`data/build/review.md` に載せてある。
