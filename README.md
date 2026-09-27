# Intern-Assignment-Agent

NUS ISS Hackathon applicant profiling, GitHub evidence, project catalog and assignment components.

## Local demo and verification

After `uv sync --locked`, run the checked-in sample workflows with visible progress:

```sh
uv run python scripts/run_local_demo.py --test
```

This runs six controlled catalog scenarios, rules-only evidence verification of a
saved applicant profile, the 20-student/4-project matching fixture, and the test
suite. Logs are saved in `data/runs/local-check/`; matching JSON is saved under
`src/matching/artifacts/`. It stops with a nonzero exit code on failure. Omit
`--test` for a shorter demo. No API keys or model calls are required for this mode.

These are **separate component checks**, not an integrated live-agent workflow.
`pipeline.orchestrator` still uses stub agents; its `llm_calls` field counts stub
invocations in demo mode, not actual paid requests. All assignment results are
drafts for mentor review. The web application is described in the next section.

For live profile/evidence calls, configure the three `LLM_*` gateway settings below.
The live catalog workflow uses `OPENAI_API_KEY` when it is set, otherwise the same
`LLM_*` gateway; the admin terminal also needs administrator credentials (see `.env.example` and `python -m project_catalog_agent.admin_setup --help`).
Profile/evidence proficiency is 1–3; the older matching fixtures use 1–5.
The connected preview below uses 1–3 on both sides without rescaling.

## Web application (MVP)

A PostgreSQL-backed API and a Next.js UI around the agent pipeline:

```
Applicant ─┐                      ┌──────────────┐
Manager  ──┴─► Next.js frontend ─►│ FastAPI API  │─► PostgreSQL (system of record)
             (frontend/, :3000)    │ (src/backend,│─► LocalStorage (data/uploads)
                                   │  :8000)      │─► profile → GitHub → evidence → resolve
                                   └──────────────┘   scoring + genetic-algorithm optimizer
```

- **Applicants** submit name, email, GitHub URL, optional portfolio URL and a PDF
  resume at `/apply`. The API stores the record and resume, then runs the existing
  agents in the background: profile agent (resume → skills), GitHub collection,
  evidence agent (claims vs. GitHub), and `pipeline/resolve_profile.py` (final
  level per skill). Every stage is recorded in `agent_runs`.
- **Managers** use `/manager` to inspect applicants (skills, levels, evidence),
  edit projects and their **roles** (capacity plus required, preferred and
  learning-opportunity skills), start assignment runs and approve, reject or
  move placements.
- **Assignment runs** reuse the existing matching engine unchanged. It has no
  notion of roles, so each project role is given to it as one matching unit
  (team size = role capacity). The result is a global optimization over
  applicant × role, not a greedy one. Runs, pairwise scores and placements are
  stored. A manager override changes the placement but keeps the solver's
  original role, so run history is never rewritten.

### Quick start (Docker)

```sh
cp .env.example .env        # fill in LLM_GATEWAY_URL / LLM_GATEWAY_API_KEY / LLM_MODEL
docker compose up --build
```

| URL | What |
|---|---|
| http://localhost:3000/apply | Applicant form |
| http://localhost:3000/manager | Manager dashboard |
| http://localhost:8000/health | Liveness (no dependencies) |
| http://localhost:8000/ready | Readiness (checks the database) |
| http://localhost:8000/docs | OpenAPI docs |

Compose starts `postgres` (host port 5433, so a local PostgreSQL on 5432 keeps
working), then the one-off `migrate` service (`alembic upgrade head` followed by the
legacy import), then `backend` and `frontend`. The database lives in the
`postgres-data` volume and uploads in the `uploads` volume;
`docker compose down -v` deletes both.

Without the `LLM_*` settings the stack still starts and the imported applicants
can be assigned, but new applications fail at the profile stage.
`GITHUB_TOKEN` is optional. Without a valid one, GitHub data is collected
anonymously (60 requests/hour, roughly one applicant); when that fails, skills
stay "unverified" rather than failing the application.

### Local development without Docker

```sh
docker compose up -d postgres
uv sync
uv run alembic upgrade head
uv run python -m backend.legacy_import
uv run uvicorn backend.main:app --reload --port 8000
cd frontend && npm install && npm run dev      # http://localhost:3000
```

### Database and migrations

The schema is managed by Alembic (`src/backend/migrations`, models in
`src/backend/db/models.py`):

- **Applicants:** `applicants`, `applicant_documents`, `applicant_skills`,
  `applicant_skill_evidence`, `agent_runs`
- **Skills:** `skills` (taxonomy ids from `data/taxonomy.json`)
- **Projects:** `projects`, `project_roles`, `project_role_skills`
- **Assignments:** `assignment_runs`, `applicant_role_scores`, `assignments`

Proficiency uses the shared 1–3 scale. A final level of 0 means the claim was
contradicted by GitHub evidence. Case-insensitive unique indexes cover applicant
email, project name and skill name. Assignment history uses `RESTRICT` foreign
keys, so projects, roles and applicants that appear in a run cannot be deleted.
Archive a project instead.

```sh
uv run alembic upgrade head                           # apply
uv run alembic revision --autogenerate -m "change"    # after editing models.py
```

### Importing the legacy data

`python -m backend.legacy_import` loads the file-based data into PostgreSQL:

| Source | Becomes |
|---|---|
| `data/taxonomy.json` | skills |
| `data/applicants.csv` + `data/resumes/specs/*.json` | applicants |
| `data/resumes/rendered/*.pdf` | resume documents (copied into storage) |
| `data/githubs/profiles/*.json` | GitHub snapshots |
| `data/evidence/*.json` | resolved skills and evidence |
| `data/projects/seed_projects.json` | sample projects with roles |

The seed projects are demo data, not client projects.

The import is idempotent: re-running updates changed applicants, never
overwrites projects that already exist, and never modifies the source files. It
prints inserted/updated/unchanged/skipped/failed counts, then source-vs-database
checks, and exits non-zero on malformed data or a mismatch. The current data
imports 59 skills, 100 applicants with resumes, 778 resolved skills with 1,339
evidence rows, and 4 projects with 10 roles.

### Tests

```sh
docker compose up -d postgres
docker compose exec postgres createdb -U utechia utechia_test   # once
uv run pytest                      # full suite; tests/backend needs PostgreSQL
cd frontend && npm run lint && npm run build
```

`tests/backend` applies the real migration to `utechia_test`
(`TEST_DATABASE_URL` overrides the location) and is skipped when PostgreSQL is
unreachable.

### Deploying on AWS ECS

Two images, both built from this repository:

| Service | Build | Port | Health check | Command |
|---|---|---|---|---|
| backend | `docker build -t backend .` | 8000 | `GET /health` | `uvicorn backend.main:app --host 0.0.0.0 --port 8000` (image default) |
| frontend | `docker build -t frontend frontend` | 3000 | `GET /apply` | `node server.js` (image default) |

Backend environment:

| Variable | Notes |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://user:pass@<rds-host>:5432/utechia`; pass it as a secret |
| `CORS_ALLOWED_ORIGINS` | The frontend's public origin |
| `LLM_GATEWAY_URL`, `LLM_GATEWAY_API_KEY`, `LLM_MODEL` | Pass as secrets |
| `GITHUB_TOKEN` | Optional; pass as a secret |
| `LOG_LEVEL` | Optional |
| `STORAGE_ROOT` | Optional |

Frontend environment: `API_BASE_URL` is the backend URL as the **browser** sees
it (e.g. the ALB path or hostname). It is read at request time, so one image
works in every environment.

Other points to plan for:

- **Migrations:** run `alembic upgrade head && python -m backend.legacy_import`
  as a one-off task with the backend image before rolling out a new revision.
  Do not run migrations on every task start.
- **Logging:** logs go to stdout, which the `awslogs` driver collects. They
  include applicant references and run ids, never resume contents.
- **Image size:** the backend image is about 2.5 GB, mostly CPU-only torch for
  Docling's PDF layout model. The model is baked in and `HF_HUB_OFFLINE=1`, so
  tasks never download it. Give the task at least 2 vCPU / 4 GB: resume
  processing runs inside the API process.
- **Outbound network:** the backend needs HTTPS access to the LLM gateway and
  `api.github.com`.

> **Resume storage is not durable on ECS.** Uploaded resumes are written by
> `LocalStorage` to the task's own filesystem, which is lost whenever a task is
> replaced. Before accepting real applicant submissions, replace `LocalStorage`
> in `src/backend/storage.py` with S3 or another durable object store. Callers
> only hold opaque storage keys, so the change is confined to that module.

### Known limitations

- **No authentication.** `/api/manager/*` is open; do not expose it publicly as is.
- **Processing is in-process.** Applicant processing (several LLM calls, a few
  minutes) and assignment runs are FastAPI background tasks in the API process.
  A task restart mid-run leaves the applicant "processing" or the run "running";
  use Reprocess or start a new run.
- **Few seats get filled.** The optimizer's objective averages fit and growth
  over placed applicants and gives filled seats a 10% weight. It often leaves
  seats empty even when qualified applicants exist (see `src/matching/scoring.py`).
- **GitHub profiles are rebuilt on disk.** Profiles collected for new applicants
  are written to `data/githubs/profiles/`, and a copy is kept in the database so
  a fresh container can rebuild the file.
- **No catalog agent in the UI.** Role requirements are edited by hand; the
  catalog agent (text → requirements) is not wired into the UI yet.

## Connected agent preview

```sh
# Replays saved profile outputs and explicit synthetic catalog extraction fixtures.
uv run python -m pipeline.integrated --mode replay --output-dir data/runs/connected-01

# New resume/PDF and catalog model calls; provide a real local environment file.
uv run python -m pipeline.integrated --mode live --env-file /path/to/.env --output-dir data/runs/live-01
```

Use a new output directory for each run. `--input` accepts a manifest shaped like
`data/integration-demo.json`; paths inside it are repository-relative. The default
contains two existing applicants and two small synthetic projects. Each project
must explicitly specify capacity; it is never invented by a model. Preview runs
are limited to five applicants and five projects.

Unlike `run_local_demo.py`, this carries the **same applicants and projects**
through profile output → the real evidence graph → profile resolution → catalog
normalization/build/validation → schema adapters → scoring → the existing GA.
Replay replaces only profile extraction and catalog extraction with declared
fixtures. Live invokes `evaluate_resume` and `LLMRequirementExtractor`; evidence
may fall back to rules, which is recorded in `evidence.json`. Both modes use the
existing collected GitHub corpus, not fresh GitHub API collection. Live needs the
three `LLM_*` settings. Catalog extraction uses OpenAI if `OPENAI_API_KEY` is set
(`OPENAI_MODEL` is optional), and the `LLM_*` gateway otherwise; `status.json`
records which one ran as `catalog_llm`.

Adapters preserve the common 1–3 scale, normalize aliases, retain unmapped skill
warnings, and reject unresolved catalog requirements. The matching taxonomy is
flat so unrelated skills in the same category are not treated as interchangeable.
`scores.json` records pairwise fit and per-skill growth diagnostics; the existing
optimizer still uses its existing fitness function. It is not a new LLM scoring
or critic agent, and its pedagogical scoring policy still needs evaluation.

Artifacts include source profiles, evidence with links, resolved skills, catalog
validation, matching inputs, pairwise scores, status, and `assignment-draft.json`.
Exit codes: 0 = complete draft, 1 = failure, 2 = applicants remain unassigned.
No result is published or approved. This is a preview that lists all three human
reviews as pending; production review/resume gates and a critic are not yet wired.
Live provider behavior must be tested with real credentials before calling the
full AI workflow validated.

## Setup

Install the locked project dependencies with `uv`:

```powershell
uv sync
```

Create a `.env` file at the repository root with the gateway settings:

```dotenv
LLM_GATEWAY_URL=https://api.softwaresystems.app
LLM_GATEWAY_API_KEY=replace-with-your-provided-key
LLM_MODEL=global.anthropic.claude-sonnet-4-5-20250929-v1:0
```

The gateway authenticates using the `X-API-Key` header, not AWS credentials. Missing values raise a clear configuration error before the model is invoked.

## Applicant profile workflow

The profile agent uses a deterministic two-node LangGraph workflow:

1. `extract_documents` validates the résumé PDF, converts it with the existing Docling extractor, and reads the optional `.pdf`, `.md`, or `.txt` portfolio.
2. `evaluate_applicant` builds the prompt, calls the Ollama-compatible gateway, validates the JSON response with Pydantic, and retries only on malformed output or transient gateway failures.

Scores come from self-reported résumé and portfolio content only. They are never independent verification.

## Extract a résumé

```powershell
uv run python -m src.profile_agent.pdf_extractor data/sample_cv.pdf --output output/sample_cv.md
```

The command prints the input filename, extracted character count, output path, and a 500-character Markdown preview.

## Evaluate an applicant profile

With a portfolio:

```powershell
uv run python -m src.profile_agent.profile_graph data/sample_cv.pdf --applicant-id APP-001 --portfolio data/sample_portfolio.pdf --ocr --output output/applicant-profile.json
```

Without a portfolio:

```powershell
uv run python -m src.profile_agent.profile_graph data/sample_cv.pdf --applicant-id APP-001 --output output/applicant-profile.json
```

When `--output` is omitted, the JSON is written to stdout as machine-readable output. Progress and errors are sent to stderr, while stdout remains valid JSON.

Supported portfolio formats are `.pdf`, `.md`, and `.txt`. Unsupported extensions are rejected before the LLM is called.

Large extracted résumés or portfolios may trigger a gateway request-size rejection. The code raises a clear error instead of silently truncating content, because silent truncation can distort proficiency scores.

## Troubleshooting

- Missing gateway configuration: ensure `.env` contains `LLM_GATEWAY_URL`, `LLM_GATEWAY_API_KEY`, and `LLM_MODEL`.
- Authentication failures: verify the gateway key is valid and that the request includes the `X-API-Key` header.
- Invalid JSON responses: the profile agent retries a bounded number of correction passes, then raises an `ApplicantEvaluationError` if the output still fails Pydantic validation.

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

## Evidence agent

Verifies each claimed skill against the applicant's GitHub profile, applying the
boundary tests in `data/proficiency_levels.md` to the collected signals. Every
claim gets `verified`, `partially_verified` (one level short), `conflicting` (two
levels short) or `not_observed` (nothing to judge; absence is never a penalty),
with the observed level, evidence strength and repository links.

```powershell
uv run python -m src.evidence_agent verify                       # all applicants -> data/evidence/
uv run python -m src.evidence_agent verify --claims output/profiles  # use the profile agent's JSON
uv run python -m src.evidence_agent plant                        # plant 10 exaggerations (once)
uv run python -m src.evidence_agent eval                         # how many were caught
```

### The agent: after the profile agent, LLM bounded by rules

`src/evidence_agent/evidence_graph.py` mirrors `src/profile_agent/profile_graph.py`
(a compiled LangGraph, one entry function, a CLI) and runs after it, since it
verifies A's verdicts:

```python
profile = evaluate_resume(pdf, applicant_id="applicant0001")   # agent A
report = evaluate_github("applicant0001", profile)             # agent C
report.payload()   # {applicant_id, skill_verification: [...]} for resolve_profile
```

`load_inputs -> assess_rules -> verify_with_llm -> reconcile`:

- **assess_rules** reads every claim deterministically, and settles the ones
  that need no judgment: GitHub already meets the claim, or no repository
  touches the skill.
- **verify_with_llm** sends only the remaining claims, with only the
  repositories behind them, to the same Ollama gateway as the profile agent
  (`LLM_GATEWAY_URL`, `LLM_GATEWAY_API_KEY`, `LLM_MODEL`), with the shared scale
  from `data/proficiency_levels.md` verbatim in the prompt.
- **reconcile** keeps a model verdict only if it cites repositories that exist
  and stays within one level of the rules; otherwise that skill falls back to
  the rules, as does everything when the gateway is missing or fails.

Every verdict carries `method` (`llm` or `rules`), the rules' own reading
(`rule_observed_level`, `rule_status`) and `notes` saying why; the report's
`trace` records which skills and repositories the model saw, and the tokens it
used. On the 100 applicants, 18% of claims need the model, 68 applicants need
one call each, and prompts are 88% smaller than sending every claim and repo.

A's free-text skill names are mapped onto `data/taxonomy.json` ids; names that
match nothing are listed in `unmapped_claims` and never verified.

```powershell
uv run python -m src.evidence_agent.evidence_graph applicant0001 --profile a.json --payload
uv run python -m src.evidence_agent.evidence_graph applicant0001 --profile a.json --rules-only
```

Without `--claims`, claims are read literally from each resume spec: a stated
level such as `Python (Advanced)`, otherwise Intermediate when the skill appears
in a project or job, and Entry when it appears only in the skills list.
