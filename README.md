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

Builds the dataset in `data/`: real public GitHub profiles, and synthetic
MIT-format resumes drafted from them. The files, identifiers, rules and privacy
guarantees are documented in [`data/README.md`](data/README.md).

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

Without a token everything still works, at 60 requests/hour instead of 5,000.
PDF rendering needs WeasyPrint's system libraries: `brew install pango`.

### 1. Build the GitHub corpus

```powershell
uv run python -m generator gh status    # where things stand, and the next command
uv run python -m generator gh sample    # find candidates for strata with empty slots
uv run python -m generator gh collect   # fetch queued candidates (resumable)
uv run python -m generator gh build     # grade profiles and fill stratum slots
uv run python -m generator gh stats     # skill coverage, and why profiles were rejected
```

Repeat until `gh status` reports `corpus complete`; its `next:` line always names
the command to run. Its `hit` column shows, per stratum, how many people found by
repository search turned out eligible for it; `collect` and `sample` fetch
`need / hit rate` people, so a stratum whose search rarely finds eligible people
automatically fetches more. Only `sample` and `collect` use the network. Responses are
cached, so both can be stopped and re-run, and `build` is free to re-run after
any rule change. `collect --refresh <logins>` rebuilds those people's raw data.

### 2. Generate the resumes

```powershell
uv run python -m generator re infoprompt --appids applicant0046 applicant0057 > prompt.md
```

Give `prompt.md` to ChatGPT or a subagent. It returns a single finished command,
which you run:

```powershell
uv run python -m generator re gen --appids applicant0046 applicant0057 --info '{...}' '{...}'
```

`--appids` and `--info` pair up by position; an info may also be `@file.json`.
`re gen -h` documents every field, in MIT Template A order. Only the name is
required: projects and skills are drafted from the applicant's real GitHub
evidence, and drafted projects are trimmed to fit one page.

Every generated PDF is recorded in `data/applicants.csv` together with the GitHub
profile it pairs with; generating again for the same applicant replaces the pair.

```powershell
uv run python -m generator re manifest                  # pairs so far, and who is still waiting
uv run python -m generator re remove applicant0046      # delete a pair; the profile stays
```

Without `--appids`, `re infoprompt` covers every placed applicant who has no resume yet.
