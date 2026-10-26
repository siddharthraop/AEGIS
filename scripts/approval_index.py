"""Write data/approvals.json: for each file in the Gemma set, its last commit, the pull request that merged it and
the reviews on that pull request.

Runs in CI before the image is built (needs the corpus submodule with full history and a GitHub token for the public
API). Usage: python scripts/approval_index.py [--corpus corpus] [--out data/approvals.json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aegis.approvals import parse_codeowners  # noqa: E402

OWNER_REPO = os.environ.get("AEGIS_CORPUS_REPO", "siddharthraop/dita-corpus")
API = "https://api.github.com"
_cache: dict[str, object] = {}


def gh(path: str):
    if path in _cache:
        return _cache[path]
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json",
                                                     "X-GitHub-Api-Version": "2022-11-28"})
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=30) as r:
        _cache[path] = json.loads(r.read())
    return _cache[path]


def git(corpus: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(corpus), *args], check=True, capture_output=True, text=True).stdout.strip()


def name_of(login: str) -> str:
    try:
        return gh(f"/users/{login}").get("name") or login
    except Exception:
        return login


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--out", default="data/approvals.json")
    a = ap.parse_args()
    corpus = Path(a.corpus)
    files = sorted(git(corpus, "ls-files", "gemma").splitlines())
    head = git(corpus, "rev-parse", "HEAD")
    co = ""
    for p in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        if (corpus / p).exists():
            co = (corpus / p).read_text(encoding="utf-8")
            break
    out = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "corpus_commit": head,
           "repo": OWNER_REPO, "codeowners": parse_codeowners(co), "files": {}}
    for f in files:
        sha, date = git(corpus, "log", "-1", "--format=%H %cs", "--", f).split()
        rec = {"commit": sha[:12], "date": date, "via": "direct-push", "pr": None, "pr_url": None,
               "pr_author": None, "approvers": []}
        try:
            pulls = [p for p in gh(f"/repos/{OWNER_REPO}/commits/{sha}/pulls") if p.get("merged_at")]
        except Exception as e:  # keep the honest answer: unknown, not approved
            print(f"warning: {f}: {e}", file=sys.stderr)
            rec["via"] = "unknown"
            pulls = []
        if pulls:
            p = pulls[0]
            reviews = gh(f"/repos/{OWNER_REPO}/pulls/{p['number']}/reviews")
            latest: dict[str, dict] = {}
            for r in reviews:
                latest[r["user"]["login"]] = r
            rec.update(via="pull-request", pr=p["number"], pr_url=p["html_url"], pr_author=p["user"]["login"],
                       approvers=[{"login": l, "name": name_of(l), "at": (r.get("submitted_at") or "")[:10]}
                                  for l, r in latest.items() if r["state"] == "APPROVED"])
        out["files"][f] = rec
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    n = sum(1 for r in out["files"].values() if r["approvers"])
    print(f"approvals: {len(files)} files, {n} merged through an approved pull request, corpus {head[:12]}")


if __name__ == "__main__":
    main()
