# Intern-Assignment-Agent

NUS ISS Hackathon résumé extraction test using Docling.

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
