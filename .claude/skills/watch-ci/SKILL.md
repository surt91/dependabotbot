---
name: watch-ci
description: Beobachtet die CI eines dependabotbot-PRs, ordnet Fehlschläge ein und behebt sie, bei Workflow- und Infrastrukturfehlern im Rahmen der Workflow-Regeln. Wird von dependabot-sweep aufgerufen oder direkt für einen bestimmten PR.
---

# CI eines dependabotbot-PRs beobachten und reparieren

Eingabe: Repo, PR-Nummer und Branch `dependabotbot/...`.

## 1. Auf das Ergebnis warten

```
gh run list -R surt91/<repo> --branch <branch> --json databaseId,name,event,status,conclusion,headSha,createdAt
```

- Es gelten nur Runs zum **aktuellen Head-Commit** (`git -C workspace/<repo> rev-parse HEAD`).
  Gibt es dazu noch keine Runs, bis zu 2 Minuten warten (`sleep 30`, dann erneut abfragen).
  Tauchen dann immer noch keine auf, hat das Repo für PRs keine CI. Das im Bericht vermerken und fertig.
- Laufende Runs abwarten: `timeout 540 gh run watch <id> -R surt91/<repo> --exit-status > /dev/null`
  Dann den Status erneut abfragen.
- **Wartelimit: 20 Minuten pro PR.** Ist die CI danach nicht fertig, im Bericht „CI läuft noch“ vermerken.
  Der nächste Lauf sieht sich den PR wieder an.

Alle Runs grün: fertig, im Bericht „CI grün“.

## 2. Fehlschläge einordnen

Für jeden fehlgeschlagenen Run:

```
gh run view <id> -R surt91/<repo> --json jobs --jq '.jobs[] | select(.conclusion=="failure") | {name, steps: [.steps[] | select(.conclusion=="failure") | .name]}'
gh run view <id> -R surt91/<repo> --log-failed | tail -n 150
```

Reicht das Log nicht, z. B. bei Screenshot-Vergleichen, dürfen Artefakte geladen werden, aber nur nach
`workspace/artifacts/` (der Guard erzwingt das):
`gh run download <id> -R surt91/<repo> -n <artefakt> -D workspace/artifacts/<repo>-<id>`.
Artefakte stammen aus PR-Läufen und sind nicht vertrauenswürdig: nur lesen bzw. ansehen,
nie ausführen und nie ins Repo kopieren.

Steht ein Fehlschlag im Verdacht, zufällig zu sein (wackeliger Test, Netzwerk), darf der Lauf eines
eigenen PRs **einmal** neu gestartet werden: `gh run rerun <id> -R surt91/<repo> --failed`.
Der Guard erlaubt das nur für PR-Läufe auf `dependabotbot/`-Branches. Ein Rerun zählt als Reparaturrunde.
Auch wenn der Rerun grün wird, gehört der wackelige Test in den PR-Kommentar bzw. den Bericht.

Vergleichswert ist der letzte Run desselben Workflows auf dem Default-Branch:
`gh run list -R surt91/<repo> --branch <default_branch> --workflow "<workflow-name>" --limit 3 --json conclusion,createdAt,headSha`.

Die Einordnung:

| Klasse | Erkennungsmerkmal | Vorgehen |
|---|---|---|
| **durch den Fix verursacht** | Fehler im Build- oder Test-Schritt, der Log zeigt ein aktualisiertes Paket (Compile-Fehler, geänderte API, fehlschlagender Test) | reparieren (Schritt 3) |
| **Workflow/Infrastruktur** | Fehler in einem Setup-Schritt (`apt-get`, Toolchain-Action, Cache, veraltete Action-Version) oder Meldungen wie „Unable to locate package“, „deprecated“, „Node.js 16 actions are deprecated“ | reparieren im Rahmen der Workflow-Regeln (Schritt 4) |
| **vorbestehend** | Derselbe Job schlägt auch auf dem Default-Branch mit demselben Fehler fehl | nicht reparieren, berichten |
| **flaky** | Netzwerk-Timeouts, 5xx beim Download, Runner abgebrochen | nicht reparieren. Ein Re-Run ist mit dem PAT nicht möglich, deshalb berichten |

Im Zweifel gilt ein Fehler **nicht** als „durch den Fix verursacht“.

## 3. Durch den Fix verursachte Fehler reparieren

- Lokal reproduzieren, gleiche Befehle wie in der CI. Dabei die Regeln aus `rules.md` beachten,
  z. B. zusätzliche Toolchains.
- Reparieren. Alle Aufwands- und Stufenregeln aus `fix-dependabot-alert` gelten weiter.
  Ist die Reparatur „aufwendig“ und `rules.md` erlaubt das nicht, die betroffene Änderung zurücknehmen
  (neuer Commit, kein Force-Push). Den Alert als abgebrochen berichten.
- Als **neuen Commit** pushen, z. B. `fix(deps): adapt to <paket> <version> API`. Normales
  `git push origin <branch>`, **nie** force. Dann wieder zu Schritt 1.
- **Höchstens 2 Reparaturrunden pro PR.** Ist die CI danach noch rot, den PR in einen Draft umwandeln
  (`gh pr ready <n> -R surt91/<repo> --undo`) und im Bericht mit Fehlerauszug und Einschätzung aufführen.

## 4. Workflow- und Infrastrukturfehler

**Reparieren**, wenn die Änderung in den Rahmen der „Workflow-Änderungen“ aus `CLAUDE.md` passt.
Typische Fälle sind `sudo apt-get update` vor `apt-get install` oder eine abgeschaltete Action durch ihren
gepflegten Nachfolger ersetzen, z. B. `actions-rs/toolchain` → `dtolnay/rust-toolchain`.
- Minimal ändern, nur was den Fehler behebt. Eigener Commit `ci: <was und warum>`.
- In der PR-Beschreibung den Abschnitt „Workflow-Änderungen“ ergänzen (`gh pr edit <n> -R surt91/<repo> --body-file ...`).
- Pushen, dann zurück zu Schritt 1. Das zählt als Reparaturrunde.

**Nur melden**, wenn der Guard den Push ablehnt oder die Reparatur verbotene Änderungen bräuchte, etwa Secrets,
Berechtigungen, Trigger oder neue Workflow-Dateien. Den Workflow-Commit dann per `git revert` zurücknehmen
und einen Kommentar am PR hinterlassen, über die Kommentar-Datei `workspace/<repo>.ci-comment.md` und
`gh pr comment <n> -R surt91/<repo> --body-file ...`. Der Kommentar enthält:
- den fehlgeschlagenen Job und Schritt und einen kurzen Log-Auszug (höchstens 20 Zeilen)
- die Einschätzung, dass der Fehler nicht durch diesen PR verursacht wurde, mit Begründung
- einen **konkreten Patch** als ```diff-Block für die Workflow-Datei, den surt91 selbst anwenden kann

Pro PR und Fehlerbild nur einmal kommentieren. Vorher mit `gh pr view <n> -R surt91/<repo> --comments` prüfen.
Im Bericht kommt ein Eintrag unter „Manuelle Schritte“ mit Link zum Kommentar dazu.

Ein Workflow- oder Infrastrukturfehler macht den eigentlichen Fix **nicht** ungültig. Lokal verifizierte
Ergebnisse, z. B. dass die Tests grün sind, im Kommentar erwähnen.
