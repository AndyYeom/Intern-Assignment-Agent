"""Command implementations for resume generation.

Argument parsing lives in `generator/__main__.py`; these are the handlers.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from generator.github import assign, normalize
from generator.resume import draft as drafter
from generator.resume import manifest, render, roster
from generator.resume.schema import Education, ResumeInfo, ResumeSpec
from generator.schemas import GitHubProfile

RENDER_DIR = roster.RESUME_DIR / "rendered"


def cmd_plan(args: argparse.Namespace) -> int:
    payload = roster.plan(batches=args.batches)
    total = sum(len(b["applicant_ids"]) for b in payload["batches"])
    print(f"[plan] {total} placed applicants -> {len(payload['batches'])} batches")
    for batch in payload["batches"]:
        print(f"  batch {batch['batch']}: {len(batch['applicant_ids']):2d}  "
              f"{', '.join(batch['applicant_ids'])}")
    print(f"[plan] wrote {roster.ROSTER_PATH}")
    print("[plan] next: `generator re draft --batch <n>` for each batch")
    return 0


def _brief(batch: int, profiles: list[GitHubProfile]) -> str:
    """The authoring packet: instructions plus the facts each resume must stay true to."""
    lines = [
        f"# Resume authoring brief — batch {batch}",
        "",
        (f"You own **exactly these {len(profiles)} applicants**. Every applicant belongs to "
         "exactly one batch; writing a resume for anyone else corrupts the evaluation."),
        "",
        "## For each applicant",
        "",
        "1. Open `data/resumes/specs/_draft_<applicant_id>.json`. Projects and skills are",
        "   already filled from the real repositories.",
        "2. Invent the identity: `first_name`, `last_name`, `email`, `phone`, `location`,",
        "   `linkedin`, `career_stage` (`student`, `intern`, `new_grad`, `switcher`),",
        "   `education`, and any `experience` the career stage implies.",
        "3. Rewrite project bullets in resume voice: action verb first, quantified.",
        "4. Save as `data/resumes/specs/<applicant_id>.json` (drop the `_draft_` prefix).",
        "   Do not change `applicant_id` or `github_login`.",
        "",
        ("Keep every claim supported by the facts below unless you were separately told to "
         "plant an exaggeration. Record planted exaggerations in your own file, never in a spec."),
        "",
        "## Applicants",
        "",
    ]
    for profile in profiles:
        lines += [
            f"### {profile.applicant_id}",
            "",
            "- Top languages: " + ", ".join(list(profile.languages_bytes)[:5]),
            "- Observed skills: " + ", ".join(e.skill_id for e in profile.skill_evidence[:12]),
            "",
            "| repo | language | skill work | commits | active days |",
            "| --- | --- | --- | ---: | ---: |",
        ]
        for repo in profile.repos:
            lines.append(
                f"| {repo.name} | {repo.primary_language or '—'} "
                f"| {'yes' if repo.skill_relevant else 'no'} "
                f"| {repo.commits.get('count', 0)} | {repo.commits.get('active_days', 0)} |"
            )
        lines.append("")
    return "\n".join(lines)


def cmd_draft(args: argparse.Namespace) -> int:
    """Write honest draft specs for one batch, plus the brief its author works from."""
    applicant_ids = roster.batch_ids(args.batch)
    profiles = []
    for applicant_id in applicant_ids:
        profile = normalize.load_profile(applicant_id)
        if profile is None:
            print(f"  ! no built profile for {applicant_id}")
            continue
        profiles.append(profile)

    roster.SPEC_DIR.mkdir(parents=True, exist_ok=True)
    for profile in profiles:
        # Placeholder identity: the author replaces these.
        info = ResumeInfo(
            github_login=profile.login,
            first_name="FIRSTNAME",
            last_name="LASTNAME",
            education=Education(major="TODO", graduation="TODO"),
        )
        spec = drafter.draft(profile, info, batch=args.batch, authored_by="draft")
        roster.spec_path(profile.applicant_id, draft=True).write_text(
            spec.model_dump_json(indent=2), encoding="utf-8")

    brief_path = roster.RESUME_DIR / f"brief_batch_{args.batch}.md"
    brief_path.write_text(_brief(args.batch, profiles), encoding="utf-8")
    print(f"[draft] batch {args.batch}: {len(profiles)} drafts in {roster.SPEC_DIR}")
    print(f"[draft] brief for the author: {brief_path}")
    return 0


def _report_verify(report: dict) -> None:
    print(f"[verify] {report['specs']} specs for {report['applicants']} applicants, "
          f"{report['expected']} expected")
    for problem in report["problems"]:
        print(f"  ! {problem}")
    if report["ok"]:
        print("[verify] OK - every applicant has at most one resume, all consistent")


def cmd_verify(args: argparse.Namespace) -> int:
    report = roster.verify()
    _report_verify(report)
    return 0 if report["ok"] else 1


def cmd_render(args: argparse.Namespace) -> int:
    drafts_only = bool(args.specs) and all(Path(p).name.startswith(roster.DRAFT_PREFIX)
                                           for p in args.specs)
    if not drafts_only:
        report = roster.verify()
        # "No resume yet" is expected mid-authoring; everything else blocks rendering.
        blocking = [p for p in report["problems"] if "have no resume" not in p]
        if blocking:
            _report_verify(report)
            print("[render] refused - fix the problems above first")
            return 1

    paths = [Path(p) for p in args.specs] if args.specs else roster.spec_paths()
    if not paths:
        print("No authored specs. Run `re draft`, then author specs into data/resumes/specs/.")
        return 1
    if not render.pdf_available():
        print("[render] WeasyPrint unavailable - HTML only.")

    rows = []
    for path in paths:
        try:
            spec = ResumeSpec.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - one bad spec must not abort rendering
            print(f"  ! {path.name}: {exc}")
            continue
        render.write_html(spec, RENDER_DIR)
        pdf_path = render.write_pdf(spec, RENDER_DIR) if not args.no_pdf else None
        # A draft is a preview, never a resume: it must not enter the manifest,
        # where it would pin a placeholder "FIRSTNAME LASTNAME" into the corpus.
        if not path.name.startswith(roster.DRAFT_PREFIX):
            rows.append(manifest.row_for(spec, pdf=pdf_path, spec_file=path))
        print(f"  {spec.applicant_id}  {spec.full_name}")

    if rows:
        merged = manifest.upsert(rows)
        print(f"[render] {manifest.MANIFEST_PATH.name} now lists {len(merged)} applicants")
    print(f"[render] {len(paths)} rendered -> {RENDER_DIR}")
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    """Show the applicant index, or regenerate it from what is on disk."""
    if args.rebuild:
        specs = []
        for path in roster.spec_paths():
            try:
                specs.append((ResumeSpec.model_validate_json(path.read_text(encoding="utf-8")),
                              path))
            except Exception as exc:  # noqa: BLE001 - a bad spec must not abort the rebuild
                print(f"  ! {path.name}: {exc}")
        rows = manifest.rebuild(specs, RENDER_DIR)
        print(f"[manifest] rebuilt from disk: {len(rows)} applicants")
    else:
        rows = manifest.load()

    for row in rows:
        mark = "pdf" if row.get("resume_pdf") else "-"
        print(f"  {row['applicant_id']}  {row['first_name']} {row['last_name']:<20} "
              f"{row.get('career_stage', ''):<9} {mark}")

    used = manifest.used_ids()
    waiting = sorted(p.applicant_id for p in assign.current().placements
                     if p.applicant_id not in used)
    print(f"[manifest] {len(rows)} with resumes, {len(waiting)} placed applicants without one")
    if waiting:
        print(f"[manifest] waiting: {', '.join(waiting[:15])}")
    return 0
