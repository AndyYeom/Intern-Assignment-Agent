"""Command implementations for resume generation.

Argument parsing lives in `generator/__main__.py`; these are the handlers.
"""
from __future__ import annotations

import argparse
import sys

from generator.github import assign
from generator.resume import careers, generate, manifest, prompt, render
from generator.resume.schema import ResumeSpec


def cmd_infoprompt(args: argparse.Namespace) -> int:
    """A static prompt plus each applicant's evidence; an LLM returns a `re gen` command."""
    appids = args.appids or sorted(
        p.applicant_id for p in assign.current().placements
        if p.applicant_id not in manifest.used_ids())
    # Assigned over the whole corpus, so any batch is consistent with the others.
    directions = careers.corpus_directions()
    blocks, failed = [], []
    for applicant_id in appids:
        try:
            blocks.append(generate.evidence_block(applicant_id, directions.get(applicant_id)))
        except generate.GenError as exc:
            failed.append(str(exc))
    if failed:
        for problem in failed:
            print(f"[infoprompt] {problem}", file=sys.stderr)
        return 1
    print(prompt.build(generate.FORMAT, blocks, careers.guide()))
    return 0


def cmd_gen(args: argparse.Namespace) -> int:
    """--appids + --info -> spec, PDF and applicants.csv row per applicant."""
    try:
        requests = generate.parse_requests(args.appids, args.info)
    except (generate.GenError, OSError, ValueError) as exc:
        print(f"[gen] {exc}")
        return 1

    failed = 0
    for request in requests:
        try:
            row, layout = generate.generate(request)
        except generate.GenError as exc:
            print(f"  ! {exc}")
            failed += 1
            continue
        note = "" if layout is render.TEMPLATE_A else f"  (tightened to layout '{layout.name}')"
        print(f"  {row['applicant_id']}  {row['first_name']} {row['last_name']}{note}")
        print(f"      pdf     {row['resume_pdf'] or '(not rendered)'}")
        print(f"      github  {row['github_profile']}  ({row['github_login']})")

    print(f"[gen] {len(requests) - failed} generated, {failed} failed; "
          f"{manifest.MANIFEST_PATH.name} lists {len(manifest.load())} applicants")
    return 1 if failed else 0


def cmd_remove(args: argparse.Namespace) -> int:
    """Delete resume pairs. The GitHub profile stays, so they can be generated again."""
    rows = {row["applicant_id"]: row for row in manifest.load()}
    targets = list(dict.fromkeys(args.appids))
    for applicant_id in targets:
        row = rows.get(applicant_id)
        label = f"{row['first_name']} {row['last_name']}" if row else "(not in applicants.csv)"
        print(f"  {applicant_id}  {label}")
    what = "PDF and CSV row" if args.keep_spec else "spec, PDF and CSV row"
    if not args.yes:
        answer = input(f"Delete the {what} for {len(targets)} applicant(s)? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("[remove] cancelled")
            return 1
    deleted = generate.remove(targets, keep_spec=args.keep_spec)
    print(f"[remove] deleted {len(deleted)} files; "
          f"{manifest.MANIFEST_PATH.name} lists {len(manifest.load())} applicants")
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    """List resume pairs, or regenerate applicants.csv from the specs on disk."""
    if args.rebuild:
        specs = []
        for path in generate.spec_paths():
            try:
                specs.append((ResumeSpec.model_validate_json(path.read_text(encoding="utf-8")),
                              path))
            except Exception as exc:  # noqa: BLE001 - a bad spec must not abort the rebuild
                print(f"  ! {path.name}: {exc}")
        rows = manifest.rebuild(specs, generate.RENDER_DIR)
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
        print(f"[manifest] waiting: {' '.join(waiting)}")
    return 0
