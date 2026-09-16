"""Draft a ResumeSpec from a GitHubProfile.

Produces an honest first pass: every project entry and skill here is backed by
something actually in the repo record. An authoring agent then rewrites the
prose, and - for the 10 designated resumes - introduces the exaggerations.

Keeping the draft honest matters. It means any exaggeration is a deliberate,
recorded edit rather than an artefact of the drafter, so the day-7 count is
measuring detection rather than noise.
"""
from __future__ import annotations

from datetime import datetime

from generator.github.skill_map import taxonomy
from generator.privacy import replace_login
from generator.resume.schema import Entry, ResumeInfo, ResumeSpec
from generator.schemas import GitHubProfile, RepoRecord

# Category order for the Skills block, following the taxonomy's own grouping.
CATEGORY_ORDER = ["Language", "Frontend", "Backend", "Data", "AI/ML", "DevOps",
                  "Quality", "Mobile", "Product"]

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_year(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        stamp = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    return f"{MONTHS[stamp.month - 1]} {stamp.year}"


def _skill_names() -> dict[str, tuple[str, str]]:
    """skill id -> (display name, category)."""
    return {s["id"]: (s["name"], s["category"]) for s in taxonomy()["skills"]}


# Repo names swallow acronyms; title-casing them blindly reads as sloppy.
ACRONYMS = {"api", "pid", "cli", "ui", "ux", "ml", "ai", "nlp", "cv", "db", "sql",
            "http", "rest", "gui", "os", "io", "css", "html", "js", "ts", "2d", "3d"}


def _handle(info: ResumeInfo) -> str:
    """A pseudonymous handle derived from the invented name."""
    return f"{info.first_name}-{info.last_name}".lower().replace(" ", "-")


def _title_from_repo(repo: RepoRecord) -> str:
    words = repo.name.replace("_", " ").replace("-", " ").split()
    return " ".join(
        w.upper() if w.lower() in ACRONYMS else (w if w.isupper() else w.capitalize())
        for w in words
    )


def _bullets_for_repo(repo: RepoRecord) -> list[str]:
    """Factual bullets. Plain and a little dry on purpose - the authoring agent
    rewrites these into resume voice."""
    bullets: list[str] = []

    if repo.description:
        text = repo.description.strip().rstrip(".")
        bullets.append(text[:1].upper() + text[1:] + ".")

    languages = sorted(repo.languages.items(), key=lambda kv: kv[1], reverse=True)[:3]
    if languages:
        named = ", ".join(name for name, _ in languages)
        bullets.append(f"Built with {named} across {repo.file_count} files.")

    # Dependencies that evidence a taxonomy skill first, so the bullet names
    # Next.js and Prisma rather than @babel/eslint-parser and @types/react.
    from generator.github.skill_map import _dep_skill

    deps = sorted({d for values in repo.manifests.values() for d in values},
                  key=lambda d: (_dep_skill(d) is None, d))
    if deps:
        bullets.append(f"Uses {', '.join(deps[:6])}.")

    infra = [label for flag, label in (
        (repo.has_ci, "continuous integration"),
        (repo.has_tests, "an automated test suite"),
        (repo.has_docker, "Docker packaging"),
    ) if flag]
    if infra:
        bullets.append(f"Includes {', '.join(infra)}.")

    commits = repo.commits.get("count", 0)
    active_days = repo.commits.get("active_days", 0)
    if commits:
        bullets.append(
            f"{commits} commit{'s' if commits != 1 else ''} over {active_days} active day"
            f"{'s' if active_days != 1 else ''}."
        )

    if repo.stargazers >= 3 or repo.forks >= 2:
        bullets.append(f"{repo.stargazers} stars, {repo.forks} forks on GitHub.")

    return bullets[:5]


def draft_projects(profile: GitHubProfile, limit: int = 4, handle: str = "") -> list[Entry]:
    """Resume projects, only from skill-relevant repos.

    A notes repo, profile README or someone-else's-work repo is not a project to
    list. And a repo name like `jsmith.github.io` carries the real login, which
    must never reach a resume with an invented name, so it is replaced.
    """
    login = profile.login
    ranked = sorted(
        (r for r in profile.repos if r.skill_relevant),
        # Skill-relevant repos first: a notes repo should never displace a project.
        key=lambda r: (r.skill_relevant, not r.is_fork, r.stargazers, r.file_count,
                       r.commits.get("count", 0)),
        reverse=True,
    )
    entries: list[Entry] = []
    for repo in ranked[:limit]:
        if repo.name.lower() == f"{login.lower()}.github.io":
            title = "Personal Website"
        else:
            title = replace_login(_title_from_repo(repo), login, handle or "Personal").strip()
        entries.append(Entry(
            title=title or "Personal Project",
            organization="Personal Project",
            start=_month_year(repo.created_at),
            end=_month_year(repo.pushed_at) or "Present",
            bullets=[replace_login(b, login, handle or "the author")
                     for b in _bullets_for_repo(repo)],
            link=repo.html_url,
            tech=[name for name, _ in
                  sorted(repo.languages.items(), key=lambda kv: kv[1], reverse=True)[:4]],
        ))
    return entries


def draft_skills(profile: GitHubProfile, min_strength: float = 0.55) -> dict[str, list[str]]:
    """Group observed skills by taxonomy category.

    The strength floor drops the weakest sources (a word in a repo name), so the
    honest draft does not claim a skill on the basis of a repo title alone.
    """
    names = _skill_names()
    grouped: dict[str, list[str]] = {}
    for evidence in profile.skill_evidence:
        if evidence.max_strength < min_strength:
            continue
        entry = names.get(evidence.skill_id)
        if not entry:
            continue
        display, category = entry
        grouped.setdefault(category, [])
        if display not in grouped[category]:
            grouped[category].append(display)

    return {
        category: grouped[category]
        for category in CATEGORY_ORDER
        if category in grouped
    }


def draft_leadership(profile: GitHubProfile) -> list[Entry]:
    """Merged PRs into other people's repos are the one genuine open-source item
    the public record reliably provides."""
    merged = [c for c in profile.external_contributions if c.merged]
    if not merged:
        return []
    repos = sorted({c.repo for c in merged})
    return [Entry(
        title="Open Source Contributor",
        organization=", ".join(repos[:3]),
        start="",
        end="",
        bullets=[(f"Merged {len(merged)} pull request"
                  f"{'s' if len(merged) != 1 else ''} into {len(repos)} external "
                  f"repositor{'ies' if len(repos) != 1 else 'y'}.")],
    )]


def draft(profile: GitHubProfile, info: ResumeInfo, *, batch: int | None = None,
          authored_by: str | None = None) -> ResumeSpec:
    """Assemble the honest first pass."""
    if info.github_login != profile.login:
        raise ValueError(
            f"ResumeInfo is for {info.github_login!r} but profile is {profile.login!r}"
        )

    return ResumeSpec(
        github_login=profile.login,
        applicant_id=profile.applicant_id,
        first_name=info.first_name,
        last_name=info.last_name,
        career_stage=info.career_stage,
        email=info.email,
        phone=info.phone,
        # Never fall back to the real person's location or site: this resume is
        # a fabricated identity, and must not carry a real stranger's details.
        location=info.location,
        linkedin=info.linkedin,
        # github.com/<invented-name> may be a real stranger's account; a reserved
        # example domain can never be.
        github_url=f"github.example.com/{info.github_handle or _handle(info)}",
        portfolio=info.portfolio,
        photo=info.photo,
        objective=info.objective,
        education=info.education,
        # Employment cannot be read off GitHub - it comes from ResumeInfo.
        experience=list(info.experience),
        projects=draft_projects(profile, handle=info.github_handle or _handle(info)),
        leadership=list(info.leadership) + draft_leadership(profile),
        skills=draft_skills(profile),
        authored_by=authored_by,
        drafted_from_profile=True,
        batch=batch,
        notes=["honest draft - bullets are factual and unpolished; rewrite in resume voice"],
    )
