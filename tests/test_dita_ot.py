"""When DITA-OT output exists (CI builds it before the image), the topics it kept per profile equal the topics the
Python DITAVAL evaluation keeps. This is what lets the API run the checks without Java."""
from pathlib import Path

import pytest

from aegis.approvals import Approvals
from aegis.corpus import load
from aegis.engine import BUILDS, Engine


@pytest.mark.parametrize("reader", ["authority", "downstream", "public"])
def test_python_profile_matches_dita_ot(reader):
    html = BUILDS / reader / "html"
    if not html.exists():
        pytest.skip("no DITA-OT output in this environment")
    built = {p.stem for p in html.rglob("*.html") if p.parent != html}
    res = Engine(load(), Approvals()).run(reader)
    assert built == set(res["built_topics"])


def test_cli_release_refuses_a_blocked_pack(tmp_path, monkeypatch):
    from aegis import cli
    assert cli.main(["check", "--reader", "public", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "summary.md").read_text().count("check_") == 4
