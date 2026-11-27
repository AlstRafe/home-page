# 共通ルール（Home Page・News Site・Infra Game）

3 つのリポジトリ（[home-page](https://github.com/AlstRafe/home-page)・[news-site](https://github.com/AlstRafe/news-site)・[infra-game](https://github.com/AlstRafe/infra-game)）で揃えている書式・ツール・CI・Git の決まりと、サイト一覧に並ぶサイトの約束ごと。新しいプロジェクトも、ここをそのまま写して始められるように書いてある。

- 設定ファイルが正本。このページと食い違ったらファイルが正しいので、このページを直す
- 共通ファイルを変えるときは 3 リポジトリ同時に（同じ変更の PR を並べる）
- ツールは持ち主の VS Code に入っている拡張と対になるものだけを使う（保存時の整形と CI の判定が一致するように）

## 新しいプロジェクトを始めるとき

1. 共通ファイルを写す（[次の表](#共通ファイル)）: `.editorconfig`・`.prettierrc.json`・`.gitattributes` は必ず、Python なら `ruff.toml`、TOML があれば `.taplo.toml`、JS があれば `eslint.config.mjs`
2. `package.json` を作り、スクリプト名を揃える（`format`・`lint`、テストが Node なら `test`）→ `npm install` → `package-lock.json` もコミット
3. `.vscode/extensions.json`・`.vscode/settings.json` を、使う言語の分だけ写す
4. `.github/workflows/ci.yml` を写す（Python あり: home-page か news-site、JS だけ: infra-game）
5. 既存のコードがあるなら一度だけ全体を整形し、そのコミットを `.git-blame-ignore-revs` に書く
6. README に「書式とチェック」の節（コマンドとこのページへのリンク）
7. サイトなら [サイトの約束](#サイトの約束) を満たして `sites.toml` に登録する
8. push して CI が緑になるのを確かめる

## 共通ファイル

| ファイル                                   | 中身                                                                   | 置き場所                                     |
| ------------------------------------------ | ---------------------------------------------------------------------- | -------------------------------------------- |
| [`.editorconfig`](../.editorconfig)        | 文字コード・改行・インデント・行の長さ（全ファイル）                   | 3 リポジトリで同じファイル                   |
| [`.prettierrc.json`](../.prettierrc.json)  | Prettier の設定                                                        | 3 リポジトリで同じファイル                   |
| [`.gitattributes`](../.gitattributes)      | チェックアウト時の改行（Windows でも LF、`.bat` は CRLF）              | 3 リポジトリで同じファイル                   |
| [`ruff.toml`](../ruff.toml)                | Python の整形とチェック                                                | Python のリポジトリで同じファイル            |
| [`.taplo.toml`](../.taplo.toml)            | TOML の整形                                                            | TOML のあるリポジトリで同じファイル          |
| `eslint.config.mjs`                        | JS のチェック。最初の `rules` ブロックは共通、ファイルごとの部分は各自 | JS のあるリポジトリ（news-site・infra-game） |
| `.prettierignore`                          | 整形しないもの（[下](#整形しないもの)）                                | 各リポジトリ                                 |
| `package.json`                             | 整形・チェック用ツールの版（固定）とスクリプト                         | 各リポジトリ（アプリ自体は npm に頼らない）  |
| `.vscode/extensions.json`・`settings.json` | 推奨拡張と、保存時にどの拡張で整形するか                               | 各リポジトリ（言語の分だけ）                 |
| `.github/workflows/ci.yml`                 | テストと書式チェック                                                   | 各リポジトリ                                 |
| `.git-blame-ignore-revs`                   | 整形だけのコミット（git blame が飛ばす）                               | 各リポジトリ                                 |

## 書式

### すべてのファイル（`.editorconfig`）

- UTF-8、改行は LF（`.bat` だけ CRLF。cmd.exe のため）
- インデントは空白 2 つ（Python は 4 つ）
- 1 行 120 字まで、ファイルの最後は改行、行末の空白は消す（Markdown は消さない: 行末の空白 2 つが改行）
- パッチ（`.patch`）は作ったときのまま触らない

### 言語ごとの担当

| 対象                                   | 整形                  | チェック                              | VS Code 拡張                                   |
| -------------------------------------- | --------------------- | ------------------------------------- | ---------------------------------------------- |
| Python                                 | Ruff（`ruff format`） | Ruff（`ruff check`）                  | Ruff（`charliermarsh.ruff`）                   |
| JavaScript                             | Prettier              | ESLint（警告 0 件まで）               | Prettier・ESLint                               |
| CSS・JSON・Markdown・YAML              | Prettier              | `prettier --check`                    | Prettier（`esbenp.prettier-vscode`）           |
| TOML                                   | Taplo                 | `taplo fmt --check`                   | Even Better TOML（`tamasfe.even-better-toml`） |
| シェルスクリプト                       | 手で                  | ShellCheck（warning 以上）・`bash -n` | ShellCheck（`timonwong.shellcheck`）           |
| HTML・Jinja テンプレート               | 整形しない            | 各リポジトリのテスト                  | Jinja（`samuelcolvin.jinjahtml`、色分けだけ）  |
| そのほか（`.bat`・systemd・Caddyfile） | EditorConfig だけ     | —                                     | EditorConfig（`editorconfig.editorconfig`）    |

- Prettier（`.prettierrc.json`）: 120 字、LF、オブジェクトのキーの引用符は揃える（`quoteProps: consistent`）。ほかは既定のまま（ダブルクォート・セミコロンあり・末尾カンマあり）
- Ruff（`ruff.toml`）: 120 字、Python 3.11 以上として書く（`target-version = "py311"`）。チェックは `E4 E7 E9 F I UP B`（構文と明らかな誤り・import の順・新しい書き方・バグになりやすい書き方）。外しているのは `B905`・`E402`・`E731`・`E741`・`UP031` で、理由はファイルのコメント
- Taplo（`.taplo.toml`）: 120 字、コメントの位置は揃えない（揃えると長い行に引きずられて右へ飛ぶ）、配列は書いたままの形（短いものは 1 行、コメント付きは 1 行 1 項目）
- ESLint: `@eslint/js` の recommended に、共通の `rules` ブロック（使わない引数・catch の変数は可、`no-useless-assignment`・`no-useless-escape`・`preserve-caught-error` は警告、全角空白は文字列の中なら可、`el.textContent = el.textContent` は可）。ブラウザのスクリプトは `sourceType: "script"` で、サイトの名前空間（CoreLab は `IG`、NewsBridge は `NR`）を globals に足す

### 整形しないもの

ツールに任せると読みにくくなる、または中身が変わってしまうものは `.prettierignore` に理由と一緒に書いて外す。

- HTML（Jinja の `{{ }}`・`{% %}` を Prettier が読めない。CoreLab の index.html は本文が訳を引くキーなので行を崩さない）
- 1 行 1 項目の表: 訳（`js/i18n/`・`newsreader/locale/`）、コマンド辞典（`js/ref/`）
- テストの入力データ（`tests/fixtures/`）、渡したパッチ（`patches/`）、`package-lock.json`、実行時のデータ（`instance/`・`articles/`）

## ツールの版と入れ方

| ツール                        | 版                                                 | 決めている場所                                   |
| ----------------------------- | -------------------------------------------------- | ------------------------------------------------ |
| Ruff                          | 0.16.9                                             | `ci.yml`（`uvx ruff@0.16.9`）、README のコマンド |
| Prettier                      | 3.9.10                                             | `package.json`（3 リポジトリ）                   |
| Taplo                         | 0.9.3                                              | `ci.yml`（`uvx taplo@0.9.3`）、README のコマンド |
| ESLint・`@eslint/js`・globals | 10.14.0・10.0.1・17.14.0                           | `package.json`（news-site・infra-game）          |
| Python                        | 3.12（書き方は 3.11 まで）                         | `ci.yml`（VM の Ubuntu 24.04 と同じ）            |
| Node                          | 22                                                 | `ci.yml`                                         |
| Actions                       | checkout・setup-python・setup-node v6、setup-uv v7 | `ci.yml`                                         |

- `package.json` の版は `^` なしで固定する。`npm install` しておくと VS Code の Prettier・ESLint 拡張もリポジトリの版を使うので、保存時の整形と CI が一致する
- Ruff・Taplo の VS Code 拡張は拡張に入っている版を使う。版の違いで差が出たら CI が正しい
- Ruff と Taplo はネイティブ版を `uvx`（PyPI）で動かす。npm の `@taplo/cli` は Windows でファイルを 1 つも見つけられず、チェックが素通りになるので使わない
- 版を上げるときは 3 リポジトリ同時に。`npm run format`・`uvx ruff@<新しい版> format .`・`uvx taplo@<新しい版> fmt` で差分を見て、整形だけのコミットは `.git-blame-ignore-revs` へ
- 新しいツールを足すときは、対になる VS Code 拡張も持ち主の VS Code に入れる（入れられないツールは使わない）

## コマンド

どのリポジトリでも同じ名前で動く。

```bash
npm install                 # 初回だけ（整形・チェック用のツール。サイト自体は使わない）
npm run format              # Prettier で整形
npm run lint                # 整形済みかの確認（Prettier）と ESLint（警告 0 件まで）
uvx ruff@0.16.9 format .    # Python の整形（uv がなければ pip install ruff==0.16.9）
uvx ruff@0.16.9 check .     # Python のチェック（--fix で直せるものは直す）
uvx taplo@0.9.3 fmt         # TOML の整形（--check で確認だけ）
```

uv のない PC（持ち主の PC もそう）では、Ruff と Taplo は VS Code の拡張が保存時に整形し、確認は CI に任せる。

テストはリポジトリごと: home-page `python -m unittest discover -s tests`、news-site `python -m pytest tests -q`、infra-game `npm test`。

## CI（GitHub Actions）

master は 1 分以内に VM から公開される。CI の赤が、公開前（または直後）に気づく唯一の合図。

- `.github/workflows/ci.yml`: すべてのブランチへの push と手動で動く（`pull_request` では動かさない。PR には枝の最後のコミットの結果が出るので二重になる）
- `permissions: contents: read`、同じ枝の古い実行は止める（`concurrency: ci-${{ github.ref }}`）、各ジョブに `timeout-minutes`
- Python のテストは `ubuntu-24.04`（VM と同じ）と `windows-latest`（持ち主の PC）の両方、`fail-fast: false`、`PYTHONUTF8: "1"`（Windows の runner は cp1252 で日本語を出せない）
- 書式のジョブは Ruff・Taplo（`uvx`、キャッシュなし）→ `npm ci` → `npm run lint`。JS だけのリポジトリは 1 ジョブで `npm ci`・`npm test`・`npm run lint`
- 警告も 0 件にしてから merge する。緑にするためにテストを飛ばしたり消したりしない
- home-page の [`live.yml`](../.github/workflows/live.yml) は公開中のサイトを外から確かめる（6 時間ごと、master への push のあと、手動）。push のあとは `/version.json` にその push のコミットが出るまで待ってから（`--expect`）、ページ・プレビュー画像・manifest・`/news/api/version`・カードの検索・robots.txt・セキュリティヘッダを見る（[`deploy/livecheck.py`](../deploy/livecheck.py)）。新しいサイトを足したらここにも足す。ほかのリポジトリで公開後を確かめるときも、決まった秒数待つ代わりに `/version.json` の `"/val"` などが自分のコミットになるのを待つ

## Git と PR

- 作業は枝で → PR → CI が緑 → master へ squash merge。master に入ったものはそのまま公開される
- PR は持ち主（AlstRafe）の名前で作られるので、レビュー依頼はできない。担当者（assignee）に AlstRafe を入れる
- PR のタイトルは、利用者から見て何が変わるかを一文で（読むのは持ち主なので日本語が基本）。本文に理由と確かめたこと
- コミットのメッセージも「何が変わるか」を文で書く。整形だけのコミットは分けて `.git-blame-ignore-revs` に足す
- 改行は `.gitattributes` が決める（Windows でチェックアウトしても LF）
- 秘密情報（API キーなど）はリポジトリに入れない。実行時のデータは `instance/` などに置いて `.gitignore`
- 時刻は日本時間（JST）で書く（VM・GitHub のログは UTC）

## サイトの約束

サイト一覧（home-page）に並ぶサイトは、どれも同じ動きをする。新しいサイトもこれに合わせる。

### 言語

- 日本語・韓国語・英語（英国）・繁体字中国語（台湾）。コードは `ja` `ko` `en-GB` `zh-TW`
- 選んだ言語は `lang` クッキー（`Path=/`、ホスト全体で共通）。どのアドレスでも `?lang=<コード>` で切り替わる（ポータルが受けて、クッキーを付けて同じアドレスへ戻す）
- まだ選んでいなければ Accept-Language（`zh-*` → `zh-TW`、`en-*` → `en-GB`、対応外だけなら `en-GB`、なければ `ja`）
- ヘッダー右上に言語メニュー: `<details class="lang">`、地球のアイコンと今の言語名、4 つの `?lang=` リンク（日本語 / 한국어 / English (UK) / 中文（台灣））。外をクリックか Esc で閉じ、フォーカスはボタンへ戻す
- 文言は日本語をキーに引き、訳がなければ日本語を出す。画面の文言・中身（問題やコマンドの説明）も訳す。持ち主専用の画面（設定・状態）も訳す（持ち主も別の言語で見るため。開発者向けのエラー文は日本語のままでよい）
- 訳の抜けはテストで見つける（CoreLab `node tests/run-i18n.js`、NewsBridge `python tests/test_i18n.py --missing`）
- 基準の実装は [`homepage/i18n.py`](../homepage/i18n.py)

### ダーク / ライト

- ボタンは 自動 → オフ → オン（ダークモードの 自動 / オフ / オン）を繰り返す
- 選択は localStorage `"theme"`（`"light"` / `"dark"`、自動なら消す）。全サイトが同じオリジンなので、1 か所で選べば全部に効く。ほかのタブで変えたら `storage` イベントで追う
- 最初の描画の前に `<html data-theme>` を付ける（`<head>` の中の小さな同期スクリプト。CSP は sha256 で許す）
- 色は CSS 変数にして、ライトとダークを同じ変数名で持つ。`color-scheme` と `<meta name="theme-color">` も合わせる

### デザインの共通トークン

どのサイトも「製品ページ」の形と色を使う（2026-11-20、ユーザーが 20 案から 18 を選んだ。Apple の製品ページの考え方）。1 サイト（または 1 機能）を 1 区画に置き、名前（見出し）・何ができるかの具体的な 2〜3 文・入口のボタン・そのサイトの画面の見本を並べる（2026-11-27 から標語の見出しと飾りの数字はやめた。下の「AI っぽく見せない」）。色はほぼ白・淡い灰・ほぼ黒の面に、サイトごとの色が 1 つとリンクの青だけ。区画どうしは線や枠ではなく背景の色と余白で分ける。動きはスクロールに合わせて中身を見せるためのもので、飾りでは使わない（下の「動き」）。2026-11-20 のユーザーの指示: apple.com/jp の品質と体験を手本にするが、ロゴ・図形・文章・製品画像・画面配置は写さない。それまでの「藍刷り」（藍と山吹、2026-11-19）と、その前の「淡いにじみ・半透明・やわらかい影」は取りやめ（後者は「AI に作らせた感」）。基準の実装は [`homepage/portal.css`](../homepage/portal.css) の先頭。

#### AI っぽく見せない（2026-11-27）

ユーザーの周りで「全部 AI っぽい」と言われた。原因は色ではなく、どのサイトも同じ型をなぞっていたこと。次はしない:

- 標語の見出し（「同じニュースを、各社で読み比べ。」「〜を、〜まで。」「読む。学ぶ。調べる。」のような、句点で終わる 2 行の決め台詞）。見出しはサイト名・機能名・画面名にし、何ができるかは説明文に具体的に書く（媒体名・数・手順）
- 中身のない「大きな数字 3 つ」（「無料」「通算」「上位 %」「毎時」）。数字は本当に数えたものを、文の中か表に
- ✓ 付きの「登録不要・無料・スマホでも」の並び、英字の大文字のキッカー（YOUR DATA CENTER）、区画の上の小さな色文字（アイブロウ）を毎区画に置くこと
- 一覧に飾りで付ける 01・02・03 の番号（順番に意味があるときだけ）
- すべての区画を中央ぞろえにし、すべての文字を下からふわっと出すこと。動きは見本や図など 1 区画に 1 つまで
- 人のいない文（「〜できます」だけが続く宣伝文）。作っている人がいることがわかる中身（日付つきの「最近の変更」、何が作り物で何が本物か）を出す

| 変数        | ライト    | ダーク    | 使いどころ                                                                             |
| ----------- | --------- | --------- | -------------------------------------------------------------------------------------- |
| `--bg`      | `#fbfbfa` | `#0f0f10` | ページと固定ナビ（ベタ）。`theme-color` と manifest もこの色                           |
| `--alt`     | `#f0f0ee` | `#161618` | 区画を交互に分ける面（区画ごとに `--bg` と `--alt` を入れ替える）                      |
| `--screen`  | `#ffffff` | `#1c1c1f` | 画面の見本の枠の中・入力欄・メニュー・持ち主の欄                                       |
| `--ink`     | `#1a1a1c` | `#ececed` | 文字（16.8:1 / 16.2:1）                                                                |
| `--soft`    | `#5f6166` | `#a3a5ab` | 補助の文字・説明文（`--alt` の上でも 5.4:1 / 7.3:1）                                   |
| `--line`    | `#d6d6d3` | `#2a2b2f` | 区切りの細い線（入力欄やボタンの枠にはしない: 3:1 に届かない）                         |
| `--edge`    | `#7d7f84` | `#6b6d73` | 入力欄・メニュー・副ボタンの枠（3.3:1 以上）                                           |
| `--link`    | `#1f5fd1` | `#7fa8f5` | リンク・主ボタンの地・フォーカスの輪・選んでいるもの（`--alt` の上でも 5.1:1 / 7.6:1） |
| `--on-link` | `#ffffff` | `#0f0f10` | 主ボタンの文字（5.8:1 / 8:1）                                                          |
| `--plate`   | `#121315` | `#0b0b0c` | 黒い面: ページに 1 つだけ、どちらのテーマでも白い文字の区画（下）                      |

- 黒い面（`.plate`）の中では同じ変数を置き換える: `--ink #ededee`・`--soft #a3a5ab`・`--line #2b2d31`・`--edge #6b6d73`・`--link #8fb3ff`・`--screen #18191c`、`color-scheme: dark`。部品は変数だけで書くので、面の上でもそのまま使える
- サイトの色（ライト / ダーク）は区画の上のサイト名とアイコンだけに（どちらも 5.2:1 以上）: 朱 `#b5341f` / `#e8826d`（NewsBridge）、橙 `#ac3f0e` / `#ec915e`（CoreLab）、VAL の赤 `#b8202f` / `#ef7b85`、ほか青・ティール `#1f6e66`・緑 `#2c7430`・琥珀 `#8f5400`・紫 `#6b3fa0`。黒い面とダークではダークの色。本文やボタンには使わない（ボタンは `--link`）。1 画面に色は、その色と青の 2 つまで
- 形: 区画・枠・行・写真の角は 0。ボタンと入力欄だけ 2px（`--r`）。丸いピル・カードの角丸・浮いたカードは使わない
- 影: 使わない（メニューも 1px の `--edge` の枠だけ）。グラデーション・光る効果・網点も使わない。半透明とぼかしは固定ナビだけ（下）
- 区画: 上下の余白は `clamp(4rem, 2rem + 7vw, 8.5rem)`、中身の幅は最大 65rem（説明文は 40rem、1〜2 文まで）。区画は `--bg` と `--alt` を交互に、どこか 1 つを黒い面に。どの幅でも左ぞろえ（中央ぞろえはやめた）。64rem 以上では偶数番目の区画を左右に分け（`.side`）、文を左、画面の見本を右の窓の端まで広げる。左右の余白は 1rem / 1.5rem（48rem 以上）/ 3rem（64rem 以上）。ページの最初の区画は中身の高さだけ（画面いっぱいの標語にしない）
- 文字: 書体は言語ごとの `--sans`（ヒラギノ角ゴ・游ゴシック UI・メイリオ / Apple SD Gothic Neo・Malgun Gothic / PingFang TC・Microsoft JhengHei / system-ui）と `--mono` だけ。明朝は使わない。大見出し（サイト名）`clamp(2.75rem, 1.2rem + 5.5vw, 5.5rem)`・区画の見出し（機能名）`clamp(2.25rem, 1.1rem + 4vw, 4.25rem)`、どちらも 800・行間 1.04〜1.06・字間 -0.03〜-0.035em（標語はやめても、文字の大きさと余白は Apple の製品ページの大きさのまま、2026-11-27）・`"palt"`・`text-wrap: balance`（改行は下）。区画の上の名前は 1.1〜1.3rem 700。説明文は 1.05〜1.25rem の `--soft`。本文に 0.875rem より小さい文字は使わない
- 改行: 日本語・中国語は語の途中で折らない。どのブラウザでも同じになるよう、サーバーで文節の間に `<wbr>` を入れ（Home Page は [`homepage/phrases`](../homepage/phrases/__init__.py)。Google BudouX の学習済みモデル。中国語はモデルが確かな位置だけ使い、1 字だけの塊は隣とつなぐ。日本語は漢字と漢字の間で切らない）、CSS は `word-break: keep-all; overflow-wrap: anywhere`。`word-break: auto-phrase` は Chrome だけなので頼らない。韓国語は `keep-all`、見出しと中央寄せの説明文は `text-wrap: balance`、本文は `pretty`。どのモデルを使うかはページの言語でなく文字で決める（英語のページの日本語の記事名も）。短い英字の名前（「Riot ID」）、英字・数字とその後の語（「Riot ID を」「約 1 分」「60 試験」）はノーブレークスペースで、閉じ括弧とその後の助詞（「）を」「]]를」）は U+2060 でつなぐ。「16 GB」のような値の並びは 1 つずつ `white-space: nowrap`。確かめるときは 360〜1920px × 4 言語で全テキストの改行位置を取り出し、語の途中・1 字だけの行がないことを見る
- 入口: 主ボタンは `--link` の地に `--on-link` の文字（ホバーで `--ink` の地に `--bg` の文字）、高さ 2.75rem。続くリンクは「文 ›」（下線なし、ホバーで下線）
- 画面の見本（`.screen`）: 1px `--line` の枠、`--screen` の地。上の帯にサイト名・副題・そのサイトの検索欄、中に今ある中身（行ごとに 1px の線、番号は `--mono`、行全体がリンク、右に ›）か、よく使うページのタイル（線でつないだ格子）
- 数字の事実（`.facts`）: 2〜4 個を横に並べ、それぞれの前に 1px の縦線。大きな文字 `clamp(2rem, 1.4rem + 2vw, 3rem)` 800（`.side` では最大 4.5rem）。列の幅を超えない（`li` に `container-type: inline-size`、文字は `min(…, 16cqi)`。英語の「languages」が途中で折れないように）、下に 1rem の `--soft` の説明。スマホでは縦に並べ、上に横線
- 固定ナビ（`.ln`）: 高さ 3.25rem、下に 1px `--line`。地は `--bg` を 86% にして `backdrop-filter: saturate(180%) blur(20px)`（ぼかせないブラウザではベタ）。左に名前、中央に区画へのジャンプ、右にダークモードと言語。48rem 未満は固定せず、ジャンプを 2 段目に
- 入力欄: `--screen` の地に 1px `--edge` の枠、検索ボタンは枠につないだ `--link` の四角。フォーカスは `outline: 2px solid var(--link)`（`outline-offset: 2px`、どこでも同じ）
- 操作の反応: 色・下線・「›」の小さな横移動が 240ms の `cubic-bezier(0.25, 0.1, 0.25, 1)` で変わる。持ち上げたり影を付けたりしない
- 動き（いちばん大事）: スクロールに結び付けた CSS（`animation-timeline: view()` と名前付きの `view-timeline`、`@supports` の中）で作り、JavaScript は使わない。上へ戻ると逆に再生される。区画ごとに違う見せ方にする: 最初の区画は開いたときに句ごとに時間差で現れ（1 回だけ、`cubic-bezier(0.16, 1, 0.3, 1)`）、スクロールで奥へ下がって消える / 名前・見出し・説明・入口は下からせり上がる / 画面の見本は小さめから大きくなり、ページより少し遅れて上がる（視差）/ 見本の行は 1 行ずつ横から、タイルは上下から組み上がる / 数字は下から現れる / `.side` では見本が右の端から入って止まり、数字が画面の中央を通るときだけ明るくなる。ずっと動き続けるものは置かない
- `prefers-reduced-motion: reduce` では動きをすべて止める（`@media (prefers-reduced-motion: no-preference)` の中にだけ書く）。動きがなくても、スクロールに結び付けられないブラウザでも、すべてが最初から見えて使える

### ヘッダーと画面の幅

- ヘッダーは折り返さない。狭くなったら、なくても困らないものから順に隠す（説明文 → 補助の文字 → ラベルをアイコンだけに）
- 隠す幅は、いちばん長くなる英語で測る。ナビの文言や訳を変えたら測り直す
- スマホ幅（CoreLab は 760px 以下）はナビを画面下のタブバーに。入力中は隠す
- 確かめる幅の目安: 360・760・1000・1440px、4 言語、ライトとダーク

### 入口とのつながり

- `sites.toml` の `[[site]]` に登録する（静的なら `folder`、Python なら `python` と `entry`）。名前・説明・タグは `[site.ko]` などで 4 言語
- 画面の見本に並べる中身は `preview`（静的サイトは `portal.json`、文は `{"ja": …, "ko": …, "en-GB": …, "zh-TW": …}`）
- サイト内の検索があれば `search`（`{q}` 入りのアドレス）と `search_hint` で区画の画面の見本に検索欄を、よく使うページは `links` で並べる（どちらも 4 言語）
- 区画の大きな見出しは `headline`、数字の事実は `facts`（`[["25", "ミッション"], …]`、4 つまで）、黒い面にするなら `dark = true`（ページに 1 つ）。どれも 4 言語
- 「← サイト一覧」へ戻る道を必ず持つ（自前で持つなら `home_link = "own"`、なければポータルが左下に付ける）
- サイト一覧へ戻る道は、どのページでもスクロールせずに押せる所に置く（2026-11 「簡単に押せる位置にない」を受けて）:
  - スマホより広い画面: ヘッダーの最初（サイト名より左）。ヘッダーは上に留める（`position: sticky`）。アンカーへの移動がヘッダーの下に隠れないよう `scroll-padding-top`
  - スマホ（下にタブバーがある幅）: タブバーの最初のタブ。サイトのタブとは罫で区切る
  - いつも言葉つき（矢印 `←` だけにしない）。狭い所では矢印の下に言葉。押せる大きさは 44px 以上。名前は `サイト一覧`、読み上げは `サイト一覧へ戻る`
  - 実装: NewsBridge `base.html` の `.portal-link` / `.tab-home`、VAL Tracker `base.html` の `.home-link` / `.home-tab`
- 見つからないページは訪問者の言語で、サイトのトップとサイト一覧へのリンク付き

### リンクのプレビューとアイコン

- `og.png`（1200×630）、`apple-touch-icon.png`（180×180）、`favicon.svg`。ホーム画面に追加できるように manifest（192・512・maskable のアイコン）
- `og:image`・`og:url` は相対で書いてよい（ポータルが訪問者のアドレスで補う）
- サイト一覧の og.png は各サイトの名前と見出しを並べているので、サイトを足したら作り直す（1200×630 の HTML を Playwright で撮り、128 色に減色）

### 使いやすさ

- `:focus-visible` で、キーボードでの位置がいつも見える
- `prefers-reduced-motion` で動きを止める
- ナビの長いサイトは本文へ飛ぶリンクを先頭に（CoreLab の `.skip`）。アイコンだけのボタンには `aria-label` か `title`
- 目標は Lighthouse のアクセシビリティ 100

### 速さ

- VM は CPU 1/8。サーバーの仕事は軽く、静的ファイルは ETag と gzip（ポータルがやる）
- スクリプトは `defer`。読み込みでページがずれない（CLS ≒ 0）ように場所を先に取る
- Lighthouse はモバイル・`--throttling-method=devtools`・`--chrome-flags=--lang=xx` で測る

### セキュリティ

- 公開の名前で開かれたページには、サーバーが HSTS を付ける（`homepage/server.py`）
- 静的サイトにはポータルが CSP（自分のファイルだけ）・`nosniff`・`X-Frame-Options` などを付ける。Python のサイトは自分で付ける（NewsBridge は `newsreader/web/security.py`）
- インラインスクリプトは原則なし。どうしても要るもの（テーマの初期化）は CSP の sha256 で許す
- 外部の CDN やフォントは読まない（すべて自分のファイル）

## このページを変えるとき

ルールを足したり変えたりしたら、設定ファイルと一緒にこのページも同じ PR で直す。ツールの版はテスト（`tests/test_conventions.py`）が `ci.yml`・`package.json` と照らし合わせる。
