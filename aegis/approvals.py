"""The approval record, read from Git and GitHub once at build time and baked into the image.

For each file in the Gemma set: the last commit that changed it, the pull request that merged that commit, who
authored the pull request and who approved it. check_approval reads only this index, so a page view never calls the
GitHub API. scripts/approval_index.py writes it.
"""
from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .corpus import ROOT

INDEX = Path(os.environ.get("AEGIS_APPROVALS", ROOT / "data" / "approvals.json"))
AGENTS = {"github-actions[bot]", "aegis-agent"}


@dataclass
class Approval:
    file: str
    commit: str | None = None
    date: str | None = None
    via: str = "unknown"                 # pull-request | direct-push | unknown
    pr: int | None = None
    pr_url: str | None = None
    pr_author: str | None = None
    approvers: list[dict] = field(default_factory=list)   # {"login", "name", "at"}

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def codeowners_for(path: str, rules: list[list[str]]) -> list[str]:
    """CODEOWNERS semantics: the last matching pattern wins."""
    owners: list[str] = []
    for pattern, *who in rules:
        p = pattern
        if p == "*":
            hit = True
        elif p.startswith("/"):
            p = p[1:]
            hit = path.startswith(p) if p.endswith("/") else fnmatch.fnmatch(path, p) or path.startswith(p.rstrip("/") + "/")
        else:
            hit = fnmatch.fnmatch(path, p) or fnmatch.fnmatch(path, f"*/{p}") or f"/{p.rstrip('/')}/" in f"/{path}"
        if hit:
            owners = [w.lstrip("@").lower() for w in who]
    return owners


def parse_codeowners(text: str) -> list[list[str]]:
    rules = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            rules.append(line.split())
    return rules


class Approvals:
    def __init__(self, path: Path = INDEX, data: dict | None = None):
        if data is None:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.data = data
        self.generated = data.get("generated")
        self.corpus_commit = data.get("corpus_commit")
        self.codeowners = data.get("codeowners", [])
        self.files = {f: Approval(file=f, **v) for f, v in data.get("files", {}).items()}

    @property
    def available(self) -> bool:
        return bool(self.files)

    def get(self, file: str) -> Approval:
        return self.files.get(file) or Approval(file=file)

    def owners(self, file: str) -> list[str]:
        return codeowners_for(file, self.codeowners)

    def verdict(self, file: str) -> dict:
        """Pass when the last change merged through a pull request that a code owner approved and didn't author."""
        a = self.get(file)
        owners = self.owners(file)
        out = {"file": file, "commit": a.commit, "date": a.date, "via": a.via, "pr": a.pr, "pr_url": a.pr_url,
               "author": a.pr_author, "approved_by": None, "owners": owners}
        if a.via == "unknown":
            return dict(out, ok=False, reason="No approval record for this file.")
        if a.via == "direct-push" or not a.pr:
            return dict(out, ok=False, reason="The last change was pushed directly, not merged through a reviewed pull request.")
        valid = [r for r in a.approvers
                 if r["login"].lower() not in AGENTS and not r["login"].lower().endswith("[bot]")
                 and r["login"].lower() != (a.pr_author or "").lower()
                 and r["login"].lower() in owners]
        if not valid:
            who = ", ".join(r["login"] for r in a.approvers) or "nobody"
            return dict(out, ok=False, reason=f"PR #{a.pr} by {a.pr_author} was approved by {who}: no code owner other than the author or the agent.")
        r = valid[-1]
        return dict(out, ok=True, approved_by=r.get("name") or r["login"], approver_login=r["login"],
                    approved_at=r.get("at"), reason=f"PR #{a.pr} approved by code owner {r['login']}.")
