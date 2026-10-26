"""Each check, on the real Gemma source in dita-corpus, with a fixed approval index."""
import copy

import pytest

from aegis.approvals import Approvals, codeowners_for
from aegis.corpus import load
from aegis.ditaval import Profile
from aegis.engine import Engine, empty_overlay


@pytest.fixture(scope="module")
def eng():
    return Engine(load(), Approvals())


def ids(res, check):
    return sorted(f["id"] for f in res["findings"] if f["check"] == check)


# -- profiles ----------------------------------------------------------------------------------------------------
def test_profiles_filter_like_dita_ot(eng):
    auth = eng.profile("authority")
    pub = eng.profile("public")
    assert auth.keeps({"audience": "authority", "product": "gemma-4"})
    assert not auth.keeps({"audience": "downstream"})
    assert not auth.keeps({"product": "gemma-3"})
    assert auth.keeps({"audience": None, "product": None})
    assert not pub.keeps({"audience": "authority"}) and not pub.keeps({"audience": "internal"})
    assert pub.keeps({"product": "gemma-4"}) and not pub.keeps({"product": "gemma-3"})


# -- check_coverage ----------------------------------------------------------------------------------------------
def test_coverage_finds_the_real_annex_xi_gaps(eng):
    res = eng.run("authority")
    cov = res["checks"][0]
    assert (cov["passed"], cov["total"]) == (8, 11)
    assert ids(res, "check_coverage") == ["coverage:aia.xi-1c", "coverage:aia.xi-2d", "coverage:aia.xi-2e"]


def test_coverage_downstream_and_public(eng):
    d = eng.run("downstream")
    assert ids(d, "check_coverage") == ["coverage:aia.xii-1c", "coverage:aia.xii-1e"]
    p = eng.run("public")
    assert p["checks"][0]["passed"] == p["checks"][0]["total"] == 11


def test_gemma3_evidence_never_counts_for_gemma4(eng):
    # 2(d) has Gemma 3 evidence (hardware) in the trace, but the authority profile keeps only gemma-4.
    res = eng.run("authority")
    item = next(r for r in res["requirements"] if r["id"] == "aia.xi-2d")
    assert not item["covered"] and item["evidence"] == []


def test_sandbox_link_covers_a_requirement_and_is_labelled(eng):
    ov = empty_overlay()
    ov["links"].append({"requirement": "aia.xi-2d", "topic": "gemma4-training-data", "status": "approved",
                        "proposal": {"confidence": 0.7, "reason": "test"}})
    res = eng.run("authority", ov)
    assert res["checks"][0]["passed"] == 9
    item = next(r for r in res["requirements"] if r["id"] == "aia.xi-2d")
    assert item["evidence"][0]["link"]["source"] == "sandbox"
    assert res["checks"][2]["sandbox_links"][0]["approved_by"].endswith("(sandbox)")
    # A pending or rejected proposal never counts.
    for status in ("pending", "rejected"):
        ov2 = copy.deepcopy(ov)
        ov2["links"][0]["status"] = status
        assert eng.run("authority", ov2)["checks"][0]["passed"] == 8


# -- check_currency ----------------------------------------------------------------------------------------------
def test_currency_passes_at_the_version_date(eng):
    assert eng.run("authority")["checks"][1]["ok"]


def test_model_update_makes_topics_with_literal_values_stale(eng):
    ov = empty_overlay()
    ov["model_update"] = "2026-07-15"
    res = eng.run("authority", ov)
    stale = ids(res, "check_currency")
    assert "currency:gemma4-overview" in stale        # revised 2026-07-08, states 2B, 4B, 12B ... as text
    assert "currency:gemma4-licence" not in stale      # revised 2026-07-30


def test_key_only_topic_cleared_by_an_approved_key_change(eng):
    # gemma4-licence holds only key references. After a model update past its revised date, it is still current
    # when the key map changed in an approved commit after that date (the fixture approves it on 2026-10-26).
    ov = empty_overlay()
    ov["model_update"] = "2026-08-15"
    res = eng.run("authority", ov)
    assert "currency:gemma4-licence" not in ids(res, "check_currency")
    assert any(n["topic"] == "gemma4-licence" for n in res["checks"][1]["cleared_by_rule"])
    assert "currency:gemma4-overview" in ids(res, "check_currency")


# -- check_approval ----------------------------------------------------------------------------------------------
def test_approval_needs_a_code_owner_who_is_not_the_author_or_the_agent():
    ap = Approvals()
    assert ap.verdict("gemma/evidence/gemma4-licence.dita")["ok"]
    direct = ap.verdict("gemma/evidence/gemma3-safety.dita")
    assert not direct["ok"] and "directly" in direct["reason"]
    assert not ap.verdict("gemma/evidence/gemma3-limitations.dita")["ok"]     # self-approval
    assert not ap.verdict("gemma/evidence/gemma3-evaluation.dita")["ok"]      # approved only by the bot


def test_approval_rejects_a_reviewer_who_is_not_a_code_owner():
    data = {"codeowners": [["/gemma/", "@siddharthraop"]], "files": {"gemma/x.dita": {
        "commit": "a", "date": "2026-10-26", "via": "pull-request", "pr": 9, "pr_url": None,
        "pr_author": "github-actions[bot]", "approvers": [{"login": "someone-else", "name": "X", "at": ""}]}}}
    assert not Approvals(data=data).verdict("gemma/x.dita")["ok"]


def test_no_index_means_not_approved(eng):
    res = Engine(eng.corpus, Approvals(data={})).run("public")
    assert res["checks"][2]["passed"] == 0 and res["status"] == "needs-decisions"


def test_codeowners_last_match_wins():
    rules = [["*", "@a"], ["/gemma/", "@b"]]
    assert codeowners_for("gemma/evidence/x.dita", rules) == ["b"]
    assert codeowners_for("tpu/x.dita", rules) == ["a"]


# -- check_consistency -------------------------------------------------------------------------------------------
def test_conflicting_licence_statements_are_caught(eng):
    for reader in ("authority", "downstream", "public"):
        assert "conflict:gemma4-licence" in ids(eng.run(reader), "check_consistency")


def test_leak_test_blocks_public_and_downstream_but_not_authority(eng):
    ov = empty_overlay()
    ov["leak"] = {"topic": "gemma4-training-data", "key": "gemma-4-train-compute"}
    for reader in ("public", "downstream"):
        res = eng.run(reader, ov)
        leaks = [f for f in res["findings"] if f.get("kind") == "leak"]
        assert leaks and not leaks[0]["decidable"]
        assert res["status"] == "blocked"
    auth = eng.run("authority", ov)
    assert not [f for f in auth["findings"] if f.get("kind") == "leak"]
    assert auth["status"] != "blocked"


def test_a_decision_cannot_release_a_leak(eng):
    ov = empty_overlay()
    ov["leak"] = {"topic": "gemma4-training-data", "key": "gemma-4-train-compute"}
    ov["decisions"] = {"leak:gemma4-training-data:gemma-4-train-compute": {"choice": "release-with-gap", "reason": "x"}}
    assert eng.run("public", ov)["status"] == "blocked"


def test_authority_keys_resolve_nowhere_in_the_real_source(eng):
    auth = eng.corpus.authority_keys()
    assert auth
    assert not any(r.key in auth for t in eng.corpus.topics.values() for r in t.keyrefs)


# -- status and decisions ----------------------------------------------------------------------------------------
def test_recording_every_decision_makes_the_pack_releasable(eng):
    res = eng.run("authority")
    assert res["status"] == "needs-decisions"
    ov = empty_overlay()
    ov["decisions"] = {f["id"]: {"choice": "release-with-gap", "reason": "recorded in test"} for f in res["findings"]}
    assert eng.run("authority", ov)["status"] == "ready-with-recorded-gaps"
