#!/bin/bash
# Oracle Cloud のインスタンス作成画面で「拡張オプションの表示 → 管理 → cloud-init スクリプトの貼付け」に
# この内容をそのまま貼る。書き換えるのは TS_AUTHKEY の1行だけ
# （Tailscale 管理画面 → Settings → Keys → Generate auth key… で作ったキー）。
# VM が起動すると Tailscale に参加し、PC から `ssh ubuntu@sites` で入れるようになる。
TS_AUTHKEY="tskey-auth-ここに貼る"
NAME="sites"

hostnamectl set-hostname "$NAME"
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --auth-key="$TS_AUTHKEY" --ssh --hostname="$NAME"
