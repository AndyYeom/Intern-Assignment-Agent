"""Tests for stratified sampling, collection planning and corpus status."""
from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from generator.github import sampler
from generator.github.plan import compute_status, render

STRATA = ["alpha", "beta", "gamma", "delta"]


def _cand(login: str, stratum: str, selected: bool = True) -> dict[str, Any]:
    return {"login": login, "stratum": stratum, "selected": selected}


def _status(candidates, *, collected=(), usability=None, target=8):
    return compute_status(candidates, collected=set(collected), usability=usability or {},
                          target=target, strata=STRATA)


# -- quota -------------------------------------------------------------------

@pytest.mark.parametrize(("target", "strata", "quota"), [(40, 10, 4), (41, 10, 5), (3, 10, 1)])
def test_quota_rounds_up_so_the_target_is_always_covered(target, strata, quota):
    assert sampler.stratum_quota(target, strata) == quota


# -- planning ----------------------------------------------------------------

def test_surplus_in_one_stratum_is_reserve_not_planned():
    """The bug this fixes: 32 people from one stratum must not all be collected."""
    candidates = [_cand(f"py{i}", "alpha") for i in range(32)]
    status = _status(candidates)
    alpha = status.rows[0]
    assert status.quota == 2
    assert alpha.planned == ["py0", "py1"]
    assert alpha.reserve == 30
    assert status.planned == ["py0", "py1"]


def test_unusable_profile_is_replaced_from_reserve_without_searching():
    candidates = [_cand(f"py{i}", "alpha") for i in range(4)]
    status = _status(candidates, collected={"py0", "py1"},
                     usability={"py0": False, "py1": True})
    alpha = status.rows[0]
    assert alpha.planned == ["py1", "py2"]
    assert alpha.unusable == 1
    assert alpha.usable == 1
    assert alpha.need == 1


def test_rejected_candidates_are_never_planned():
    status = _status([_cand("org", "alpha", selected=False), _cand("ok", "alpha")])
    assert status.rows[0].planned == ["ok"]
    assert status.rejected == 1


def test_candidates_from_retired_strata_are_shown_but_not_planned():
    status = _status([_cand("old", "rust-systems")])
    retired = next(r for r in status.rows if r.stratum == "rust-systems")
    assert retired.quota == 0
    assert retired.planned == []


# -- next step ------------------------------------------------------------------

def _full(n_per: int = 2) -> list[dict[str, Any]]:
    return [_cand(f"{s}{i}", s) for s in STRATA for i in range(n_per)]


def test_next_step_walks_the_pipeline_in_order():
    assert "gh sample" in _status([]).next_step()

    candidates = _full()
    logins = {c["login"] for c in candidates}
    assert "gh collect" in _status(candidates).next_step()
    assert "gh build" in _status(candidates, collected=logins).next_step()

    done = _status(candidates, collected=logins, usability=dict.fromkeys(logins, True))
    assert "re plan" in done.next_step()
    assert sum(r.need for r in done.rows) == 0


def test_next_step_asks_for_more_sampling_when_reserves_run_out():
    candidates = _full()
    logins = {c["login"] for c in candidates}
    usability = dict.fromkeys(logins, True)
    usability["alpha0"] = False  # no reserve left in alpha
    status = _status(candidates, collected=logins, usability=usability)
    assert "gh sample" in status.next_step()


def test_render_is_plain_text_when_not_a_terminal():
    text = render(_status(_full()))
    assert "\033[" not in text
    assert "alpha" in text
    assert "next:" in text


# -- sampler ---------------------------------------------------------------------

class FakeClient:
    """Search returns a fresh page of eligible users per query."""

    authenticated = True

    def __init__(self, page: int = 12) -> None:
        self.page = page
        self.searches: Counter[str] = Counter()
        self._n = 0

    def get(self, path: str, *, params: dict[str, Any] | None = None, max_age=None) -> Any:
        if path == "/search/users":
            query = (params or {})["q"]
            self.searches[query.split(" ")[0]] += 1
            items = []
            for _ in range(self.page):
                self._n += 1
                items.append({"login": f"user{self._n}"})
            return {"items": items}
        login = path.rsplit("/", 1)[-1]
        return {"login": login, "type": "User", "public_repos": 10, "followers": 5,
                "created_at": "2022-01-01T00:00:00Z", "html_url": f"https://github.com/{login}"}


@pytest.fixture
def _no_state(tmp_path, monkeypatch):
    monkeypatch.setattr(sampler, "CANDIDATES_PATH", tmp_path / "candidates.json")


@pytest.mark.usefixtures("_no_state")
def test_sample_fills_every_stratum_to_quota_plus_reserve():
    strata = {name: f"language:{name}" for name in STRATA}
    candidates, _ = sampler.sample(FakeClient(), target=8, strata=strata, reserve=1)

    per_stratum = Counter(c.stratum for c in candidates if c.selected)
    assert per_stratum == dict.fromkeys(STRATA, 3)  # quota 2 + reserve 1


@pytest.mark.usefixtures("_no_state")
def test_sample_does_not_pile_into_the_first_stratum():
    strata = {name: f"language:{name}" for name in STRATA}
    candidates, _ = sampler.sample(FakeClient(page=50), target=8, strata=strata, reserve=0)
    per_stratum = Counter(c.stratum for c in candidates if c.selected)
    assert max(per_stratum.values()) == 2


def test_sample_skips_strata_already_at_ceiling(tmp_path, monkeypatch):
    import json

    path = tmp_path / "candidates.json"
    path.write_text(json.dumps({
        "consumed": {},
        "candidates": [_cand(f"a{i}", "alpha") | {"html_url": "", "query": "",
                                                 "discovered_at": ""} for i in range(5)],
    }))
    monkeypatch.setattr(sampler, "CANDIDATES_PATH", path)

    client = FakeClient()
    strata = {name: f"language:{name}" for name in STRATA}
    sampler.sample(client, target=8, strata=strata, reserve=1)
    assert client.searches["language:alpha"] == 0
    assert client.searches["language:beta"] >= 1


def test_unusable_candidates_do_not_count_towards_their_stratum(tmp_path, monkeypatch):
    import json

    path = tmp_path / "candidates.json"
    path.write_text(json.dumps({
        "consumed": {},
        "candidates": [_cand(f"a{i}", "alpha") | {"html_url": "", "query": "",
                                                 "discovered_at": ""} for i in range(3)],
    }))
    monkeypatch.setattr(sampler, "CANDIDATES_PATH", path)

    client = FakeClient()
    strata = {name: f"language:{name}" for name in STRATA}
    sampler.sample(client, target=8, strata=strata, reserve=1,
                   unusable={"a0", "a1", "a2"})
    assert client.searches["language:alpha"] >= 1
