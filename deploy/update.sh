#!/usr/bin/env bash
# Brings the three repositories up to their master on GitHub and puts what changed into effect. Run
# every minute by sites-update.timer (as root; git runs as the sites account). The server copies are
# never edited by hand: a push to master (even a force push) is what they become. master, not the
# repository's default branch: a clone follows the default branch, which need not be master (Infra
# Game's was an old work branch, so the site stayed on it).
#
# The VM has an eighth of a CPU, so each minute does as little as it can: one git fetch per
# repository and nothing more while nothing changed.
#
# - Home Page: the server notices new homepage/*.py or sites.toml settings itself and restarts
#   (homepage/server.py); changed systemd units under deploy/ are installed (setup.sh --sync).
# - News Site: VERSION is rewritten, which restarts the server into the new code; a changed
#   requirements.txt installs the packages first (setup.sh --sync). The collector runs the new code
#   at its next hour.
# - Infra Game: static files, served as they are at once.
set -euo pipefail

ROOT=/srv/sites
ACCOUNT=sites
HOME_PAGE="$ROOT/Home Page"

as_site() { runuser -u "$ACCOUNT" -- env HOME="$ROOT" "$@" </dev/null; }

repos() {
  printf '%s\t%s\n' home-page "Home Page" news-site "News Site/work/app" infra-game "Infra Game"
}

while IFS=$'\t' read -r name dir; do
  repo="$ROOT/$dir"
  [ -d "$repo/.git" ] || continue
  if ! as_site git -C "$repo" fetch -q origin master 2>"$ROOT/state/fetch.err"; then
    echo "$name: GitHub から取得できませんでした: $(head -c 300 "$ROOT/state/fetch.err")"
    continue
  fi
  { read -r old; read -r new; } < <(as_site git -C "$repo" rev-parse HEAD origin/master)
  [ "$old" = "$new" ] && continue
  as_site git -C "$repo" reset -q --hard "$new"
  echo "$name: ${old:0:7} -> ${new:0:7} $(as_site git -C "$repo" log -1 --format=%s | head -c 120)"
done < <(repos)

bash "$HOME_PAGE/deploy/setup.sh" --sync
