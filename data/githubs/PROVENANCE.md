# GitHub corpus — provenance and scope

## What this is
40 public GitHub profiles of students and junior developers, used to verify
skill claims made in resumes. Collected by `generator/`.

## How the people were selected
Programmatically, via the GitHub Search API, stratified by primary language.
The exact queries and the inclusion criteria are recorded in `candidates.json`,
together with every candidate that was examined and rejected, and the reason.
No profile was hand-picked.

## What is collected
Public metadata only, through the documented public REST API:
profile fields, repository metadata, language byte counts, file paths,
dependency manifests, README excerpts, and commit timestamps and messages.

## What is not collected
- No private data of any kind; no authenticated-only endpoints.
- No repository source code is vendored into this repository.
- Public email addresses are dropped at collection time.

## What is tracked in git
`profiles/` (normalised), `candidates.json` and `index.json`.
`raw/` and the HTTP cache are ignored — they are large and fully reproducible
from `candidates.json` plus the collector code.

## Re-running
```
python -m generator.cli sample
python -m generator.cli collect
python -m generator.cli build
```
