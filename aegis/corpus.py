"""Read the Gemma evidence set in dita-corpus: topics, keys, the requirement map and its relationship table.

Nothing here calls a model. Every fact carries the file and line it was read from, so a check result or an answer
can point a reader at the source.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
CORPUS = Path(os.environ.get("AEGIS_CORPUS", ROOT / "corpus"))
PACKS = Path(os.environ.get("AEGIS_PACKS", ROOT / "packs"))
SET = "gemma"
REPO = "https://github.com/siddharthraop/dita-corpus"

_PARSER = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, remove_comments=False)
NUMBER = re.compile(r"\d[\d,.]*\s*(?:[KMB]\b|%|B\b)?")


def parse(path: Path):
    return etree.parse(str(path), _PARSER)


@dataclass
class Key:
    name: str
    value: str
    file: str
    line: int
    audience: str | None = None


@dataclass
class KeyRef:
    key: str
    line: int
    element: str


@dataclass
class Topic:
    id: str
    file: str
    kind: str                     # requirement | evidence
    title: str
    shortdesc: str
    audience: str | None          # requirement topics: the pack they belong to
    product: str | None           # evidence topics: the model version they describe
    created: str | None
    revised: str | None
    source: dict | None
    subject: str | None = None
    requirement_id: str | None = None
    framework: str | None = None
    legal_source: str | None = None
    keyrefs: list[KeyRef] = field(default_factory=list)
    literals: list[str] = field(default_factory=list)     # numbers written as text, not resolved from a key
    paragraphs: list[dict] = field(default_factory=list)  # {"text", "line"} with keys resolved
    raw: bytes = b""

    @property
    def url(self) -> str:
        return f"{REPO}/blob/main/{self.file}"

    def text(self) -> str:
        return "\n".join(p["text"] for p in self.paragraphs)

    def brief(self) -> dict:
        return {"id": self.id, "title": self.title, "file": self.file, "kind": self.kind, "url": self.url}


@dataclass
class Link:
    """One evidence topicref in a relationship table cell."""
    requirement: str               # requirement id, e.g. aia.xi-2d
    topic: str                     # evidence topic id
    product: str | None
    coverage: str | None           # stated | partly | linked | conflicting
    line: int
    source: str = "reltable"       # reltable | sandbox
    proposal: dict | None = None


@dataclass
class Row:
    requirement: str
    requirement_topic: str
    audience: str | None
    line: int
    links: list[Link]


class Corpus:
    def __init__(self, root: Path = CORPUS, packs: Path = PACKS):
        self.root = root
        self.packs = packs
        self.base = root / SET
        self.keys: dict[str, Key] = {}
        self.topics: dict[str, Topic] = {}
        self.by_file: dict[str, Topic] = {}
        self.rows: list[Row] = []
        self.map_file = f"{SET}/gemma.ditamap"
        self.commit = os.environ.get("AEGIS_CORPUS_COMMIT") or _git_head(root)
        self._load_keys(self.base / "keys" / "gemma-keys.ditamap")
        self._load_keys(packs / "authority-keys.ditamap", default_audience=None, fixture=True)
        for sub in ("requirements", "evidence"):
            for f in sorted((self.base / sub).glob("*.dita")):
                t = self._load_topic(f, "requirement" if sub == "requirements" else "evidence")
                self.topics[t.id] = t
                self.by_file[t.file] = t
        self._load_reltable(self.base / "gemma.ditamap")
        self.models = yaml.safe_load((packs / "models.yaml").read_text(encoding="utf-8"))["models"]
        self.card_sections = yaml.safe_load((packs / "model-card-sections.yaml").read_text(encoding="utf-8"))

    # -- keys --------------------------------------------------------------------------------------------------
    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return "packs/" + path.name

    def _load_keys(self, path: Path, default_audience=None, fixture=False):
        if not path.exists():
            return
        for kd in parse(path).getroot().iter("keydef"):
            kw = kd.find(".//keyword")
            value = "".join(kw.itertext()).strip() if kw is not None else ""
            for name in (kd.get("keys") or "").split():
                self.keys[name] = Key(name, value, self._rel(path), kd.sourceline, kd.get("audience") or default_audience)

    def authority_keys(self) -> set[str]:
        return {k for k, v in self.keys.items() if v.audience == "authority"}

    # -- topics ------------------------------------------------------------------------------------------------
    def resolve(self, el) -> str:
        """Text of an element with keyrefs resolved to their key values."""
        out = [el.text or ""] if not isinstance(el, etree._Comment) else []
        for child in el:
            if isinstance(child, etree._Comment):
                pass
            elif child.get("keyref") and child.get("keyref") in self.keys and not len(child) and not (child.text or "").strip():
                out.append(self.keys[child.get("keyref")].value)
            else:
                out.append(self.resolve(child))
            out.append(child.tail or "")
        return re.sub(r"\s+", " ", "".join(out)).strip()

    def _literals(self, el) -> list[str]:
        """Numbers written into the text itself, outside any keyref."""
        found = []
        def walk(e):
            if e.get("keyref"):
                if e.tail:
                    found.extend(NUMBER.findall(e.tail))
                return
            if e.text and not isinstance(e, etree._Comment):
                found.extend(NUMBER.findall(e.text))
            for c in e:
                walk(c)
            if e is not el and e.tail and not isinstance(e, etree._Comment):
                found.extend(NUMBER.findall(e.tail))
        for c in el:
            walk(c)
        return [n.strip().rstrip(".,") for n in found if n.strip().rstrip(".,")]

    def _load_topic(self, path: Path, kind: str) -> Topic:
        tree = parse(path)
        r = tree.getroot()
        rel = self._rel(path)

        def data(name, attr="value"):
            d = r.find(f"prolog/data[@name='{name}']")
            return d.get(attr) if d is not None else None

        crit = r.find("prolog/critdates")
        created = crit.find("created").get("date") if crit is not None and crit.find("created") is not None else None
        revised = crit.find("revised").get("modified") if crit is not None and crit.find("revised") is not None else None
        aud = r.find("prolog/metadata/audience")
        src = r.find("prolog/data[@name='source']")
        legal = None
        for prop in r.iter("property"):
            if (prop.findtext("proptype") or "").strip() == "Legal source":
                legal = self.resolve(prop.find("propvalue"))
        body = r.find("conbody") if r.find("conbody") is not None else r.find("refbody")
        paragraphs = []
        if body is not None:
            for el in body.iter("p", "property", "li", "row", "strow", "sthead"):
                if el.tag == "property":
                    txt = f"{self.resolve(el.find('proptype'))}: {self.resolve(el.find('propvalue'))}"
                elif el.tag in ("row", "strow", "sthead"):
                    txt = " | ".join(self.resolve(e) for e in el if e.tag in ("entry", "stentry"))
                elif el.getparent() is not None and el.getparent().tag in ("li", "entry", "stentry"):
                    continue
                else:
                    txt = self.resolve(el)
                if txt:
                    paragraphs.append({"text": txt, "line": el.sourceline})
        keyrefs = [KeyRef(e.get("keyref"), e.sourceline, e.tag) for e in r.iter() if isinstance(e.tag, str) and e.get("keyref")]
        return Topic(
            id=r.get("id"), file=rel, kind=kind,
            title=self.resolve(r.find("title")), shortdesc=self.resolve(r.find("shortdesc")) if r.find("shortdesc") is not None else "",
            audience=(aud.get("type") if aud is not None else None) or r.get("audience"),
            product=data("model-version") or r.get("product"),
            created=created, revised=revised,
            source={"name": src.get("value"), "href": src.get("href")} if src is not None else None,
            subject=data("evidence-subject"), requirement_id=data("requirement-id"), framework=data("framework"),
            legal_source=legal, keyrefs=keyrefs, literals=self._literals(body) if body is not None else [],
            paragraphs=paragraphs, raw=path.read_bytes())

    def requirement(self, rid: str) -> Topic | None:
        return next((t for t in self.topics.values() if t.requirement_id == rid), None)

    # -- the trace ---------------------------------------------------------------------------------------------
    def _load_reltable(self, path: Path):
        r = parse(path).getroot()
        for row in r.iter("relrow"):
            cells = row.findall("relcell")
            if not cells:
                continue
            req_ref = cells[0].find("topicref")
            if req_ref is None:
                continue
            req_topic = self.by_file.get(f"{SET}/{req_ref.get('href')}")
            if req_topic is None:
                continue
            links = []
            for cell in cells[1:]:
                for tr in cell.findall("topicref"):
                    ev = self.by_file.get(f"{SET}/{tr.get('href')}")
                    if ev is None:
                        continue
                    cov = tr.find("topicmeta/data[@name='coverage']")
                    links.append(Link(req_topic.requirement_id, ev.id, tr.get("product"),
                                      cov.get("value") if cov is not None else None, tr.sourceline))
            self.rows.append(Row(req_topic.requirement_id, req_topic.id, req_ref.get("audience") or req_topic.audience,
                                 row.sourceline, links))

    def conflicting(self) -> dict[str, Link]:
        """Evidence topics the trace marks as stating something two different ways."""
        out = {}
        for row in self.rows:
            for l in row.links:
                if l.coverage == "conflicting":
                    out.setdefault(l.topic, l)
        return out

    def evidence_for(self, topic_id: str) -> list[dict]:
        """Requirements this evidence topic answers, from the trace."""
        out = []
        for row in self.rows:
            for l in row.links:
                if l.topic == topic_id:
                    out.append({"requirement": row.requirement, "coverage": l.coverage, "line": l.line,
                                "title": self.topics[row.requirement_topic].title})
        return out

    def stats(self) -> dict:
        return {"commit": self.commit, "topics": len(self.topics),
                "requirements": sum(t.kind == "requirement" for t in self.topics.values()),
                "evidence": sum(t.kind == "evidence" for t in self.topics.values()),
                "rows": len(self.rows), "keys": len(self.keys)}


def _git_head(root: Path) -> str:
    try:
        git = root / ".git"
        if git.is_file():  # submodule: "gitdir: ../.git/modules/corpus"
            git = (root / git.read_text().split(":", 1)[1].strip()).resolve()
        head = (git / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            ref = git / head.split(" ", 1)[1]
            if ref.exists():
                return ref.read_text().strip()[:12]
            packed = git / "packed-refs"
            for line in packed.read_text().splitlines() if packed.exists() else []:
                if line.endswith(head.split(" ", 1)[1]):
                    return line.split()[0][:12]
        return head[:12]
    except Exception:
        return "unknown"


@lru_cache(maxsize=1)
def load() -> Corpus:
    return Corpus()
