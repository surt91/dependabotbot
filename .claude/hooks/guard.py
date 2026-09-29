#!/usr/bin/env python3
"""PreToolUse-Guard für dependabotbot.

Verhindert u. a.: Pushes außerhalb von dependabotbot/*-Branches, Force-Pushes, Änderungen an
.github/workflows/ (der PAT hat keine Workflows-Berechtigung), Mergen von PRs,
schreibende GitHub-API-Aufrufe (außer Reviewer/Assignees/Kommentare), Zugriff auf .env und Token,
Umgehen der isolierten gh/git-Konfiguration sowie Dateiänderungen außerhalb von workspace/ und reports/.

Das ist eine Leitplanke, keine Sandbox: Die eigentliche Grenze ziehen die Rechte des PAT.
Exit-Code 2 blockiert den Tool-Aufruf; stderr geht als Begründung an Claude.
"""
import json
import os
import re
import shlex
import subprocess
import sys

OWNER = "surt91"
BRANCH_PREFIX = "dependabotbot/"
WORKFLOW_DIR = ".github/workflows/"

ALLOWED_GH = {
    "pr": {"list", "view", "create", "edit", "checks", "diff", "status", "comment", "ready"},
    "repo": {"list", "view", "clone"},
    "issue": {"list", "view"},
    "run": {"list", "view", "watch"},
    "workflow": {"list", "view"},
    "release": {"list", "view"},
    "ruleset": {"list", "view", "check"},
    "label": {"list"},
    "search": None,  # alle Unterbefehle
    "status": None,
    "api": None,  # gesondert geprüft
    "auth": {"status"},
}
POST_ALLOWED = re.compile(
    rf"^/?repos/({OWNER}|\{{owner\}})/[^/]+/(pulls/\d+/requested_reviewers|issues/\d+/(comments|assignees))$"
)
FORBIDDEN_TEXT = [
    (re.compile(r"(?<![\w.-])\.env(?![\w.-])"), ".env enthält den PAT und ist tabu."),
    (re.compile(r"GH_TOKEN|GITHUB_TOKEN|GH_ENTERPRISE_TOKEN"), "Token-Variablen dürfen nicht angefasst oder ausgegeben werden."),
    (re.compile(r"GH_CONFIG_DIR|GIT_CONFIG|GIT_SSH|SSH_AUTH_SOCK|\.config/gh|\.ssh/|\.git-credentials|/\.gitconfig"),
     "Die isolierte gh/git-Konfiguration darf nicht umgangen werden."),
    (re.compile(r"\benviron\b"), "Umgebungsvariablen dürfen nicht ausgelesen werden."),
]
SEPARATORS = {"&&", "||", ";", "|", "&", ";;", "|&", "\n", "(", ")"}


def deny(reason):
    print(f"dependabotbot-guard: {reason}", file=sys.stderr)
    sys.exit(2)


def segments(command):
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        tokens = list(lex)
    except ValueError:
        deny("Befehl konnte nicht sicher geparst werden – bitte einfacher formulieren.")
    current = []
    for tok in tokens:
        if tok in SEPARATORS or set(tok) <= set(";&|\n"):
            if current:
                yield current
            current = []
        else:
            current.append(tok)
    if current:
        yield current


def strip_prefix(words):
    """Entfernt führende VAR=wert-Zuweisungen und Wrapper wie `env`, `command`, `time`, `timeout`."""
    while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in {"command", "time", "nohup", "nice"}):
        words = words[1:]
    if words and words[0] == "env" and len(words) > 1:
        return strip_prefix(words[1:])
    if words and words[0] == "timeout":
        rest = words[1:]
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in {"-k", "-s", "--kill-after", "--signal"} else rest[1:]
        return strip_prefix(rest[1:])  # rest[0] ist die Dauer
    return words


def positionals(args, value_flags):
    result, i = [], 0
    while i < len(args):
        a = args[i]
        if a in value_flags:
            i += 2
            continue
        if not a.startswith("-") or a == "-":
            result.append(a)
        i += 1
    return result


def check_git(args, cwd):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-c":
            deny("`git -c` ist nicht erlaubt.")
        if args[i] == "-C" and i + 1 < len(args):
            cwd = os.path.join(cwd, os.path.expanduser(args[i + 1]))
        i += 2 if args[i] in {"-C", "--git-dir", "--work-tree", "--namespace"} else 1
    if i >= len(args):
        return
    sub, rest = args[i], args[i + 1:]

    if sub == "push":
        for a in rest:
            if a.startswith("--force") or a in {"--delete", "--mirror", "--all", "--tags", "--prune"}:
                deny(f"`git push {a}` ist nicht erlaubt.")
            if re.match(r"^-[a-zA-Z]*[fd]", a):
                deny("Force-Push und Löschen von Branches sind nicht erlaubt.")
        pos = positionals(rest, {"-o", "--push-option", "--repo", "--receive-pack", "--exec"})
        if len(pos) < 2:
            deny(f"Push nur mit explizitem Branch: `git push -u origin {BRANCH_PREFIX}<name>`.")
        if pos[0] != "origin":
            deny("Gepusht wird nur nach `origin`.")
        for ref in pos[1:]:
            if ref.startswith("+"):
                deny("Force-Push (`+refspec`) ist nicht erlaubt.")
            src, _, dst = ref.rpartition(":") if ":" in ref else (ref, "", ref)
            if ":" in ref and not src:
                deny("Löschen von Remote-Branches ist nicht erlaubt.")
            dst = dst.removeprefix("refs/heads/")
            if not dst.startswith(BRANCH_PREFIX):
                deny(f"Push nur auf Branches mit Präfix `{BRANCH_PREFIX}` erlaubt, nicht auf `{dst}`.")
            check_no_workflow_changes(cwd, src)
    elif sub == "remote" and rest[:1] and rest[0] in {"add", "set-url", "rename", "remove", "rm"}:
        deny("Remotes dürfen nicht verändert werden.")
    elif sub == "config" and any(a in {"--global", "--system", "--file", "-f"} for a in rest):
        deny("Nur lokale git-Konfiguration ist erlaubt.")
    elif sub == "clone":
        urls = [p for p in positionals(rest, {"-b", "--branch", "--depth", "-o", "--origin", "-c", "--config"})
                if "github.com" in p]
        if not urls or not all(re.search(rf"github\.com[/:]{OWNER}/", u) for u in urls):
            deny(f"Nur Repos von {OWNER} dürfen geklont werden (am besten mit `gh repo clone {OWNER}/<repo>`).")


def check_no_workflow_changes(cwd, src):
    """Verweigert den Push, wenn src gegenüber dem Default-Branch Dateien unter .github/workflows/ ändert."""
    diff = subprocess.run(["git", "-C", cwd, "diff", "--name-only", f"origin/HEAD...{src}"],
                          capture_output=True, text=True)
    if diff.returncode != 0:
        error = (diff.stderr.strip().splitlines() or ["unbekannter Fehler"])[0]
        deny(f"Konnte nicht prüfen, ob `{src}` Workflow-Dateien ändert ({error}). "
             "Push bitte aus dem Repo heraus (`git -C workspace/<repo> push ...`); origin/HEAD muss existieren "
             "(ggf. `git remote set-head origin --auto`).")
    changed = [f for f in diff.stdout.splitlines() if f.startswith(WORKFLOW_DIR)]
    if changed:
        deny(f"Der Branch ändert Workflow-Dateien ({', '.join(changed)}). Das darf der PAT nicht. "
             "Änderungen daran zurücknehmen und den Alert als manuellen Schritt berichten.")


def check_gh_api(args):
    method, has_body, endpoint = None, False, None
    value_flags = {"-H", "--header", "--jq", "-q", "--template", "-t", "--cache", "-p", "--preview", "--hostname"}
    i = 0
    while i < len(args):
        a = args[i]
        if a in {"-X", "--method"} and i + 1 < len(args):
            method = args[i + 1].upper()
            i += 2
        elif a.startswith("--method="):
            method = a.split("=", 1)[1].upper()
            i += 1
        elif a in {"-f", "-F", "--field", "--raw-field", "--input"}:
            has_body = True
            i += 2
        elif a in value_flags:
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            endpoint = endpoint or a
            i += 1
    method = method or ("POST" if has_body else "GET")
    if method in {"GET", "HEAD"}:
        return
    if endpoint == "graphql":
        if any("mutation" in a.lower() for a in args):
            deny("GraphQL-Mutations sind nicht erlaubt.")
        return
    if method == "POST" and endpoint and POST_ALLOWED.match(endpoint):
        return
    deny(f"`gh api -X {method} {endpoint}` ist nicht erlaubt. Schreibend erlaubt sind nur "
         "Reviewer, Assignees und Kommentare; PRs bitte mit `gh pr create` erstellen.")


def check_gh(args):
    words = [a for a in args if not a.startswith("-")]
    if not words:
        return  # z. B. `gh --version`
    group = words[0]
    if group not in ALLOWED_GH:
        deny(f"`gh {group}` ist nicht erlaubt.")
    allowed = ALLOWED_GH[group]
    if group == "api":
        return check_gh_api(args[args.index("api") + 1:])
    sub = words[1] if len(words) > 1 else None
    if allowed is not None and sub not in allowed:
        deny(f"`gh {group} {sub}` ist nicht erlaubt.")
    if group == "auth" and any(a in {"-t", "--show-token"} for a in args):
        deny("Das Token darf nicht ausgegeben werden.")
    if group == "repo" and sub == "clone":
        target = words[2] if len(words) > 2 else ""
        if not re.match(rf"^(https://github\.com/)?{OWNER}/[\w.-]+(\.git)?$", target):
            deny(f"Nur Repos von {OWNER} dürfen geklont werden.")


def check_bash(command, cwd):
    for pattern, reason in FORBIDDEN_TEXT:
        if pattern.search(command):
            deny(reason)
    for words in segments(command):
        words = strip_prefix(words)
        if not words:
            continue
        prog, args = os.path.basename(words[0]), words[1:]
        if prog == "cd" and args:
            cwd = os.path.join(cwd, os.path.expanduser(args[0]))
        if prog in {"printenv", "sudo", "su", "doas", "eval", "exec", "ssh", "scp", "xargs"}:
            deny(f"`{prog}` ist nicht erlaubt.")
        if prog in {"env", "set", "export", "declare", "typeset"} and (not args or args[0] in {"-p", "-x"}):
            deny("Umgebungsvariablen dürfen nicht ausgegeben werden.")
        if prog in {"bash", "sh", "zsh", "dash"} and "-c" in args:
            deny("Verschachtelte Shells (`bash -c`) sind nicht erlaubt.")
        if prog == "git":
            check_git(args, cwd)
        elif prog == "gh":
            check_gh(args)


def check_file_tool(tool, tool_input, project):
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or ""
    real = os.path.realpath(path or os.getcwd())
    if re.search(r"(^|/)\.env$", real) or "/.gh-config" in real:
        deny(".env und .gh-config/ enthalten Zugangsdaten und sind tabu.")
    if real != project and not real.startswith(project + os.sep):
        deny("Zugriff nur innerhalb des dependabotbot-Projekts erlaubt.")
    if tool in {"Read", "Grep", "Glob"}:
        if tool == "Grep" and real == project:
            deny("Grep bitte nicht über das ganze Projekt (dort liegt .env), sondern z. B. in workspace/<repo>.")
        return
    if "/" + WORKFLOW_DIR in real:
        deny("Dateien unter .github/workflows/ dürfen nicht geändert werden (keine Workflows-Berechtigung). "
             "Den Alert als manuellen Schritt berichten.")
    if not any(real.startswith(os.path.join(project, d) + os.sep) for d in ("workspace", "reports")):
        deny("Dateien dürfen nur unter workspace/ und reports/ geändert werden.")


def main():
    data = json.load(sys.stdin)
    tool, tool_input = data.get("tool_name", ""), data.get("tool_input", {})
    project = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())

    if tool == "Bash":
        if os.environ.get("DEPENDABOTBOT_RUN") != "1":
            deny("Session wurde nicht über ./run.sh gestartet – ohne isolierte Umgebung sind keine Befehle erlaubt.")
        check_bash(tool_input.get("command", ""), data.get("cwd") or os.getcwd())
    elif tool in {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Grep", "Glob"}:
        check_file_tool(tool, tool_input, project)


if __name__ == "__main__":
    main()
