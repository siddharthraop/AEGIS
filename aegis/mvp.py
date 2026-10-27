"""The MVP flow: pick a system, get the authority pack and one downstream pack, and the metrics from the design.

Nothing here is new logic. It runs the engine for two readers, measures what the design says to measure, and labels
each number as measured, modeled or not part of the MVP. Nothing is written back to the corpus.
"""
from __future__ import annotations

import re
import time

from .engine import BUILDS, LEGAL, Engine, pack_id

PACK_READERS = ("authority", "downstream")

SYSTEMS = [
    {"id": "gemma-4", "name": "Gemma 4", "available": True,
     "note": "Evidence set in dita-corpus: 11 evidence topics, Annex XI Section 1 and Annex XII requirement maps."},
    {"id": "gemma-3", "name": "Gemma 3", "available": False,
     "note": "The corpus holds Gemma 3 evidence topics but no requirement map for it yet."},
]


def system(system_id: str) -> dict | None:
    return next((s for s in SYSTEMS if s["id"] == system_id and s["available"]), None)


def mvp_pack_id(system_id: str, reader: str, commit: str) -> str:
    """Deterministic for a corpus commit, so the hash shown before download is the hash of what is downloaded."""
    return f"{system_id.replace('-', '')}-{reader}-{commit[:7]}"


# -- leak scan ---------------------------------------------------------------------------------------------------
def _needles(engine: Engine) -> list[tuple[str, re.Pattern]]:
    c = engine.corpus
    out: list[tuple[str, re.Pattern]] = [("authority topic id", re.compile(r"aia-xi-\d")),
                                         ("authority requirement", re.compile(r"Annex XI(?!I)"))]
    for t in c.topics.values():
        if t.audience == "authority":
            out.append((f"title of {t.id}", re.compile(re.escape(t.title))))
    for k in sorted(c.authority_keys()):
        out.append((f"value of key {k}", re.compile(re.escape(c.keys[k].value))))
    return out


def scan(engine: Engine, reader: str) -> dict | None:
    """Search the DITA-OT HTML output of a pack for authority-only content. None when the pack wasn't built."""
    root = BUILDS / reader / "html"
    if not root.exists():
        return None
    needles = _needles(engine)
    files = sorted(p for p in root.rglob("*.html"))
    hits = []
    for p in files:
        text = p.read_text(errors="ignore")
        rel = str(p.relative_to(root))
        for label, pat in needles:
            if pat.search(text) or pat.search(rel):
                hits.append({"file": rel, "what": label})
    return {"files": len(files), "needles": len(needles), "hits": hits}


def leak_measurement(engine: Engine, reader: str) -> dict:
    """The downstream scan, plus a positive control: the same scan over the authority pack must find the content,
    or a result of zero would only mean the scanner can't see it."""
    s, control = scan(engine, reader), scan(engine, "authority")
    if s is None or control is None:
        return {"measured": False, "hits": None, "files": 0, "control_hits": None}
    return {"measured": bool(control["hits"]), "hits": len(s["hits"]), "files": s["files"],
            "control_hits": len(control["hits"]), "examples": s["hits"][:5]}


# -- metrics -----------------------------------------------------------------------------------------------------
def _fully_evidenced(res: dict) -> tuple[int, int]:
    """Requirements that are covered, whose evidence is current and approved."""
    stale = {f["topic"] for f in res["findings"] if f["check"] == "check_currency"}
    ok = 0
    for r in res["requirements"]:
        ev = r["evidence"]
        if r["covered"] and all(e["approval_ok"] and e["topic"] not in stale for e in ev):
            ok += 1
    return ok, len(res["requirements"])


def metrics(engine: Engine, results: dict[str, dict], seconds: float) -> list[dict]:
    a, d = results["authority"], results["downstream"]
    ok = tot = 0
    for res in results.values():
        o, t = _fully_evidenced(res)
        ok, tot = ok + o, tot + t
    gaps = sum(1 for res in results.values() for f in res["findings"] if f["check"] == "check_coverage")
    decided = sum(1 for res in results.values() for f in res["findings"] if f["check"] == "check_coverage" and f.get("decision"))

    ev = [e for res in results.values() for r in res["requirements"] for e in r["evidence"]]
    named = sum(1 for e in ev if e["approval_ok"] and e["approved_by"])

    vals = sum(c["passed"] for res in results.values() for c in res["checks"] if c["name"] == "check_consistency")
    vals_t = sum(c["total"] for res in results.values() for c in res["checks"] if c["name"] == "check_consistency")

    leak = leak_measurement(engine, "downstream")
    index = engine.approvals.available

    m = [
        {"id": "covered", "label": "Requirements covered, current and approved",
         "value": f"{ok} of {tot}", "pct": round(100 * ok / tot) if tot else 0,
         "target": "100%, or a recorded decision for each gap", "kind": "measured",
         "status": "pass" if ok == tot else "open",
         "note": f"{gaps} requirement{'s' if gaps != 1 else ''} with no evidence topic ({decided} with a recorded decision)."
                 + ("" if index else " The approval index isn't loaded, so nothing counts as approved.")},
        {"id": "approvers", "label": "Evidence items with a named human approver from Git",
         "value": f"{named} of {len(ev)}", "pct": round(100 * named / len(ev)) if ev else 0,
         "target": "100%", "kind": "measured", "status": "pass" if ev and named == len(ev) else "open",
         "note": "Read from the pull request reviews on each file's last commit." if index
                 else "The approval index isn't loaded."},
        {"id": "keys", "label": "Values in the packs that resolve from a key",
         "value": f"{vals} of {vals_t}", "pct": round(100 * vals / vals_t) if vals_t else 0,
         "target": "100%", "kind": "measured", "status": "pass" if vals_t and vals == vals_t else "open",
         "note": "Key references checked across both packs by check_consistency."},
        {"id": "leak", "label": "Authority content found in downstream output",
         "value": "not measured" if leak["hits"] is None else str(leak["hits"]),
         "pct": None, "target": "0", "kind": "measured",
         "status": "open" if not leak["measured"] else "pass" if leak["hits"] == 0 else "fail",
         "note": ("Scanned the built downstream HTML (" + f"{leak['files']} files) for authority topic ids, titles and key values. "
                  f"The same scan finds {leak['control_hits']} matches in the authority pack, so a zero is a real zero.")
                 if leak["measured"] else "No DITA-OT output is loaded in this environment, so the scan couldn't run."},
        {"id": "time", "label": "Time from request to a pack ready for release",
         "value": "under 1 second" if seconds < 1 else f"{seconds:.1f} seconds", "pct": None, "target": "Under 1 working day", "kind": "measured",
         "status": "pass", "note": "Checks and both pack builds, on this server. A person still has to review the findings."},
        {"id": "hours", "label": "People hours per pack",
         "value": "modeled", "pct": None, "target": "Under 4, against a modeled 32 by hand", "kind": "modeled",
         "status": "info", "note": "The design models this. The MVP doesn't measure it."},
        {"id": "sealed", "label": "Packs sealed with a locked policy and a manifest hash",
         "value": "0 of 2", "pct": 0, "target": "100%", "kind": "not-in-mvp", "status": "info",
         "note": "These packs carry a manifest hash. Sealing needs a human release and a locked bucket, which the MVP leaves out."},
    ]
    return m


def generate(engine: Engine, system_id: str) -> dict:
    """Run both packs, build their zips (for size and hashes), and return the results with the metrics."""
    t0 = time.perf_counter()
    results, packs = {}, {}
    for reader in PACK_READERS:
        res = engine.run(reader)
        pid = mvp_pack_id(system_id, reader, res["source"]["commit"])
        data, man = engine.build_zip(res, pid, sandbox=True)
        results[reader] = res
        packs[reader] = {"pack_id": pid, "bytes": len(data), "manifest_sha256": man["manifest_sha256"],
                         "files": man["files"], "has_documentation": any(f["path"].startswith("documentation/") for f in man["files"])}
    seconds = time.perf_counter() - t0
    sys_ = system(system_id)
    return {"system": sys_, "legal": LEGAL, "seconds": round(seconds, 2), "packs": packs,
            "results": {r: _slim(res) for r, res in results.items()}, "metrics": metrics(engine, results, seconds),
            "source": next(iter(results.values()))["source"]}


def _slim(res: dict) -> dict:
    """What the page needs from a run: status, checks, requirements and findings, without the sandbox plumbing."""
    return {"reader": res["reader"], "reader_info": res["reader_info"], "status": res["status"], "summary": res["summary"],
            "checks": [{k: c[k] for k in ("name", "passed", "total", "ok")} for c in res["checks"]],
            "requirements": [{"id": r["id"], "title": r["title"], "covered": r["covered"],
                              "evidence": [{"topic": e["topic"], "approved_by": e["approved_by"], "approval_ok": e["approval_ok"]}
                                           for e in r["evidence"]]} for r in res["requirements"]],
            "findings": [{k: f.get(k) for k in ("id", "check", "reason", "decidable")} for f in res["findings"]]}
