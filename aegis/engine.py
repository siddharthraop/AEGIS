"""Assemble one evidence pack: a reader's profile, the sandbox overlay, the four checks, the manifest and the files.

The overlay is what a visitor did in the sandbox: links they approved or rejected as the information architect,
decisions they recorded as the compliance lead, a leak they planted, a model update they simulated. It is applied
on top of the corpus in memory and never written back to dita-corpus.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import html
import io
import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .approvals import Approvals
from .checks import check_approval, check_consistency, check_coverage, check_currency
from .corpus import ROOT, Corpus, Link, Topic, load
from .ditaval import Profile

BUILDS = Path(os.environ.get("AEGIS_BUILDS", ROOT / "build" / "packs"))
LEGAL = "AEGIS is a documentation tool. It isn't legal advice, and it doesn't decide whether an obligation applies."

READERS = {
    "authority": {"label": "AI Office and national authorities", "pack": "Authority pack", "set": "EU AI Act Annex XI, Section 1",
                  "basis": "Article 53(1)(a)", "ditaval": "corpus:gemma/filters/authority.ditaval", "frameworks": ["eu-ai-act"]},
    "downstream": {"label": "Downstream provider", "pack": "Downstream pack", "set": "EU AI Act Annex XII",
                   "basis": "Article 53(1)(b)", "ditaval": "corpus:gemma/filters/downstream.ditaval", "frameworks": ["eu-ai-act"]},
    "public": {"label": "Public", "pack": "Public model card", "set": "Model card sections (documentation, not legal)",
               "basis": "none (public information)", "ditaval": "packs:public.ditaval", "frameworks": ["model-card"]},
}
MODEL = "gemma-4"


def empty_overlay() -> dict:
    return {"links": [], "decisions": {}, "leak": None, "model_update": None}


@dataclass
class Engine:
    corpus: Corpus
    approvals: Approvals

    @classmethod
    def default(cls) -> "Engine":
        return cls(load(), Approvals())

    # -- profile and requirement set ---------------------------------------------------------------------------
    def profile(self, reader: str) -> Profile:
        where, rel = READERS[reader]["ditaval"].split(":", 1)
        base = self.corpus.root if where == "corpus" else self.corpus.packs
        p = Profile.load(reader, base / rel, root=self.corpus.root if where == "corpus" else None)
        if where == "packs":
            p.file = f"packs/{rel}"
        return p

    def requirements(self, reader: str, prof: Profile) -> tuple[list[dict], dict[str, list[Link]]]:
        c = self.corpus
        reqs, links = [], {}
        if reader == "public":
            for s in c.card_sections["sections"]:
                reqs.append({"id": s["id"], "title": s["title"], "legal_source": None, "framework": "model-card",
                             "topic": None, "map_file": "packs/model-card-sections.yaml", "row_line": None})
                links[s["id"]] = [Link(s["id"], t.id, t.product, "stated", 0, source="subject")
                                  for t in c.topics.values()
                                  if t.kind == "evidence" and t.subject == s["subject"] and prof.keeps({"product": t.product})]
            return reqs, links
        for row in c.rows:
            if not prof.keeps({"audience": row.audience}):
                continue
            rt = c.topics[row.requirement_topic]
            reqs.append({"id": row.requirement, "title": rt.title.split(": ", 1)[-1], "full_title": rt.title,
                         "legal_source": rt.legal_source, "framework": rt.framework, "topic": rt.id,
                         "topic_file": rt.file, "map_file": c.map_file, "row_line": row.line})
            links[row.requirement] = [l for l in row.links if prof.keeps({"product": l.product})
                                      and prof.keeps({"product": c.topics[l.topic].product})]
        return reqs, links

    # -- run ---------------------------------------------------------------------------------------------------
    def run(self, reader: str, overlay: dict | None = None) -> dict:
        if reader not in READERS:
            raise ValueError(f"unknown reader {reader}")
        c, ov = self.corpus, overlay or empty_overlay()
        prof = self.profile(reader)
        reqs, links = self.requirements(reader, prof)
        req_ids = {r["id"] for r in reqs}

        sandbox_links = []
        for sl in ov.get("links", []):
            if sl.get("status") == "approved" and sl["requirement"] in req_ids and sl["topic"] in c.topics:
                t = c.topics[sl["topic"]]
                if prof.keeps({"product": t.product}) and not any(l.topic == t.id for l in links[sl["requirement"]]):
                    l = Link(sl["requirement"], t.id, t.product, sl.get("coverage", "stated"), 0, source="sandbox",
                             proposal=sl.get("proposal"))
                    links[sl["requirement"]].append(l)
                    sandbox_links.append(l)

        linked_ids = sorted({l.topic for ls in links.values() for l in ls})
        linked = [c.topics[i] for i in linked_ids]
        req_topics = [c.topics[r["topic"]] for r in reqs if r.get("topic")]
        built = [t for t in c.topics.values()
                 if prof.keeps({"audience": t.audience if t.kind == "requirement" else None, "product": t.product})]

        version_dates = {k: v["version_date"] for k, v in c.models.items()}
        if ov.get("model_update"):
            version_dates[MODEL] = ov["model_update"]
        extra = {}
        if ov.get("leak"):
            extra = {ov["leak"]["topic"]: [ov["leak"]["key"]]}

        checks = [
            check_coverage(reqs, links),
            check_currency(c, self.approvals, linked, version_dates),
            check_approval(self.approvals, linked + req_topics, sandbox_links),
            check_consistency(c, built, linked, prof.includes_audience("authority"), extra),
        ]
        decisions = ov.get("decisions", {})
        findings = []
        for ch in checks:
            for f in ch["findings"]:
                f["decision"] = decisions.get(f["id"]) if f.get("decidable") else None
                findings.append(f)
        blocking = [f for f in findings if not f.get("decidable")]
        open_ = [f for f in findings if f.get("decidable") and not f.get("decision")]
        status = "blocked" if blocking else "needs-decisions" if open_ else \
            "ready-with-recorded-gaps" if findings else "ready"

        items = []
        for r in reqs:
            ls = links[r["id"]]
            ev = []
            for l in ls:
                t = c.topics[l.topic]
                v = self.approvals.verdict(t.file)
                ev.append({"topic": t.id, "title": t.title, "file": t.file, "url": t.url, "coverage": l.coverage,
                           "revised": t.revised, "model_version": t.product, "commit": v["commit"], "pr": v["pr"],
                           "pr_url": v.get("pr_url"), "approved_by": v.get("approved_by"), "approval_ok": v["ok"],
                           "link": {"source": l.source, "line": l.line, "proposal": l.proposal}})
            items.append(dict(r, evidence=ev, covered=bool(ls),
                              findings=[f["id"] for f in findings if f.get("requirement") == r["id"]
                                        or f.get("topic") in {e["topic"] for e in ev}]))
        return {
            "aegis": __version__, "reader": reader, "reader_info": READERS[reader], "model_version": MODEL,
            "version_date": version_dates[MODEL], "model_update": ov.get("model_update"),
            "source": {"repo": "siddharthraop/dita-corpus", "commit": c.commit, "map": c.map_file,
                       "profile": prof.file, "approvals_index": self.approvals.generated},
            "requirements": items, "checks": checks, "findings": findings, "status": status,
            "summary": {"requirements": len(reqs), "covered": sum(i["covered"] for i in items),
                        "topics": len(linked), "built_topics": len(built),
                        "approved": checks[2]["passed"], "approval_total": checks[2]["total"],
                        "current": checks[1]["passed"], "blocking": len(blocking), "open": len(open_)},
            "built_topics": [t.id for t in built], "candidates": self.candidates(reader, prof),
            "leak": ov.get("leak"), "legal": LEGAL,
        }

    def candidates(self, reader: str, prof: Profile | None = None) -> list[dict]:
        """Evidence topics a link may point at in this pack: real ids only, titles and short descriptions only."""
        prof = prof or self.profile(reader)
        return [{"id": t.id, "title": t.title, "shortdesc": t.shortdesc} for t in self.corpus.topics.values()
                if t.kind == "evidence" and prof.keeps({"product": t.product})]

    # -- pack files ----------------------------------------------------------------------------------------------
    def manifest(self, result: dict, pack_id: str, sandbox: bool = True) -> dict:
        items = []
        for r in result["requirements"]:
            if r["covered"]:
                for e in r["evidence"]:
                    item = {"req": r["id"], "topics": [e["topic"]], "revised": e["revised"], "commit": e["commit"],
                            "approved_by": e["approved_by"], "pr": e["pr"],
                            "checks": "pass" if not [f for f in result["findings"] if f.get("topic") == e["topic"]] else "see findings"}
                    if e["link"]["source"] == "sandbox":
                        item["link"] = {"proposed_by": "propose_mapping", "approved_by": "visitor as information architect (sandbox)",
                                        **({k: e["link"]["proposal"].get(k) for k in ("confidence", "reason")} if e["link"]["proposal"] else {})}
                    items.append(item)
            else:
                f = next((x for x in result["findings"] if x["id"] == f"coverage:{r['id']}"), None)
                items.append({"req": r["id"], "topics": [], "checks": "gap", "decision": (f or {}).get("decision")})
        return {
            "pack_id": pack_id, "sandbox": sandbox, "legal": LEGAL,
            "request": {"from": result["reader_info"]["label"], "basis": result["reader_info"]["basis"],
                        "requirement_set": result["reader_info"]["set"]},
            "source": dict(result["source"], model_version=result["model_version"], version_date=result["version_date"]),
            "status": result["status"],
            "checks": {ch["name"]: {"passed": ch["passed"], "total": ch["total"], "ok": ch["ok"]} for ch in result["checks"]},
            "items": items,
            "findings": [{k: f.get(k) for k in ("id", "check", "reason", "file", "line", "decision")} for f in result["findings"]],
            "built": {"tool": "DITA-OT 4.4", "profile": result["source"]["profile"],
                      "note": "The documentation files were built by DITA-OT in CI from the corpus commit above with this "
                              "reader's DITAVAL profile. Sandbox links and decisions are recorded here and in the report; "
                              "they don't change the built topics."},
            "files": [], "released": None, "sealed": None,
        }

    def report_html(self, result: dict, manifest: dict) -> str:
        e = html.escape
        rows = []
        for r in result["requirements"]:
            ev = "<br>".join(f"<code>{e(x['topic'])}</code> · {e(x['coverage'] or '')} · rev {e(x['revised'] or '')} · "
                             f"{e(x['commit'] or '')} · {e(x['approved_by'] or 'not approved')}"
                             + (" · <b>sandbox link</b>" if x['link']['source'] == 'sandbox' else "") for x in r["evidence"]) \
                or "<b>gap</b>"
            rows.append(f"<tr><td><code>{e(r['id'])}</code><br>{e(r['title'])}</td><td>{ev}</td></tr>")
        finds = "".join(f"<li><code>{e(f['check'])}</code> {e(f['reason'])}"
                        + (f" <b>Decision:</b> {e(f['decision']['choice'])}, {e(f['decision'].get('reason',''))}" if f.get("decision") else "")
                        + "</li>" for f in result["findings"]) or "<li>None.</li>"
        chk = "".join(f"<li><code>{c['name']}</code>: {c['passed']}/{c['total']} {'pass' if c['ok'] else 'findings'}</li>"
                      for c in result["checks"])
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>AEGIS report {e(manifest['pack_id'])}</title>
<style>body{{font:14px/1.6 system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 16px;color:#1a1917}}
table{{border-collapse:collapse;width:100%}}td{{border-top:1px solid #ddd;padding:6px;vertical-align:top}}code{{font-size:12px}}
.legal{{border-left:3px solid #b07010;padding:6px 10px;background:#fdf4e3}}</style></head><body>
<h1>{e(result['reader_info']['pack'])}: {e(manifest['pack_id'])}</h1>
<p class="legal">{e(LEGAL)}{' This pack was built in the public sandbox and is not released or sealed.' if manifest['sandbox'] else ''}</p>
<p>Reader: {e(result['reader_info']['label'])} · Requirement set: {e(result['reader_info']['set'])} · Corpus commit
<code>{e(result['source']['commit'])}</code> · Profile <code>{e(result['source']['profile'])}</code> · Model version
<code>{e(result['model_version'])}</code> (version date {e(result['version_date'])}) · Status <b>{e(result['status'])}</b></p>
<h2>Checks</h2><ul>{chk}</ul><h2>Requirements</h2><table>{''.join(rows)}</table>
<h2>Findings and decisions</h2><ul>{finds}</ul></body></html>"""

    def build_zip(self, result: dict, pack_id: str, sandbox: bool = True, released: dict | None = None) -> tuple[bytes, dict]:
        man = self.manifest(result, pack_id, sandbox)
        man["released"] = released
        files: dict[str, bytes] = {}
        built = BUILDS / result["reader"]
        if built.exists():
            for p in sorted(built.rglob("*")):
                if p.is_file():
                    files[f"documentation/{p.relative_to(built)}"] = p.read_bytes()
        else:
            man["built"]["note"] = "No DITA-OT output in this environment; the pack holds the manifest and report only."
        report = self.report_html(result, man)
        files["report.html"] = report.encode()
        cov = io.StringIO()
        w = csv.writer(cov)
        w.writerow(["requirement", "title", "covered", "topic", "coverage", "revised", "commit", "approved_by", "link_source"])
        for r in result["requirements"]:
            for e in r["evidence"] or [None]:
                w.writerow([r["id"], r["title"], r["covered"]] + ([e["topic"], e["coverage"], e["revised"], e["commit"],
                                                                 e["approved_by"], e["link"]["source"]] if e else [""] * 6))
        files["coverage.csv"] = cov.getvalue().encode()
        man["files"] = [{"path": p, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for p, b in sorted(files.items())]
        mbytes = json.dumps(man, indent=2).encode()
        files["manifest.json"] = mbytes
        sums = "".join(f"{f['sha256']}  {f['path']}\n" for f in man["files"])
        sums += f"{hashlib.sha256(mbytes).hexdigest()}  manifest.json\n"
        files["SHA256SUMS"] = sums.encode()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p, b in sorted(files.items()):
                z.writestr(f"{pack_id}/{p}", b)
        man["manifest_sha256"] = hashlib.sha256(mbytes).hexdigest()
        return buf.getvalue(), man


def pack_id(reader: str, session: str | None = None) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"gemma4-{reader}-{stamp}" + (f"-{session[:6]}" if session else "")
