"""DITAVAL profiles, evaluated the way DITA-OT filters content.

An element is excluded when every value of a filtered attribute is excluded, either by a rule for that value or by
the attribute's default rule (a <prop> with @att and no @val). Values with no rule and no default are included.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree


@dataclass
class Profile:
    name: str
    file: str
    rules: dict[str, dict[str | None, str]] = field(default_factory=dict)

    @classmethod
    def load(cls, name: str, path: Path, root: Path | None = None) -> "Profile":
        tree = etree.parse(str(path))
        rules: dict[str, dict[str | None, str]] = {}
        for p in tree.getroot().iter("prop"):
            att = p.get("att")
            if not att:
                continue
            rules.setdefault(att, {})[p.get("val")] = p.get("action", "include")
        rel = str(path.relative_to(root)) if root else path.name
        return cls(name=name, file=rel, rules=rules)

    def value_excluded(self, att: str, value: str) -> bool:
        r = self.rules.get(att)
        if not r:
            return False
        return r.get(value, r.get(None, "include")) == "exclude"

    def keeps(self, attrs: dict[str, str | None]) -> bool:
        """True when an element with these attribute values survives the profile."""
        for att, raw in attrs.items():
            values = (raw or "").split()
            if values and all(self.value_excluded(att, v) for v in values):
                return False
        return True

    def includes_audience(self, audience: str) -> bool:
        return not self.value_excluded("audience", audience)
