#!/usr/bin/env bash
# Startet dependabotbot in einer isolierten Umgebung: gh aus bin/, eigene gh- und git-Konfiguration,
# kein SSH-Agent. Authentifiziert wird ausschließlich mit dem PAT aus .env.
#
#   ./run.sh              interaktive Session
#   ./run.sh --headless   unbeaufsichtigter Lauf (/dependabot-sweep), z. B. per cron
#   ./run.sh --notify-test  Testnachricht an den Home-Assistant-Webhook schicken
set -euo pipefail

project="$(dirname "$(readlink -f "$0")")"
cd "$project"

[[ -x bin/gh ]] || { echo "bin/gh fehlt – bitte scripts/install-gh.sh ausführen." >&2; exit 1; }
[[ -f .env ]] || { echo ".env fehlt – siehe .env.example." >&2; exit 1; }

# Fremde GitHub-Zugangsdaten aus der aufrufenden Shell entfernen, bevor .env geladen wird
unset GITHUB_TOKEN GH_ENTERPRISE_TOKEN GITHUB_ENTERPRISE_TOKEN GH_HOST SSH_AUTH_SOCK SSH_AGENT_PID
set -a
# shellcheck source=/dev/null
source .env
set +a
[[ -n "${GH_TOKEN:-}" ]] || { echo "GH_TOKEN ist in .env nicht gesetzt." >&2; exit 1; }
export GH_TOKEN

# Die Webhook-URL braucht nur run.sh selbst, nicht Claude
ha_webhook="${HA_WEBHOOK_URL:-}"
unset HA_WEBHOOK_URL

# Schickt eine Nachricht an den Home-Assistant-Webhook (falls konfiguriert). Fehler brechen den Lauf nicht ab.
notify() {
  local title="$1" message="$2"
  [[ -n "$ha_webhook" ]] || return 0
  python3 -c 'import json, sys; print(json.dumps({"title": sys.argv[1], "message": sys.argv[2], "url": sys.argv[3]}))' \
    "$title" "$message" "https://github.com/pulls/assigned" \
    | curl -fsS --max-time 15 -X POST -H "Content-Type: application/json" --data @- "$ha_webhook" >/dev/null \
    || echo "Benachrichtigung an Home Assistant fehlgeschlagen." >&2
}

if [[ "${1:-}" == "--notify-test" ]]; then
  [[ -n "$ha_webhook" ]] || { echo "HA_WEBHOOK_URL ist in .env nicht gesetzt." >&2; exit 1; }
  notify "dependabotbot" "Testnachricht – der Webhook funktioniert." && echo "Gesendet."
  exit 0
fi

# gh: nur das lokale Binary, leere eigene Konfiguration -> kein Zugriff auf deinen gh-Login/Keyring
export PATH="$project/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export GH_CONFIG_DIR="$project/.gh-config"
export GH_PROMPT_DISABLED=1 GH_NO_UPDATE_NOTIFIER=1
mkdir -p "$GH_CONFIG_DIR"

# git: eigene globale Konfiguration (Identität, Credential-Helper über gh/PAT, HTTPS statt SSH),
# systemweite Konfiguration und SSH komplett abgeschaltet
export GIT_CONFIG_GLOBAL="$project/gitconfig"
export GIT_CONFIG_NOSYSTEM=1
export GIT_SSH_COMMAND=false
export GIT_TERMINAL_PROMPT=0
[[ -n "${GIT_AUTHOR_NAME:-}" && -n "${GIT_AUTHOR_EMAIL:-}" ]] \
  || { echo "GIT_AUTHOR_NAME und GIT_AUTHOR_EMAIL müssen in .env gesetzt sein." >&2; exit 1; }
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

# Marker für den Guard-Hook: ohne run.sh verweigert er alle Befehle
export DEPENDABOTBOT_RUN=1

mkdir -p workspace reports

if [[ "${1:-}" == "--headless" ]]; then
  today="$(date +%F)"
  log="reports/$today-run.log"
  limits=()
  [[ -n "${MAX_BUDGET_USD:-}" ]] && limits+=(--max-budget-usd "$MAX_BUDGET_USD")

  status=0
  timeout --kill-after=2m "${RUN_TIMEOUT:-90m}" claude -p "/dependabot-sweep" "${limits[@]}" >>"$log" 2>&1 || status=$?

  if [[ $status -ne 0 ]]; then
    if [[ $status -eq 124 || $status -eq 137 ]]; then
      reason="Zeitlimit ${RUN_TIMEOUT:-90m} erreicht"
    else
      reason="Exit-Code $status, siehe $log"
    fi
    printf '\n> ⚠️ Lauf abgebrochen: %s. Der Bericht ist unvollständig.\n' "$reason" >>"reports/$today.md"
    [[ -s "reports/$today.summary.txt" ]] || echo "dependabotbot: Lauf abgebrochen ($reason)" >"reports/$today.summary.txt"
  fi

  summary="reports/$today.summary.txt"
  [[ -s "$summary" ]] || echo "dependabotbot: Lauf beendet, aber keine Kurzfassung geschrieben – siehe $log" >"$summary"
  if [[ "$(head -n1 "$summary")" != "dependabotbot: nichts zu tun" || "${NOTIFY_ALWAYS:-}" == 1 ]]; then
    notify "dependabotbot" "$(cat "$summary")"$'\n\n'"Bericht: $project/reports/$today.md"
  fi
  exit $status
fi
exec claude "$@"
