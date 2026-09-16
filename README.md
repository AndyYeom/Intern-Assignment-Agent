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

Builds the dataset: real public GitHub profiles, and synthetic MIT-format resumes
generated from them. One entry point, two command groups:

```powershell
uv run python -m generator gh --help   # GitHub collection
uv run python -m generator re --help   # resume generation
```

### Setup

Create `.env` in the repo root with a GitHub token (fine-grained, *Public
repositories (read-only)*, no extra permissions):

```
GITHUB_TOKEN=github_pat_...
```

Without a token everything still works at 60 requests/hour instead of 5,000.
PDF rendering needs WeasyPrint's system libraries: `brew install pango`.

### 1. Build the GitHub corpus

```powershell
uv run python -m generator gh status    # where things stand, and what to run next
uv run python -m generator gh sample    # find candidates, 4 per language stratum
uv run python -m generator gh collect   # fetch the planned profiles (resumable)
uv run python -m generator gh build     # normalise, and mark each profile usable or not
uv run python -m generator gh stats     # skill coverage, and why profiles were rejected
```

Repeat until `gh status` reports `corpus complete`. Its `next:` line always names
the command to run.

- **`sample`** searches ten strata, one per primary language, and fills the
  emptiest first. Each stratum gets `ceil(40 / 10) = 4` places plus 2 reserves.
  Re-running searches new account-creation date windows, so it finds new people.
  Every candidate examined, and why any was rejected, is kept in
  `data/githubs/candidates.json`.
- **`collect`** fetches only the 4 planned people per stratum, 5 repos each. It is
  the only stage that uses the network; responses are cached, so it can be
  stopped and re-run. `--all` collects every selected candidate instead.
- **`build`** costs nothing and can be re-run any time. A profile is **usable**
  only with at least 3 skill-relevant repos, 20 commits, 3 strongly evidenced
  skills and something readable. An unusable profile is replaced by a reserve
  on the next `collect`.

### 2. Generate the resumes

```powershell
uv run python -m generator re plan --batches 5   # split usable profiles into 5 exclusive batches
uv run python -m generator re brief --batch 1    # the authoring packet for batch 1
uv run python -m generator re draft --batch 1    # starter specs built from the real repos
```

Then author each draft in `data/resumes/specs/`:

1. Invent the identity: name, contact, school, major, graduation, `career_stage`
   (`student`, `intern`, `new_grad`, `switcher`) and any employment.
2. Rewrite the project bullets in resume voice.
3. Rename `_draft_<login>.json` to `<first>-<last>.json`.

Batches never share a profile, so several people or agents can author batches in
parallel. Record planted exaggerations separately; never in the spec.

```powershell
uv run python -m generator re verify     # fails if any profile is used twice
uv run python -m generator re render     # specs -> PDF, and update data/applicants.csv
uv run python -m generator re manifest   # who has a resume, and which profiles are unused
```

`data/applicants.csv` pairs every applicant with their GitHub profile and resume
PDF. It is the file downstream agents read. `re manifest --rebuild` regenerates
it from disk.

### Privacy

The GitHub side is real; the people on the resumes are invented. A resume never
carries the real person's name, bio, location, website or repository links, and
its GitHub handle is a slug of the invented name that resolves to nobody. The
real login is kept only in the profile JSON and `applicants.csv`, where the
evidence agent needs it.

### What is committed

| committed | not committed |
| --- | --- |
| `data/githubs/candidates.json`, `profiles/` | `data/githubs/raw/`, `.cache/` (large, reproducible) |
| `data/resumes/specs/*.json` | `data/resumes/specs/_draft_*.json` (placeholders) |
| `data/resumes/rendered/*.pdf` (~25 KB each) | `data/resumes/rendered/*.html` (duplicate of the PDF) |
| `data/applicants.csv` | `.env` |
