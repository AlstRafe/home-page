# クラウドのサーバーで配信する（Oracle Cloud Always Free）

PC を切っても `/`・`/news`・`/infra`・`/val` が動き続けるように、Oracle Cloud の無料 VM で配信する。費用は 0 円（Always Free の範囲だけを使う）。

## しくみ

- **VM**: Oracle Cloud の Always Free、Arm の VM.Standard.A1.Flex（2 OCPU・12 GB、Ubuntu 24.04）
- **公開**: Tailscale Funnel（`https://<名前>.<tailnet>.ts.net/`）。ポート開放もドメインもいらない。移行のときに PC の今のアドレスを VM に引き継ぐので、配ったリンクはそのまま使える。ただし Funnel は接続のたびに暗号化の握手で 0.7〜5 秒かかるので、速くするには下の「直接配信」で VM から直接配信する（DuckDNS の無料の名前と Caddy）
- **コード**: GitHub の `home-page`・`news-site`・`infra-game`・`valorant-project`。VM が 1 分ごとに見に行き、**master** に push されたものに切り替える（`update.sh`。リポジトリの既定ブランチではなく、いつも master）。サーバーは新しいコードで自分で再起動する
- **データ**: News Site の DB・設定・記事は VM の中（`/srv/sites/News Site/work/app` の `instance/` と `articles/`）。git には入れない。毎時の収集も VM で動く。毎日 4:30 ごろ `instance/` を `/srv/sites/backup` に保存（14 日分）
- **止められないために**: Always Free の VM は「7 日間、CPU・ネットワーク・メモリがどれも 20% 未満」だと Oracle に回収されることがある。`keepalive.py` がメモリの 25%（4 GB 以上のとき）と、毎晩 3〜5 時（日本時間）の 2 時間だけ CPU を使う。日中は何もしない（1/8 OCPU の VM では、どんなに譲っても使った分だけサイトが遅くなるため）

## 初めてのとき（30 分ほど）

### 1. Tailscale の鍵を作る

[Tailscale の管理画面 → Settings → Keys](https://login.tailscale.com/admin/settings/keys) で **Generate auth key…**（Reusable はオフ、有効期限は 1 日でよい）。`tskey-auth-…` をコピーしておく。

### 2. Oracle Cloud に登録して VM を作る

1. https://signup.cloud.oracle.com/ で登録する（カードの登録はあるが、Always Free の範囲なら請求されない）。**ホーム・リージョンは後から変えられない**ので、Japan East (Tokyo) か Japan Central (Osaka) を選ぶ
2. メニュー → コンピュート → インスタンス → **インスタンスの作成**
   - イメージ: **Canonical Ubuntu 24.04**
   - シェイプ: Ampere → **VM.Standard.A1.Flex**、OCPU **2**・メモリ **12 GB**（「Always Free 対象」と出ていること）
   - ネットワーク: 既定のまま
   - SSH キー: **キーなし**でよい（入るのは Tailscale SSH）
   - ブート・ボリューム: 既定のまま（約 50 GB）
   - 拡張オプション → 管理 → 初期化スクリプト → **cloud-init スクリプトの貼付け**: [`cloud-init.sh`](cloud-init.sh) の中身を貼り、`TS_AUTHKEY` の行を 1. のキーに書き換える
3. **作成**。「容量不足（Out of capacity）」と出たら、OCPU 1・メモリ 6 GB に下げるか、時間をおいて作り直す（東京・大阪は可用性ドメインが 1 つだけ）。どうしても空かなければ Specialty and previous generation の VM.Standard.E2.1.Micro（AMD・1 GB、これも無料）でも動く（setup.sh が 2 GB のスワップを足す）
4. 数分で Tailscale の管理画面（Machines）に `sites` が出る。その行の「…」→ **Disable key expiry**（しないと 180 日で tailnet から外れ、公開も止まる）

### 3. PC から移す

Home Page のフォルダで:

```
py -3 deploy\migrate.py
```

1. VM を準備する。GitHub の鍵の登録ページの URL と鍵が 3 組出るので、それぞれのページで **Add deploy key** に貼る（Title は `sites-server`、Allow write access は付けない）→ Enter
2. 「続けますか？」で `y`: PC の毎時の収集を止め、記事・DB・設定・API キーを VM へ送り、PC のサーバー・自動起動・Funnel を止めて、今の公開アドレスを VM に渡す（PC は Tailscale で `<名前>-pc` になる）
3. 「公開アドレスが答えています」と出たら完了。PC は切ってよい

アドレスを引き継がず VM 自身の名前（`https://sites.<tailnet>.ts.net/`）で公開するなら `--new-address`。

## そのあと

- **変更は GitHub に push するだけ**（1 分以内に反映）。VM の中のファイルは直接書き換えない（次の反映で GitHub の内容に戻る）
- VM に入る: `ssh ubuntu@<名前>.<tailnet>.ts.net`（公開アドレスのホスト名。移行後は PC の元の名前なので、短い名前だと PC 自身を指してしまう）
- 記録: `journalctl -u homepage -u sites-update -u news-collector -n 50`
- 持ち主向けのページ（一覧の「持ち主向け」欄、News Site の設定）: tailnet の端末から `http://<名前>:5000/`、または下の「持ち主のログイン」でログインした端末から公開アドレスで
- 再起動: `sudo systemctl restart homepage`
- 外からの見え方: GitHub Actions の **Live site** が 6 時間ごとと master への push の後に公開アドレスを開き、各サイトのトップ・リンクのプレビュー画像・セキュリティのヘッダを確かめる（`deploy/livecheck.py`。PC で `py -3 deploy\livecheck.py` でもよい）。赤くなると GitHub からメールが来る
- News Site のデータだけ PC から送り直す: `py -3 deploy\migrate.py --host <名前> --data-only`（VM にあったデータは `/srv/sites/backup` に移る）
- 設定の入れ直し（何度実行してもよい）: `sudo bash "/srv/sites/Home Page/deploy/setup.sh"`

## リポジトリ（サイト）を足す

例: VAL Tracker（`valorant-project` → `/srv/sites/VALORANT-Project`、`/val`）。

1. `deploy/setup.sh` と `deploy/update.sh` の `repos()` に `<リポジトリ名> "<フォルダ名>"` を足し、`sites.toml` に `[[site]]` を足して master へ（フォルダは PC と同じ並び。まだ取得していないサイトは一覧に出ないだけ）
2. PC で `ssh -t haruxera-vm "sudo bash '/srv/sites/Home Page/deploy/setup.sh' --repos"` → 出た URL を開き、**Add deploy key** に鍵を貼る（Title は `sites-server`、Allow write access は付けない）
3. 同じコマンドをもう一度。取得し、requirements.txt のパッケージを入れ、サーバーを再起動して読み込む
4. `deploy/livecheck.py` の確認先にそのサイトを足す

VM からの外向きの通信（HTTPS）は制限していないので、サイトが使う外部の API（VAL Tracker なら api.henrikdev.xyz・valorant-api.com・media.valorant-api.com）はそのまま使える。API キーが要るサイトは、持ち主のログインをした端末からそのサイトの設定ページで入れる（VAL Tracker は `/val/settings`）。

## 直接配信（Funnel より速い）

Funnel は Tailscale の中継を通るので、新しい接続のたびに 0.7〜5 秒待つ（VM の中なら 0.05 秒）。VM の 443 番で Caddy が直接答えるようにすると、この待ちがなくなる。費用は 0 円のまま。

1. https://www.duckdns.org/ で GitHub などでログイン → sub domain に `haruxera` → **add domain**。画面上部の **token** をコピーしておく
2. Oracle Cloud: メニュー → ネットワーキング → 仮想クラウド・ネットワーク → VM の VCN → セキュリティ・リスト → **Default Security List** → **イングレス・ルールの追加**: ソース CIDR `0.0.0.0/0`、宛先ポート範囲 `80,443` → 追加
3. PC で `ssh -t ubuntu@<名前>.<tailnet>.ts.net "sudo bash '/srv/sites/Home Page/deploy/setup.sh' --direct haruxera"` → token を貼って Enter（表示されない）。`公開アドレス: https://haruxera.duckdns.org/` と出れば完了

setup.sh が DuckDNS の名前をこの VM の公開 IP に向け（毎日 `sites-duckdns.timer` が見直す）、Caddy を入れて Let's Encrypt の証明書を取り（更新も Caddy）、VM のファイアウォール（iptables）で 80 と 443 を開ける。サーバーがこの名前を訪問者として扱うのは `sites.toml` の `[server] public` に書いてあるから。`moved_to` も書くと、Funnel のアドレスで開かれたページはこの名前へ転送される（307。POST は転送しない）。Funnel はそのまま動かしておく（古いリンクと tailnet のため）。

## 持ち主のログイン（Tailscale なしで全機能）

公開アドレスでは、だれでも訪問者として表示される（News Site の設定・取得の状況・保存・単語帳はなく、既読も残らない）。持ち主の端末はパスワードでログインすると、公開アドレスのままで全部使える。

1. PC で `ssh -t ubuntu@haruxera.duckdns.org "sudo bash '/srv/sites/Home Page/deploy/setup.sh' --owner"` → パスワード（10 文字以上）を 2 回。表示されない
2. 各端末で `https://haruxera.duckdns.org/owner` を開いてログイン（400 日覚えている）

パスワードは scrypt のハッシュだけが `/srv/sites/state/owner.json` に残る。決め直すと、すべての端末がログアウトされる。やめるときは `--owner off`。パスワードの間違いは全体で 1 分に 5 回・1 時間に 20 回まで。

VM へは鍵の SSH でも入れる（Tailscale がなくてよい）: PC の公開鍵を VM の `~ubuntu/.ssh/authorized_keys` に足して `ssh ubuntu@haruxera.duckdns.org`。鍵がなくなったときは Oracle Cloud のコンソール（インスタンス → コンソール接続 / Cloud Shell）から足し直す。

## うまくいかないとき

- **ssh で入れない**: 古い tailnet だと SSH の許可がない。管理画面の Access controls の `"ssh"` に `{"action": "check", "src": ["autogroup:member"], "dst": ["autogroup:self"], "users": ["autogroup:nonroot", "root"]}` を足す
- **直接配信で「証明書が取れませんでした」**: 2. のセキュリティ・リストを確かめて、3. をもう一度（token は覚えているので貼らなくてよい）。新しく作ったセキュリティ・リストは、VM のサブネット（サブネット → セキュリティ → セキュリティ・リストの追加）に付けるまで効かない。記録は `journalctl -u caddy -n 30`
- **Tailscale のない端末から開けない / Funnel が有効にならない**: PC で `ssh -t ubuntu@<名前>.<tailnet>.ts.net "sudo bash '/srv/sites/Home Page/deploy/setup.sh' --funnel"`。URL が出たら開いて Funnel を許可する。`公開アドレス:` と出れば外から開ける（反映に数分かかることがある）
- **アドレスの引き継ぎで PC の名前を変えられなかった**: 管理画面で PC の名前を `<名前>-pc` に変えてから `py -3 deploy\migrate.py --address-only`
- **PC で配信に戻す**: VM の名前を変える（`sudo tailscale set --hostname=sites`）→ PC の名前を元に戻す → PC で `py -3 launcher.py --take-over` と `tailscale funnel --bg 5000`、News Site の収集タスクを有効に戻す（`schtasks /Change /TN <タスク名> /ENABLE`）

## ファイル

```
cloud-init.sh            VM を作るときに貼る（Tailscale に参加）
migrate.py               PC で実行: VM の準備、データの移動、アドレスの引き継ぎ
setup.sh                 VM の準備（何度実行してもよい）、--repos / --import / --funnel / --direct / --owner / --units / --sync
update.sh                1 分ごとに GitHub から取り込む（sites-update.timer）
import_news_data.py      PC から来た News Site のデータを取り込む
backup.py                News Site の instance/ を毎日保存（sites-backup.timer）
keepalive.py             Always Free の VM が回収されないように（sites-keepalive.service）
livecheck.py             公開アドレスを外から確かめる（GitHub Actions の Live site）
systemd/                 homepage.service（サーバー）、news-collector.timer（毎時の収集）ほか
```

VM の中の配置は PC と同じ並び（`/srv/sites/Home Page`・`/srv/sites/News Site/work/app`・`/srv/sites/Infra Game`・`/srv/sites/VALORANT-Project`）なので、sites.toml はそのまま使える。Python のパッケージは `/srv/sites/venv`、API キーは sites アカウントだけが読めるファイル（keyrings.alt）。
