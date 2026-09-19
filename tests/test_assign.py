"""Tests for stratum eligibility and optimal slot assignment."""
from __future__ import annotations

from generator.github import assign, sampler
from generator.github.assign import Assignment, eligibility
from generator.schemas import GitHubProfile, RepoRecord


def _repo(name: str, language: str, *, skills: tuple[str, ...] = (),
          relevant: bool = True) -> RepoRecord:
    return RepoRecord(
        name=name, full_name=f"u/{name}", html_url="",
        languages={language: 10_000}, primary_language=language,
        skill_relevant=relevant,
        skill_signals=[{"skill_id": s, "source": "manifest", "strength": 0.9} for s in skills],
    )


def _person(applicant_id: str, tier: str, *languages: str,
            stratum: str = "python-backend") -> GitHubProfile:
    return GitHubProfile(
        applicant_id=applicant_id, login=f"login-{applicant_id}", html_url="",
        repos=[_repo(f"{applicant_id}-{i}", lang) for i, lang in enumerate(languages)],
        tier=tier, search_stratum=stratum,
    )


def _grades(profile: GitHubProfile) -> dict[str, str]:
    return {e.stratum: e.tier for e in eligibility(profile)}


# -- eligibility ------------------------------------------------------------------

def test_every_stratum_has_a_language_mapping():
    assert set(assign.STRATUM_LANGUAGES) == set(sampler.STRATA)


def test_one_person_is_a_candidate_for_several_strata():
    person = _person("a", "strict", "C#", "C#", "Python", "TypeScript")
    assert _grades(person) == {
        "csharp": "strict", "python-backend": "relaxed", "typescript-fullstack": "relaxed",
    }


def test_search_stratum_does_not_decide_eligibility():
    """Found by a Go search, but builds C#: eligible for csharp, not go."""
    person = _person("a", "strict", "C#", "C#", "C#", stratum="go-systems")
    assert _grades(person) == {"csharp": "strict"}


def test_python_with_ml_skills_counts_as_data_ml_not_backend():
    person = GitHubProfile(
        applicant_id="a", login="a", html_url="", tier="strict",
        repos=[_repo("model", "Python", skills=("machine-learning",)),
               _repo("eda", "Python", skills=("pandas",))],
    )
    assert _grades(person) == {"python-data-ml": "strict"}


def test_relaxed_profile_is_never_strict_in_any_stratum():
    assert _grades(_person("a", "relaxed", "Go", "Go", "Go")) == {"go-systems": "relaxed"}


def test_unusable_profile_and_irrelevant_repos_give_no_eligibility():
    assert eligibility(_person("a", "unusable", "Go", "Go", "Go")) == []
    person = _person("b", "strict", "Go", "Go")
    person.repos.append(_repo("notes", "Kotlin", relevant=False))
    assert "android-kotlin" not in _grades(person)


# -- assignment -------------------------------------------------------------------

def _placed(result: Assignment) -> dict[str, str]:
    return {p.applicant_id: p.stratum for p in result.placements}


def test_fills_as_many_slots_as_possible():
    a = _person("a", "strict", "C#", "C#", "Go", "Go")     # csharp or go
    b = _person("b", "strict", "C#", "C#", "C#")           # csharp only
    result = assign.assign([a, b], ["csharp", "go-systems"], quota=1)
    assert _placed(result) == {"a": "go-systems", "b": "csharp"}


def test_filling_a_slot_beats_strictness():
    """Never leave a slot empty just to place one more strict profile."""
    a = _person("a", "strict", "C#", "C#", "Go")           # strict csharp, relaxed go
    b = _person("b", "strict", "C#", "C#")                 # strict csharp only
    result = assign.assign([a, b], ["csharp", "go-systems"], quota=1)
    assert _placed(result) == {"a": "go-systems", "b": "csharp"}
    assert {p.applicant_id: p.tier for p in result.placements} == {"a": "relaxed", "b": "strict"}


def test_strict_is_preferred_when_slots_are_scarce():
    strict = _person("s", "strict", "Go", "Go", "Go")
    relaxed = _person("r", "relaxed", "Go", "Go", "Go")
    result = assign.assign([relaxed, strict], ["go-systems"], quota=1)
    assert _placed(result) == {"s": "go-systems"}


def test_people_go_where_they_are_most_specialised():
    a = _person("a", "strict", "C#", "C#", "C#", "Go", "Go")
    b = _person("b", "strict", "C#", "C#", "Go", "Go", "Go")
    result = assign.assign([a, b], ["csharp", "go-systems"], quota=1)
    assert _placed(result) == {"a": "csharp", "b": "go-systems"}


def test_a_person_with_a_resume_is_never_dropped():
    """Even when a stricter competitor wants the only slot."""
    has_resume = _person("r", "relaxed", "Go", "Go", "Go")
    stricter = _person("s", "strict", "Go", "Go", "Go")
    free = assign.assign([has_resume, stricter], ["go-systems"], quota=1)
    assert _placed(free) == {"s": "go-systems"}

    kept = assign.assign([has_resume, stricter], ["go-systems"], quota=1,
                         pinned={"r": "go-systems"})
    assert _placed(kept) == {"r": "go-systems"}
    assert kept.placements[0].pinned


def test_a_person_with_a_resume_stays_in_their_previous_stratum():
    a = _person("a", "strict", "C#", "C#", "Go", "Go")
    b = _person("b", "strict", "C#", "C#", "Go", "Go")
    kept = assign.assign([a, b], ["csharp", "go-systems"], quota=1,
                         pinned={"a": "go-systems"})
    assert _placed(kept) == {"a": "go-systems", "b": "csharp"}


def test_keeping_a_resume_never_leaves_a_slot_empty():
    """Moving a person between strata is harmless; an empty slot is not."""
    a = _person("a", "strict", "C#", "C#", "Go")           # csharp or go
    b = _person("b", "strict", "Go", "Go")                 # go only
    result = assign.assign([a, b], ["csharp", "go-systems"], quota=1,
                           pinned={"a": "go-systems"})
    assert _placed(result) == {"a": "csharp", "b": "go-systems"}


def test_each_person_fills_at_most_one_slot():
    people = [_person(str(i), "strict", "C#", "C#", "Go", "Go", "Java", "Java") for i in range(2)]
    result = assign.assign(people, ["csharp", "go-systems", "java-backend"], quota=2)
    assert len(result.placements) == 2
    assert len({p.applicant_id for p in result.placements}) == 2


def test_need_and_spare_are_reported():
    people = [_person(str(i), "strict", "Go", "Go") for i in range(3)]
    result = assign.assign(people, ["go-systems", "csharp"], quota=2)
    assert result.need("go-systems") == 0
    assert result.need("csharp") == 2
    assert result.eligible_count("go-systems") == 3
    assert len(set(result.eligibility) - result.placed_ids) == 1


def test_assignment_is_deterministic():
    people = [_person(str(i), "strict", "C#", "C#", "Go", "Go") for i in range(6)]
    first = assign.assign(people, ["csharp", "go-systems"], quota=2)
    second = assign.assign(list(reversed(people)), ["csharp", "go-systems"], quota=2)
    assert _placed(first) == _placed(second)


# -- probabilistic eligibility ---------------------------------------------------

def _mixed(name: str, languages: dict[str, int], *, deps: tuple[str, ...] = (),
           skills: tuple[str, ...] = ()) -> RepoRecord:
    return RepoRecord(
        name=name, full_name=f"u/{name}", html_url="", languages=languages,
        primary_language=max(languages, key=languages.__getitem__), skill_relevant=True,
        manifests={"package.json": list(deps)} if deps else {},
        skill_signals=[{"skill_id": s, "source": "file", "strength": 0.6} for s in skills],
    )


def _profile(*repos: RepoRecord, tier: str = "strict") -> GitHubProfile:
    return GitHubProfile(applicant_id="a", login="a", html_url="", tier=tier, repos=list(repos))


def test_minor_go_in_a_typescript_backend_gives_partial_go_eligibility():
    """Go at 10% of a repo is real Go work, not nothing."""
    person = _profile(
        _mixed("api", {"TypeScript": 90_000, "Go": 10_000}),
        _mixed("web", {"TypeScript": 50_000}),
        _mixed("cli", {"TypeScript": 40_000}),
    )
    grades = {e.stratum: e for e in eligibility(person)}
    assert grades["go-systems"].tier == "partial"
    assert 0 < grades["go-systems"].share < grades["typescript-fullstack"].share


def test_react_native_app_is_mobile_evidence_despite_being_javascript():
    person = _profile(
        _mixed("app", {"JavaScript": 80_000}, deps=("react-native", "react")),
        _mixed("site", {"JavaScript": 20_000}),
        _mixed("tool", {"JavaScript": 20_000}),
    )
    assert "mobile" in {e.stratum for e in eligibility(person)}


def test_hybrid_capacitor_app_is_mobile_evidence():
    person = _profile(_mixed("app", {"TypeScript": 50_000}, deps=("@capacitor/core",)),
                      _mixed("b", {"TypeScript": 9_000}), _mixed("c", {"TypeScript": 9_000}))
    assert "mobile" in {e.stratum for e in eligibility(person)}


def test_stray_bytes_are_not_evidence():
    person = _profile(_mixed("api", {"Python": 90_000, "Go": 300}),
                      _mixed("b", {"Python": 9_000}), _mixed("c", {"Python": 9_000}))
    assert "go-systems" not in {e.stratum for e in eligibility(person)}


def test_probabilities_sum_to_one():
    person = _profile(_mixed("a", {"Go": 5_000, "TypeScript": 5_000}),
                      _mixed("b", {"Kotlin": 9_000}, skills=("native-mobile",)),
                      _mixed("c", {"C#": 9_000}))
    assert abs(sum(e.share for e in eligibility(person)) - 1.0) < 1e-3


def test_a_partial_placement_fills_an_otherwise_empty_slot():
    ts_with_some_go = _profile(_mixed("api", {"TypeScript": 90_000, "Go": 10_000}),
                               _mixed("web", {"TypeScript": 50_000}),
                               _mixed("cli", {"TypeScript": 40_000}))
    result = assign.assign([ts_with_some_go], ["go-systems"], quota=1)
    assert [(p.stratum, p.tier) for p in result.placements] == [("go-systems", "partial")]


def test_least_surprise_decides_between_equal_tiers():
    """Both partial for go and mobile; the person's evidence leans mobile."""
    person = GitHubProfile(applicant_id="a", login="a", html_url="", tier="strict", repos=[
        _mixed("app", {"TypeScript": 60_000, "Go": 5_000}, deps=("react-native",)),
        _mixed("b", {"TypeScript": 9_000}, deps=("react-native",)),
        _mixed("c", {"TypeScript": 9_000}),
    ])
    other = _person("b", "strict", "TypeScript", "TypeScript", "TypeScript")
    result = assign.assign([person, other], ["go-systems", "mobile", "typescript-fullstack"],
                           quota=1)
    placed = {p.applicant_id: p.stratum for p in result.placements}
    assert placed["b"] == "typescript-fullstack"
    assert placed["a"] == "mobile"


def test_tier_still_beats_probability():
    """A relaxed placement is preferred to a partial one, however likely the partial."""
    relaxed = _person("r", "relaxed", "Go", "Go", "Go")
    partial = _profile(_mixed("api", {"TypeScript": 60_000, "Go": 40_000}),
                       _mixed("b", {"TypeScript": 9_000}), _mixed("c", {"TypeScript": 9_000}))
    partial.applicant_id = "p"
    result = assign.assign([partial, relaxed], ["go-systems"], quota=1)
    assert [p.applicant_id for p in result.placements] == ["r"]


def test_cost_levels_nest_across_every_slot():
    """Each priority must outweigh the maximum total of every lower one."""
    slots = assign.MAX_SLOTS
    assert abs(assign.COST_PREVIOUS_STRATUM_BONUS) > assign.MAX_SURPRISAL * slots
    assert assign.COST_TIER_STEP > abs(assign.COST_PREVIOUS_STRATUM_BONUS) * slots
    assert abs(assign.COST_HAS_RESUME_BONUS) > assign.COST_TIER_STEP * 2 * slots
    assert assign.COST_INELIGIBLE > abs(assign.COST_HAS_RESUME_BONUS) * slots
