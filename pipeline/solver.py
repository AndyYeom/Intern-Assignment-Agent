"""
Assignment solver. Pure code, no LLM — the assignment must be reproducible.

Projects have capacity > 1, so each project's column is duplicated `capacity`
times before solving, then the duplicated column indices are mapped back.
That mapping is the single most likely place for a silent bug, so validate()
runs after every solve.
"""
import numpy as np
from scipy.optimize import linear_sum_assignment


def solve(matrix, applicant_ids, projects):
    """
    matrix        : list[list[float]]  scores, higher is better  (N x M)
    applicant_ids : list[str]                                    (N)
    projects      : list[dict] with "id" and "capacity"          (M)

    returns: {applicant_id: project_id}, list[str] unplaced
    """
    scores = np.asarray(matrix, dtype=float)
    n, m = scores.shape
    assert len(applicant_ids) == n, f"{len(applicant_ids)} ids vs {n} rows"
    assert len(projects) == m, f"{len(projects)} projects vs {m} cols"

    # expand: one column per seat, remembering which project each seat belongs to
    seat_project = []          # seat index -> project index
    for j, p in enumerate(projects):
        seat_project.extend([j] * int(p["capacity"]))

    total_seats = len(seat_project)
    if total_seats < n:
        raise ValueError(
            f"{n} applicants but only {total_seats} seats. "
            "Increase capacity or the run cannot place everyone."
        )

    expanded = scores[:, seat_project]                 # N x seats

    # linear_sum_assignment minimises, so negate
    rows, cols = linear_sum_assignment(-expanded)

    assignment = {}
    for r, c in zip(rows, cols):
        assignment[applicant_ids[r]] = projects[seat_project[c]]["id"]

    unplaced = [a for a in applicant_ids if a not in assignment]
    return assignment, unplaced


def validate(assignment, unplaced, applicant_ids, projects):
    """Five checks that catch the silent failures. Run after every solve."""
    errors = []
    by_id = {p["id"]: p for p in projects}

    # 1. everyone accounted for exactly once
    covered = set(assignment) | set(unplaced)
    if covered != set(applicant_ids):
        missing = set(applicant_ids) - covered
        errors.append(f"applicants unaccounted for: {sorted(missing)}")
    if len(assignment) + len(unplaced) != len(applicant_ids):
        errors.append("duplicate applicant in the result")

    # 2. every assigned project actually exists
    for a, p in assignment.items():
        if p not in by_id:
            errors.append(f"{a} assigned to unknown project {p!r}")

    # 3. no project over capacity
    counts = {}
    for p in assignment.values():
        counts[p] = counts.get(p, 0) + 1
    for p, c in counts.items():
        cap = by_id.get(p, {}).get("capacity", 0)
        if c > cap:
            errors.append(f"{p} over capacity: {c} > {cap}")

    # 4. nobody placed twice
    if len(set(assignment)) != len(assignment):
        errors.append("an applicant appears more than once")

    # 5. coverage promise
    if unplaced:
        errors.append(f"unplaced applicants escalate to a mentor: {unplaced}")

    return errors


if __name__ == "__main__":
    import random
    random.seed(0)
    ids = [f"app_{i:02d}" for i in range(8)]
    projs = [{"id": f"proj_{j}", "capacity": 3} for j in range(3)]
    mat = [[round(random.uniform(0, 100), 1) for _ in projs] for _ in ids]

    a, u = solve(mat, ids, projs)
    errs = validate(a, u, ids, projs)
    for k, v in a.items():
        print(f"  {k} -> {v}")
    print("  errors:", errs or "none")
