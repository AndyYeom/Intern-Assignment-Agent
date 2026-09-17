# data/

The dataset: real GitHub evidence, synthetic resumes, curated projects, and the
shared ruler every agent scores against. How to (re)generate it is in the
repository README; this file is the data contract.

| path | holds | real or synthetic |
| --- | --- | --- |
| `taxonomy.json`, `proficiency_levels.md` | the shared skill list and 1-3 scale; every agent injects the same copy | — |
| `githubs/` | public GitHub profiles | **real**, collected from the public API |
| `resumes/` | applicant resumes, MIT format | **synthetic**, drafted from `githubs/` |
| `projects/` | project records | curated |
| `applicants.csv` | one row per applicant, pairing profile and resume | index |
| `static/` | placeholder resume photo | — |

Only the GitHub side is real, on purpose. The system compares what a resume
*claims* with what the commit record *shows*, which only means something if one
side is ground truth. Resumes are synthetic so that what they claim, including
the planted exaggerations, is controlled.

## Identifiers

Every file joins on one key: **`applicant_id`** (`applicant0001`, ...). It is
assigned the first time a profile is built, stored on that person's record in
`githubs/candidates.json`, and never changes or gets reused. The GitHub login is
kept as a field (repository URLs contain it anyway), never used as a key.

## githubs/

| file | contents | committed |
| --- | --- | --- |
| `candidates.json` | everyone examined, with inclusion criteria, search queries, the repository that surfaced them, reject reasons, date windows searched, and applicant IDs | yes |
| `profiles/<applicant_id>.json` | normalised evidence per person | yes |
| `corpus.json` | which applicants fill which stratum slot, and at which tier | yes |
| `raw/` | verbatim API payloads | no: large, reproducible |

### Sampling

Candidates are the owners of non-fork repositories (`fork:false size:>=100
stars:0..50`) whose primary language belongs to a stratum, found through GitHub
repository search. Searching *users* by language was dropped: it matches anyone
with any repo in that language, forks included, and for Go found nobody who wrote
Go. Each person must then pass the account filters (4-80 public repos, at most
400 followers, account 6 months to 7 years old). Earlier user-search candidates
are kept, marked `method: users`.

### Usability tiers

A profile is graded when built:

| tier | requires |
| --- | --- |
| relaxed | 3+ skill-relevant repos, and 1+ repo with a README or manifest |
| strict | relaxed, plus 20+ commits and 3+ skills evidenced by a language, dependency or file |
| unusable | anything less |

A repo is **skill-relevant** when every rule holds: not a fork; its name does not
*end* in a non-project word (`notes`, `dotfiles`, `config`, ...; `config-parser`
is fine) and it is not the `username/username` profile page; at least one code
file or notebook; at least 2 KB in a language that maps to the taxonomy; at least
one strong skill signal; at least one commit by the person; and, in a shared
repo, at least 20% of the commits. Each repo stores which rules failed under
`relevance`.

### Commit attribution

GitHub only links commits made with an email tied to the account. On a repo the
person owns, unlinked commits are credited to them (`attribution: sole_author`)
only when no other GitHub account contributed, at most one unlinked identity
exists, and the history was not imported (nearly all commits dated long before
the repo was created, as when a tutorial is cloned and re-pushed). Otherwise
`attribution` is `author`, or `refused_imported_history`.

### Slots

Ten strata, `ceil(40 / 10) = 4` slots each. A person is not tied to the search
that found them. Each gets a **probability for every stratum**: each
skill-relevant repo spreads one unit across the strata it shows evidence for,
weighted by language bytes (at least 1 KB), with skill evidence also counting: a
`react-native` or Capacitor dependency, a `pubspec.yaml`, an `AndroidManifest.xml`
or `.xcodeproj`, a `go.mod`. A Go backend outweighed by TypeScript still carries
Go probability.

| tier for a stratum | requires |
| --- | --- |
| strict | strict profile, and 2+ repos mainly in the stratum (primary language or 25%+ of bytes) |
| relaxed | 1+ repo mainly in the stratum |
| partial | any evidence at all |

An optimal assignment fills the slots, in priority order: as many slots as
possible; never drop anyone who already has a resume; strict, then relaxed,
then partial; keep committed people in their previous stratum; and least
surprise, minimising `-log2 p(stratum)` so each person lands where their
evidence is most concentrated. `search_stratum` on a profile records which search
*found* the person, not the slot they fill.

## resumes/

| path | contents | committed |
| --- | --- | --- |
| `specs/<applicant_id>.json` | the full resume content, as generated | yes |
| `rendered/<applicant_id>.pdf` | the resume, MIT Template A, one page, ~20 KB | yes |
| `raw/<applicant_id>.html` | local preview of each PDF | no |

Every PDF is written by `generator re gen`, which records its row in
`applicants.csv` first: no resume PDF exists without a pair. Each PDF also carries
its `applicant_id` in its document Keywords metadata.

## applicants.csv

| column | meaning |
| --- | --- |
| `applicant_id` | the key |
| `first_name`, `last_name` | the invented identity |
| `github_login` | the real account the resume was drafted from |
| `github_profile` | `data/githubs/profiles/<applicant_id>.json` |
| `resume_pdf`, `spec` | the rendered resume and the spec it came from |
| `career_stage`, `batch` | `student`, `intern`, `new_grad` or `switcher`; authoring batch |

Written by `generator re gen` under a lock, sorted by `applicant_id`, with no
timestamps, so regenerating an unchanged resume produces no diff.
`generator re manifest --rebuild` regenerates it from disk. It deliberately has
no column marking planted exaggerations: that answer key must not sit in the
index the evidence agent reads.

## evidence/ and eval/

| path | contents |
| --- | --- |
| `evidence/<applicant_id>.json` | the evidence agent's report: one verification per claimed skill, plus skills observed but not claimed |
| `eval/planted_exaggerations.json` | the answer key: 10 resumes given an Advanced claim that GitHub does not support |
| `eval/summary.json` | how many planted exaggerations were caught, and how many unplanted claims were flagged |

Half the plants inflate a skill the person used only thinly (the fewest commits);
half claim a skill with no evidence at all. They are chosen from the collector's
raw skill evidence, not from the agent's judgement, and the key is kept out of
`applicants.csv`.

## Privacy

Collected through the documented public REST API only; no repository source is
stored in this repo.

- **Profiles** hold no name, bio, company, location, website, avatar or email.
  Email addresses and phone numbers are scrubbed from README excerpts, repo
  descriptions and commit messages, and the `username/username` profile README is
  not kept at all.
- **Resumes** carry an invented identity. They never show the real login: the
  printed GitHub handle is a slug of the invented name, repository links are not
  rendered, and a repo named after its owner becomes "Personal Website".
- **Kept deliberately**: the login and repository URLs, in profiles and
  `applicants.csv`, because the evidence agent must cite repositories.
- **Local only**: `githubs/raw/` and `.cache/` hold full API responses, including
  profile fields removed above. Both are gitignored; delete them to purge.
