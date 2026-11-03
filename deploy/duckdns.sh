#!/usr/bin/env bash
# Points the DuckDNS name at this VM's public address (setup.sh --direct, then sites-duckdns.timer every
# day, so the name follows the address if it ever changes). Nothing to do without /etc/sites/duckdns.
set -euo pipefail

CONFIG=/etc/sites/duckdns
[ -f "$CONFIG" ] || exit 0
domain="" token=""
while IFS='=' read -r key value; do  # read, never sourced: the file holds data only
  case "$key" in
    DOMAIN) domain="$value" ;;
    TOKEN) token="$value" ;;
  esac
done < "$CONFIG"
[ -n "$domain" ] && [ -n "$token" ] || { echo "$CONFIG に DOMAIN と TOKEN がありません" >&2; exit 1; }
# The token goes in curl's config on stdin, not on its command line (other accounts could read that).
answer="$(printf 'url = "https://www.duckdns.org/update?domains=%s&token=%s&ip="\n' "$domain" "$token" |
  curl -fsS -m 30 --retry 3 -K -)"
if [ "$answer" != "OK" ]; then
  echo "DuckDNS が $domain の更新を断りました（$answer）。token とサブドメイン名を確かめてください。" >&2
  exit 1
fi
