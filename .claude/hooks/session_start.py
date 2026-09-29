#!/usr/bin/env python3
"""SessionStart-Hook: prüft, ob die isolierte Umgebung aus run.sh aktiv ist, und meldet das Ergebnis als Kontext."""
import os
import shutil
import subprocess

problems = []
if os.environ.get("DEPENDABOTBOT_RUN") != "1":
    problems.append("Die Session wurde nicht über ./run.sh gestartet. Bash-Befehle werden vom Guard blockiert.")
gh = shutil.which("gh")
project = os.environ.get("CLAUDE_PROJECT_DIR", "")
if not gh or not gh.startswith(os.path.join(project, "bin")):
    problems.append(f"gh wird nicht aus bin/ verwendet (gefunden: {gh}).")
if not os.environ.get("GH_TOKEN"):
    problems.append("Kein PAT geladen.")
elif gh:
    login = subprocess.run([gh, "api", "user", "--jq", ".login"], capture_output=True, text=True)
    if login.returncode == 0:
        print(f"dependabotbot: Umgebung ok, gh authentifiziert als {login.stdout.strip()}.")
    else:
        problems.append(f"PAT funktioniert nicht: {login.stderr.strip()}")

if problems:
    print("dependabotbot: Umgebung NICHT in Ordnung – nichts tun außer den Nutzer zu informieren:")
    for p in problems:
        print(f"- {p}")
