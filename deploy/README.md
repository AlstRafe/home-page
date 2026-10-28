# クラウドのサーバーで配信する（Oracle Cloud Always Free）

PC を切っても `/`・`/news`・`/infra` が動き続けるように、Oracle Cloud の無料 VM で配信する。費用は 0 円（Always Free の範囲だけを使う）。

## しくみ

- **VM**: Oracle Cloud の Always Free、Arm の VM.Standard.A1.Flex（2 OCPU・12 GB、Ubuntu 24.04）
- **公開**: Tailscale Funnel（`https://<名前>.<tailnet>.ts.net/`）。ポート開放もドメインもいらない。移行のときに PC の今のアドレスを VM に引き継ぐので、配ったリンクはそのまま使える
- **コード**: GitHub の `home-page`・`news-site`・`infra-game`。VM が 1 分ごとに見に行き、**master** に push されたものに切り替える（`update.sh`。リポジトリの既定ブランチではなく、いつも master）。サーバーは新しいコードで自分で再起動する
- **データ**: News Site の DB・設定・記事は VM の中（`/srv/sites/News Site/work/app` の `instance/` と `articles/`）。git には入れない。毎時の収集も VM で動く。毎日 4:30 ごろ `instance/` を `/srv/sites/backup` に保存（14 日分）
- **止められないために**: Always Free の VM は「7 日間、CPU・ネットワーク・メモリがどれも 20% 未満」だと Oracle に回収されることがある。`keepalive.py` がメモリの 25% と、10 分ごとに 90 秒の CPU を最低優先度で使う（サイトの処理がいつも先）

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
- 持ち主向けのページ（一覧の「持ち主向け」欄、News Site の設定）: tailnet の端末から `http://<名前>:5000/`
- 再起動: `sudo systemctl restart homepage`
- News Site のデータだけ PC から送り直す: `py -3 deploy\migrate.py --host <名前> --data-only`（VM にあったデータは `/srv/sites/backup` に移る）
- 設定の入れ直し（何度実行してもよい）: `sudo bash "/srv/sites/Home Page/deploy/setup.sh"`

## うまくいかないとき

- **ssh で入れない**: 古い tailnet だと SSH の許可がない。管理画面の Access controls の `"ssh"` に `{"action": "check", "src": ["autogroup:member"], "dst": ["autogroup:self"], "users": ["autogroup:nonroot", "root"]}` を足す
- **Tailscale のない端末から開けない / Funnel が有効にならない**: PC で `ssh -t ubuntu@<名前>.<tailnet>.ts.net "sudo bash '/srv/sites/Home Page/deploy/setup.sh' --funnel"`。URL が出たら開いて Funnel を許可する。`公開アドレス:` と出れば外から開ける（反映に数分かかることがある）
- **アドレスの引き継ぎで PC の名前を変えられなかった**: 管理画面で PC の名前を `<名前>-pc` に変えてから `py -3 deploy\migrate.py --address-only`
- **PC で配信に戻す**: VM の名前を変える（`sudo tailscale set --hostname=sites`）→ PC の名前を元に戻す → PC で `py -3 launcher.py --take-over` と `tailscale funnel --bg 5000`、News Site の収集タスクを有効に戻す（`schtasks /Change /TN <タスク名> /ENABLE`）

## ファイル

```
cloud-init.sh            VM を作るときに貼る（Tailscale に参加）
migrate.py               PC で実行: VM の準備、データの移動、アドレスの引き継ぎ
setup.sh                 VM の準備（何度実行してもよい）、--import / --funnel / --units / --sync
update.sh                1 分ごとに GitHub から取り込む（sites-update.timer）
import_news_data.py      PC から来た News Site のデータを取り込む
backup.py                News Site の instance/ を毎日保存（sites-backup.timer）
keepalive.py             Always Free の VM が回収されないように（sites-keepalive.service）
systemd/                 homepage.service（サーバー）、news-collector.timer（毎時の収集）ほか
```

VM の中の配置は PC と同じ並び（`/srv/sites/Home Page`・`/srv/sites/News Site/work/app`・`/srv/sites/Infra Game`）なので、sites.toml はそのまま使える。Python のパッケージは `/srv/sites/venv`、API キーは sites アカウントだけが読めるファイル（keyrings.alt）。
