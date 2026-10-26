"""The only model calls: propose_mapping (a link for an unmapped requirement) and the Ask page's composer.

Gemini gets requirement text and candidate titles and short descriptions, never topic bodies, for propose_mapping.
The schema is built per call, so the candidate must be a topic id that exists in this pack, or "none".
"""
from __future__ import annotations

import json
import os
import re
import time

MIN_CONFIDENCE = 0.6

PROPOSE = """You help an information architect link a regulatory requirement to the documentation topic that answers it.
You get one requirement and a list of candidate topics (id, title, short description). Pick the one candidate whose
title and description show that it states the information the requirement asks for, or "none" if no candidate does.
Don't guess from a loosely related subject: a topic about training data doesn't state training compute.
Return JSON only, matching the schema. "reason" is one or two plain sentences. "confidence" is 0 to 1.
If you return "none", write a "gap_note" that says what information is missing, for the topic owner."""

ASK = """You answer questions about a sample set of model documentation used as regulatory evidence (Gemma model cards,
EU AI Act Annex XI and XII requirement topics, NIST AI RMF subcategories). Use ONLY the topics provided.

Return JSON: {"summary": str, "points": [{"text": str, "topic": str, "quote": str}], "not_covered": str}

Rules:
- 1 to 4 points that answer the question. Each point is one or two plain sentences.
- "topic" is a topic id from the input. "quote" is an exact, contiguous passage of at least 6 words copied character
  for character from that topic's text that supports the point.
- Every number, version and named value in a point must appear in the cited topic's text.
- If the topics show the information is missing (a requirement with no evidence), say so plainly; that is an answer.
- "summary" is one sentence. "not_covered" says briefly what the question asks that the topics don't state.
- This is documentation, not legal advice. Don't say whether an obligation applies."""


def _clean_key():
    for var in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        raw = os.environ.get(var, "")
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        if lines and (len(lines) > 1 or lines[0] != raw):
            os.environ[var] = next((l for l in lines if re.fullmatch(r"(AIza[\w-]{30,}|AQ\.[\w.-]{20,})", l)), lines[0])


def has_key() -> bool:
    return bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))


def _json(text: str):
    text = (text or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


def mapping_schema(requirement: str, candidate_ids: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False,
            "required": ["requirement", "candidate", "reason", "confidence"],
            "properties": {"requirement": {"type": "string", "enum": [requirement]},
                           "candidate": {"type": "string", "enum": candidate_ids + ["none"]},
                           "reason": {"type": "string", "maxLength": 300},
                           "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                           "gap_note": {"type": "string", "maxLength": 400}}}


class Gemini:
    name = "gemini"

    def __init__(self, model_id: str | None = None):
        _clean_key()
        from google import genai
        from google.genai import types
        self.id = model_id or os.environ.get("AEGIS_MODEL", "gemini-3.8-flash")
        self.client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
        self.types = types
        self.tokens = {"input": 0, "output": 0}

    def generate(self, system: str, prompt: str, schema: dict | None = None):
        kw = dict(system_instruction=system, temperature=0.1, response_mime_type="application/json")
        if schema:
            kw["response_json_schema"] = schema
        try:
            cfg = self.types.GenerateContentConfig(**kw)
        except Exception:  # older SDKs: the schema is still enforced below
            kw.pop("response_json_schema", None)
            cfg = self.types.GenerateContentConfig(**kw)
        r = self.client.models.generate_content(model=self.id, contents=prompt, config=cfg)
        um = getattr(r, "usage_metadata", None)
        if um:
            self.tokens["input"] += um.prompt_token_count or 0
            self.tokens["output"] += um.candidates_token_count or 0
        return _json(r.text)


class Scripted:
    """Replays fixed responses. Tests use it to prove what the code does with a model's answer."""
    name = "scripted"
    id = "scripted"

    def __init__(self, *responses: dict):
        self.responses = list(responses)
        self.tokens = {"input": 0, "output": 0}
        self.prompts: list[str] = []

    def generate(self, system, prompt, schema=None):
        self.prompts.append(prompt)
        return json.loads(json.dumps(self.responses.pop(0))) if self.responses else {}


def propose_mapping(requirement: dict, candidates: list[dict], model) -> dict:
    """Ask the model for one link. Anything outside the schema, or under the confidence floor, becomes a gap note."""
    ids = [c["id"] for c in candidates]
    schema = mapping_schema(requirement["id"], ids)
    prompt = json.dumps({"requirement": {"id": requirement["id"], "title": requirement.get("full_title") or requirement["title"],
                                         "legal_source": requirement.get("legal_source"),
                                         "asks_for": requirement.get("shortdesc", "")},
                         "candidates": [{k: c[k] for k in ("id", "title", "shortdesc")} for c in candidates]}, indent=1)
    t0 = time.time()
    raw = model.generate(PROPOSE, prompt, schema)
    out = {"requirement": requirement["id"], "model": getattr(model, "id", "?"), "ms": int((time.time() - t0) * 1000),
           "tokens": dict(model.tokens), "sent": {"requirement": True, "candidate_titles": len(ids), "topic_bodies": 0}}
    cand = raw.get("candidate")
    conf = raw.get("confidence")
    if raw.get("requirement") != requirement["id"] or cand not in ids + ["none"] or not isinstance(conf, (int, float)):
        return dict(out, outcome="gap-note", candidate=None, confidence=None, reason="The model's answer didn't match the schema.",
                    gap_note=f"No evidence topic is linked to {requirement['id']}, and the proposal was rejected by the schema check.")
    conf = max(0.0, min(1.0, float(conf)))
    if cand == "none" or conf < MIN_CONFIDENCE:
        note = raw.get("gap_note") or f"No candidate topic states what {requirement['id']} asks for."
        return dict(out, outcome="gap-note", candidate=None if cand == "none" else cand, confidence=conf,
                    reason=raw.get("reason", ""), gap_note=note,
                    rule=("model returned none" if cand == "none" else f"confidence {conf:.2f} is under {MIN_CONFIDENCE}"))
    return dict(out, outcome="proposal", candidate=cand, confidence=conf, reason=raw.get("reason", ""))
