# 作業状況（2026-09-04 時点）

**完成して稼働中。** 以降は不具合の修正と改善が中心。

- 公開先: **https://aoe99.github.io/sc-am2-study/app/**（アプリ名: SC試験対策）
- 問題データ:
  - 午前 19回 × （午前I 30問 + 午前II 25問）= **1,045問**
  - 午後 19回 = **90事例 / 839設問**（記号選択112 / 語句312 / 記述415）、図表668枚
- 検証はすべて通過（`tools/08_validate.py` の全項目が ✓）

---

## 修正を依頼されたときの手順

**別コンテキストで指示を受けた場合も、修正から公開・コミットまで通しで行う。**
途中で止めて確認を取る必要はない（初期開発時のフェーズ確認はもう不要）。

### 1. 原因を実データで特定する

推測で直さない。必ず現物を見る。

```bash
# 対象の問題が今どうなっているか
python3 -c "import json;d=json.load(open('data/questions.json'));q=[x for x in d['questions'] if x['id']=='R05haru-am2-17'][0];print(q)"

# OCRの生の座標（不具合の原因はたいていここに出る）
python3 - <<'PY'
import importlib.util, sys
sys.argv=['x','--section','am2']          # am1 / am2
spec=importlib.util.spec_from_file_location('p','tools/04_parse.py')
p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
lines=p.load('R05haru'); h=p.find_headings(lines); order=sorted(h)
k=order.index(17); end=h[order[k+1]] if k+1<len(order) else len(lines)
for l in lines[h[17]:end]:
    print(f"x={l['x']:.3f} y={l['y']:.3f} h={l['h']:.3f} | {l['text'][:50]!r}")
PY
```

画像の不具合は **切り出した画像を実際に開いて見る**。OCRで中身を読ませて照合すると
確実（`sips -Z 700 data/figures/... --out /tmp/x.png` して Read、または
`./bin/pdfkit-tool ocr /tmp/x.png`）。

### 2. 直す

データ側は `tools/` を、アプリ側は `app/` を編集する。手で直せる設定は
`tools/corrections.json`（OCRの既知の誤読）と `tools/tags.json`（分野タグ）。

### 3. 作り直す

```bash
# 午前
python3 tools/04_parse.py   --section am1   # 抽出を変えたとき
python3 tools/04_parse.py   --section am2
python3 tools/05_figures.py --section am1   # 図表の切り出しを変えたとき
python3 tools/05_figures.py --section am2

# 午後（--section は取らない。区分がひとつしかない）
python3 tools/11_pm_answers.py              # 解答例 → 設問の骨格
python3 tools/12_pm_commentary.py           # 採点講評
python3 tools/13_pm_explanations.py         # 教科書解説
python3 tools/14_pm_parse.py                # OCR → 事例本文・設問文
python3 tools/15_pm_figures.py              # 図表の切り出し

python3 tools/06_build.py                   # 統合（常に必要）
python3 tools/09_duplicates.py --apply      # 午前だけが対象
python3 tools/10_pack.py                    # → sc-data-{am,pm}.json + -figures.bin
python3 tools/08_validate.py                # 全項目が ✓ になること
```

**午後は「解答から問題文へ」の順に依存している。** `11_pm_answers` が設問の骨格
（どの設問に、どの空欄があるか）を作り、`14_pm_parse` はその記号をOCRした問題文から
探す。11を流し直したら14も流し直すこと。

**各ステージの終了コードを必ず確認する。** 出力を `head` などで切ると SIGPIPE で
ファイル書き込み前に落ちるのに気づけない（実際に一度やった）。

### 4. アプリを変えたら Service Worker の版を上げる

```bash
# app/sw.js の VERSION を v13 → v14 のように上げる
```

**これを忘れると端末に修正が届かない。** キャッシュされた古いモジュールが動き続ける。

### 5. コミットして公開

```bash
git add -A && git commit -m "…" && git push origin main
```

コミットメッセージは日本語で、**何を直したかではなく、なぜそうなっていたか**を書く。
末尾に `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` を付ける。

GitHub Pages への反映は1〜2分。確認:

```bash
curl -s https://aoe99.github.io/sc-am2-study/app/sw.js | grep -o "sc-am2-v[0-9]*"
```

### 6. 利用者に伝えること

- **データを作り直したなら**「新しいパックの読み込みが必要」と明記する。どの区分を
  作り直したかで渡すファイルが変わる:
  - 午前 → `data/sc-data-am.json` ＋ `data/sc-data-am-figures.bin`
  - 午後 → `data/sc-data-pm.json` ＋ `data/sc-data-pm-figures.bin`

  **区分ごとに独立している。** 午後だけ入れ直しても午前の1,045問と学習記録は残る。
  ホーム画面下部に出る「問題データ 2026-09-04 06:18」は**選んでいる区分のもの**
- アプリだけの変更なら読み込み直しは不要

---

## やってはいけないこと

- **`data/` を公開しない。** IPA の問題冊子と翔泳社の解説はどちらも著作物。
  `.gitignore` で除外済みだが、コミット前に `git diff --cached --name-only` で確認する
- IndexedDB名 `sc-am2`、localStorageキー `sc-am2:settings`、書き出しの
  `kind: sc-am2-progress` を変えない。**識別子であって表示名ではない。**
  変えると読み込み済みの1,045問と学習記録が孤立する
- **走行状態（kv の `run`）は、解答画面が保存と削除の両方をすること。** 保存だけして
  削除しないと、採点し終えた走行が残り続けてホームに「中断した学習 0問」が出続ける
- **問題IDを変えない。** `states` は questionId をキーにしている。午後の
  `R07aki-pm-1-2-3`（回-区分-大問-設問-小問）も同じで、採番を変えると自己採点の
  履歴が全部孤立する
- **図表を base64 でJSONに戻さない。** 午後は668枚・63MBあり、data: URI にすると
  パックが84MBになって iPhone の Safari が落ちる。`.bin` は ArrayBuffer から
  Blob を切り出すだけで、文字列にもJSONにもしない
- サブセット実行（`--section am2 R05haru` のように回を指定）しても中間ファイルは
  マージ書き込みになっている。全回を消さないこと

---

## 残っている品質課題

### 午後

**設問文が取れているのは 771/839（91.9%）。** 残り68件は H28春・H28秋・H30秋・R01秋
などのスキャンが**上余白ごと見出しを落としている**ため、PDFに文字が存在しない。
解答例・採点講評・解説は揃っているので学習はできる。直すには元PDFを取り直すしかない。

**解説があるのは 825/839。** 残り14件は教科書解説側にその設問の見出しが立っていない回。

**記号の読めない空欄と、ただの隙間は区別できない。** 2026-09-04 に手がかりを4つ測った
（`data/build/pm/pages/` の画像とOCRの座標で再現できる）。

| 手がかり | 結果 |
|---|---|
| 隙間の幅 | 分離しない。本物の中央値0.049 / それ以外0.078で重なりが大きい |
| 枠線の形（上下の横罫線を検出） | 記号入りの枠758個のうち検出できたのは81%。フィルタにすると本物の19%を失う |
| 設問から数えた「本文にあるべき数」 | 594に対し実際885。事例ごとのばらつきが大きく削る根拠にならない |
| インク量（ほぼ真っ白か） | **安全だが取り分が少ない。** しきい値0.02で本物の損失1.6%・ノイズ除去11%。本文の散文だけなら約60個 |

インク量による除去は未実装。取り分（本文556個中60個ほど）に対して、Swift側に
`ink` コマンドを足し、全回を再抽出し、利用者にパックを入れ直してもらう必要がある。
やるなら他のデータ変更とまとめる。

**本文の空欄の枠は918個、うち記号が読めているのは537個。** 素直に隙間を拾うと5,154個
になり、表の列の罫線と図の配置が混ざる。縦に揃う隙間（同一ページで3行以上）と、
1行に2つ以上ある枠を落としている。`tools/14_pm_parse.py` の `column_edges` と
`drop_layout_boxes`。

**下線の丸数字は、設問が参照する358個のうち334個（93%）が本文にある。** 残り24個は
OCRが落としている。アプリは押されたときに「読み取れていません」と出す。下線そのもの
（線）は図形なので、どの語句までが下線かは復元できない。丸数字の位置だけを示している。

**図表はキャプションのある678件のうち631件（93%）を切り出せている。** 図は
「取りこぼすより広めに取る」方針なので、上に導入文が1行入ることがある。

`data/build/pm/answers.json` の `flags` に「表の列を推定」が19件。IPAの解答例PDFは
2列の解答（`利点`／`内容` など）をテキスト層で1行に潰してしまい、折り返しと区別が
つかない。分けたほうが原文に近いので分けているが、目視の価値がある。

### 午前

`data/build/review.md` に要確認179問。大半は「選択肢が表形式（画像化済み）」と
「解説に存在しない漢字」（誤検出を半分程度含むヒント）。

`data/build/cross-check.md` に**回をまたいだ不一致**がある。同じ問題が複数の回に
出ているため、抽出が食い違う箇所はどちらかが誤読。ここを潰すのが最も効率がよい。
ただし `探索`↔`発見`、`登録`↔`記載` のように**IPAが実際に文言を変えている**ものも
混ざるので、機械的に統一してはいけない。

分野タグは23種。「その他」が114問残っており、`tools/tags.json` にキーワードを
足せば減る。

## 未確認

- iPhone 実機での「ホーム画面に追加」。表示は 375px エミュレーションで確認済み
- Safari(mac) の実機表示

## 今後の拡張

- `meta.sections` に問数と制限時間があるので、区分を増やしても本番モードは追従する
- 解答履歴の `mode` は自由文字列なので、新モードを足しても既存記録と衝突しない
- 午後の記述は自己採点なので、`answers` に書いた本文（`typed`）が溜まる。同じ設問を
  解き直したときに前回の答案を並べて見せる余地がある
- `commentaryRate`（正答率 高/やや高/平均/やや低/低）は保存してあるが、まだ絞り込みに
  使っていない。「正答率が低い設問だけ」の練習は足せる
