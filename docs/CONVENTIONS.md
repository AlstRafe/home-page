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

どのサイトも同じ紙・インク・第 2 色・罫線・角を使う（2026-11-19 の刷新。最初の案「淡いにじみ・半透明・やわらかい影」は「AI に作らせた感」で取りやめ）。方向は「藍刷り」: 藍のインクと山吹の 2 色で刷った印刷物のように、紙はベタ、面は不透明、影もぼかしもなく、罫線と文字組みで形を作る。目が疲れないように、純白・純黒・ネオンの色は使わない。基準の実装は [`homepage/portal.css`](../homepage/portal.css) の先頭。

| 変数        | ライト    | ダーク    | 使いどころ                                                                                   |
| ----------- | --------- | --------- | -------------------------------------------------------------------------------------------- |
| `--paper`   | `#edf0f2` | `#141822` | ページ（ベタ。グラデーションなし）。`theme-color` と manifest もこの色                       |
| `--card`    | `#f8f9fa` | `#1b2030` | 不透明の面: 入力欄・メニュー・持ち主の欄                                                     |
| `--ink`     | `#19223a` | `#e3e6ec` | 文字・太い罫線・入力欄とボタンの枠（藍がかった黒 / 白ではない明るい灰）                      |
| `--soft`    | `#4c5770` | `#a4adbd` | 補助の文字（6.3:1 / 7.8:1）                                                                  |
| `--rule`    | `#c9d0da` | `#2d3446` | 行や段のあいだの細い罫線（入力欄やボタンの枠にはしない: 3:1 に届かない）                     |
| `--link`    | `#2a4a8f` | `#9db4ec` | リンク・選んでいるもの・フォーカスの輪（7.4:1 / 8.6:1）                                      |
| `--mark`    | `#e8b04a` | `#d8ab52` | 第 2 色（山吹）: 塗り・ハイライト・大きな飾りの数字・網点。紙の上の文字には使わない（1.7:1） |
| `--on-mark` | `#19223a` | `#141822` | `--mark` で塗った上の文字（8:1）                                                             |

- サイトの色（ライト / ダーク）は小さな印（見出しの前の棒・四角・グラフ）だけに: 朱 `#b5341f` / `#e8826d`（NewsBridge）、橙 `#ac3f0e` / `#ec915e`（CoreLab）、VAL の赤 `#b8202f` / `#ef7b85`、ほか青 `#2a4a8f`・ティール `#1f6e66`・緑 `#2c7430`・琥珀 `#8f5400`・紫 `#6b3fa0`（ダークは彩度を落とした色）。どれも紙の上で 5.2:1 以上。文字の多い部分はインク・`--soft`・`--link` で組む
- 角: 区画・カード・行・写真は 0。入力欄とボタンだけ 2px（`--r`）
- 影: 使わない。メニューだけ、ずらした `--mark` のベタ影（`box-shadow: 4px 4px 0 var(--mark)`、刷りのずれ）。半透明・`backdrop-filter`・グラデーションも使わない（網点だけは例外）
- 罫線: 細い線 `1px var(--rule)`、太い線 `2px var(--ink)`、題字の下の二重線は 3px + 1px のインク（2px あける）。段のあいだは `1px var(--rule)` の縦線
- ボタン: 主ボタンはライトがインクのベタに紙の色の文字、ダークは `--mark` のベタに `--on-mark` の文字（明るい灰のベタはまぶしい）。ホバーで入れ替える。副ボタンは透明に 1px のインクの枠、ホバーで `--mark`
- 入力欄: `--card` の地に 1px のインクの枠。フォーカスは `outline: 2px solid var(--link)`（どこでも同じ、`outline-offset: 2px`）
- 文字: 書体は言語ごとの `--sans` / `--serif` / `--mono` のまま。見出しは明朝（`--serif`）600、`font-feature-settings: "palt"`、`text-wrap: balance`、日本語は `word-break: auto-phrase`。小見出し（キッカー）は 0.72〜0.78rem・字間 0.12em・`--soft`。数字は `tabular-nums`、大きな飾りの数字は `--mark`（`aria-hidden`）
- 動き: 色と下線が変わるだけ（120ms、linear）。持ち上げたり動かしたりしない。`prefers-reduced-motion: reduce` では止める
- 飾り（使ってよい）: 第 2 色の網点 `radial-gradient(circle, var(--mark) 1.4px, transparent 1.9px) 0 0 / 11px 11px` を、文字のない隅だけに、マスクで消えていくように。不透明度はライト 0.55・ダーク 0.3 まで。`data:` の画像は CSP で読めないので使わない
- サイト一覧の形: 目次のように 1 サイト 1 行（番号・名前とボタン・中身の 3 段、段のあいだに縦の罫線）。パソコン幅（60rem 以上）では題字を左に縦書き（`writing-mode: vertical-rl`、本の背のように）

### ヘッダーと画面の幅

- ヘッダーは折り返さない。狭くなったら、なくても困らないものから順に隠す（説明文 → 補助の文字 → ラベルをアイコンだけに）
- 隠す幅は、いちばん長くなる英語で測る。ナビの文言や訳を変えたら測り直す
- スマホ幅（CoreLab は 760px 以下）はナビを画面下のタブバーに。入力中は隠す
- 確かめる幅の目安: 360・760・1000・1440px、4 言語、ライトとダーク

### 入口とのつながり

- `sites.toml` の `[[site]]` に登録する（静的なら `folder`、Python なら `python` と `entry`）。名前・説明・タグは `[site.ko]` などで 4 言語
- カードに並べる中身は `preview`（静的サイトは `portal.json`、文は `{"ja": …, "ko": …, "en-GB": …, "zh-TW": …}`）
- サイト内の検索があれば `search`（`{q}` 入りのアドレス）と `search_hint` でカードに検索欄を、よく使うページは `links` で並べる（どちらも 4 言語）
- 「← サイト一覧」へ戻る道を必ず持つ（自前で持つなら `home_link = "own"`、なければポータルが左下に付ける）
- 見つからないページは訪問者の言語で、サイトのトップとサイト一覧へのリンク付き

### リンクのプレビューとアイコン

- `og.png`（1200×630）、`apple-touch-icon.png`（180×180）、`favicon.svg`。ホーム画面に追加できるように manifest（192・512・maskable のアイコン）
- `og:image`・`og:url` は相対で書いてよい（ポータルが訪問者のアドレスで補う）
- サイト一覧の og.png はサイトのカードを写しているので、サイトを足したら作り直す

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
