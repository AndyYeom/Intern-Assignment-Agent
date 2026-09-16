"""Corpus status and collection planning, driven by slot assignment.

Reads what exists on disk - candidates.json, raw/, profiles/, applicants.csv -
places the built profiles into stratum slots (assign.py), and from what is still
empty decides what to collect or sample next.

`compute_status` is pure, so the planning logic is testable without disk or network.
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from generator import config
from generator.github import assign, collector, normalize, sampler

# How many candidates a stratum needs per empty slot depends on how often its
# search turns up someone eligible for it - near 100% for Python, near 0% for Go
# under the old user search. The hit rate is measured per stratum, only over
# candidates found by the current search method, with a Laplace prior (starts at
# 50%, converges on the observed rate) so a stratum with no data yet is not
# over- or under-fetched.
PRIOR_HITS, PRIOR_TRIALS = 1, 2
MIN_HIT_RATE = 0.15          # below this, fetch no more than 1/0.15 per slot
MAX_PER_SLOT = 6             # hard cap on candidates fetched per empty slot


def hit_rate(hits: int, trials: int) -> float:
    return max(MIN_HIT_RATE, (hits + PRIOR_HITS) / (trials + PRIOR_TRIALS))


@dataclass
class StratumRow:
    stratum: str
    quota: int
    strict: int = 0
    relaxed: int = 0
    partial: int = 0
    eligible: int = 0          # usable profiles that could fill this stratum
    pending: list[str] = field(default_factory=list)  # selected, found here, not collected
    hits: int = 0              # collected via current search, and eligible here
    trials: int = 0            # collected via current search

    @property
    def filled(self) -> int:
        return self.strict + self.relaxed + self.partial

    @property
    def need(self) -> int:
        return max(0, self.quota - self.filled)

    @property
    def hit_rate(self) -> float:
        return hit_rate(self.hits, self.trials)

    @property
    def fetch(self) -> int:
        """Candidates to fetch so that, at the observed hit rate, the gap closes."""
        if not self.need:
            return 0
        return min(math.ceil(self.need / self.hit_rate), self.need * MAX_PER_SLOT)

    @property
    def to_collect(self) -> list[str]:
        return self.pending[: self.fetch]

    @property
    def wanted(self) -> int:
        """New candidates to sample, beyond those already queued."""
        return max(0, self.fetch - len(self.pending))


@dataclass
class CorpusStatus:
    target: int
    quota: int
    rows: list[StratumRow]
    examined: int
    rejected: int
    collected: int
    unbuilt: int
    tiers: dict[str, int]
    placed: int
    spare: int
    windows_consumed: int = 0
    windows_total: int = 0
    resumes: int = 0
    authenticated: bool = False

    @property
    def to_collect(self) -> list[str]:
        seen: set[str] = set()
        out = []
        for row in self.rows:
            for login in row.to_collect:
                if login not in seen:
                    seen.add(login)
                    out.append(login)
        return out

    @property
    def wanted(self) -> dict[str, int]:
        return {row.stratum: row.wanted for row in self.rows if row.wanted}

    def total(self, name: str) -> int:
        return sum(getattr(row, name) for row in self.rows)

    def next_step(self) -> str:
        if self.unbuilt:
            return "uv run python -m generator gh build    (collected profiles not built yet)"
        if not self.total("need"):
            return "corpus complete - uv run python -m generator re infoprompt > prompt.md"
        # Sample before collecting, so one collect round fetches everyone a short
        # stratum needs, repository-search candidates first.
        if self.wanted:
            return "uv run python -m generator gh sample   (short strata need more candidates)"
        return "uv run python -m generator gh collect  (enough candidates queued)"


def compute_status(
    candidates: list[dict[str, Any]],
    *,
    collected: set[str],
    built: set[str],
    assignment: assign.Assignment,
    tiers: dict[str, int],
    login_of: dict[str, str] | None = None,
    target: int,
    strata: list[str],
    windows_consumed: int = 0,
    windows_total: int = 0,
    resumes: int = 0,
    authenticated: bool = False,
) -> CorpusStatus:
    rows = {s: StratumRow(stratum=s, quota=assignment.quota) for s in strata}
    for s, row in rows.items():
        row.strict = assignment.filled(s, "strict")
        row.relaxed = assignment.filled(s, "relaxed")
        row.partial = assignment.filled(s, "partial")
        row.eligible = assignment.eligible_count(s)

    # Eligibility is keyed by applicant_id; candidates by login.
    eligible_logins: dict[str, set[str]] = {}
    for applicant_id, options in assignment.eligibility.items():
        login = (login_of or {}).get(applicant_id, applicant_id)
        eligible_logins[login] = {option.stratum for option in options}

    # Candidates are queued under the stratum whose search found them - the best
    # available guess at where they will be eligible, before collection. Those
    # from the current search method are queued first: they are more precise.
    queued = sorted(
        (c for c in candidates if c.get("selected")),
        key=lambda c: c.get("method", "users") != sampler.SEARCH_METHOD,
    )
    for candidate in queued:
        row = rows.get(candidate.get("stratum", ""))
        if row is None:
            continue
        login = candidate["login"]
        if login not in collected:
            row.pending.append(login)
        elif candidate.get("method") == sampler.SEARCH_METHOD and login in built:
            row.trials += 1
            row.hits += row.stratum in eligible_logins.get(login, set())

    return CorpusStatus(
        target=target,
        quota=assignment.quota,
        rows=list(rows.values()),
        examined=len(candidates),
        rejected=sum(1 for c in candidates if not c.get("selected")),
        collected=len(collected),
        unbuilt=len(collected - built),
        tiers=tiers,
        placed=len(assignment.placements),
        spare=len(set(assignment.eligibility) - assignment.placed_ids),
        windows_consumed=windows_consumed,
        windows_total=windows_total,
        resumes=resumes,
        authenticated=authenticated,
    )


def load_status(target: int = config.TARGET_PROFILE_COUNT) -> CorpusStatus:
    """Assemble the status from disk. Never touches the network."""
    state = sampler.load_state()
    profiles = normalize.load_all_profiles()
    strata = list(sampler.STRATA)
    assignment = assign.assign(profiles, strata, sampler.stratum_quota(target, len(strata)),
                               assign.pins_from_disk())

    resumes = 0
    manifest_path = config.DATA / "applicants.csv"
    if manifest_path.exists():
        resumes = max(0, len(manifest_path.read_text(encoding="utf-8").splitlines()) - 1)

    tiers = {"strict": 0, "relaxed": 0, "unusable": 0}
    for profile in profiles:
        tiers[profile.tier] = tiers.get(profile.tier, 0) + 1

    return compute_status(
        state["candidates"],
        collected=set(collector.collected_logins()),
        built={p.login for p in profiles},
        assignment=assignment,
        tiers=tiers,
        login_of={p.applicant_id: p.login for p in profiles},
        target=target,
        strata=strata,
        windows_consumed=sum(len(v) for v in state["consumed"].values()),
        windows_total=len(sampler.windows_for(state)) * len(strata),
        resumes=resumes,
        authenticated=bool(config.github_token()),
    )


# -- rendering --------------------------------------------------------------

def _colour() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _colour() else text


def render(status: CorpusStatus) -> str:
    headers = ["stratum", "quota", "strict", "relaxed", "partial", "need", "eligible",
               "queued", "hit"]
    widths = [22, 5, 6, 7, 7, 5, 8, 6, 7]

    def line(cells: list[str], painted: dict[int, str] | None = None) -> str:
        out = []
        for i, (cell, width) in enumerate(zip(cells, widths, strict=True)):
            text = cell.ljust(width) if i == 0 else cell.rjust(width)
            if painted and i in painted:
                text = _paint(text, painted[i])
            out.append(text)
        return "  ".join(out)

    rule = "─" * (sum(widths) + 2 * (len(widths) - 1))
    lines = [
        _paint("GitHub corpus status", "1"),
        (f"target {status.target} placed profiles · {len(status.rows)} strata · "
         f"{status.quota} slots each"),
        rule,
        _paint(line(headers), "2"),
        rule,
    ]
    for row in status.rows:
        need = "✓" if row.need == 0 else str(row.need)
        lines.append(line(
            [row.stratum, str(row.quota), str(row.strict), str(row.relaxed),
             str(row.partial), need,
             str(row.eligible), str(len(row.pending)),
             f"{row.hits}/{row.trials}" if row.trials else "—"],
            {5: "32" if need == "✓" else "33"},
        ))
    lines += [
        rule,
        _paint(line(
            ["total", str(status.target), str(status.total("strict")),
             str(status.total("relaxed")), str(status.total("partial")),
             str(status.total("need")), "", "", ""],
        ), "1"),
        rule,
        (f"profiles: {status.collected} collected · {status.tiers.get('strict', 0)} strict · "
         f"{status.tiers.get('relaxed', 0)} relaxed · {status.tiers.get('unusable', 0)} unusable"
         f" · {status.placed} placed · {status.spare} usable but unplaced"),
        (f"candidates: {status.examined} examined · {status.rejected} rejected · "
         f"date windows searched {status.windows_consumed}/{status.windows_total}"),
        f"resumes rendered: {status.resumes}",
        "token: " + (_paint("set", "32") if status.authenticated
                     else _paint("not set - 60 requests/hour", "33")),
        "",
        "next: " + _paint(status.next_step(), "36"),
    ]
    return "\n".join(lines)


def to_json(status: CorpusStatus) -> str:
    return json.dumps({
        "target": status.target,
        "quota": status.quota,
        "strata": [
            {"stratum": r.stratum, "quota": r.quota, "strict": r.strict, "relaxed": r.relaxed,
             "partial": r.partial,
             "need": r.need, "eligible": r.eligible, "queued": len(r.pending),
             "hits": r.hits, "trials": r.trials, "fetch": r.fetch}
            for r in status.rows
        ],
        "tiers": status.tiers,
        "placed": status.placed,
        "to_collect": status.to_collect,
        "wanted": status.wanted,
        "next_step": status.next_step(),
    }, indent=2)
