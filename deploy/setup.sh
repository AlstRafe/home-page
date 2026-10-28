#!/usr/bin/env bash
# Sets this Linux server up as the server of the sites: Home Page (the site list and the server
# itself), News Site under /news and Infra Game (CoreLab) under /infra, each cloned from its GitHub
# repository, served on https://<this machine>.<tailnet>.ts.net/ through Tailscale Funnel.
#
#   sudo bash setup.sh                  first time, and again after adding the deploy keys it prints
#   sudo bash setup.sh --import FILE    take in News Site's data from the PC (made by migrate.py)
#   sudo bash setup.sh --units          reinstall the systemd units only (update.sh does this when deploy/ changed)
#   sudo bash setup.sh --funnel         publish port 5000 again (after the machine was renamed)
#   sudo bash setup.sh --sync           what update.sh runs after pulling (units, packages, VERSION as needed)
#
# Safe to run again: whatever is in place already is kept. Ubuntu 22.04 or newer.
# Layout (the same relative places as on the PC, so sites.toml works as it is):
#   /srv/sites/Home Page   /srv/sites/News Site/work/app   /srv/sites/Infra Game
#   /srv/sites/venv (Python packages)   /srv/sites/state   /srv/sites/backup
set -euo pipefail

OWNER="${OWNER:-AlstRafe}"
ROOT=/srv/sites
ACCOUNT=sites
VENV="$ROOT/venv"
STATE="$ROOT/state"
PORT=5000
PACKAGES=("waitress>=3.0,<4" "keyrings.alt>=5,<6")
export PYTHON_KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring

# GitHub repository <TAB> folder under /srv/sites
repos() {
  printf '%s\t%s\n' home-page "Home Page" news-site "News Site/work/app" infra-game "Infra Game"
}

as_site() { runuser -u "$ACCOUNT" -- env HOME="$ROOT" PYTHON_KEYRING_BACKEND="$PYTHON_KEYRING_BACKEND" "$@" </dev/null; }
say() { printf '\n== %s\n' "$*"; }

pick_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys, venv; sys.exit(sys.version_info < (3, 11))' 2>/dev/null \
       && "$candidate" -c 'import ensurepip' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

install_packages() {
  say "パッケージ"
  export DEBIAN_FRONTEND=noninteractive
  apt-get -o DPkg::Lock::Timeout=600 update -q
  apt-get -o DPkg::Lock::Timeout=600 install -y -q git curl ca-certificates python3 python3-venv
  if ! pick_python >/dev/null; then  # Ubuntu 22.04: Python 3.10 only by default
    apt-get -o DPkg::Lock::Timeout=600 install -y -q python3.11 python3.11-venv
  fi
  if ! command -v tailscale >/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
  fi
}

# A small VM (the 1 GB VM.Standard.E2.1.Micro) gets 2 GB of swap: installing the packages, the server
# and an hourly collection at once would not fit in its memory otherwise.
add_swap() {
  local memory
  memory="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
  if [ "${memory:-0}" -lt 3000000 ] && [ -z "$(swapon --show --noheadings)" ]; then
    say "スワップ（メモリが少ないので 2 GB）"
    [ -f /swapfile ] || { fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none; }
    chmod 600 /swapfile
    mkswap -q /swapfile
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
}

make_account() {
  if ! id "$ACCOUNT" >/dev/null 2>&1; then
    useradd --system --home-dir "$ROOT" --shell /usr/sbin/nologin "$ACCOUNT"
  fi
  install -d -o "$ACCOUNT" -g "$ACCOUNT" -m 700 "$ROOT" "$ROOT/.ssh" "$STATE" "$ROOT/backup"
}

# One read-only deploy key per repository (GitHub accepts a key for one repository only).
make_keys() {
  local name dir config="$ROOT/.ssh/config"
  : > "$config.new"
  while IFS=$'\t' read -r name dir; do
    [ -f "$ROOT/.ssh/deploy_$name" ] || as_site ssh-keygen -q -t ed25519 -N "" -C "sites-server $name" -f "$ROOT/.ssh/deploy_$name"
    printf 'Host github-%s\n  HostName github.com\n  User git\n  IdentityFile %s\n  IdentitiesOnly yes\n  StrictHostKeyChecking accept-new\n\n' \
      "$name" "$ROOT/.ssh/deploy_$name" >> "$config.new"
  done < <(repos)
  mv "$config.new" "$config"
  chown "$ACCOUNT:$ACCOUNT" "$config"
  chmod 600 "$config"
}

clone_repos() {
  say "GitHub のリポジトリ（$OWNER）"
  local name dir missing=()
  while IFS=$'\t' read -r name dir; do
    if [ -d "$ROOT/$dir/.git" ]; then
      echo "$dir: あり"
      continue
    fi
    if ! as_site git ls-remote -q "git@github-$name:$OWNER/$name.git" HEAD >/dev/null 2>&1; then
      missing+=("$name")
      continue
    fi
    install -d -o "$ACCOUNT" -g "$ACCOUNT" "$(dirname "$ROOT/$dir")"
    as_site git clone -q -b master "git@github-$name:$OWNER/$name.git" "$ROOT/$dir"
    echo "$dir: 取得しました"
  done < <(repos)
  if [ ${#missing[@]} -gt 0 ]; then
    echo
    echo "次のリポジトリを読めません。GitHub の各ページで、下の鍵を Deploy key として登録してください"
    echo "（Title は sites-server、「Allow write access」は付けない）。登録したらもう一度このスクリプトを実行します。"
    for name in "${missing[@]}"; do
      echo
      echo "[$name] https://github.com/$OWNER/$name/settings/keys/new"
      cat "$ROOT/.ssh/deploy_$name.pub"
    done
    exit 3
  fi
}

requirements_stamp() {
  { printf '%s\n' "${PACKAGES[@]}"; cat "$ROOT/News Site/work/app/requirements.txt"; } | sha256sum | cut -d' ' -f1
}

# Every minute (update.sh): nothing but a checksum while the venv and the packages are in place.
install_python_packages() {
  local stamp
  stamp="$(requirements_stamp)"
  if [ -x "$VENV/bin/python" ] && [ "$(cat "$STATE/requirements" 2>/dev/null)" = "$stamp" ]; then
    return 0
  fi
  if [ ! -x "$VENV/bin/python" ]; then
    as_site "$(pick_python)" -m venv "$VENV"
  fi
  if [ "$(cat "$STATE/requirements" 2>/dev/null)" != "$stamp" ]; then
    say "Python のパッケージ"
    as_site "$VENV/bin/python" -m pip install -q --upgrade pip
    as_site "$VENV/bin/python" -m pip install -q "${PACKAGES[@]}" -r "$ROOT/News Site/work/app/requirements.txt"
    echo "$stamp" > "$STATE/requirements"
    "$VENV/bin/python" --version
  fi
}

# News Site's VERSION (ignored by git) names the commit being served; the server restarts into
# the new code when it changes (homepage/server.py).
write_version() {
  local app="$ROOT/News Site/work/app" version
  version="$(as_site git -C "$app" log -1 --format='git %h %cI')"
  if [ "$(cat "$app/VERSION" 2>/dev/null)" != "$version" ]; then
    as_site sh -c 'printf "%s\n" "$1" > "$2.tmp" && mv "$2.tmp" "$2"' - "$version" "$app/VERSION"
    echo "News Site: $version"
  fi
}

units_stamp() {
  cat "$ROOT/Home Page/deploy/systemd/"* | sha256sum | cut -d' ' -f1
}

install_units() {
  say "常駐の設定（systemd）"
  local unit
  for unit in "$ROOT/Home Page/deploy/systemd/"*; do
    install -m 644 "$unit" /etc/systemd/system/
  done
  systemctl daemon-reload
  systemctl enable --now homepage.service sites-keepalive.service \
    sites-update.timer news-collector.timer sites-backup.timer
  units_stamp > "$STATE/units"
}

# What update.sh runs every minute after pulling: each step only when what it depends on changed,
# so a step that failed (PyPI unreachable, say) is simply tried again a minute later. VERSION is
# written last: the server restarts into the new News Site only once its packages are in place.
sync_changes() {
  if [ "$(cat "$STATE/units" 2>/dev/null)" != "$(units_stamp)" ]; then
    install_units
    systemctl try-restart homepage.service sites-keepalive.service
  fi
  install_python_packages
  write_version
}

public_name() {
  tailscale status --json 2>/dev/null | "$VENV/bin/python" -c \
    'import json, sys; print((json.load(sys.stdin).get("Self") or {}).get("DNSName", "").rstrip("."))' 2>/dev/null || true
}

# Whether this machine is open to the internet through Funnel, not only to the tailnet.
funnel_on() {
  tailscale serve status --json 2>/dev/null | "$VENV/bin/python" -c \
    'import json, sys; sys.exit(0 if any((json.load(sys.stdin).get("AllowFunnel") or {}).values()) else 1)' 2>/dev/null
}

publish() {
  say "公開（Tailscale Funnel）"
  if ! tailscale status >/dev/null 2>&1; then
    echo "Tailscale にまだ参加していません。sudo tailscale up --ssh を実行してから --funnel でもう一度どうぞ。" >&2
    return 1
  fi
  tailscale funnel reset >/dev/null 2>&1 || true  # its settings name the machine: start over after a rename
  timeout 300 tailscale funnel --bg "$PORT" || true
  if funnel_on; then
    echo "公開アドレス: https://$(public_name)/"
  else
    echo "Funnel を有効にできませんでした（今は Tailscale の中からしか開けません）。表示された URL か、" \
      "Tailscale 管理画面の Access controls で Funnel を許可してから、" \
      "sudo bash \"$ROOT/Home Page/deploy/setup.sh\" --funnel でもう一度どうぞ。" >&2
    return 1
  fi
}

import_data() {
  local file="$1"
  [ -f "$file" ] || { echo "$file がありません" >&2; exit 1; }
  say "News Site のデータを取り込みます"
  local staged="$STATE/import.tar.gz"
  install -o "$ACCOUNT" -g "$ACCOUNT" -m 600 "$file" "$staged"
  rm -f "$file"
  systemctl stop news-collector.timer homepage.service
  systemctl stop news-collector.service 2>/dev/null || true
  as_site "$VENV/bin/python" "$ROOT/Home Page/deploy/import_news_data.py" "$staged" "$ROOT/News Site/work/app" "$ROOT/backup"
  rm -f "$staged"
  systemctl start homepage.service news-collector.timer
}

wait_until_answering() {
  local _
  for _ in $(seq 60); do
    if curl -fs -o /dev/null "http://127.0.0.1:$PORT/news/"; then
      echo "サーバーが答えています: http://127.0.0.1:$PORT/"
      return 0
    fi
    sleep 2
  done
  echo "サーバーが答えません。journalctl -u homepage -n 50 を見てください。" >&2
  return 1
}

main() {
  [ "$(id -u)" = 0 ] || { echo "sudo bash $0 で実行してください" >&2; exit 1; }
  case "${1:-}" in
    --units) install_units; return ;;
    --funnel) publish; return ;;
    --sync) sync_changes; return ;;
    --import) import_data "${2:?取り込むファイルを指定してください}"; wait_until_answering; return ;;
    "") ;;
    *) echo "使い方: sudo bash setup.sh [--import FILE | --units | --funnel | --sync]" >&2; exit 2 ;;
  esac
  install_packages
  add_swap
  make_account
  make_keys
  clone_repos
  say "Python の環境"
  install_python_packages
  write_version
  install_units
  wait_until_answering
  publish
  say "完了"
  echo "push は1分以内にここへ反映されます（sites-update.timer）。記録: journalctl -u homepage -u sites-update -u news-collector"
}

main "$@"
