"""Corpus planning and status: who to collect, and how far along each stratum is.

Reads four places, because no single file knows everything:

  candidates.json   who was examined and selected, per stratum
  raw/<login>/      who has been collected
  profiles/         who has been built, and whether they are usable
  applicants.csv    who has a rendered resume

`compute_status` is pure, so the counting can be tested without disk or network.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from generator import config
from generator.github import collector, normalize, sampler


@dataclass
class StratumRow:
    stratum: str
    quota: int
    selected: int = 0
    planned: list[str] = field(default_factory=list)
    reserve: int = 0
    collected: int = 0
    built: int = 0
    usable: int = 0
    unusable: int = 0
    unbuilt: int = 0          # planned, collected, but no profile built yet

    @property
    def need(self) -> int:
        """Usable profiles still missing for this stratum."""
        return max(0, self.quota - self.usable)


@dataclass
class CorpusStatus:
    target: int
    quota: int
    rows: list[StratumRow]
    examined: int
    rejected: int
    windows_consumed: int
    windows_total: int
    resumes: int
    authenticated: bool

    @property
    def planned(self) -> list[str]:
        return [login for row in self.rows for login in row.planned]

    def total(self, name: str) -> int:
        return sum(getattr(row, name) for row in self.rows)

    def next_step(self) -> str:
        if any(row.selected - row.unusable < row.quota for row in self.rows if row.quota):
            return "uv run python -m generator gh sample   (some strata are short of candidates)"
        if any(row.collected < len(row.planned) for row in self.rows):
            return "uv run python -m generator gh collect  (planned profiles not fetched yet)"
        if self.total("unbuilt"):
            return "uv run python -m generator gh build    (collected profiles not built yet)"
        if any(row.need for row in self.rows if row.quota):
            return "uv run python -m generator gh collect  (reserves replace unusable profiles)"
        return "corpus complete - uv run python -m generator re plan --batches 5"


def compute_status(
    candidates: list[dict[str, Any]],
    *,
    collected: set[str],
    usability: dict[str, bool],
    target: int,
    strata: list[str],
    windows_consumed: int = 0,
    windows_total: int = 0,
    resumes: int = 0,
    authenticated: bool = False,
) -> CorpusStatus:
    """Count every stage per stratum and choose which logins to collect.

    Planned = the first `quota` selected candidates in each stratum, in discovery
    order, skipping any whose built profile proved unusable. That skip is what
    lets a reserve candidate slide in without a new search.
    """
    quota = sampler.stratum_quota(target, len(strata))

    names = list(strata) + sorted(
        {c["stratum"] for c in candidates if c.get("stratum") not in strata}
    )
    rows = {name: StratumRow(stratum=name, quota=quota if name in strata else 0)
            for name in names}

    for candidate in candidates:
        if not candidate.get("selected"):
            continue
        login = candidate["login"]
        row = rows[candidate["stratum"]]
        row.selected += 1
        if login in usability:
            row.built += 1
            if usability[login]:
                row.usable += 1
            else:
                row.unusable += 1
        if len(row.planned) < row.quota and usability.get(login, True):
            row.planned.append(login)

    for row in rows.values():
        row.reserve = max(0, row.selected - row.unusable - len(row.planned))
        # Progress against the plan, not against everyone ever selected.
        row.collected = sum(1 for login in row.planned if login in collected)
        row.unbuilt = sum(
            1 for login in row.planned if login in collected and login not in usability
        )

    return CorpusStatus(
        target=target,
        quota=quota,
        rows=list(rows.values()),
        examined=len(candidates),
        rejected=sum(1 for c in candidates if not c.get("selected")),
        windows_consumed=windows_consumed,
        windows_total=windows_total,
        resumes=resumes,
        authenticated=authenticated,
    )


def load_status(target: int = config.TARGET_PROFILE_COUNT) -> CorpusStatus:
    """Assemble the status from disk. Never touches the network."""
    state = sampler.load_state()
    profiles = normalize.load_all_profiles()

    resumes = 0
    manifest_path = config.DATA / "applicants.csv"
    if manifest_path.exists():
        resumes = max(0, len(manifest_path.read_text(encoding="utf-8").splitlines()) - 1)

    return compute_status(
        state["candidates"],
        collected=set(collector.collected_logins()),
        usability={p.login: p.usable for p in profiles},
        target=target,
        strata=list(sampler.STRATA),
        windows_consumed=sum(len(v) for v in state["consumed"].values()),
        windows_total=len(sampler.date_windows()) * len(sampler.STRATA),
        resumes=resumes,
        authenticated=bool(config.github_token()),
    )


def planned_logins(target: int = config.TARGET_PROFILE_COUNT) -> list[str]:
    return load_status(target).planned


# -- rendering --------------------------------------------------------------

def _colour() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _colour() else text


def render(status: CorpusStatus) -> str:
    headers = ["stratum", "quota", "selected", "reserve", "collected",
               "usable", "unusable", "need"]
    widths = [22, 5, 8, 7, 9, 6, 8, 6]

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
        (f"target {status.target} usable profiles · {len(status.rows)} strata · "
         f"quota {status.quota} each"),
        rule,
        _paint(line(headers), "2"),
        rule,
    ]
    for row in status.rows:
        need = "✓" if row.need == 0 and row.quota else str(row.need)
        lines.append(line(
            [row.stratum, str(row.quota), str(row.selected), str(row.reserve),
             f"{row.collected}/{len(row.planned)}", str(row.usable), str(row.unusable), need],
            {7: "32" if need == "✓" else "33"},
        ))
    lines += [
        rule,
        _paint(line(
            ["total", str(status.target), str(status.total("selected")),
             str(status.total("reserve")),
             f"{status.total('collected')}/{len(status.planned)}",
             str(status.total("usable")), str(status.total("unusable")),
             str(sum(r.need for r in status.rows if r.quota))],
        ), "1"),
        rule,
        (f"examined {status.examined} · rejected {status.rejected} · "
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
        "planned": status.planned,
        "strata": [
            {**row.__dict__, "need": row.need} for row in status.rows
        ],
        "next_step": status.next_step(),
    }, indent=2)
