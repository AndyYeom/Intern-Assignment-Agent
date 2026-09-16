# data/

Three inputs, one shared ruler.

| directory | what it holds | how it is produced | real or synthetic |
| --- | --- | --- | --- |
| `githubs/` | public GitHub profiles | `generator gh collect` + `build` | **real** — collected from the public API |
| `resumes/` | applicant resumes, MIT format | `generator re draft` + `render` | **synthetic** — generated from `githubs/` |
| `projects/` | project records | curated from app-ideas / GSoC lists | curated |

## applicants.csv

The index that pairs the two halves. One row per applicant:

| column | meaning |
| --- | --- |
| `idx` | stable integer id; survives re-renders |
| `first_name`, `last_name` | the invented identity |
| `github_login` | the real profile it was generated from |
| `github_profile` | path to the collected profile JSON |
| `resume_pdf`, `resume_html` | paths to the rendered resume |
| `spec` | path to the resume spec it was rendered from |
| `career_stage`, `batch` | `student`/`intern`/`new_grad`/`switcher`; authoring batch |
| `rendered_at` | UTC timestamp |

`generator re render` upserts into it automatically, keyed on `github_login`, so
it also answers "has this profile been used yet". Paths are repo-relative.

It is derived, never authoritative: `generator re manifest --rebuild`
regenerates it from the spec and rendered files on disk.

It deliberately carries **no column marking a planted exaggeration** — that
answer key belongs with whoever plants them, not in the index the evidence agent
reads.

`taxonomy.json` and `proficiency_levels.md` are the shared ruler. Every agent
injects the same copy; a divergence between them makes the gap arithmetic
downstream meaningless.

## Sampling is additive, and selection is not usability

`gh sample` is deliberately **not** idempotent. Each run skips every login
already examined and consumes fresh account-creation date windows, so re-running
finds people earlier runs never saw. The spent windows are recorded in
`githubs/candidates.json` under `consumed`.

This matters because **a selected candidate is not necessarily a usable one**.
The sampler filters on user-level counts — repo count, followers, account age —
which someone can satisfy with eight empty forks. Whether a profile carries
enough evidence is only knowable after collection, so `build` assesses each one
and records a verdict:

| check | why |
| --- | --- |
| `skill_relevant_repos` >= 3 | repos that are real skill work (rules below) |
| `total_commits` >= 20 | enough history to read a pattern from |
| `distinct_skills` >= 3 | at language/manifest strength, not repo-name guesses |
| `readable_repos` >= 1 | something with a README or a manifest |

A repo is **skill-relevant** only if every rule holds:

- not a fork, and not the `username/username` profile-README repo
- its name does not *end* in a non-project word (`dotfiles`, `notes`,
  `cheatsheet`, `config`, `awesome-*`, ...); `config-parser-rs` is fine
- at least 3 code files, or at least 2 notebooks
- at least 2 KB in a language that maps to a taxonomy skill (Markdown and TeX do not)
- at least one strong skill signal: a language, a dependency or a file, not a
  topic or a word in the name
- at least 3 commits by the person

Each repo's verdict and failed rules are stored under `relevance` in its
profile, and `gh stats` counts which rules reject the most repos.

The loop is therefore: `sample` -> `collect` -> `build` -> check `stats` -> if
usable < 40, `sample` again. The thresholds are starting guesses; `gh stats`
prints the rejections with reasons so they can be tuned.

## Real people, invented identities

Resumes carry a fabricated name, and the drafter never copies the real person's
name, bio, location or personal site into one. The GitHub handle printed on a
resume is a slug of the invented name and resolves to nobody — a fabricated
identity must not link to a real stranger's account.

The real login is kept in `applicants.csv` and in the profile JSON, because the
evidence agent has to join a resume back to the record it was generated from,
and its output is required to cite repository links.

Repository licences are recorded per repo and summarised by `gh stats`. Note
that what is collected is factual metadata — commit timestamps, language byte
counts, file paths, dependency names — not copyrightable source, and no
repository content is redistributed in this repo.

## Why only the GitHub side is real

The whole system rests on comparing what a resume *claims* against what the
commit record *shows*. That comparison only means anything if one side is
ground truth, so `githubs/` is collected rather than invented. Resumes are
synthetic because we need to control what is claimed — including the planted
exaggerations the evidence agent is measured against.

`githubs/raw/` and `.cache/` are gitignored: large, and fully reproducible from
`githubs/candidates.json` plus the collector code.
