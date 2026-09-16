# Proficiency Levels (v0.1)

**This is the single source of truth.** The Profile agent, the Evidence agent and the
Catalog agent all inject the same block below. Do not reword it in any individual prompt.
If a definition needs to change, change it here and re-inject everywhere.

---

## Shared block — inject as `{proficiency_taxonomy}`

```
PROFICIENCY SCALE (1-3):

1 = Entry
    Has seen the skill but cannot yet work with it unsupervised.
    Coursework, tutorials, bootcamp exercises, a follow-along project,
    or a single small script. Someone else made the structural decisions.

2 = Intermediate
    Can complete normal tasks in this skill independently, with occasional help.
    Has built something where they chose the structure themselves, or has used
    the skill on a real project, internship, or piece of work someone else relied on.

3 = Advanced
    Can handle non-obvious problems in this skill: debugging unfamiliar failures,
    making performance or design trade-offs, extending someone else's system,
    or being the person others ask about it.

A level is a claim about what the person can DO, not how long they have been doing it.
Time spent is not evidence.
```

---

## Boundary tests — the part that actually decides the score

Most applicants will land at Entry or Intermediate. That boundary is where the whole system's
discrimination comes from, so it gets explicit tests.

### Entry vs Intermediate (1 vs 2) — the decisive question

> **Did the applicant make the structural decisions, or follow someone else's?**

| Choose Entry (1) | Choose Intermediate (2) |
|---|---|
| Tutorial, course project, bootcamp assignment | Chose the architecture, schema or approach themselves |
| A clone built by following a guide | Solved a problem that had no ready-made walkthrough |
| Code exists but only as a single file or notebook | Someone other than the applicant used the result |
| Skill appears only in a skills list | Deployed it, or maintained it past the first version |

When the work looks like a follow-along, choose Entry.

### Intermediate vs Advanced (2 vs 3) — the decisive question

> **Is there evidence of judgment under difficulty?**

Advanced needs a visible sign of it: an optimization with a reason, a non-trivial bug
traced and fixed, a design trade-off explained, a substantial contribution to a codebase
they did not start, or others depending on their work in this skill.

Scale alone is not Advanced. A large tutorial project is still Entry.

### Tie-break rule

**When the evidence is ambiguous, choose the lower level.**
The system is allowed to under-rate. It is not allowed to place a student on work
they cannot do.

---

## Direction depends on the agent

The numbers mean the same thing everywhere, but the *sentence* differs by side.

**Profile agent** — what the applicant can do, from self-reported documents.
> "This applicant is at Entry / Intermediate / Advanced in this skill."
> Note: self-reported only. Never claim independent verification.

**Evidence agent** — what the public GitHub record supports.
> "GitHub evidence supports Entry / Intermediate / Advanced in this skill."
> Absence of evidence is `not_observed`, never a level below Entry and never a reduction.

**Catalog agent** — the minimum an applicant needs to do the work.
> "An applicant needs Entry / Intermediate / Advanced to complete this work with normal mentoring."
> "Intermediate required" means someone at Intermediate can do it independently;
> someone at Entry will struggle without heavy support.

---

## Why the project side must use the same scale

The whole system rests on comparing `applicant_level` against `required_level`.
That comparison is meaningless unless both are on the same ruler.

The scoring rubric reads the gap, not the match:

| Gap (required − applicant) | Meaning |
|---|---|
| −2 or −1 | Already beyond it. Low learning gain. |
| 0 | Comfortable fit. Moderate gain. |
| +1 | **The target.** Reachable stretch. Highest gain. |
| +2 | Likely too hard without heavy support. |

A perfect skill match is not the goal. A +1 gap on the skills that matter is.

---

## Not in scope for v0.1

- Sub-levels or half-points. Three levels (Entry, Intermediate, Advanced), stored as integers 1-3.
- Weighting skills by importance inside a project — that lives in `ProjectRecord`,
  not here.
- Separate scales for soft skills. If it cannot be evidenced, leave it out.
