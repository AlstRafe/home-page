# Home Page — このPCのサイトとサーバー

このパソコンから配信しているサイト（News Site の NewsBridge、Infra Game の CoreLab など）の入口ページと、それらをまとめて配信するサーバー。
`/` がサイト一覧、各サイトは `/news`・`/infra` のように自分のパスの下で動く。ポート 5000 で Tailscale・LAN・このPC（Funnel のテスト公開はここ経由）から受け付ける。

## 構成

```
sites.toml            サーバー設定（[server]）と、一覧に並べるサイト（ここを書き換えればサイトが増える）
launcher.py           起動役: 仮想環境の準備、ログオン時の自動起動、サーバーの見張りと再起動
start.bat             launcher.py をダブルクリックで動かす
homepage/server.py    サーバー本体（waitress）: 待ち受け、ホスト名の確認、テスト公開の https/noindex、自動再起動
homepage/__init__.py  ポータル（WSGI）: 振り分け、一覧ページ、静的サイトの配信
homepage/compat.py    News Site に newsreader.hosting が入るまでの代わりの読み込み口（入ったら消す）
homepage/page.html    一覧ページのひな形 / portal.css 見た目 / icons/*.svg アイコン / favicon.svg
homepage/__main__.py  python -m homepage --demo: 一覧の見た目だけを試す小さなサーバー
tests/                python -m unittest discover -s tests
patches/              News Site へ渡したパッチの控え
instance/             server.log など（git 管理外）
```

Python 3.11 以上。サーバー用の仮想環境は `%LOCALAPPDATA%\HomePage\venvs\<フォルダのハッシュ>`（waitress と、各 Python サイトの requirements.txt）。

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
- 「← サイト一覧」へ戻るリンクは、サイトが自前で持っていなければポータルが各 HTML の左下に自動で付ける（自前で持つなら `home_link = "own"`）
- `public = false` でテスト公開（Funnel）の名前からは隠す。このPC・LAN からは見えるので、公開前の確認に使える
- 書き間違いや読み込めなかったサイトは、このPCから一覧を開いたときだけページ下の「このPCの持ち主向け」欄に理由が出る
- Python の Web アプリは `python = "フォルダ"` と `entry = "モジュール:関数"` で足す。関数は `site(mount=..., host={...})` で `{"app": WSGIアプリ, "name", "subtitle", "preview", "disallow", "legacy", "version"}` を返す（homepage/server.py の説明、News Site の newsreader/hosting.py が実例）

デザイン（page.html・portal.css・icons）の変更は再読み込みで反映される。見た目だけ試すなら:

```bash
python -m homepage --demo
```

→ http://127.0.0.1:5055/

## News Site との関係

- News Site は sites.toml の `python = "../News Site/work/app"`、`entry = "newsreader.hosting:site"` でこのサーバーに読み込まれる（同じプロセスで動く）
- 読み込まれた News Site は、自分のログオン時の自動起動を外し、`instance\hosted.json` に配信先を書く。News Site の launcher.py は、このサーバーが動いていれば2台目を起動せずにここを開く（パッチ適用後）
- News Site 単体（他のPC・テスト版）は今までどおり自分で起動し、`/` は `/news/` へ転送される
- 旧アドレス（`/a/123` など）は `/news/…` へ 308 転送、`/relay/…` はそのまま News Site が答える
- `News Site\work\app` には直接コミットしない。News Site 側の変更はパッチにして News Site プロジェクトに取り込んでもらう

## 取り込み待ち

- `News Site\work\scratch\home-page-server-20261024.patch`（控え: `patches/`、1 コミット）
  - `newsreader/hosting.py`（このサーバー向けの読み込み口）を追加、`newsreader/portal` を News Site 単体用に縮小（一覧ページ・CoreLab 配信を削除）、launcher.py が Home Page 配信中は2台目を起動しない、テスト更新
  - 取り込まれるまでは `homepage/compat.py` が代わりを務める。取り込み後の配備（VERSION の更新）でサーバーが再起動し、自動で hosting.py に切り替わる。その後 compat.py と server.py の `COMPAT` を消す

## 今後の候補

- 静的サイトの「最新状況」（今は更新日だけ）をサイト側の小さな JSON から読む
