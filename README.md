# Home Page — サイト一覧とサーバー

サイト（News Site の NewsBridge、Infra Game の CoreLab など）の入口ページと、それらをまとめて配信するサーバー。
`/` がサイト一覧、各サイトは `/news`・`/infra` のように自分のパスの下で動く。ポート 5000 で Tailscale・LAN・自分自身（Funnel の公開はここ経由）から受け付ける。

**配信はクラウドの VM（Oracle Cloud Always Free）で、GitHub に push すると 1 分以内に反映される。** 準備と移し方は [deploy/README.md](deploy/README.md)。以下の「起動と切り替え」は PC で動かすときの話。

## 構成

```
sites.toml            サーバー設定（[server]）と、一覧に並べるサイト（ここを書き換えればサイトが増える）
launcher.py           起動役: 仮想環境の準備、ログオン時の自動起動、サーバーの見張りと再起動
start.bat             launcher.py をダブルクリックで動かす
homepage/server.py    サーバー本体（waitress）: 待ち受け、ホスト名の確認、テスト公開の https/noindex、自動再起動
homepage/__init__.py  ポータル（WSGI）: 振り分け、sites.toml、一覧ページ、カードの検索（/search）、/version.json、/portal.webmanifest
homepage/static.py    フォルダのサイトの配信（ETag・gzip・?v= の版・戻るリンク・og:image の補完）
homepage/pages.py     ポータル自身の小さなページ（404・持ち主のログイン）と、ダーク/ライト（THEME_SCRIPT。localStorage "theme" は全サイト共通）
homepage/web.py       答え方の共通部品（セキュリティヘッダ、転送、アドレス、パッケージのファイル）
homepage/status.py    動いている版（各リポジトリの .git を直接読む）と、VM の負荷・メモリ・ディスク
homepage/owner.py     持ち主のログイン（/owner）: パスワード、署名つきクッキー、試行回数の制限
homepage/i18n.py      言語（日本語・한국어・English (UK)・中文（台灣））: 訪問者の選択、ブラウザの言語、言語メニュー、ページの文言
homepage/page.html    一覧ページのひな形 / portal.css 見た目 / icons/*.svg アイコン / favicon.svg
homepage/og.png       リンクを貼ったときのプレビュー画像（1200×630）/ apple-touch-icon.png ホーム画面のアイコン（180×180）
homepage/icon-*.png   ホーム画面に追加したときのアプリのアイコン（192・512・maskable。favicon.svg から作った）
homepage/__main__.py  python -m homepage --demo: 一覧の見た目だけを試す小さなサーバー
tests/                python -m unittest discover -s tests
deploy/               クラウドの VM で配信する: 準備（setup.sh）、GitHub からの自動反映（update.sh）、PC からの移行（migrate.py）
docs/CONVENTIONS.md   3 リポジトリ共通のルール（書式・ツール・CI・Git・サイトの約束）
patches/              News Site へ渡したパッチの控え
instance/             server.log、owner-notes/（VM の setup.sh が一覧の持ち主欄に出すメモ）など（git 管理外）
```

Python 3.11 以上。サーバー用の仮想環境は `%LOCALAPPDATA%\HomePage\venvs\<フォルダのハッシュ>`（waitress と、各 Python サイトの requirements.txt）。

## 書式とチェック

News Site・Infra Game と共通のルール（1 行 120 字・ダブルクォート・LF ほか）。まとめは [docs/CONVENTIONS.md](docs/CONVENTIONS.md)。VS Code は推奨拡張（EditorConfig・Ruff・Prettier・Even Better TOML・ShellCheck ほか）を入れると保存時に整形する。

```bash
uvx ruff@0.16.9 format .   # Python の整形
uvx ruff@0.16.9 check .    # Python のチェック
uvx taplo@0.9.3 fmt        # TOML の整形（確かめるだけなら --check）
npm install                # 初回だけ（Prettier。サーバー自体は使わない）
npm run format             # CSS・Markdown・JSON・YAML の整形
npm run lint               # 整形済みかの確認
```

GitHub に push すると Actions（`.github/workflows/ci.yml`）がテスト（Ubuntu と Windows）・Ruff・Prettier・Taplo・ShellCheck を通す。VM は master を 1 分以内に配信するので、赤くなったらすぐ直す。page.html と patches/ は整形しない（`.prettierignore`）。

## 起動と切り替え

- 初めて（News Site のサーバーから切り替えるとき）: `py -3 launcher.py --take-over`
  ログオン時の自動起動（タスク `HomePage-Server-<ハッシュ>`）を登録し、News Site 自身のサーバー（launcher.py・app.py。収集の collector は止めない）を止めて、このサーバーを裏で起動する
- 以降はログオンの 30 秒後に自動で起動する。手で起動するなら `start.bat`（すでに動いていれば一覧を開くだけ）
- ログは `instance\server.log`
- 自動起動をやめる: `py -3 launcher.py --no-logon`
- 元に戻す: `--no-logon` → このサーバーを止める → News Site の `launcher.py` を起動（News Site の設定画面で「ログオン時に起動」を入れ直す）

サーバーは次のとき自動で再起動する（処理中の要求を返してから。約15秒以内に気づく）:

- `homepage/*.py` が変わった
- sites.toml の `[server]` か Python サイトの指定（mount・python・entry）が変わった
- Python サイトの版が変わった（News Site は配備で `VERSION` が書き換わる）。requirements.txt が変わっていればパッケージも入れ直す
- 起動後に Tailscale や LAN のアドレスが使えるようになった

## サイトの足し方

`sites.toml` に `[[site]]` を1つ書き足して、一覧ページを再読み込みするだけ（静的サイトは再起動不要）。
書き方の見本と各項目の意味は sites.toml の先頭にある。最小限は次の4行:

```toml
[[site]]
mount = "/memo"        # アドレス
folder = "../Memo"     # index.html のあるフォルダ（sites.toml からの相対パスか絶対パス）
name = "Memo"
```

- 静的ファイルは `.html .css .js .json .svg .png .jpg .gif .webp .ico .woff2 .mp3 .mp4 .webm .wasm` だけ配信。ドットファイル・ドットフォルダ・フォルダの外は 404、GET/HEAD のみ
- 静的ファイルには ETag を付け、変わっていなければ 304（中身なし）で返す。1KB 以上のテキスト（html・css・js・json・svg・wasm）は gzip で送る（CoreLab のスクリプト約 1.2MB が 2 回目以降はほぼ 0、初回も約 1/5）
- `preview = "portal.json"` で、サイトのフォルダにある JSON の中身をカードに並べる（`{"title": "見出し", "items": [["文", "/サイト内のパス"], ...]}`、最大 5 件、サイト内のパスだけ）。JSON を書き換えると一覧に即反映。CoreLab は「すぐ遊べるミッション」を Infra Game 側の portal.json で持つ
- 「← サイト一覧」へ戻るリンクは、サイトが自前で持っていなければポータルが各 HTML の左下に自動で付ける（自前で持つなら `home_link = "own"`）
- HTML の `og:image`・`og:url` は相対で書いてよい（`content="og.png"`）。リンクのプレビューには完全なアドレスが要るので、ポータルが訪問者の使ったアドレスで補う（CoreLab の og.png）
- `search = "/search?q={q}"` でカードに検索欄が付く。入れた言葉を `{q}` に入れて、サイト内のそのアドレスへ送る（ポータルの `/search?site=/val&q=…` が転送するので、CoreLab の `/#/ref?q={q}` のような `#` の中も可）。薄い文字は `search_hint`
- `links = [["ランキング", "/leaderboard"], ...]` でカードに「よく使うページ」が並ぶ。ほかの言語は `[site.ko]` などに `links = ["리더보드", ...]`（文だけを同じ順に）
- `public = false` でテスト公開（Funnel）の名前からは隠す。このPC・LAN からは見えるので、公開前の確認に使える
- 書き間違いや読み込めなかったサイトは、このPCから一覧を開いたときだけページ下の「このPCの持ち主向け」欄に理由が出る
- Python の Web アプリは `python = "フォルダ"` と `entry = "モジュール:関数"` で足す。関数は `site(mount=..., host={...})` で `{"app": WSGIアプリ, "name", "subtitle", "preview", "disallow", "legacy", "version"}` を返す（homepage/server.py の説明、News Site の newsreader/hosting.py が実例）

デザイン（page.html・portal.css・icons）の変更は再読み込みで反映される。見た目だけ試すなら:

```bash
python -m homepage --demo
```

→ http://127.0.0.1:5055/

## 動いている版と VM の状態

- `/version.json` は、いま公開中の各サイトのコミット（`"/"` が Home Page）とサーバーの起動時刻を返す。
  Home Page の新しい .py は再起動してから、ページ・CSS・sites.toml・フォルダのサイトはすぐに数える
- Live site（`.github/workflows/live.yml`）は master への push のあと、`deploy/livecheck.py --expect <コミット>` で
  その版が出るのを待ってから（最大 8 分）ページを確かめる。ほかのリポジトリでも `--site /val` で同じように待てる。
  ほかのリポジトリのマージは、Live site を手動で実行し site（`/infra` など）と commit（マージのコミット全体）を入れると同じ確認になる
- 一覧の下の持ち主向けの欄に、各サイトの版と届いた時刻、再起動待ちかどうか、VM の負荷・メモリ・スワップ・ディスクが出る（訪問者には出ない）
- 一覧はスマホのホーム画面にアプリとして追加できる（`/portal.webmanifest`。iPhone は apple-touch-icon）

## 言語

どのサイトも日本語・韓国語・英語（英国）・繁体字中国語（台湾）で表示できる。

- 訪問者は各サイトの右上の言語メニュー（地球のマーク）で選ぶ。選んだ言語は `lang` クッキー（このホスト全体）に残り、一覧・NewsBridge・CoreLab のどれでも同じ言語になる
- まだ選んでいなければブラウザの言語（Accept-Language）で決める。対応していない言語だけなら英語、何も送ってこなければ日本語
- どのアドレスでも `?lang=ko`（`ja` `ko` `en-GB` `zh-TW`）を付けると、その言語を覚えて同じアドレスへ戻す（ポータルが受けるので、静的サイトも Python サイトも同じ）
- 一覧ページの文言は sites.toml の `[ko]` `[en-GB]` `[zh-TW]`、各サイトの紹介は `[[site]]` の下の `[site.ko]` など。書いていない項目は日本語のまま
- `preview` の JSON の文は `{"ja": "…", "ko": "…", "en-GB": "…", "zh-TW": "…"}` でもよい。Python サイトの `preview` は言語を1つ受け取れる（`preview(lang)`）
- 見つからないページは、ブラウザには訪問者の言語で「ページが見つかりません」とサイトのトップ・サイト一覧へのリンクを返す

## News Site との関係

- News Site は sites.toml の `python = "../News Site/work/app"`、`entry = "newsreader.hosting:site"` でこのサーバーに読み込まれる（同じプロセスで動く）
- 読み込まれた News Site は、自分のログオン時の自動起動を外し、`instance\hosted.json` に配信先を書く。News Site の launcher.py は、このサーバーが動いていれば2台目を起動せずにここを開く
- News Site 単体（他のPC・テスト版）は今までどおり自分で起動し、`/` は `/news/` へ転送される
- 旧アドレス（`/a/123` など）は `/news/…` へ 302 転送、`/relay/…` はそのまま News Site が答える（恒久的な 308 にしないのは、ブラウザがそれを覚え続け、あとで足したサイトのアドレスまで News Site へ行ってしまうため）
- `News Site\work\app` には直接コミットしない。News Site 側の変更はパッチにして News Site プロジェクトに取り込んでもらう

## パッチ

News Site へ渡したパッチの控えは `patches/` にある（どれも取り込み済み。最後の `news-site-i18n-20261027.patch` は News Site の ba2225f）。

## 今後の候補

- サイトを足したら og.png（一覧のプレビュー画像。いまは NewsBridge・CoreLab・VAL Tracker のカード）も作り直す
