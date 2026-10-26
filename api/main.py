"""AEGIS API: run the four checks for a reader, act in a private sandbox, build and download a pack, ask the corpus."""
from __future__ import annotations

import os
import re
import threading
import time
from collections import deque

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from aegis import __version__
from aegis.approvals import Approvals
from aegis.ask import Asker
from aegis.corpus import load
from aegis.engine import LEGAL, READERS, Engine, empty_overlay, pack_id
from aegis.model import Gemini, has_key, propose_mapping
from aegis.store import Store

app = FastAPI(title="AEGIS", version=__version__)
origins = os.environ.get("AEGIS_CORS_ORIGINS", "https://siddharthraop.github.io,http://localhost:8000").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["Content-Type"], expose_headers=["Content-Disposition", "X-Aegis-Manifest-Sha256"])

corpus = load()
approvals = Approvals()
engine = Engine(corpus, approvals)
asker = Asker(corpus, approvals)
store = Store()
PROPOSALS_PER_DAY = int(os.environ.get("AEGIS_PROPOSALS_PER_DAY", "20"))
ASKS_PER_DAY = int(os.environ.get("AEGIS_ASKS_PER_DAY", "150"))
ASKS_PER_MINUTE = int(os.environ.get("AEGIS_ASKS_PER_MINUTE", "12"))
_recent: deque = deque()
_lock = threading.Lock()
SID = re.compile(r"^[a-z0-9-]{16,48}$")


def model():
    return Gemini() if has_key() else None


def sandbox(sid: str) -> dict:
    if not SID.match(sid or ""):
        raise HTTPException(400, "Bad sandbox id.")
    return store.get(sid) or empty_overlay()


def reader_ok(reader: str):
    if reader not in READERS:
        raise HTTPException(400, f"Reader must be one of {', '.join(READERS)}.")


def view(reader: str, sid: str, ov: dict | None = None) -> dict:
    ov = ov if ov is not None else sandbox(sid)
    r = engine.run(reader, ov)
    r["sandbox"] = {"id": sid, "overlay": ov, "store": store.backend, "expires_days": 7,
                    "proposals_left_today": max(0, PROPOSALS_PER_DAY - store.used("propose")) if has_key() else 0}
    return r


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__, "model": os.environ.get("AEGIS_MODEL", "gemini-3.8-flash") if has_key()
            else "none", "store": store.backend, "corpus": corpus.stats(),
            "approvals": {"generated": approvals.generated, "corpus_commit": approvals.corpus_commit,
                          "approved_files": sum(1 for a in approvals.files.values() if a.approvers)},
            "legal": LEGAL}


@app.get("/api/readers")
def readers():
    return {"readers": READERS, "legal": LEGAL,
            "authority_keys": [{"key": k, "value": corpus.keys[k].value} for k in sorted(corpus.authority_keys())],
            "leak_targets": [{"id": t.id, "title": t.title} for t in corpus.topics.values()
                             if t.kind == "evidence" and t.product == "gemma-4"]}


@app.get("/api/run")
def run(reader: str = Query(...), sid: str = Query(...)):
    reader_ok(reader)
    return view(reader, sid)


class Propose(BaseModel):
    sid: str
    reader: str
    requirement: str


@app.post("/api/propose")
def propose(b: Propose):
    """propose_mapping: the only model call in the checks path. Titles and short descriptions only."""
    reader_ok(b.reader)
    ov = sandbox(b.sid)
    res = engine.run(b.reader, ov)
    req = next((r for r in res["requirements"] if r["id"] == b.requirement), None)
    if req is None:
        raise HTTPException(404, "That requirement isn't in this pack.")
    if req["covered"]:
        raise HTTPException(409, "That requirement already has evidence; propose_mapping runs only for unmapped requirements.")
    m = model()
    if m is None:
        raise HTTPException(503, "No model key on this deployment, so propose_mapping is off.")
    if store.used("propose") >= PROPOSALS_PER_DAY:
        raise HTTPException(429, f"The public sandbox has used its {PROPOSALS_PER_DAY} proposals for today. Try again tomorrow.")
    store.take("propose")
    rt = corpus.topics.get(req.get("topic") or "")
    req = dict(req, shortdesc=rt.shortdesc if rt else "")
    try:
        p = propose_mapping(req, res["candidates"], m)
    except Exception as e:
        raise HTTPException(502, f"The model call failed: {type(e).__name__}. Nothing was changed.")
    ov["links"] = [l for l in ov["links"] if not (l["requirement"] == b.requirement and l["status"] == "pending")]
    if p["outcome"] == "proposal":
        ov["links"].append({"requirement": b.requirement, "topic": p["candidate"], "status": "pending", "proposal": p})
    else:
        ov.setdefault("gap_notes", {})[b.requirement] = p
    store.put(b.sid, ov)
    return {"proposal": p, "run": view(b.reader, b.sid, ov)}


class LinkAct(BaseModel):
    sid: str
    reader: str
    requirement: str
    topic: str
    status: str = Field(pattern="^(approved|rejected)$")


@app.post("/api/link")
def link(b: LinkAct):
    """The visitor reviews a proposed link as the information architect."""
    reader_ok(b.reader)
    ov = sandbox(b.sid)
    hit = next((l for l in ov["links"] if l["requirement"] == b.requirement and l["topic"] == b.topic), None)
    if hit is None:
        raise HTTPException(404, "No proposal for that requirement and topic in this sandbox.")
    hit["status"] = b.status
    hit["reviewed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    store.put(b.sid, ov)
    return view(b.reader, b.sid, ov)


class Decision(BaseModel):
    sid: str
    reader: str
    findings: list[str] = Field(min_length=1, max_length=60)
    choice: str = Field(pattern="^(release-with-gap|hold|clear)$")
    reason: str = Field(default="", max_length=300)


@app.post("/api/decision")
def decision(b: Decision):
    """The visitor records a decision as the compliance lead. A leak can't be decided: it must be fixed."""
    reader_ok(b.reader)
    ov = sandbox(b.sid)
    res = engine.run(b.reader, ov)
    decidable = {f["id"] for f in res["findings"] if f.get("decidable")}
    if b.choice != "clear" and len(b.reason.strip()) < 5:
        raise HTTPException(400, "Give a reason: a recorded gap needs one.")
    bad = [f for f in b.findings if f not in decidable]
    if bad:
        raise HTTPException(409, "These can't take a decision (a leak or an unresolved key must be fixed in the source): "
                                 + ", ".join(bad))
    for f in b.findings:
        if b.choice == "clear":
            ov["decisions"].pop(f, None)
        else:
            ov["decisions"][f] = {"choice": b.choice, "reason": b.reason.strip(), "by": "visitor as compliance lead (sandbox)",
                                  "date": time.strftime("%Y-%m-%d", time.gmtime())}
    store.put(b.sid, ov)
    return view(b.reader, b.sid, ov)


class Leak(BaseModel):
    sid: str
    reader: str
    topic: str | None = None
    key: str | None = None


@app.post("/api/leak")
def leak(b: Leak):
    """The leak test: put an authority-only key reference into an evidence topic, in the sandbox only."""
    reader_ok(b.reader)
    ov = sandbox(b.sid)
    if b.topic is None:
        ov["leak"] = None
    else:
        if b.topic not in corpus.topics or b.key not in corpus.authority_keys():
            raise HTTPException(400, "Pick a Gemma 4 evidence topic and an authority-only key.")
        ov["leak"] = {"topic": b.topic, "key": b.key}
    store.put(b.sid, ov)
    return view(b.reader, b.sid, ov)


class ModelUpdate(BaseModel):
    sid: str
    reader: str
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


@app.post("/api/model-update")
def model_update(b: ModelUpdate):
    reader_ok(b.reader)
    ov = sandbox(b.sid)
    ov["model_update"] = b.date
    store.put(b.sid, ov)
    return view(b.reader, b.sid, ov)


@app.delete("/api/sandbox")
def reset(sid: str = Query(...), reader: str = Query("authority")):
    sandbox(sid)
    store.delete(sid)
    return view(reader, sid, empty_overlay())


@app.get("/api/pack")
def pack(reader: str = Query(...), sid: str = Query(...)):
    """build_pack in the sandbox: DITA-OT output from CI, the manifest, the coverage report and SHA-256 hashes."""
    reader_ok(reader)
    res = engine.run(reader, sandbox(sid))
    if res["status"] == "blocked":
        why = "; ".join(f["reason"] for f in res["findings"] if not f.get("decidable"))
        raise HTTPException(409, "Release blocked: " + why)
    pid = pack_id(reader, sid)
    data, man = engine.build_zip(res, pid, sandbox=True)
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{pid}.zip"', "X-Aegis-Manifest-Sha256": man["manifest_sha256"]})


@app.get("/api/register")
def register():
    return {"store": store.backend, "packs": store.register()}


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/api/ask")
def ask(b: Ask):
    now = time.time()
    with _lock:
        while _recent and now - _recent[0] > 60:
            _recent.popleft()
        if len(_recent) >= ASKS_PER_MINUTE:
            raise HTTPException(429, "Too many questions this minute. Try again shortly.")
        _recent.append(now)
    m = None
    if has_key() and store.used("ask") < ASKS_PER_DAY:
        store.take("ask")
        m = model()
    out = asker.ask(b.question, m)
    out["legal"] = LEGAL
    if has_key() and m is None:
        out["model"]["error"] = f"Daily limit of {ASKS_PER_DAY} model answers reached; this answer is extractive."
    return out
