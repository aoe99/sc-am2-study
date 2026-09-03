# 作業状況（2026-09-04 時点）

**完成して稼働中。** 以降は不具合の修正と改善が中心。

- 公開先: **https://aoe99.github.io/sc-am2-study/app/**（アプリ名: SC試験対策）
- 問題データ: 19回 × （午前I 30問 + 午前II 25問）= **1,045問**
- 検証はすべて通過（IPA解答例と教科書解説の正解一致 1,045/1,045）

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
python3 tools/04_parse.py   --section am1   # 抽出を変えたとき
python3 tools/04_parse.py   --section am2
python3 tools/05_figures.py --section am1   # 図表の切り出しを変えたとき
python3 tools/05_figures.py --section am2
python3 tools/06_build.py                   # 統合（常に必要）
python3 tools/09_duplicates.py --apply
python3 tools/10_pack.py                    # → data/sc-data.json
python3 tools/08_validate.py                # 全項目が ✓ になること
```

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

- **データを作り直したなら**「新しい `data/sc-data.json` の読み込みが必要」と明記する。
  ホーム画面下部と設定画面に表示される「問題データ 2026-09-04 06:18」で判別できる
- アプリだけの変更なら読み込み直しは不要

---

## やってはいけないこと

- **`data/` を公開しない。** IPA の問題冊子と翔泳社の解説はどちらも著作物。
  `.gitignore` で除外済みだが、コミット前に `git diff --cached --name-only` で確認する
- IndexedDB名 `sc-am2`、localStorageキー `sc-am2:settings`、書き出しの
  `kind: sc-am2-progress` を変えない。**識別子であって表示名ではない。**
  変えると読み込み済みの1,045問と学習記録が孤立する
- サブセット実行（`--section am2 R05haru` のように回を指定）しても中間ファイルは
  マージ書き込みになっている。全回を消さないこと

---

## 残っている品質課題

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

- `id` は `R07aki-am1-01` の形式で区分を含むので、午後は `pm` を足せばよい
- `meta.sections` に問数と制限時間があるので、区分を増やしても本番モードは追従する
- 解答履歴の `mode` は自由文字列なので、新モードを足しても既存記録と衝突しない
