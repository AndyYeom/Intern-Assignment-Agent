# Intern-Assignment-Agent

NUS ISS Hackathon résumé extraction test using Docling.

## Setup

Install the locked project dependencies with `uv`:

```powershell
uv sync
```

## Extract a résumé

```powershell
uv run python -m src.profile_agent.pdf_extractor data/sample_cv.pdf --output output/sample_cv.md
```

The command prints the input filename, extracted character count, output path, and a 500-character Markdown preview.

## Tests

```powershell
uv run pytest
```

## Data generator

Builds the evidence corpus: public GitHub profiles, and MIT-format resumes
generated from them.

```powershell
uv run python -m generator --help
```

### GitHub collection (`gh`)

```powershell
uv run python -m generator gh doctor              # check rate budget
uv run python -m generator gh sample --target 40  # select the corpus
uv run python -m generator gh collect             # fetch raw payloads
uv run python -m generator gh build               # raw -> profiles
uv run python -m generator gh stats               # taxonomy coverage report
```

`sample` selects profiles programmatically through the GitHub Search API,
stratified by primary language, and records every candidate it examined —
including rejections and their reasons — in `data/githubs/candidates.json`.

`collect` is the only expensive stage and the only one that touches the network.
Every response is cached on disk with its ETag, so the stage is resumable after a
rate-limit wall and re-runs are nearly free. `build` reads only the cache, so
schema and heuristic changes cost nothing to re-apply.

Set `GITHUB_TOKEN` in `.env` for 5,000 requests/hour. Without one the collector
still works at 60/hour, roughly 30 hours for a cold run of 40 profiles.

### Resume generation (`re`)

```powershell
uv run python -m generator re plan --batches 5   # exclusive split of the corpus
uv run python -m generator re brief --batch 1    # authoring packet for one agent
uv run python -m generator re draft --batch 1    # first-pass specs from GitHub
uv run python -m generator re verify             # no profile used twice
uv run python -m generator re render             # specs -> HTML + PDF
uv run python -m generator re manifest           # the applicant index
```

Resumes follow the MIT CAPD format. Section order varies by `career_stage`
(`student`, `intern`, `new_grad`, `switcher`).

`draft` fills projects and skills from the real repository record; the identity
half — name, school, major, graduation, employment — is supplied per person in a
`ResumeInfo`, since none of it is derivable from GitHub.

`plan` partitions the corpus so each profile belongs to exactly one batch, which
lets several authors work in parallel without collisions. `verify` re-checks the
written specs and fails if any profile was used twice.

`render` upserts each applicant into `data/applicants.csv`, the index pairing
each GitHub profile with its resume. Writes take an exclusive lock, so parallel
renders cannot corrupt it, and `manifest --rebuild` regenerates it from disk.

PDF output needs WeasyPrint's system libraries (`brew install pango`); without
them `render` writes HTML only.
