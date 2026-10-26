"""propose_mapping with a scripted model, the sandbox API end to end, the pack download, and the Ask path."""
import hashlib
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from aegis.model import Scripted, propose_mapping

REQ = {"id": "aia.xi-2d", "title": "Training compute", "full_title": "Annex XI 2(d): Training compute",
       "legal_source": "Annex XI 2(d)", "shortdesc": "The computational resources used to train the model."}
CANDS = [{"id": "gemma4-training-data", "title": "Gemma 4: Training data", "shortdesc": "Training data for Gemma 4."},
         {"id": "gemma4-overview", "title": "Gemma 4: Model overview", "shortdesc": "Overview for Gemma 4."}]


def test_proposal_inside_the_schema():
    m = Scripted({"requirement": "aia.xi-2d", "candidate": "gemma4-overview", "reason": "r", "confidence": 0.8})
    p = propose_mapping(REQ, CANDS, m)
    assert p["outcome"] == "proposal" and p["candidate"] == "gemma4-overview"
    assert p["sent"]["topic_bodies"] == 0


def test_invented_topic_id_becomes_a_gap_note():
    m = Scripted({"requirement": "aia.xi-2d", "candidate": "gemma4-training-compute", "reason": "r", "confidence": 0.9})
    assert propose_mapping(REQ, CANDS, m)["outcome"] == "gap-note"


def test_low_confidence_and_none_become_gap_notes():
    low = Scripted({"requirement": "aia.xi-2d", "candidate": "gemma4-training-data", "reason": "r", "confidence": 0.4})
    assert propose_mapping(REQ, CANDS, low)["outcome"] == "gap-note"
    none = Scripted({"requirement": "aia.xi-2d", "candidate": "none", "reason": "r", "confidence": 0.9, "gap_note": "No compute."})
    p = propose_mapping(REQ, CANDS, none)
    assert p["outcome"] == "gap-note" and p["gap_note"] == "No compute."


def test_the_prompt_carries_titles_not_topic_bodies():
    from aegis.corpus import load
    c = load()
    cands = [{"id": t.id, "title": t.title, "shortdesc": t.shortdesc} for t in c.topics.values() if t.product == "gemma-4"]
    m = Scripted({"requirement": "aia.xi-2d", "candidate": "none", "reason": "r", "confidence": 0.1})
    propose_mapping(REQ, cands, m)
    body = c.topics["gemma4-overview"].paragraphs[0]["text"]
    assert body[:40] not in m.prompts[0]


@pytest.fixture()
def client(monkeypatch):
    import api.main as main
    main.store.mem.clear()
    main.store.count.clear()
    return TestClient(main.app), main


SID = "test-session-0000000001"


def test_sandbox_end_to_end(client, monkeypatch):
    c, main = client
    r = c.get("/api/run", params={"reader": "authority", "sid": SID}).json()
    assert r["summary"]["covered"] == 8 and "legal" in r
    # 1. propose a link (scripted model), approve it, rerun
    monkeypatch.setattr(main, "has_key", lambda: True)
    monkeypatch.setattr(main, "model", lambda: Scripted(
        {"requirement": "aia.xi-2d", "candidate": "gemma4-training-data", "reason": "test", "confidence": 0.75}))
    p = c.post("/api/propose", json={"sid": SID, "reader": "authority", "requirement": "aia.xi-2d"}).json()
    assert p["proposal"]["outcome"] == "proposal"
    assert p["run"]["summary"]["covered"] == 8            # pending does not count
    r = c.post("/api/link", json={"sid": SID, "reader": "authority", "requirement": "aia.xi-2d",
                                  "topic": "gemma4-training-data", "status": "approved"}).json()
    assert r["summary"]["covered"] == 9
    # a covered requirement can't be proposed again
    assert c.post("/api/propose", json={"sid": SID, "reader": "authority", "requirement": "aia.xi-2d"}).status_code == 409
    # 2. record a decision for a gap
    bad = c.post("/api/decision", json={"sid": SID, "reader": "authority", "findings": ["coverage:aia.xi-2e"],
                                        "choice": "release-with-gap", "reason": ""})
    assert bad.status_code == 400
    r = c.post("/api/decision", json={"sid": SID, "reader": "authority", "findings": ["coverage:aia.xi-2e"],
                                      "choice": "release-with-gap", "reason": "Energy estimate due with next release"}).json()
    f = next(x for x in r["findings"] if x["id"] == "coverage:aia.xi-2e")
    assert f["decision"]["reason"].startswith("Energy")
    # 4. build and download: hashes match the files
    z = c.get("/api/pack", params={"reader": "authority", "sid": SID})
    assert z.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    names = zf.namelist()
    root = names[0].split("/")[0]
    man = json.loads(zf.read(f"{root}/manifest.json"))
    assert man["sandbox"] is True and man["source"]["profile"] == "gemma/filters/authority.ditaval"
    for line in zf.read(f"{root}/SHA256SUMS").decode().splitlines():
        digest, path = line.split("  ", 1)
        assert hashlib.sha256(zf.read(f"{root}/{path}")).hexdigest() == digest
    item = next(i for i in man["items"] if i["req"] == "aia.xi-2d")
    assert item["link"]["proposed_by"] == "propose_mapping"
    assert z.headers["x-aegis-manifest-sha256"] == hashlib.sha256(zf.read(f"{root}/manifest.json")).hexdigest()


def test_leak_blocks_the_download(client):
    c, _ = client
    c.post("/api/leak", json={"sid": SID, "reader": "public", "topic": "gemma4-training-data", "key": "gemma-4-train-compute"})
    r = c.get("/api/pack", params={"reader": "public", "sid": SID})
    assert r.status_code == 409 and "Leak" in r.json()["detail"]
    d = c.post("/api/decision", json={"sid": SID, "reader": "public",
                                      "findings": ["leak:gemma4-training-data:gemma-4-train-compute"],
                                      "choice": "release-with-gap", "reason": "try to override"})
    assert d.status_code == 409
    c.post("/api/leak", json={"sid": SID, "reader": "public"})
    assert c.get("/api/pack", params={"reader": "public", "sid": SID}).status_code == 200


def test_propose_without_a_key_is_off(client):
    c, _ = client
    assert c.post("/api/propose", json={"sid": SID, "reader": "authority", "requirement": "aia.xi-2d"}).status_code == 503


def test_daily_proposal_cap(client, monkeypatch):
    c, main = client
    monkeypatch.setattr(main, "has_key", lambda: True)
    monkeypatch.setattr(main, "PROPOSALS_PER_DAY", 1)
    monkeypatch.setattr(main, "model", lambda: Scripted({"requirement": "aia.xi-1c", "candidate": "none", "reason": "r", "confidence": 0.1}))
    assert c.post("/api/propose", json={"sid": SID, "reader": "authority", "requirement": "aia.xi-1c"}).status_code == 200
    assert c.post("/api/propose", json={"sid": SID, "reader": "authority", "requirement": "aia.xi-2e"}).status_code == 429


def test_bad_sandbox_id(client):
    c, _ = client
    assert c.get("/api/run", params={"reader": "authority", "sid": "../x"}).status_code == 400


# -- Ask ---------------------------------------------------------------------------------------------------------
def test_ask_extractive_cites_topic_commit_and_trace(client):
    c, _ = client
    r = c.post("/api/ask", json={"question": "What does Annex XI 2(d) ask for, and is it documented for Gemma 4?"}).json()
    assert r["retrieved"][0] == "aia-xi-2d"
    src = next(s for s in r["sources"] if s["id"] == "aia-xi-2d") if any(s["id"] == "aia-xi-2d" for s in r["sources"]) else None
    assert src is not None and "commit" in src and "linked_evidence" in src
    assert "legal" in r


def test_ask_drops_a_point_whose_quote_or_number_is_not_in_the_source():
    from aegis.approvals import Approvals
    from aegis.ask import Asker
    from aegis.corpus import load
    a = Asker(load(), Approvals())
    m = Scripted({"summary": "s", "not_covered": "", "points": [
        {"text": "Gemma 3 was trained on 14 trillion tokens at 27B.", "topic": "gemma3-training-data",
         "quote": "27B | 14 trillion 12B | 12 trillion"},
        {"text": "Gemma 3 was trained on 99 trillion tokens.", "topic": "gemma3-training-data", "quote": "2 trillion Knowledge cutoff: August 2024."},
        {"text": "Made up.", "topic": "gemma3-training-data", "quote": "this sentence does not appear anywhere in it"}]})
    m.name, m.id = "scripted", "scripted"
    r = a.ask("How many tokens was Gemma 3 trained on?", m)
    assert [p["text"] for p in r["points"]] == ["Gemma 3 was trained on 14 trillion tokens at 27B."]
    reasons = [d["why"] for d in r["dropped"]]
    assert any("99" in w for w in reasons) and any("word for word" in w for w in reasons)
