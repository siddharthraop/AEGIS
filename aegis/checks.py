"""The four checks. Plain code: the same input gives the same answer, and the answer decides whether a pack can be
released. Each returns {"name", "passed", "total", "ok", "findings": [...]}; a finding names a file and a line.
"""
from __future__ import annotations

import re

from .approvals import Approvals
from .corpus import Corpus, Link, Topic


def _result(name, passed, total, findings, extra=None):
    d = {"name": name, "passed": passed, "total": total, "ok": not findings, "findings": findings}
    d.update(extra or {})
    return d


def check_coverage(requirements: list[dict], links: dict[str, list[Link]]) -> dict:
    """Every requirement has at least one evidence topic that survives the pack's profile."""
    findings = []
    for r in requirements:
        if not links.get(r["id"]):
            findings.append({"id": f"coverage:{r['id']}", "check": "check_coverage", "requirement": r["id"],
                             "file": r.get("map_file"), "line": r.get("row_line"), "decidable": True, "proposable": True,
                             "reason": f"{r['id']} ({r['title']}) has no evidence topic in this pack."})
    return _result("check_coverage", len(requirements) - len(findings), len(requirements), findings)


def check_currency(c: Corpus, ap: Approvals, topics: list[Topic], version_dates: dict[str, str]) -> dict:
    """Each evidence topic was revised on or after its model version date, or holds only key references whose keys
    changed in an approved commit after that date."""
    findings, notes = [], []
    keys_file = "gemma/keys/gemma-keys.ditamap"
    kv = ap.verdict(keys_file)
    for t in topics:
        vd = version_dates.get(t.product or "")
        if not vd or (t.revised or "") >= vd:
            continue
        if not t.literals and t.keyrefs and kv["ok"] and (kv.get("date") or "") >= vd:
            notes.append({"topic": t.id, "reason": f"Revised {t.revised}, before {vd}, but holds only key references; "
                                                   f"the keys changed in approved {kv['commit']} on {kv['date']}."})
            continue
        why = f"{t.id} was revised {t.revised}, before the {t.product} version date {vd}"
        why += f", and states {len(t.literals)} value(s) as text (" + ", ".join(t.literals[:4]) + ")." if t.literals \
            else "; its key references don't come from an approved key change after that date."
        findings.append({"id": f"currency:{t.id}", "check": "check_currency", "topic": t.id, "file": t.file,
                         "line": 1, "decidable": True, "reason": why})
    return _result("check_currency", len(topics) - len(findings), len(topics), findings, {"cleared_by_rule": notes})


def check_approval(ap: Approvals, topics: list[Topic], sandbox_links: list[Link]) -> dict:
    """The last change to each topic merged through a pull request approved by a code owner who isn't the author or
    the agent. A link the visitor approved in the sandbox is recorded as a sandbox approval, never as Git."""
    findings, approved = [], []
    for t in topics:
        v = ap.verdict(t.file)
        if v["ok"]:
            approved.append({"topic": t.id, "approved_by": v["approved_by"], "pr": v["pr"], "commit": v["commit"]})
        else:
            findings.append({"id": f"approval:{t.id}", "check": "check_approval", "topic": t.id, "file": t.file,
                             "line": 1, "decidable": True, "reason": f"{t.id}: {v['reason']}"})
    links = [{"requirement": l.requirement, "topic": l.topic, "approved_by": "you, as information architect (sandbox)"}
             for l in sandbox_links]
    return _result("check_approval", len(approved), len(topics), findings,
                   {"approved": approved, "sandbox_links": links, "index_available": ap.available})


def check_consistency(c: Corpus, built: list[Topic], linked: list[Topic], profile_allows_authority: bool,
                      extra_keyrefs: dict[str, list[str]] | None = None) -> dict:
    """Every value resolves from a key; no topic states a fact two ways; no authority-only key resolves in a public or
    downstream build. A leak can't be released with a recorded decision; it must be fixed."""
    findings = []
    extra_keyrefs = extra_keyrefs or {}
    auth = c.authority_keys()
    valued = {k: v for k, v in c.keys.items() if re.search(r"\d", v.value) and len(v.value) >= 3 and v.audience is None}
    checked = 0
    for t in built:
        refs = [(r.key, r.line, False) for r in t.keyrefs] + [(k, "sandbox", True) for k in extra_keyrefs.get(t.id, [])]
        for key, line, sandbox in refs:
            checked += 1
            if key not in c.keys:
                findings.append({"id": f"unresolved:{t.id}:{key}", "check": "check_consistency", "topic": t.id,
                                 "file": t.file, "line": line, "decidable": False, "kind": "unresolved",
                                 "reason": f"{t.id} refers to key {key}, which no key map defines."})
            elif key in auth and not profile_allows_authority:
                findings.append({"id": f"leak:{t.id}:{key}", "check": "check_consistency", "topic": t.id,
                                 "file": t.file, "line": line, "decidable": False, "kind": "leak", "sandbox": sandbox,
                                 "reason": f"Leak: {t.id} resolves the authority-only key {key} "
                                           f"(\"{c.keys[key].value}\") in a build for readers who must not get it."})
        if not profile_allows_authority and t.audience == "authority":
            findings.append({"id": f"leak-topic:{t.id}", "check": "check_consistency", "topic": t.id, "file": t.file,
                             "line": 1, "decidable": False, "kind": "leak",
                             "reason": f"Leak: authority-only topic {t.id} is in this build."})
    conflicting = c.conflicting()
    for t in linked:
        lits = {l.replace(" ", "") for l in t.literals}
        for k, v in valued.items():
            if v.value.replace(" ", "") in lits:
                    findings.append({"id": f"literal:{t.id}:{k}", "check": "check_consistency", "topic": t.id,
                                     "file": t.file, "line": 1, "decidable": True, "kind": "literal",
                                     "reason": f"{t.id} writes \"{v.value}\" as text; key {k} holds that value. "
                                               f"Use a key reference so every pack resolves one value."})
        if t.id in conflicting:
            l = conflicting[t.id]
            findings.append({"id": f"conflict:{t.id}", "check": "check_consistency", "topic": t.id,
                             "file": c.map_file, "line": l.line, "decidable": True, "kind": "conflict",
                             "reason": f"{t.id} states this two ways: the trace marks it 'conflicting' for "
                                       f"{l.requirement}. " + (t.paragraphs[0]["text"] if t.paragraphs else "")})
    return _result("check_consistency", checked - sum(f["kind"] in ("leak", "unresolved") for f in findings), checked,
                   findings, {"keys": len(c.keys), "authority_keys": sorted(auth)})
