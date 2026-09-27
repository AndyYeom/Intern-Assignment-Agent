# Data notice

This repository contains a research and demonstration dataset built from
**public GitHub activity**, paired with **synthetic resumes**. This notice
explains where the data comes from, what was done to protect the people behind
it, and how to ask for removal. It is not legal advice, and it is not a software
license (see [License](#license) below).

## Why real GitHub data

The system checks what a resume *claims* against what a public commit record
*shows*. That comparison is only meaningful if one side is real, so the GitHub
side is collected from real public profiles and the resume side is invented.

## What was collected

- Only data that GitHub makes public, fetched through the documented GitHub
  REST API within its published rate limits: public repositories, languages,
  dependency manifests, file structure, commit metadata, stars and forks.
- No private data, no authentication beyond an optional read-only token, and no
  repository source code is stored in this repository.
- Candidates were found through GitHub repository search and filtered by
  account criteria (for example 4-80 public repositories, at most 400
  followers); see [`legacy/README.md`](legacy/README.md).

## How it was cleaned

- **Profiles** (`legacy/githubs/profiles/`) are named by a pseudonymous ID
  (`applicant0001`, ...), not by username. They hold no name, bio, company,
  location, website, avatar or email.
- **Free text** copied from GitHub (README excerpts, repository descriptions,
  commit messages) has email addresses and phone numbers replaced
  ([`generator/privacy.py`](generator/privacy.py)); a user's profile README is
  not kept at all.
- **Raw API responses** stay on the collector's machine only (git-ignored) and
  are never published.

## How the synthetic resumes were made

- Every resume (`legacy/resumes/`) carries an **invented identity**: name,
  schools, employers, clubs, awards, city and contact details are fictional.
- Contact details can only use domains reserved for examples (RFC 2606 /
  RFC 6761, such as `example.com`), so they cannot reach a real person. The
  printed GitHub link points to `github.example.com/<invented-handle>`, never to
  a real account, and the real username is removed from any resume text.
- Each applicant is given a career direction from
  [`resources/career_path.md`](resources/career_path.md) (15 career families),
  assigned deterministically and spread evenly across the corpus. The direction
  shapes the story (objective, major, coursework, activities); the technical
  claims stay tied to the person's real public evidence, except for 10
  deliberately exaggerated claims used to evaluate the evidence agent.
- A resume therefore does **not** describe the real account holder, and nothing
  in it should be read as a statement about them.

## What is deliberately kept

The GitHub username and repository URLs remain inside each profile and in
`legacy/applicants.csv`, and are shown to managers in the application, because
the evidence agent must cite the repositories it relied on. This makes the
dataset **pseudonymous, not anonymous**: a profile can be linked back to a
public GitHub account.

## Acceptable use

- Use this dataset only to develop, test and evaluate this system, or for
  comparable non-commercial research and teaching.
- Do not use it to contact, profile, rank, recruit, or make any decision about
  the real account holders, and do not combine it with other data to identify
  them further.
- Do not republish the profiles as a list of people, sell them, or use them for
  spam. Use of GitHub data is also subject to GitHub's
  [Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service)
  and [Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies),
  including their rules on information usage.
- Verification results (for example "not observed" or "conflicting") compare a
  **synthetic** claim with public signals. They are not an assessment of the
  real person's skills.

## Removal requests

If your public GitHub account is included and you want it removed, open an
issue in this repository asking for removal of your username (no other personal
detail is needed), or contact the repository maintainers. We will delete the
profile, the resume and evidence derived from it, its row in
`legacy/applicants.csv`, and the corresponding record in any deployment we run,
and exclude the account from future collection.

## License

No open-source license has been chosen for this repository yet. Until one is
added, the code is not licensed for reuse, and the GitHub data remains subject
to its owners' rights and GitHub's terms, whatever license is later applied to
the code.
