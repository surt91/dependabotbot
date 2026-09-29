# Eigene Regeln für dependabotbot

Diese Datei nach `rules.md` kopieren (`run.sh` erledigt das beim ersten Start) und anpassen.
`rules.md` ist nicht im Repo.

Die Regeln hier **ergänzen oder lockern** die Vorgaben aus `CLAUDE.md` und den Skills, z. B. Aufwandsstufen,
Zeitlimits oder zusätzliche Prüfungen. Die **harten Regeln** lassen sich nicht aufheben: nie mergen,
nie auf den Default-Branch pushen, keine riskanten Workflow-Änderungen (Secrets, Berechtigungen,
Trigger, neue Dateien), keine Einstellungen ändern.
Diese Grenzen setzt ohnehin der Guard durch.

Bei Widersprüchen gilt der spezifischere Abschnitt: **Repo > Ecosystem > Alle Repos**.

## Alle Repos

- (Beispiel) PR-Titel und Beschreibungen auf Englisch schreiben.

## Ecosystem: Rust

- (Beispiel) Nach dem Fix zusätzlich mit nightly prüfen:
  `rustup toolchain install nightly --profile minimal` (falls nötig), dann
  `cargo +nightly build --all-features` und `cargo +nightly test`.
  Schlägt nur nightly fehl, stable aber nicht, ist das ein Hinweis im PR und kein Grund zum Abbruch.

## Repo: surt91/beispiel

- (Beispiel) **Großflächige Updates erwünscht:** Neben den Security-Fixes alle Abhängigkeiten auf die
  neueste Version heben, auch Major-Versionen (`cargo update` plus Anheben der Versionen in `Cargo.toml`).
  Nötige Code-Anpassungen gelten bis zu mittlerem Umfang als „moderat“ statt „aufwendig“.
  Security-Fixes und allgemeine Updates in getrennten Commits.
- (Beispiel) Zeitlimit pro Repo: 45 Minuten statt 20.
