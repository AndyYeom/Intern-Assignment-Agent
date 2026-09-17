"""
Orchestrator. Runs the pipeline, caches every stage to disk, retries, and
stops if the run gets expensive.

Agents are injected as callables, so this file works today with stubs and
works on day 7 with the real agents. Nothing here changes when A, B and C land.

    python -m pipeline.orchestrator
"""
import json
import time
import pathlib
from concurrent.futures import ThreadPoolExecutor

from .solver import solve, validate
from .resolve_profile import resolve_profile

RUN_DIR = pathlib.Path("data/runs")
MAX_LLM_CALLS = 2000          # hard ceiling; a runaway run stops instead of billing
MAX_WORKERS = 6


class Budget:
    def __init__(self, limit=MAX_LLM_CALLS):
        self.limit, self.used = limit, 0

    def spend(self, n=1):
        self.used += n
        if self.used > self.limit:
            raise RuntimeError(f"cost ceiling hit: {self.used} calls > {self.limit}")


def retry(fn, *args, attempts=3, base=1.0, **kwargs):
    """LLM and GitHub calls will fail mid-demo. Back off and try again."""
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if i == attempts - 1:
                raise
            wait = base * (2 ** i)
            print(f"    retry {i+1}/{attempts-1} after {wait:.0f}s — {type(e).__name__}: {e}")
            time.sleep(wait)


def stage(run_id, name, compute):
    """Run a stage, or load it from disk if it already succeeded.

    This is what lets you re-run after a failure on applicant #31 without
    redoing the other 39.
    """
    path = RUN_DIR / run_id / f"{name}.json"
    if path.exists():
        print(f"  [{name}] cached")
        return json.loads(path.read_text())
    print(f"  [{name}] running")
    result = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2))
    return result


def fan_out(items, fn):
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        return list(ex.map(fn, items))


def run(run_id, applicants, project_inputs, agents, budget=None):
    """
    agents: dict of callables — profile, evidence, catalog, score
            Swap stubs for real agents; nothing else changes.
    """
    budget = budget or Budget()

    # ---- applicant branch -------------------------------------------------
    profiles = stage(run_id, "01_profiles", lambda: fan_out(
        applicants, lambda a: (budget.spend(), retry(agents["profile"], a))[1]))

    evidence = stage(run_id, "02_evidence", lambda: fan_out(
        profiles, lambda p: (budget.spend(), retry(agents["evidence"], p))[1]))

    resolved = stage(run_id, "03_resolved",
                     lambda: [resolve_profile(p, v) for p, v in zip(profiles, evidence)])

    # ---- project branch ---------------------------------------------------
    projects = stage(run_id, "04_projects", lambda: fan_out(
        project_inputs, lambda p: (budget.spend(), retry(agents["catalog"], p))[1]))

    # ---- scoring ----------------------------------------------------------
    def build_matrix():
        rows = []
        for rp in resolved:
            row = []
            for pr in projects:
                budget.spend()
                row.append(retry(agents["score"], rp, pr))
            rows.append(row)
        return rows

    matrix = stage(run_id, "05_matrix", build_matrix)

    # ---- assignment (deterministic from here down) ------------------------
    ids = [r["applicant_id"] for r in resolved]
    assignment, unplaced = solve(matrix, ids, projects)
    errors = validate(assignment, unplaced, ids, projects)

    out = {
        "run_id": run_id,
        "assignment": assignment,
        "unplaced": unplaced,
        "validation_errors": errors,
        "llm_calls": budget.used,
    }
    (RUN_DIR / run_id / "06_assignment.json").write_text(json.dumps(out, indent=2))
    return out


# --------------------------------------------------------------------------
# Stubs — replaced by the real agents on day 7. The point is that only these
# four lines change.
# --------------------------------------------------------------------------
def _stub_agents():
    import random
    rnd = random.Random(0)

    def profile(raw):
        return {"applicant_id": raw["id"],
                "skills": [{"canonical_skill": s, "claimed_level": rnd.randint(1, 3)}
                           for s in raw["skills"]],
                "interests": []}

    def evidence(prof):
        return {"applicant_id": prof["applicant_id"], "skill_verification": [
            {"canonical_skill": s["canonical_skill"],
             "github_observed_level": max(1, s["claimed_level"] - rnd.randint(0, 1)),
             "verification_status": rnd.choice(
                 ["verified", "partially_verified", "not_observed", "conflicting"])}
            for s in prof["skills"]]}

    def catalog(raw):
        return {"id": raw["id"], "name": raw["name"], "capacity": raw["capacity"],
                "skills": [{"skill": s, "level": rnd.randint(1, 3), "core": True}
                           for s in raw["skills"]]}

    def score(resolved_profile, project):
        return round(rnd.uniform(0, 100), 1)

    return {"profile": profile, "evidence": evidence, "catalog": catalog, "score": score}


if __name__ == "__main__":
    applicants = [{"id": f"app_{i:02d}", "skills": ["python", "react", "sql"]} for i in range(8)]
    project_inputs = [{"id": f"proj_{j}", "name": f"Project {j}", "capacity": 3,
                       "skills": ["python", "react"]} for j in range(3)]

    result = run("demo", applicants, project_inputs, _stub_agents())

    print("\n  assignment")
    for a, p in result["assignment"].items():
        print(f"    {a} -> {p}")
    print(f"\n  llm calls : {result['llm_calls']}")
    print(f"  errors    : {result['validation_errors'] or 'none'}")
    print(f"\n  stages cached in {RUN_DIR / 'demo'} — re-run to see them load")
