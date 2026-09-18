"""Generate resumes: request -> spec -> PDF, always recorded in applicants.csv.

Every PDF this project produces goes through `publish`, which is what makes the
guarantee hold: no resume PDF exists without a row pairing it to its GitHub
profile. The PDF is rendered to a temporary file, the manifest row is written,
and only then does the temporary file become the real PDF, so a failure at any
step leaves neither behind. The PDF also names its applicant_id in its own
document metadata, so a copy of the file on its own still identifies its pair.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from generator.config import DATA
from generator.resume import draft as drafter
from generator.resume import manifest, render
from generator.resume.careers import Direction
from generator.resume.schema import GenRequest, ResumeInfo, ResumeSpec

RESUME_DIR = DATA / "resumes"
SPEC_DIR = RESUME_DIR / "specs"
RENDER_DIR = RESUME_DIR / "rendered"
RAW_DIR = RESUME_DIR / "raw"          # HTML previews; gitignored


def spec_path(applicant_id: str) -> Path:
    return SPEC_DIR / f"{applicant_id}.json"


def spec_paths() -> list[Path]:
    return sorted(SPEC_DIR.glob("*.json")) if SPEC_DIR.exists() else []

FORMAT = """\
workflow:
  1. re infoprompt --appids applicant0046 applicant0009 > prompt.md
     give prompt.md to ChatGPT or a subagent; it returns a finished `re gen` command
  2. run that command

--appids and --info pair up by position: the first info is the first applicant's
resume, and so on. Each info is a JSON object, or @path to a file holding one.

Length budget (fits MIT Template A exactly): at most 9 bullets and 160 words of
bullets in total, 22 words per bullet. Longer resumes get a tighter layout (down to
10pt, 0.5in margins); one that still overflows is refused - nothing is written.

Every school, city, company, club and award must be fictional. Email, LinkedIn and
portfolio must use reserved domains (*.example, example.com); others are rejected.

Fields follow MIT Resume Template A, top to bottom. Only first_name and last_name
are required; projects and skills are drafted from the applicant's real GitHub
evidence unless given.

{
  -- header ------------------------------------------------------------------
  "first_name": "Ada", "last_name": "Okonkwo",
  "location": "Port Calder", "phone": "(555) 010-0142", "email": "ada@northbridge.example",
  "linkedin": "linkedin.example.com/in/ada-okonkwo",   optional
  "github_handle": "ada-okonkwo",          optional; shown as github.example.com/<handle>
  "career_stage": "intern",                student | intern | new_grad | switcher
                                           (decides section order)
  -- Education ---------------------------------------------------------------
  "education": {
    "school": "Northbridge Institute of Technology", "location": "Port Calder",
    "degree": "Bachelor of Science", "major": "Computer Science", "minor": null,
    "graduation": "June 2027", "gpa": "4.8/5.0",
    "coursework": ["Algorithms", "Computer Systems"],
    "honors": ["Dean's List, Fall 2024"]         shown under Awards & Accomplishments
  },
  -- Experience --------------------------------------------------------------
  "experience": [
    {"organization": "Tidewell Robotics", "location": "Port Calder",
     "title": "Software Engineering Intern", "start": "Jun 2025", "end": "Aug 2025",
     "bullets": ["[Action verb] + [task] -> [outcome]"]}
  ],
  -- Projects (not in Template A; styled like Experience) --------------------
  "projects": null,          omit or null = drafted from GitHub, trimmed to fit one page;
                             or a list of {"title", "organization", "start", "end",
                                           "tech": [...], "bullets": [...]}
  -- Activities & Extracurriculars -------------------------------------------
  "leadership": [
    {"organization": "Northbridge Hacking Society", "title": "Workshop Lead",
     "start": "Sep 2024", "end": "Present", "bullets": ["..."]}
  ],
  -- Awards & Accomplishments ------------------------------------------------
  "awards": [{"title": "Northbridge Hackathon Finalist", "start": "Oct 2024"}],
  -- Skills & Interests ------------------------------------------------------
  "skills": null             omit or null = drafted from GitHub evidence;
                             or {"Languages": ["Python", "Go"], "Frameworks": [...]}
}

Each resume writes data/resumes/specs/<applicant_id>.json and
data/resumes/rendered/<applicant_id>.pdf, and records the pair in data/applicants.csv.
Generating again for the same applicant replaces its pair.
"""


class GenError(ValueError):
    pass


def parse_requests(appids: list[str], infos: list[str]) -> list[GenRequest]:
    """Pair --appids with --info by position. Each info is JSON or @path."""
    if len(appids) != len(infos):
        raise GenError(f"{len(appids)} applicant IDs but {len(infos)} infos - "
                       "they pair up by position, so the counts must match")
    duplicates = sorted({a for a in appids if appids.count(a) > 1})
    if duplicates:
        raise GenError(f"applicant IDs repeated: {', '.join(duplicates)}")

    requests = []
    for applicant_id, raw in zip(appids, infos, strict=True):
        text = Path(raw[1:]).read_text(encoding="utf-8") if raw.startswith("@") else raw
        try:
            info = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GenError(f"{applicant_id}: info is not valid JSON ({exc})") from exc
        if not isinstance(info, dict):
            raise GenError(f"{applicant_id}: info must be a JSON object")
        if info.get("applicant_id") not in (None, applicant_id):
            raise GenError(f"{applicant_id}: info names a different applicant "
                           f"({info['applicant_id']})")
        requests.append(GenRequest.model_validate({**info, "applicant_id": applicant_id}))
    return requests


def evidence_block(applicant_id: str, direction: Direction | None = None) -> str:
    """One applicant's evidence, as it appears in the infoprompt.

    Built from the drafted projects and skills, so it contains exactly what the
    resume would show - with the real login replaced, and no URLs - because this
    text is meant to be pasted into an external service.
    """
    import re

    from generator.github import assign, normalize
    from generator.privacy import replace_login, scrub

    profile = normalize.load_profile(applicant_id)
    if profile is None:
        raise GenError(f"{applicant_id}: no built profile")
    placement = next((p for p in assign.current().placements
                      if p.applicant_id == applicant_id), None)
    if placement is None:
        raise GenError(f"{applicant_id}: not placed in the corpus")

    def clean(text: str) -> str:
        text = replace_login(scrub(text) or "", profile.login, "the applicant")
        return re.sub(r"https?://\S+", "[link]", text)

    probe = ResumeInfo(github_login=profile.login, first_name="X", last_name="Y")
    drafted = drafter.draft(profile, probe)
    first = min((r.created_at for r in profile.repos if r.created_at), default=None)
    last = max((r.pushed_at for r in profile.repos if r.pushed_at), default=None)

    lines = [
        f"## {applicant_id}",
        "",
        f"- Slot: {placement.stratum} ({placement.tier} evidence)",
        *([(f"- **Career direction: {direction.family}** - {direction.creative_type}: "
            f"{direction.type_hint}")] if direction else []),
        f"- Main languages: {', '.join(list(profile.languages_bytes)[:5]) or '-'}",
        (f"- Active on GitHub: {(first or '')[:7]} to {(last or '')[:7]}; "
         f"{profile.total_commits} commits across {len(profile.repos)} repos"),
        "- Evidenced skills: " + (", ".join(
            f"{name} ({', '.join(items)})" for name, items in drafted.skills.items()) or "-"),
        "",
        "Projects the resume will show (factual; rewrite in resume voice if you list them):",
    ]
    for project in drafted.projects:
        lines.append(f"- **{clean(project.title)}** ({project.start} - {project.end}; "
                     f"{', '.join(project.tech)})")
        lines += [f"  - {clean(bullet)}" for bullet in project.bullets]
    if not drafted.projects:
        lines.append("- (none drafted)")
    lines.append("")
    return "\n".join(lines)


def build_spec(request: GenRequest) -> tuple[ResumeSpec, bool]:
    """Merge the request with the applicant's GitHub draft.

    Returns the spec and whether its projects were drafted (and so may be
    trimmed to fit one page).
    """
    from generator.github import assign, ids, normalize

    profile = normalize.load_profile(request.applicant_id)
    if profile is None:
        raise GenError(f"{request.applicant_id}: no built profile")
    if request.applicant_id not in assign.current().placed_ids:
        raise GenError(f"{request.applicant_id}: not placed in the corpus")
    if ids.id_for(profile.login) != request.applicant_id:
        raise GenError(f"{request.applicant_id}: profile and ID registry disagree")
    if request.github_login and request.github_login != profile.login:
        raise GenError(f"{request.applicant_id}: github_login in the request belongs to "
                       "a different applicant")

    identity = request.model_dump(exclude={"applicant_id", "projects", "skills", "awards",
                                           "github_login"})
    info = ResumeInfo(github_login=profile.login, **identity)
    spec = drafter.draft(profile, info, authored_by="gen")
    spec.notes = []
    spec.awards = list(request.awards)
    drafted = request.projects is None
    if not drafted:
        spec.projects = list(request.projects or [])
    if request.skills is not None:
        spec.skills = request.skills
    return spec, drafted


# The length budget the infoprompt asks for. A resume within it fits MIT Template A
# exactly; beyond it the layout tightens, and past the tightest layout gen refuses.
BUDGET = {"bullets": 9, "bullet_words": 160, "words_per_bullet": 22}


def budget_report(spec: ResumeSpec) -> str:
    entries = spec.experience + spec.projects + spec.leadership + spec.awards
    bullets = [b for e in entries for b in e.bullets]
    words = sum(len(b.split()) for b in bullets)
    longest = max((len(b.split()) for b in bullets), default=0)
    return (f"{len(bullets)} bullets (budget {BUDGET['bullets']}), {words} bullet words "
            f"(budget {BUDGET['bullet_words']}), longest bullet {longest} words "
            f"(budget {BUDGET['words_per_bullet']})")


def fit_one_page(spec: ResumeSpec, *, drafted: bool) -> tuple[ResumeSpec, render.Layout]:
    """Fit the resume on one page, losing as little as possible.

    1. Tighten the layout, from MIT Template A down to the minimum MIT guidance
       allows (10pt, 0.5in margins). No content is lost.
    2. Only if even that overflows, and only for projects we drafted, drop
       drafted projects and bullets. An author's own words are never cut.
    3. Otherwise refuse: a two-page resume is never written.
    """
    layout = render.fitted_layout(spec)
    if layout is not None:
        return spec, layout
    if drafted:
        candidates = [spec.model_copy(update={"projects": spec.projects[:limit]})
                      for limit in range(len(spec.projects) - 1, 0, -1)]
        candidates += [spec.model_copy(update={"projects": [
            p.model_copy(update={"bullets": p.bullets[:n]}) for p in spec.projects[:1]]})
            for n in (2, 1)]
        for candidate in candidates:
            layout = render.fitted_layout(candidate)
            if layout is not None:
                return candidate, layout
    raise GenError(f"{spec.applicant_id}: does not fit one page even at the tightest "
                   f"layout - shorten it. {budget_report(spec)}")


def publish(spec: ResumeSpec, spec_file: Path, layout: render.Layout) -> dict[str, Any]:
    """Render the PDF and record the pair. The only way a resume PDF is written."""
    if not spec.applicant_id:
        raise GenError(f"{spec_file.name}: no applicant_id - cannot pair with a profile")
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    final = RENDER_DIR / f"{spec.applicant_id}.pdf"
    tmp = final.with_suffix(".pdf.tmp")

    rendered = render.render_pdf(spec, layout)
    try:
        if rendered is not None:
            tmp.write_bytes(rendered)
        row = manifest.row_for(spec, pdf=final if rendered is not None else None,
                               spec_file=spec_file)
        manifest.upsert([row])
        if rendered is not None:
            tmp.replace(final)
    finally:
        tmp.unlink(missing_ok=True)

    RAW_DIR.mkdir(parents=True, exist_ok=True)   # local preview only; gitignored
    (RAW_DIR / f"{spec.applicant_id}.html").write_text(render.to_html(spec, layout),
                                                       encoding="utf-8")
    return row


def generate(request: GenRequest) -> tuple[dict[str, Any], render.Layout]:
    """Build, fit and publish one resume. Nothing is written if it cannot fit."""
    spec, drafted = build_spec(request)
    spec, layout = fit_one_page(spec, drafted=drafted)
    spec_file = spec_path(spec.applicant_id or request.applicant_id)
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    return publish(spec, spec_file, layout), layout


def remove(applicant_ids: list[str], *, keep_spec: bool = False) -> list[str]:
    """Delete resume pairs: the PDF, its preview, the spec, and the manifest row.

    The GitHub profile is untouched, so the applicant stays in the corpus and
    can be generated again.
    """
    deleted: list[str] = []
    for applicant_id in applicant_ids:
        paths = [RENDER_DIR / f"{applicant_id}.pdf", RAW_DIR / f"{applicant_id}.html"]
        if not keep_spec:
            paths.append(spec_path(applicant_id))
        for path in paths:
            if path.exists():
                path.unlink()
                deleted.append(str(path))
    manifest.remove(applicant_ids)
    return deleted
