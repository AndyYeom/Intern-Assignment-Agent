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
