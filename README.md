# dependabotbot

Ein Claude-Code-Agent, der die Dependabot-Alerts aller eigenen Repos von surt91 abarbeitet:
Er listet mergebare Dependabot-PRs auf, baut für die restlichen Alerts Fix-PRs, schreibt einen Bericht
nach `reports/` und benachrichtigt dich über Home Assistant. Gemergt wird nie vom Agenten.

## Setup

1. `scripts/install-gh.sh` installiert gh nach `bin/`, nur für diesen Agenten.
2. Einen Fine-grained PAT anlegen (siehe unten), dann `cp .env.example .env`, Token und Commit-Identität
   (`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`) eintragen und `chmod 600 .env` ausführen.
3. `./run.sh` für eine interaktive Session oder `./run.sh --headless` für einen unbeaufsichtigten Lauf.

### Fine-grained PAT

Unter https://github.com/settings/personal-access-tokens/new:

- **Resource owner:** surt91
- **Expiration:** z. B. 90 Tage
- **Repository access:** All repositories (bzw. nur die gewünschten)
- **Repository permissions:**

| Permission | Zugriff | Wofür |
|---|---|---|
| Metadata | Read | Pflicht (automatisch) |
| Dependabot alerts | Read | Alerts lesen |
| Contents | Read and write | Klonen (auch privat), `dependabotbot/*`-Branches pushen |
| Pull requests | Read and write | PRs erstellen, Assignee/Reviewer setzen, `@dependabot rebase` kommentieren |
| Actions | Read | CI-Runs und Logs der eigenen PRs lesen (`watch-ci`) |
| Commit statuses | Read | *optional:* Status-Checks externer CI-Dienste sehen |

Alles andere bleibt auf „No access“, insbesondere **Workflows**, Administration, Secrets und Account-Permissions.
Ohne Workflows-Recht kann der Agent nichts unter `.github/workflows/` ändern. Alerts für GitHub Actions
landen deshalb immer im Bericht, und der Guard blockiert solche Änderungen schon vorher.

## Eigene Regeln

In `rules.md` stehen deine eigenen Vorgaben, global, pro Ecosystem oder pro Repo. Beispiele: zusätzlich mit
nightly bauen, großflächige Updates erlauben, längeres Zeitlimit. Beim ersten Start legt `run.sh` die Datei
aus `rules.example.md` an. `rules.md` ist nicht im Repo. Die Regeln können Vorgaben lockern, aber nicht die
harten Regeln aufheben (mergen, Default-Branch, Workflow-Dateien, Einstellungen).

## CI

Nach dem Anlegen der PRs beobachtet der Agent deren CI (Skill `watch-ci`):
- Fehler, die sein Fix verursacht hat, repariert er mit neuen Commits, höchstens 2 Runden pro PR.
- Fehler in Workflow oder Infrastruktur, z. B. ein fehlendes `apt-get update`, repariert er nicht. Dafür
  fehlt ihm das Workflows-Recht. Er kommentiert stattdessen am PR mit einem Patch-Vorschlag.
- Ist die CI nach 20 Minuten nicht fertig, sieht er beim nächsten Lauf wieder nach.

## Isolation

`run.sh` startet Claude mit folgenden Einstellungen:
- `gh` aus `bin/` mit eigener, leerer Konfiguration (`GH_CONFIG_DIR=.gh-config`). Ein systemweit
  installiertes gh und dein eigener gh-Login bzw. Keyring werden nicht verwendet.
- Eigene git-Konfiguration (`GIT_CONFIG_GLOBAL=./gitconfig`, `GIT_CONFIG_NOSYSTEM=1`). git authentifiziert sich
  über HTTPS mit dem PAT, SSH ist abgeschaltet und der SSH-Agent wird aus der Umgebung entfernt.
- Der Guard-Hook `.claude/hooks/guard.py` verweigert alle Bash-Befehle, wenn die Session nicht über `run.sh`
  läuft. Außerdem blockiert er Merges, Force-Pushes, Pushes außerhalb von `dependabotbot/*`,
  Änderungen an `.github/workflows/`, schreibende API-Aufrufe, Zugriffe auf `.env` bzw. Tokens sowie Dateizugriffe außerhalb des Projekts.

Der Hook ist eine Leitplanke und keine Sandbox. Die harte Grenze ziehen die Rechte des PAT.

Tests für den Guard (nach jeder Änderung am Hook ausführen):

```
python3 -m unittest discover tests
```

## Wöchentlich per cron

```
crontab -e
# Montags 7:00
0 7 * * 1  /pfad/zu/dependabotbot/run.sh --headless
```

Die Ausgabe landet in `reports/<Datum>-run.log`, der Bericht in `reports/<Datum>.md`.
Harte Limits lassen sich in `.env` einstellen: `RUN_TIMEOUT` (Standard 120m) und optional `MAX_BUDGET_USD`.

## Benachrichtigung über Home Assistant

Nach einem headless-Lauf schickt `run.sh` die Kurzfassung (`reports/<Datum>.summary.txt`) per POST an
`HA_WEBHOOK_URL`, allerdings nur, wenn es etwas zu tun gibt oder der Lauf abgebrochen wurde
(`NOTIFY_ALWAYS=1` für jede Woche). Die URL wird nicht an Claude weitergegeben.
Payload: `{"title": ..., "message": ..., "url": "https://github.com/pulls/assigned"}`.

Automation in Home Assistant (Einstellungen → Automationen → neu → ⋮ → „In YAML bearbeiten“):

```yaml
alias: dependabotbot Benachrichtigung
mode: queued
triggers:
  - trigger: webhook
    webhook_id: <ID aus HA_WEBHOOK_URL>
    allowed_methods: [POST]
    local_only: true
actions:
  - action: notify.mobile_app_<dein_gerät>
    data:
      title: "{{ trigger.json.title }}"
      message: "{{ trigger.json.message }}"
      data:
        url: "{{ trigger.json.url }}"
        clickAction: "{{ trigger.json.url }}"
```

Test: `./run.sh --notify-test`.

## Hinweis zu Reviewern

Mit einem PAT von surt91 ist surt91 auch Autor der PRs. GitHub erlaubt nicht, den Autor als Reviewer
anzufragen. Der Agent setzt surt91 deshalb als **Assignee**, die PRs erscheinen unter
https://github.com/pulls/assigned. Ein echter Review-Request ginge nur mit einem separaten Bot-Account.
