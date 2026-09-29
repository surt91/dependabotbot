---
name: dependabot-sweep
description: Kompletter Lauf von dependabotbot. Prüft alle Repos von surt91 auf Dependabot-Alerts, legt Fix-PRs an und schreibt einen Bericht. Für den wöchentlichen Lauf oder wenn der Nutzer "alles prüfen" möchte.
---

# Dependabot-Sweep

## 1. Umgebung prüfen

Meldet der SessionStart-Hook Probleme, sofort abbrechen und nur einen kurzen Bericht mit dem Problem schreiben.
Danach `gh api user --jq .login` ausführen und den Login merken. Er wird in Schritt 3 gebraucht.

## 2. Bestandsaufnahme

```
python3 scripts/list-alerts.py > workspace/status.json
```

Für jedes Repo in `workspace/status.json`:

- `alerts_error` gesetzt (z. B. Dependabot-Alerts deaktiviert oder fehlendes Recht): als manuellen Schritt notieren.
- Alerts in Gruppen einteilen:
  - **Abgedeckt:** Es gibt einen offenen Dependabot-PR, dessen Titel oder Branch das Paket nennt
    (Branch `dependabot/<ecosystem>/<paket>-<version>`) und dessen Zielversion ≥ `patched_version` ist.
    Diese Alerts nicht selbst fixen.
  - **Schon in Arbeit:** Ein offener `dependabotbot/`-PR nennt die GHSA-ID in Titel oder Beschreibung
    (`gh pr view <n> -R surt91/<repo> --json body`). Nichts tun, im Bericht erwähnen.
  - **Zurückgestellt:** Der Alert steht in `reports/state.json` (Schlüssel `<repo>#<GHSA>`), und nichts
    davon trifft zu:
    - `patched_version` hat sich geändert (bei `unmöglich`: es gibt jetzt eine).
    - `retry_after` ist erreicht.

    Nicht anfassen, im Bericht nur als Einzeiler unter „Zurückgestellt“ aufführen.
  - **Workflow-Datei:** Ecosystem `github-actions`, also betroffene `uses:`-Einträge in `.github/workflows/`.
    Der PAT darf keine Workflow-Dateien ändern, der Guard blockiert das. Nie selbst fixen. Gibt es einen
    Dependabot-PR, kommt er unter „Mergebar“. Sonst ein manueller Schritt mit Datei, Action und gepatchter Version.
  - **Offen:** alle übrigen Alerts. Sie werden in Schritt 3 gefixt.

Einträge in `reports/state.json` entfernen, deren Alert nicht mehr offen ist.

Bei offenen Dependabot-PRs mit `mergeable == "CONFLICTING"`: `@dependabot rebase` kommentieren
(`gh pr comment <n> -R surt91/<repo> --body "@dependabot rebase"`), höchstens einmal pro PR.
Vorher mit `gh pr view --comments` prüfen, ob der Kommentar schon da ist.

## 3. Offene Alerts fixen

Für jedes Repo mit offenen Alerts den Skill **`fix-dependabot-alert`** befolgen. Alle offenen Alerts eines Repos
kommen in einen gemeinsamen PR. Repos mit `critical`/`high` zuerst bearbeiten, damit sie ein hartes Zeitlimit
möglichst nicht trifft.

**Nach jedem Repo** den Bericht (Schritt 4) und `reports/state.json` aktualisieren.

Format von `reports/state.json` für abgebrochene bzw. nicht behebbare Alerts:

```json
{
  "surt91/<repo>#GHSA-xxxx-xxxx-xxxx": {
    "status": "unmöglich | aufwendig | abgebrochen",
    "reason": "kurze Begründung",
    "patched_version": "<Wert zum Zeitpunkt der Entscheidung oder null>",
    "decided": "YYYY-MM-DD",
    "retry_after": "YYYY-MM-DD"
  }
}
```

`retry_after`: bei `unmöglich` in 4 Wochen (vorher greift nur eine neue `patched_version`),
bei `aufwendig` in 12 Wochen, bei `abgebrochen` (Versuchs- oder Zeitlimit) in 1 Woche.
Nach dem zweiten `abgebrochen` in Folge wird daraus `aufwendig`.

**Reviewer:** Ist der Login aus Schritt 1 `surt91`, kann GitHub den Autor nicht als Reviewer anfragen.
Dann `--assignee surt91` statt `--reviewer surt91` verwenden. Ansonsten `--reviewer surt91 --assignee surt91`.

## 4. Bericht

`reports/<YYYY-MM-DD>.md` mit genau diesen Abschnitten, jeweils mit klickbaren Links:

```markdown
# dependabotbot – <Datum>

## Mergebar: Dependabot-PRs
- surt91/<repo>: <Titel> – <URL> (<mergeable>, Alter)

## Neue PRs von dependabotbot
- surt91/<repo>: <Titel> – <URL> (behebt GHSA-..., GHSA-...)

## Bereits offene PRs von dependabotbot
- ...

## Manuelle Schritte
- surt91/<repo>: <was und warum, ggf. Link zur Einstellungsseite>

## Abgebrochen / nicht behebbar
- surt91/<repo>: <Paket> [<GHSA>](<Alert-URL>) – Stufe: <…> – **Grund:** <…> – Versucht: <…> – **Empfehlung:** <…>

## Zurückgestellt
- surt91/<repo>: <Paket> <GHSA> – <status> seit <decided>, Wiedervorlage <retry_after>
```

Leere Abschnitte mit „– keine –“ füllen. Die Datei nach jedem Repo mit dem Write-Tool komplett neu schreiben.
Solange der Lauf noch nicht fertig ist, steht oben `> Lauf läuft noch …`. Diese Zeile am Ende entfernen.

## 5. Kurzfassung

Zum Schluss `reports/<YYYY-MM-DD>.summary.txt` schreiben. Das ist reiner Text für eine Benachrichtigung:

- Zeile 1: `dependabotbot: <n> PRs zum Mergen, <m> neue Fix-PRs, <k> manuelle Schritte, <j> abgebrochen`
- Danach höchstens 10 Zeilen mit den wichtigsten Links, `critical`/`high` zuerst.
- Gibt es nichts zu tun: nur `dependabotbot: nichts zu tun`.

Dieselbe Kurzfassung auch als letzte Ausgabe des Laufs ausgeben.
