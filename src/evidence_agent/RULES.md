# Evidence agent rules

Generated from the code by `uv run python -m src.evidence_agent rules`, and
rewritten whenever the rules change. Do not edit by hand: follow a link to the
code, change it there, then regenerate. Levels use the shared scale in
[`data/proficiency_levels.md`](../../data/proficiency_levels.md): 1 Entry,
2 Intermediate, 3 Advanced.

## 1. Which evidence counts

- A skill signal counts only if its source is one of
  `file`, `language`, `manifest` ([`HARD_SOURCES`](../../src/evidence_agent/observe.py#L27)),
  with strength at least 0.5 ([`MIN_SIGNAL_STRENGTH`](../../src/evidence_agent/observe.py#L28)).
- Source strengths ([`SOURCE_STRENGTH`](../../generator/github/skill_map.py#L26)): `language` 1.0, `manifest` 0.9, `file` 0.6, `topic` 0.3, `repo_name` 0.2.
- A repository name or topic alone is never enough: the skill is then only
  weakly signalled, and reported as not observed ([`observe()`](../../src/evidence_agent/observe.py#L76)).
- Only the applicant's own work counts: not a fork, the applicant has commits,
  and in a shared repository at least 20% of them
  ([`_own_work()`](../../src/evidence_agent/observe.py#L47), [`MIN_RELEVANT_CONTRIBUTION_SHARE`](../../generator/github/signals.py#L260)).

## 2. The level of one repository ([`repo_level()`](../../src/evidence_agent/observe.py#L52))

- **Entry (1)** if any follow-along flag is set ([`FOLLOW_ALONG_FLAGS`](../../src/evidence_agent/observe.py#L30)):
  - `tutorial_name_hit`: repository name looks like a tutorial or clone (`*-clone`, `todo-app`, ...) ([code](../../generator/github/signals.py#L169))
  - `follow_along_phrase`: README says it follows a course or tutorial ("following along") ([code](../../generator/github/signals.py#L170))
  - `is_template`: generated from a template repository ([code](../../generator/github/signals.py#L172))
  - `notebook_only`: the only code is Jupyter notebooks ([code](../../generator/github/signals.py#L167))
  - `single_file_project`: at most one code file ([code](../../generator/github/signals.py#L168))
  - `single_commit`: at most one commit ([code](../../generator/github/signals.py#L164))
  - `all_commits_one_day`: every commit on a single day ([code](../../generator/github/signals.py#L165))
- **Entry (1)** also if fewer than 5 commits
  ([`MIN_COMMITS_INTERMEDIATE`](../../src/evidence_agent/observe.py#L29)), or fewer than 2 independent-work
  flags ([observe.py:61](../../src/evidence_agent/observe.py#L61)).
- **Intermediate (2)** with 5+ commits and at least 2
  independent-work flags ([`INDEPENDENT_WORK_FLAGS`](../../src/evidence_agent/observe.py#L33)):
  - `has_ci`: CI configuration (e.g. `.github/workflows/`) ([code](../../generator/github/signals.py#L178))
  - `has_tests`: a test directory or test files ([code](../../generator/github/signals.py#L179))
  - `has_docker`: a Dockerfile or compose file ([code](../../generator/github/signals.py#L180))
  - `deployed`: a homepage or deployment is set ([code](../../generator/github/signals.py#L181))
  - `multi_month_span`: commits span 60+ days, on 5+ active days ([code](../../generator/github/signals.py#L182))
  - `many_active_days`: commits on 8+ different days ([code](../../generator/github/signals.py#L183))
  - `used_by_others`: 3+ stars or 2+ forks ([code](../../generator/github/signals.py#L184))
  - `documented`: a README longer than 800 characters ([code](../../generator/github/signals.py#L187))
- **Advanced (3)** if Intermediate and either:
  - others depend on it: 3+ stars or 2+ forks ([code](../../generator/github/signals.py#L130),
    checked at [observe.py:69](../../src/evidence_agent/observe.py#L69)); or
  - sustained maintenance, commits spanning 90+ days on 10+ active days
    ([code](../../generator/github/signals.py#L126)), with 3+ fix/perf/refactor commits
    ([observe.py:71](../../src/evidence_agent/observe.py#L71)).

## 3. The level of a skill ([`observe()`](../../src/evidence_agent/observe.py#L76))

- The skill's observed level is its best repository's level; none if no
  repository counts ([observe.py:97](../../src/evidence_agent/observe.py#L97)).
- Evidence strength ([observe.py:99](../../src/evidence_agent/observe.py#L99)): **strong** if 2+
  repositories at level 2+, or any at level 3; **moderate** if one at level 2+,
  or 2+ repositories; **weak** if a single Entry repository, or only a
  repository name or topic; **none** otherwise.

## 4. The verdict ([`judge()`](../../src/evidence_agent/verify.py#L54))

| claimed vs observed | status |
| --- | --- |
| observed >= claimed | `verified` |
| observed = claimed - 1 | `partially_verified` |
| observed <= claimed - 2 | `conflicting` |
| nothing observed | `not_observed` (absence is never a penalty) |

Computed at [verify.py:71](../../src/evidence_agent/verify.py#L71).

## 5. When the model is asked ([`settled_by_rules()`](../../src/evidence_agent/evidence_graph.py#L124))

The rules settle a claim without the model when:
- GitHub already supports it (`verified`): a model could only agree.
- No repository shows the skill (`not_observed`, strength none): nothing to read.

Everything else, one or two levels short, or only weakly signalled, goes to the
model in one call per applicant, with only the repositories behind those claims
([`_prompt_parts()`](../../src/evidence_agent/evidence_graph.py#L250)).

## 6. How far the model is trusted ([`_accept()`](../../src/evidence_agent/evidence_graph.py#L341))

- A verdict with a level must cite at least one repository URL that exists in
  the profile; otherwise the rules' verdict is kept for that skill
  ([evidence_graph.py:346](../../src/evidence_agent/evidence_graph.py#L346)).
- The model may move at most 1 level(s) from the rules' level
  ([`MAX_LEVEL_SHIFT`](../../src/evidence_agent/evidence_graph.py#L78)).
- Where the rules found no repository, the model's level is capped at
  2 ([`UNSEEN_LEVEL_CAP`](../../src/evidence_agent/evidence_graph.py#L79)).
- The status is always recomputed from the levels, never taken from the model
  ([`_status()`](../../src/evidence_agent/evidence_graph.py#L334)).
- A missing or failing gateway, or output still invalid after correction,
  falls back to the rules ([`reconcile()`](../../src/evidence_agent/evidence_graph.py#L372)). Every verdict records
  `method` (`llm` or `rules`), the rules' own level, and notes on why.
