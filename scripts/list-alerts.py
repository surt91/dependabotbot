#!/usr/bin/env python3
"""Sammelt den Dependabot-Status aller eigenen Repos von OWNER (keine Forks, nicht archiviert) als JSON.

Pro Repo: offene Alerts, offene Dependabot-PRs und offene dependabotbot-PRs.

    python3 scripts/list-alerts.py            # nur relevante Repos
    python3 scripts/list-alerts.py --all      # alle Repos
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

OWNER = "surt91"
BOT_BRANCH_PREFIX = "dependabotbot/"


def gh(*args):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gh {' '.join(args)} fehlgeschlagen")
    return json.loads(result.stdout) if result.stdout.strip() else None


def api_list(path):
    pages = gh("api", "--paginate", "--slurp", path)
    return [item for page in pages for item in page]


def try_(fn, *args):
    try:
        return fn(*args), None
    except RuntimeError as e:
        return None, str(e)


def list_repos():
    repos = gh("repo", "list", OWNER, "--source", "--no-archived", "--limit", "1000",
               "--json", "name,visibility,defaultBranchRef")
    return sorted(repos, key=lambda r: r["name"].lower())


def alerts(repo):
    raw = api_list(f"repos/{OWNER}/{repo}/dependabot/alerts?state=open&per_page=100")
    return [{
        "number": a["number"],
        "severity": a["security_advisory"]["severity"],
        "ecosystem": a["dependency"]["package"]["ecosystem"],
        "package": a["dependency"]["package"]["name"],
        "manifest": a["dependency"]["manifest_path"],
        "scope": a["dependency"].get("scope"),
        "relationship": a["dependency"].get("relationship"),
        "vulnerable_range": a["security_vulnerability"]["vulnerable_version_range"],
        "patched_version": (a["security_vulnerability"].get("first_patched_version") or {}).get("identifier"),
        "ghsa": a["security_advisory"]["ghsa_id"],
        "summary": a["security_advisory"]["summary"],
        "url": a["html_url"],
    } for a in raw]


def open_prs(repo):
    return gh("pr", "list", "-R", f"{OWNER}/{repo}", "--state", "open", "--limit", "200",
              "--json", "number,title,url,headRefName,createdAt,mergeable,isDraft")


def inspect(repo):
    name = repo["name"]
    branch = (repo.get("defaultBranchRef") or {}).get("name")
    info = {"repo": f"{OWNER}/{name}", "visibility": repo["visibility"].lower(), "default_branch": branch}

    info["alerts"], info["alerts_error"] = try_(alerts, name)
    prs, info["prs_error"] = try_(open_prs, name)
    prs = prs or []
    info["dependabot_prs"] = [p for p in prs if p["headRefName"].startswith("dependabot/")]
    info["dependabotbot_prs"] = [p for p in prs if p["headRefName"].startswith(BOT_BRANCH_PREFIX)]

    return info


def is_relevant(info):
    return bool(info["alerts"] or info["dependabot_prs"] or info["dependabotbot_prs"])


def main():
    show_all = "--all" in sys.argv[1:]
    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = list(pool.map(inspect, list_repos()))
    json.dump([i for i in infos if show_all or is_relevant(i)], sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
