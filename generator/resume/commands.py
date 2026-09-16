"""Command implementations for resume generation.

Argument parsing lives in `generator/__main__.py`; these are the handlers.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from generator.github import normalize
from generator.resume import draft as drafter
from generator.resume import manifest, render, roster
from generator.resume.schema import Education, ResumeInfo, ResumeSpec

RENDER_DIR = roster.RESUME_DIR / "rendered"


def cmd_plan(args: argparse.Namespace) -> int:
    payload = roster.plan(batches=args.batches)
    print(f"[plan] {payload['total_profiles']} profiles -> {payload['batch_count']} batches")
    for batch in payload["batches"]:
        print(f"  batch {batch['batch']}: {batch['count']:2d}  {', '.join(batch['logins'])}")
    print(f"[plan] wrote {roster.ROSTER_PATH}")
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    """Emit the working packet for one authoring agent."""
    logins = roster.batch_logins(args.batch)
    profiles = {p.login: p for p in normalize.load_all_profiles() if p.login in logins}

    roster.SPEC_DIR.mkdir(parents=True, exist_ok=True)
    out = roster.RESUME_DIR / f"brief_batch_{args.batch}.md"

    lines = [
        f"# Resume authoring brief — batch {args.batch}",
        "",
        (f"You own **exactly these {len(logins)} GitHub profiles**. Do not write a resume "
         "for any profile outside this list; every profile in the corpus is owned by exactly "
         "one batch, and a duplicate corrupts the evaluation."),
        "",
        "## What to produce",
        "",
        ("One JSON file per profile in `data/resumes/specs/`, named `<first>-<last>.json`, "
         "validating against `generator/resume/schema.py::ResumeSpec`."),
        "",
        ("Start from the honest draft (`python -m generator re draft --batch "
         f"{args.batch}`), which fills projects and skills from the real repo record. "
         "Your job is to add the identity and rewrite the prose:"),
        "",
        "- `first_name`, `last_name`, `email`, `phone`, `location`, `linkedin`",
        "- `career_stage`: one of `student`, `intern`, `new_grad`, `switcher`",
        "- `education`: school, degree, major, graduation, GPA, relevant coursework",
        "- `experience`: internships or jobs, if the career stage implies any",
        "- rewrite project bullets into resume voice — action verb first, quantified",
        "",
        ("Keep every claim supported by the profile below unless you have been separately "
         "told to plant an exaggeration. Record any planted exaggeration in your own file, "
         "not in the spec."),
        "",
        "## Profiles",
        "",
    ]

    for login in logins:
        profile = profiles.get(login)
        if profile is None:
            lines.append(f"### {login}\n\n_Profile not built yet._\n")
            continue
        lines += [
            f"### {login}",
            "",
            f"- URL: {profile.html_url}",
            f"- Bio: {profile.bio or '—'}",
            f"- Location: {profile.location or '—'}",
            f"- Account created: {profile.created_at} ({profile.account_age_days} days)",
            f"- Public repos: {profile.public_repos} | followers: {profile.followers}",
            f"- Commits attributed: {profile.total_commits}",
            "- Top languages: "
            + ", ".join(f"{k} ({v:,}b)" for k, v in list(profile.languages_bytes.items())[:5]),
            "- Observed skills: "
            + ", ".join(e.skill_id for e in profile.skill_evidence[:12]),
            "",
            "| repo | language | files | commits | span | stars |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for repo in profile.repos:
            lines.append(
                f"| [{repo.name}]({repo.html_url}) | {repo.primary_language or '—'} "
                f"| {repo.file_count} | {repo.commits.get('count', 0)} "
                f"| {repo.commits.get('span_days', 0)}d | {repo.stargazers} |"
            )
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[brief] batch {args.batch}: {len(logins)} profiles -> {out}")
    return 0


def cmd_draft(args: argparse.Namespace) -> int:
    logins = roster.batch_logins(args.batch) if args.batch else [
        p.login for p in normalize.load_all_profiles()
    ]
    profiles = {p.login: p for p in normalize.load_all_profiles()}
    roster.SPEC_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    for login in logins:
        profile = profiles.get(login)
        if profile is None:
            print(f"  ! no built profile for {login}")
            continue
        # Placeholder identity: the authoring agent replaces these.
        info = ResumeInfo(
            github_login=login,
            first_name="FIRSTNAME",
            last_name="LASTNAME",
            career_stage="student",
            education=Education(major="TODO", graduation="TODO"),
        )
        spec = drafter.draft(profile, info, batch=args.batch, authored_by="draft")
        path = roster.SPEC_DIR / f"_draft_{login}.json"
        path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        written += 1

    print(f"[draft] wrote {written} draft specs to {roster.SPEC_DIR}")
    print("[draft] these are placeholders — rename to <first>-<last>.json once authored")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    report = roster.verify()
    print(f"[verify] {report['specs']} specs, {report['distinct_logins']} distinct profiles, "
          f"{report['expected']} expected")
    if report["ok"]:
        print("[verify] OK — every profile used exactly once")
        return 0
    for problem in report["problems"]:
        print(f"  ! {problem}")
    return 1


def cmd_render(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.specs] if args.specs else [
        p for p in roster.spec_paths(include_drafts=args.include_drafts)
    ]
    if not paths:
        print("No specs to render. Run `draft`, or author specs into data/resumes/specs/.")
        return 1

    if not render.pdf_available():
        print("[render] WeasyPrint unavailable — HTML only.")

    rendered = 0
    rows = []
    for path in paths:
        try:
            spec = ResumeSpec.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - one bad spec must not abort rendering
            print(f"  ! {path.name}: {exc}")
            continue
        html_path = render.write_html(spec, RENDER_DIR)
        pdf_path = render.write_pdf(spec, RENDER_DIR) if not args.no_pdf else None
        rows.append(manifest.row_for(spec, pdf=pdf_path, html=html_path, spec_path=path))
        rendered += 1
        print(f"  {spec.full_name:<28} {html_path.name}" + (f"  {pdf_path.name}" if pdf_path else ""))

    if rows:
        merged = manifest.upsert(rows)
        print(f"[render] manifest now lists {len(merged)} applicants "
              f"-> {manifest.MANIFEST_PATH.name}")
    print(f"[render] {rendered} resumes -> {RENDER_DIR}")
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    """Show the applicant index, or regenerate it from what is on disk."""
    if args.rebuild:
        specs = []
        for path in roster.spec_paths():
            try:
                specs.append(
                    (ResumeSpec.model_validate_json(path.read_text(encoding="utf-8")), path))
            except Exception as exc:  # noqa: BLE001 - a bad spec must not abort the rebuild
                print(f"  ! {path.name}: {exc}")
        rows = manifest.rebuild(specs, RENDER_DIR)
        print(f"[manifest] rebuilt from disk: {len(rows)} applicants")
    else:
        rows = manifest.load()

    if not rows:
        print("[manifest] empty - render some resumes first")
        return 0

    print(f"\n{'idx':>3}  {'name':<26} {'github':<20} {'stage':<9} pdf")
    for row in rows:
        name = f"{row['first_name']} {row['last_name']}"
        mark = "yes" if row.get("resume_pdf") else "-"
        print(f"{row['idx']:>3}  {name:<26} {row['github_login']:<20} "
              f"{row.get('career_stage', ''):<9} {mark}")

    # Which collected profiles still have no resume.
    from generator.github import normalize
    collected = {p.login for p in normalize.load_all_profiles()}
    unused = sorted(collected - manifest.used_logins())
    print(f"\n[manifest] {len(rows)} with resumes, {len(unused)} profiles unused")
    if unused:
        print(f"[manifest] unused: {', '.join(unused[:15])}")
    return 0
