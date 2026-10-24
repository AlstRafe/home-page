# Home Page — このPCのサイト一覧（ポータル）

このパソコンから配信しているサイト（News Site の NewsBridge、Infra Game の CoreLab など）を一覧し、各サイトへ進む入口ページ。
`/` が一覧、各サイトは `/news`・`/infra` のように自分のパスの下で動く。

## 構成

```
sites.toml            一覧に並べるサイトと、ページの見出し・説明文（ここを書き換えればサイトが増える）
homepage/__init__.py  ポータル本体（WSGI）: 振り分け・一覧ページ・静的サイトの配信
homepage/page.html    一覧ページのひな形（{{ … }} が差し込み口）
homepage/portal.css   見た目（ライト/ダーク、カード、色は accent-* クラス）
homepage/icons/*.svg  サイトのアイコン（sites.toml の icon = "ファイル名"）
homepage/favicon.svg
homepage/__main__.py  python -m homepage: このPCだけで一覧を試す小さなサーバー
tests/                python -m unittest discover -s tests
patches/              News Site へ渡したパッチの控え
```

Python 3.11 以上（標準ライブラリだけで動く。sites.toml は tomllib で読む）。

## サイトの足し方

`sites.toml` に `[[site]]` を1つ書き足して、一覧ページを再読み込みするだけ（サーバーの再起動は不要）。
書き方の見本と各項目の意味は sites.toml の先頭に書いてある。最小限は次の4行:

```toml
[[site]]
mount = "/memo"        # アドレス
folder = "../Memo"     # index.html のあるフォルダ（sites.toml からの相対パスか絶対パス）
name = "Memo"
```

- 静的ファイルは `.html .css .js .json .svg .png .jpg .gif .webp .ico .woff2 .mp3 .mp4 .webm .wasm` だけ配信。ドットファイル・ドットフォルダ・フォルダの外は 404、GET/HEAD のみ
- 「← サイト一覧」へ戻るリンクは、サイトが自前で持っていなければポータルが各 HTML の左下に自動で付ける（自前で持つなら `home_link = "own"`）
- `public = false` でテスト公開（Funnel）の名前からは隠す。このPC・LAN からは見えるので、公開前の確認に使える
- 書き間違い（色名の誤り、フォルダが無い、アドレスの重複など）は、このPCから一覧を開いたときだけページ下の「このPCの持ち主向け」欄に理由が出る。壊れた sites.toml は直すまで前の内容のまま表示する
- News Site のような「サーバーが用意するアプリ」は `app = "news"` で並び順と説明文だけを指定する

デザイン（page.html・portal.css・icons）の変更も再読み込みで反映される。`homepage/*.py` を変えたときは、News Site のサーバーが約15秒以内に気づいて自動で再起動する（ランチャーから起動している場合）。

## 手元で試す

```bash
python -m homepage --demo
```

→ http://127.0.0.1:5055/ （`--demo` は /news に News Site の代わりを置く。127.0.0.1 だけで待ち受け）

## News Site との関係

- サーバー（起動・自動再起動・LAN/Tailscale/Funnel での待ち受け）は今も News Site（`News Site\work\app`）が持つ
- News Site の `newsreader/portal` は、このフォルダ（`HOME_PAGE_DIR`、無ければ `~/Documents/Claude/Home Page`）の `homepage` を読み込み、自分を `App("news", "/news", …)` として渡す。プレビュー（各社が伝えた話題3件と取得状況）も News Site 側が作る
- このフォルダが無い・読み込めない・版（`homepage.API`）が合わないときは、`/` は News Site へ直接転送される（他のPCやテスト版はこの形）
- テスト公開の名前では、https 扱い・`noindex`・HSTS を News Site 側がサイト全体に付ける。ポータルはその名前の訪問者に「持ち主向け」欄と `public = false` のサイトを見せない
- 旧アドレス（`/a/123` など）は `/news/…` へ 308 転送、`/relay/…` はそのまま News Site が答える
- `work\app` は News Site のクラウド側リポジトリから同期される。**ここへ直接コミットしない**。News Site 側の変更はパッチにして News Site プロジェクトに取り込んでもらう

## 取り込み待ち

- `News Site\work\scratch\home-page-portal-20261024.patch`（控え: `patches/`）
  - News Site のポータルを Home Page 読み込み式に置き換え（`index.html`・`portal.css` を削除）、Home Page のコード変更で自動再起動、テストを更新
  - News Site 側で `git am` → テスト → いつもの同期で反映。反映されるまでは今のサーバーが古い一覧を出し続ける（このフォルダの変更はまだ効かない）

## 今後の候補

- サーバー自体を News Site から独立させる（起動・自動再起動・Funnel 公開の仕組みを Home Page 側へ移す）
- 静的サイトの「最新状況」（今は更新日だけ）をサイト側の小さな JSON から読む
