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

## Why only the GitHub side is real

The whole system rests on comparing what a resume *claims* against what the
commit record *shows*. That comparison only means anything if one side is
ground truth, so `githubs/` is collected rather than invented. Resumes are
synthetic because we need to control what is claimed — including the planted
exaggerations the evidence agent is measured against.

`githubs/raw/` and `.cache/` are gitignored: large, and fully reproducible from
`githubs/candidates.json` plus the collector code.
