---
name: fix-dependabot-alert
description: Behebt die offenen Dependabot-Alerts eines einzelnen Repos von surt91 auf einem dependabotbot/-Branch und erstellt den PR. Wird von dependabot-sweep aufgerufen oder direkt, wenn ein bestimmtes Repo gefixt werden soll.
---

# Dependabot-Alerts eines Repos fixen

Eingabe: Repo-Name und die offenen Alerts aus `workspace/status.json`
(Paket, Ecosystem, Manifest, `patched_version`, GHSA).

## 1. Arbeitskopie vorbereiten

```
gh repo clone surt91/<repo> workspace/<repo>     # nur falls noch nicht vorhanden
git -C workspace/<repo> fetch origin
git -C workspace/<repo> checkout -B dependabotbot/security-<YYYY-MM-DD> origin/<default_branch>
```

## 2. Triage: vor der ersten Änderung

Startzeit merken: `date +%s`. Dann jeden Alert **einer Stufe zuordnen, ohne schon etwas zu ändern**.
Für die Einordnung dürfen Manifest, Lockfile und Changelogs gelesen werden. Lässt sich z. B. per
`npm view <pkg>@<version> dependencies` oder `cargo tree -i <pkg>` klären, ob die Version kompatibel ist,
das vorher tun.

| Stufe | Kriterium | Vorgehen |
|---|---|---|
| **trivial** | Gepatchte Version innerhalb derselben Major-Version, Update betrifft nur Manifest oder Lockfile | umsetzen |
| **moderat** | Transitive Abhängigkeit per Override/Constraint, oder kleine Code-Anpassungen (wenige Stellen, klarer Migrationspfad) | umsetzen, Draft-PR bei Major-Sprung |
| **aufwendig** | Major-Upgrade mit breiten Breaking Changes, Umbau vieler Stellen, Toolchain-/Sprachversion-Upgrade nötig, Konflikt zwischen mehreren Abhängigkeiten | **nicht umsetzen** → Abbruch mit Empfehlung |
| **unmöglich** | Keine `patched_version`, Paket aufgegeben, Fix nur in unveröffentlichtem Upstream-Code | **nicht umsetzen** → „Nicht behebbar“ |

Im Zweifel die höhere Stufe wählen. **`rules.md` kann die Einstufung verschieben**, z. B. Major-Upgrades
für ein Repo als „moderat“ erlauben, und zusätzliche Arbeit verlangen, etwa großflächige Updates.
Die zutreffenden Abschnitte (Repo > Ecosystem > Alle Repos) vor der Triage lesen. Hilfreicher Kontext für die Empfehlung: `scope: development`
bedeutet, dass die Abhängigkeit nur beim Bauen/Testen verwendet wird. Das spricht eher für „abwarten“
oder „dismissen“ als für einen großen Umbau.

## 3. Fix pro Ecosystem

Immer auf die **kleinste Version ≥ `patched_version`** innerhalb derselben Major-Version gehen.
Die Lockfile muss konsistent bleiben. Nur das Tool des Projekts verwenden, z. B. yarn und nicht npm,
wenn dort eine `yarn.lock` liegt.

| Ecosystem | direkte Abhängigkeit | transitive Abhängigkeit |
|---|---|---|
| npm | Version in `package.json` anheben, `npm install` / `yarn` / `pnpm install` | `npm update <pkg>`; reicht das nicht: `overrides` (npm), `resolutions` (yarn), `pnpm.overrides` |
| pip / uv / poetry | Version in `pyproject.toml` / `requirements*.txt` anheben | `uv lock --upgrade-package <pkg>` / `poetry update <pkg>`; bei requirements ggf. Pin ergänzen |
| cargo | Version in `Cargo.toml` anheben | `cargo update -p <pkg> --precise <version>` |
| maven | Version bzw. Property in `pom.xml` anheben | Eintrag in `<dependencyManagement>` |
| gradle | Version im Build-Script / Version Catalog | `constraints { implementation("<g>:<a>:<v>") }` |
| go | `go get <mod>@v<version>` + `go mod tidy` | ebenso |
| rubygems | `bundle update <gem> --conservative` | ebenso |
| composer | `composer update <pkg> --with-dependencies` | ebenso |

Danach prüfen, ob der Fix greift: Die aufgelöste Version in der Lockfile ist ≥ `patched_version`,
und keine andere Stelle zieht noch die verwundbare Version.

Dateien unter `.github/workflows/` werden **nie** geändert. Das blockieren der Guard und der PAT.
Muss ein Fix dort ansetzen, z. B. bei einer Versions-Pin in einem Workflow, den Alert als manuellen Schritt berichten.

Ist das Ecosystem-Tool lokal nicht verfügbar, den Alert abbrechen mit dem Grund „Toolchain fehlt“.

Liegt ein Major-Upgrade vor, das mit überschaubaren Anpassungen machbar ist: umsetzen, PR als `--draft`
anlegen und die Breaking Changes in der Beschreibung nennen.

**Versuche zählen:** Ein Versuch besteht aus Änderung, Auflösung bzw. Lockfile-Update und Build.
Nach dem **2. gescheiterten Versuch** die Änderungen für diesen Alert verwerfen
(`git -C workspace/<repo> checkout -- <dateien>` bzw. auf den letzten guten Commit zurücksetzen)
und den Alert abbrechen. Auch abbrechen, wenn die Startzeit **mehr als 20 Minuten** zurückliegt.
Bereits erfolgreiche Commits anderer Alerts bleiben im PR.

## 4. Verifizieren

Wenn die Toolchain vorhanden und der Build schnell ist (wenige Minuten), bauen und die Tests laufen lassen,
z. B. `cargo test`, `npm test`, `uv run pytest` oder `./mvnw -q verify`.
Scheitern Tests schon auf dem Default-Branch, ist das kein Blocker. Das kommt in die PR-Beschreibung.
Ist lokales Testen nicht möglich, steht in der Beschreibung, dass die CI entscheidet.
Zusätzliche Prüfungen aus `rules.md`, z. B. ein Build mit nightly, gehören dazu. Ihr Ergebnis kommt in die PR-Beschreibung.

Nach dem Push übernimmt `watch-ci` in Schritt 4 von `dependabot-sweep`.

## 5. Commit, Push, PR

Gibt es nach Triage und Versuchen keinen einzigen erfolgreichen Fix, **keinen Branch pushen und keinen PR anlegen**.
Es gibt dann nur die Einträge im Bericht.

Ein Commit pro Paket: `fix(deps): bump <paket> to <version> (<GHSA-ID>)`.

```
git -C workspace/<repo> push -u origin dependabotbot/security-<YYYY-MM-DD>
```

PR-Beschreibung mit dem Write-Tool nach `workspace/<repo>.pr-body.md` schreiben:

```markdown
Behebt folgende Dependabot-Alerts:

| Alert | Paket | Schwere | alt → neu |
|---|---|---|---|
| [#<n>](<alert-url>) <GHSA-ID> | <paket> | <severity> | <alt> → <neu> |

**Vorgehen:** <direkt angehoben / override / lockfile-update>
**Verifikation:** <lokal getestet mit … / CI entscheidet>
**Hinweise:** <Breaking Changes, nicht behebbare Alerts dieses Repos>

---
Erstellt von dependabotbot 🤖
```

```
gh pr create -R surt91/<repo> --base <default_branch> --head dependabotbot/security-<YYYY-MM-DD> \
  --title "fix(deps): Dependabot-Alerts beheben (<YYYY-MM-DD>)" \
  --body-file workspace/<repo>.pr-body.md <Reviewer-/Assignee-Flags aus dependabot-sweep>
```

PR-URL für den Bericht merken. Abgebrochene und nicht behebbare Alerts in `reports/state.json` eintragen
(siehe `dependabot-sweep`).
