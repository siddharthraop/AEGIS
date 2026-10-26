"""Answer a question from the Gemma evidence corpus, with each point cited to a topic, its commit, date and approver.

Retrieval is SQLite FTS5 (BM25) over the requirement and evidence topics, with keys resolved. Gemini writes the
points; plain checks drop any point whose quote isn't in its topic word for word, or whose numbers aren't in it.
Without a model key the answer is extractive: the best-matching sentence of each top topic.
"""
from __future__ import annotations

import re
import sqlite3
import time

from .approvals import Approvals
from .corpus import Corpus
from .model import ASK

STOP = set("a an and are as at be by can do does for from has have how i in is it its of on or the this to what when "
           "which who why with was were will you your about there their they".split())


def terms(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9.\-]*", text.lower()) if w not in STOP and len(w) > 1]


REQ = re.compile(r"annex\s+(xii|xi)\b[^0-9]{0,24}?(\d)\s*\(?([a-h])\)?", re.I)


def requirement_ids(text: str) -> set[str]:
    """Requirement ids named in a question: 'Annex XII 1(e)' or 'aia.xii-1e'."""
    ids = {f"aia.{a.lower()}-{n}{l.lower()}" for a, n, l in REQ.findall(text)}
    ids |= set(re.findall(r"aia\.xii?-\d[a-h]|nist\.[a-z]+\.\d\.\d", text.lower()))
    return ids


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("’", "'").replace("“", '"').replace("”", '"')).strip().lower()


class Asker:
    def __init__(self, corpus: Corpus, approvals: Approvals):
        self.c, self.ap = corpus, approvals
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("create virtual table t using fts5(id unindexed, title, body, tokenize='porter')")
        for t in corpus.topics.values():
            extra = ""
            if t.kind == "requirement":
                row = next((r for r in corpus.rows if r.requirement == t.requirement_id), None)
                ev = [l.topic for l in row.links] if row else []
                extra = (f" Requirement {t.requirement_id}. {t.shortdesc} Legal source: {t.legal_source}. "
                         + ("Evidence: " + ", ".join(ev) if ev else "Gap: no evidence topic is linked to this requirement."))
            self.db.execute("insert into t values (?,?,?)", (t.id, t.title, f"{t.shortdesc} {t.text()} {extra}"))

    def topic_text(self, tid: str) -> str:
        t = self.c.topics[tid]
        body = f"{t.title}. {t.shortdesc} {t.text()}"
        if t.kind == "requirement":
            row = next((r for r in self.c.rows if r.requirement == t.requirement_id), None)
            ev = [f"{l.topic} ({l.coverage})" for l in row.links] if row else []
            body += f" Legal source: {t.legal_source}. " + ("Evidence linked in the trace: " + ", ".join(ev) + "."
                                                           if ev else "No evidence topic is linked to this requirement in the trace.")
        return body

    def search(self, q: str, k: int = 6) -> list[str]:
        ts = terms(q)
        if not ts:
            return []
        expr = " OR ".join(f'"{w}"' for w in ts)
        rows = self.db.execute("select id, bm25(t, 3.0, 1.0) s from t where t match ? order by s limit ?", (expr, k * 2)).fetchall()
        named = requirement_ids(q)
        have = {r[0] for r in rows}
        for t in self.c.topics.values():
            if t.requirement_id in named and t.id not in have:
                rows.append((t.id, 0.0))
        ql = q.lower()
        boost = []
        for tid, s in rows:
            t = self.c.topics[tid]
            b = s
            if ("gemma 3" in ql or "gemma3" in ql) and t.product == "gemma-3": b -= 2
            if ("gemma 4" in ql or "gemma4" in ql) and t.product == "gemma-4": b -= 2
            if t.requirement_id in named: b -= 50
            boost.append((b, tid))
        return [tid for _, tid in sorted(boost)[:k]]

    def cite(self, tid: str) -> dict:
        t = self.c.topics[tid]
        v = self.ap.verdict(t.file)
        d = {"id": t.id, "title": t.title, "kind": t.kind, "file": t.file, "url": t.url, "revised": t.revised,
             "model_version": t.product, "commit": v["commit"], "pr": v["pr"], "pr_url": v.get("pr_url"),
             "approved_by": v.get("approved_by"), "approval": v["reason"], "approved": v["ok"]}
        if t.kind == "evidence":
            d["evidence_for"] = self.c.evidence_for(t.id)
        else:
            row = next((r for r in self.c.rows if r.requirement == t.requirement_id), None)
            d["requirement"] = t.requirement_id
            d["linked_evidence"] = [{"topic": l.topic, "coverage": l.coverage, "product": l.product} for l in row.links] if row else []
            d["gap"] = not bool(row and row.links)
        return d

    def check(self, p: dict, ctx: set[str]) -> str | None:
        tid = p.get("topic")
        if tid not in ctx:
            return "cites a topic that wasn't retrieved"
        src = norm(self.topic_text(tid))
        q = norm(p.get("quote", ""))
        if len(q.split()) < 5 or q not in src:
            return "quote is not in the topic word for word"
        for n in re.findall(r"\d[\d,.]*", p.get("text", "")):
            n = n.rstrip(".,")
            if n and n not in src:
                return f"value {n} is not in the topic"
        return None

    def ask(self, question: str, model=None) -> dict:
        t0 = time.time()
        ids = self.search(question)
        if not ids:
            return {"question": question, "summary": "No topic in the corpus matches this question.", "points": [],
                    "dropped": [], "sources": [], "not_covered": question, "model": {"name": "none"}, "ms": 0}
        ctx = set(ids)
        error = None
        raw = None
        if model is not None:
            prompt = "Question: " + question + "\n\nTopics:\n" + "\n\n".join(f"[{i}]\n{self.topic_text(i)}" for i in ids)
            try:
                raw = model.generate(ASK, prompt)
            except Exception as e:  # serve the extractive answer rather than fail
                error = f"{type(e).__name__}: {str(e)[:160]}"
        if raw is None:
            raw = self.extractive(question, ids)
        points, dropped = [], []
        for p in raw.get("points", [])[:4]:
            why = self.check(p, ctx)
            (dropped if why else points).append(dict(p, why=why) if why else p)
        used = []
        for p in points:
            if p["topic"] not in used:
                used.append(p["topic"])
        for p in points:
            p["n"] = used.index(p["topic"]) + 1
        name = getattr(model, "name", "extractive") if model is not None and error is None else "extractive"
        return {"question": question, "summary": raw.get("summary", "") if points else
                "The checks dropped every point, so there is no checked answer. The topics below were the best matches.",
                "points": points, "dropped": dropped, "not_covered": raw.get("not_covered", ""),
                "sources": [self.cite(i) for i in (used or ids[:3])], "retrieved": ids,
                "model": {"name": name, "id": getattr(model, "id", "none") if name != "extractive" else "none",
                          "error": error, "tokens": getattr(model, "tokens", None)},
                "ms": int((time.time() - t0) * 1000)}

    def extractive(self, question: str, ids: list[str]) -> dict:
        q = set(terms(question))
        pts = []
        for tid in ids[:3]:
            t = self.c.topics[tid]
            full = self.topic_text(tid)
            # Prefer the body and the trace over the generic title and short description.
            text = full.split(t.shortdesc, 1)[-1] if t.shortdesc and t.shortdesc in full else full
            best = None
            for sent in re.split(r"(?<=[.])\s+(?=[A-Z])", text):
                sc = len(q & set(terms(sent)))
                if len(sent.split()) >= 6 and (best is None or sc > best[0]):
                    best = (sc, sent.strip())
            if best and best[0] > 0:
                pts.append({"text": best[1], "topic": tid, "quote": best[1]})
        return {"summary": "These passages from the evidence corpus match the question best.", "points": pts, "not_covered": ""}
