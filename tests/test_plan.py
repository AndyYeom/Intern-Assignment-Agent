"""Tests for corpus status, collection planning and need-driven sampling."""
from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from generator.github import plan, sampler
from generator.github.assign import Assignment, Eligibility, Placement

STRATA = ["alpha", "beta", "gamma"]


def _cand(login: str, stratum: str, selected: bool = True) -> dict[str, Any]:
    return {"login": login, "stratum": stratum, "selected": selected}


def _assignment(filled: dict[str, list[str]], quota: int = 2) -> Assignment:
    placements, options = [], {}
    for stratum, tiers in filled.items():
        for i, tier in enumerate(tiers):
            applicant = f"{stratum}{i}"
            placements.append(Placement(applicant, applicant, stratum, tier, 2, 1.0))
            options[applicant] = [Eligibility(stratum, tier, 2, 1.0)]
    return Assignment(quota, STRATA, placements, options)


def _status(candidates=(), *, filled=None, collected=(), built=None) -> plan.CorpusStatus:
    collected = set(collected)
    return plan.compute_status(
        list(candidates), collected=collected,
        built=collected if built is None else set(built),
        assignment=_assignment(filled or {}), tiers={}, target=6, strata=STRATA,
    )


@pytest.mark.parametrize(("target", "strata", "quota"), [(40, 10, 4), (41, 10, 5), (3, 10, 1)])
def test_quota_rounds_up_so_the_target_is_always_covered(target, strata, quota):
    assert sampler.stratum_quota(target, strata) == quota


def test_rows_report_strict_relaxed_and_need():
    status = _status(filled={"alpha": ["strict", "relaxed"], "beta": ["relaxed"]})
    rows = {r.stratum: r for r in status.rows}
    assert (rows["alpha"].strict, rows["alpha"].relaxed, rows["alpha"].need) == (1, 1, 0)
    assert (rows["beta"].filled, rows["beta"].need) == (1, 1)
    assert rows["gamma"].need == 2


def test_queue_holds_selected_uncollected_candidates_by_search_stratum():
    status = _status(
        [_cand("a1", "alpha"), _cand("a2", "alpha"), _cand("org", "alpha", selected=False),
         _cand("b1", "beta"), _cand("gone", "retired-stratum")],
        collected={"a2"},
    )
    rows = {r.stratum: r for r in status.rows}
    assert rows["alpha"].pending == ["a1"]
    assert rows["beta"].pending == ["b1"]


def test_full_strata_queue_nothing_for_collection():
    """The old bug: surplus candidates of a full stratum must not be collected."""
    candidates = [_cand(f"a{i}", "alpha") for i in range(30)]
    status = _status(candidates, filled={"alpha": ["strict", "strict"]})
    assert status.to_collect == []


def test_without_history_fetch_assumes_a_fifty_percent_hit_rate():
    candidates = [_cand(f"g{i}", "gamma") for i in range(30)]
    status = _status(candidates, filled={"gamma": ["strict"]})   # need 1
    assert status.to_collect == ["g0", "g1"]


def test_a_weak_search_fetches_more_per_empty_slot():
    """Four collected via repo search, none eligible: fetch far more than need."""
    row = plan.StratumRow(stratum="go", quota=4, strict=1, hits=0, trials=4)
    assert row.need == 3
    assert row.hit_rate == pytest.approx(max(plan.MIN_HIT_RATE, 1 / 6))
    assert row.fetch == 18


def test_a_strong_search_fetches_about_what_it_needs():
    row = plan.StratumRow(stratum="py", quota=4, strict=2, hits=8, trials=8)
    assert row.fetch == 3   # ceil(2 / 0.9)


def test_fetch_is_capped_per_slot():
    row = plan.StratumRow(stratum="x", quota=4, hits=0, trials=500)
    assert row.fetch == 4 * plan.MAX_PER_SLOT


def test_hit_rate_counts_only_current_search_method():
    """Candidates from the old user search must not drag the new method's rate down."""
    old = {"login": "u1", "stratum": "gamma", "selected": True, "method": "users"}
    new = {"login": "u2", "stratum": "gamma", "selected": True,
           "method": sampler.SEARCH_METHOD}
    status = _status([old, new], collected={"u1", "u2"})
    gamma = next(r for r in status.rows if r.stratum == "gamma")
    assert gamma.trials == 1


def test_queue_prefers_candidates_from_the_current_search():
    old = {"login": "old", "stratum": "gamma", "selected": True, "method": "users"}
    new = {"login": "new", "stratum": "gamma", "selected": True,
           "method": sampler.SEARCH_METHOD}
    gamma = next(r for r in _status([old, new]).rows if r.stratum == "gamma")
    assert gamma.pending == ["new", "old"]


def test_wanted_is_fetch_minus_queue():
    status = _status([_cand("b1", "beta")], filled={"alpha": ["strict", "strict"]})
    rows = {r.stratum: r for r in status.rows}
    assert status.wanted == {"beta": rows["beta"].fetch - 1, "gamma": rows["gamma"].fetch}


def test_next_step_walks_the_pipeline():
    assert "gh build" in _status(collected={"x"}, built=set()).next_step()
    assert "gh sample" in _status().next_step()
    # A short queue still samples first, so one collect round fetches everyone.
    assert "gh sample" in _status([_cand("g1", "gamma")]).next_step()

    queued = [_cand(f"g{i}", "gamma") for i in range(10)]
    only_gamma_short = {"alpha": ["strict", "strict"], "beta": ["strict", "strict"]}
    assert "gh collect" in _status(queued, filled=only_gamma_short).next_step()

    full = {s: ["strict", "strict"] for s in STRATA}
    assert "re plan" in _status(filled=full).next_step()


def test_render_is_plain_text_when_not_a_terminal():
    text = plan.render(_status([_cand("g1", "gamma")], filled={"alpha": ["strict"]}))
    assert "\033[" not in text
    assert "alpha" in text
    assert "next:" in text


# -- sampler ------------------------------------------------------------------------

class FakeClient:
    """Repository search: each item is a repo whose owner is a fresh user."""

    authenticated = True

    def __init__(self, page: int = 12, owner_type: str = "User") -> None:
        self.page = page
        self.owner_type = owner_type
        self.searches: Counter[str] = Counter()
        self.queries: list[str] = []
        self._n = 0

    def get(self, path: str, *, params: dict[str, Any] | None = None, max_age=None) -> Any:
        if path == "/search/repositories":
            query = (params or {})["q"]
            self.queries.append(query)
            self.searches[query.split(" ")[0]] += 1
            items = []
            for _ in range(self.page):
                self._n += 1
                items.append({"full_name": f"user{self._n}/repo",
                              "owner": {"login": f"user{self._n}", "type": self.owner_type}})
            return {"items": items}
        login = path.rsplit("/", 1)[-1]
        return {"login": login, "type": "User", "public_repos": 10, "followers": 5,
                "created_at": "2022-01-01T00:00:00Z", "html_url": f"https://github.com/{login}"}


@pytest.fixture
def _no_state(tmp_path, monkeypatch):
    monkeypatch.setattr(sampler, "CANDIDATES_PATH", tmp_path / "candidates.json")


STRATA_QUERIES = {name: f"language:{name}" for name in STRATA}


@pytest.mark.usefixtures("_no_state")
def test_sample_adds_exactly_what_each_stratum_wants():
    candidates, _ = sampler.sample(FakeClient(), wanted={"alpha": 3, "gamma": 1},
                                   strata=STRATA_QUERIES)
    assert Counter(c.stratum for c in candidates if c.selected) == {"alpha": 3, "gamma": 1}


@pytest.mark.usefixtures("_no_state")
def test_sample_only_searches_strata_that_want_candidates():
    client = FakeClient()
    sampler.sample(client, wanted={"beta": 2, "alpha": 0}, strata=STRATA_QUERIES)
    assert client.searches["language:beta"] >= 1
    assert client.searches["language:alpha"] == 0
    assert client.searches["language:gamma"] == 0


@pytest.mark.usefixtures("_no_state")
def test_sample_with_nothing_wanted_makes_no_requests():
    client = FakeClient()
    sampler.sample(client, wanted={}, strata=STRATA_QUERIES)
    assert sum(client.searches.values()) == 0


def test_sample_never_re_examines_a_login(tmp_path, monkeypatch):
    import json

    path = tmp_path / "candidates.json"
    path.write_text(json.dumps({"consumed": {}, "candidates": [
        _cand("user1", "alpha") | {"html_url": "", "query": "", "discovered_at": ""}]}))
    monkeypatch.setattr(sampler, "CANDIDATES_PATH", path)

    candidates, _ = sampler.sample(FakeClient(page=3), wanted={"alpha": 2},
                                   strata=STRATA_QUERIES)
    logins = [c.login for c in candidates]
    assert logins.count("user1") == 1


@pytest.mark.usefixtures("_no_state")
def test_sample_searches_non_fork_repositories_and_records_provenance():
    client = FakeClient()
    candidates, consumed = sampler.sample(client, wanted={"alpha": 1}, strata=STRATA_QUERIES)
    assert "fork:false" in client.queries[0]
    assert candidates[0].method == sampler.SEARCH_METHOD
    assert candidates[0].found_via == "user1/repo"
    assert f"{sampler.SEARCH_METHOD}:alpha" in consumed


@pytest.mark.usefixtures("_no_state")
def test_organisation_owned_repos_are_skipped():
    candidates, _ = sampler.sample(FakeClient(owner_type="Organization"), wanted={"alpha": 1},
                                   strata=STRATA_QUERIES)
    assert candidates == []


@pytest.mark.usefixtures("_no_state")
def test_multi_language_strata_rotate_languages_across_windows():
    client = FakeClient(page=1)
    sampler.sample(client, wanted={"mobile": 2},
                   strata={"mobile": ["language:Dart", "language:Swift"]})
    assert {q.split(" ")[0] for q in client.queries} == {"language:Dart", "language:Swift"}


@pytest.mark.usefixtures("_no_state")
def test_repository_search_starts_from_the_newest_window():
    """Old repositories belong to senior accounts; juniors are in recent windows."""
    client = FakeClient(page=1)
    sampler.sample(client, wanted={"alpha": 1}, strata=STRATA_QUERIES)
    newest_start = sampler.date_windows()[-1][0]
    assert f"created:{newest_start}" in client.queries[0]


@pytest.mark.usefixtures("_no_state")
def test_sampling_continues_across_windows_until_the_stratum_has_enough():
    client = FakeClient(page=1)                  # one person per window
    candidates, _ = sampler.sample(client, wanted={"alpha": 4}, strata=STRATA_QUERIES)
    assert len(client.queries) == 4
    assert sum(c.selected for c in candidates) == 4
