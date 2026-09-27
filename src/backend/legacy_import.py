"""Import the legacy file-based data into PostgreSQL. Idempotent; never deletes sources.

    python -m backend.legacy_import [--skip-projects] [--data-dir legacy]

Sources (all read-only):
  resources/taxonomy.json           -> skills
  resources/seed_projects.json      -> sample projects and roles
  legacy/applicants.csv             -> applicants (index of the cohort)
  legacy/resumes/specs/<id>.json    -> applicant name, email, education, experience
  legacy/resumes/rendered/<id>.pdf  -> resume document (copied into blob storage)
  legacy/githubs/profiles/<id>.json -> GitHub snapshot
  legacy/evidence/<id>.json         -> resolved skills + evidence (claims from the
                                       resume spec, verified against GitHub by the
                                       evidence agent's rules)

Re-running updates changed applicants and leaves projects that already exist
untouched, so manager edits survive. Exits non-zero on malformed critical data.
"""

import argparse
import csv
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.config import LEGACY_DATA, RESOURCES, get_settings
from backend.db import session_scope
from backend.db.models import (
    Applicant,
    ApplicantDocument,
    ApplicantSkill,
    Project,
    ProjectRole,
    ProjectRoleSkill,
    Skill,
)
from backend.services.persistence import replace_applicant_skills, upsert_taxonomy
from backend.services.skill_resolution import resolve_skills
from backend.storage import LocalStorage

log = logging.getLogger("backend.legacy_import")

CSV_COLUMNS = {"applicant_id", "first_name", "last_name", "github_login", "resume_pdf", "spec"}


class ImportDataError(ValueError):
    """Critical source data is malformed; the import stops."""


@dataclass
class Report:
    counts: Counter = field(default_factory=Counter)
    problems: list[str] = field(default_factory=list)

    def add(self, entity: str, outcome: str) -> None:
        self.counts[(entity, outcome)] += 1

    def lines(self) -> list[str]:
        entities = sorted({e for e, _ in self.counts})
        out = [f"{'entity':<18}{'inserted':>9}{'updated':>9}{'unchanged':>10}{'skipped':>9}{'failed':>8}"]
        for e in entities:
            c = {o: self.counts[(e, o)] for o in ("inserted", "updated", "unchanged", "skipped", "failed")}
            out.append(
                f"{e:<18}{c['inserted']:>9}{c['updated']:>9}{c['unchanged']:>10}{c['skipped']:>9}{c['failed']:>8}"
            )
        return out


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImportDataError(f"cannot read {path}: {exc}") from exc


def _legacy_profile(spec: dict) -> dict:
    return {
        "career_stage": spec.get("career_stage"),
        "education": spec.get("education") or [],
        "work_experience": spec.get("experience") or [],
        "source": "resume spec (legacy import)",
    }


def import_applicants(session: Session, data_dir: Path, storage: LocalStorage, report: Report) -> None:
    csv_path = data_dir / "applicants.csv"
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = CSV_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ImportDataError(f"{csv_path} is missing columns: {sorted(missing)}")
        rows = list(reader)
    refs = [r["applicant_id"] for r in rows]
    if len(refs) != len(set(refs)):
        raise ImportDataError("applicants.csv has duplicate applicant_id values")

    root = data_dir.parent
    known_skills = set(session.scalars(select(Skill.id)))
    for row in rows:
        ref = row["applicant_id"].strip()
        try:
            spec = _read_json(root / row["spec"])
            email = (spec.get("email") or "").strip()
            name = " ".join(p for p in (row["first_name"].strip(), row["last_name"].strip()) if p)
            if not ref or not name or not email:
                raise ImportDataError(f"{ref or '?'}: missing id, name or email")
        except ImportDataError as exc:
            report.add("applicants", "failed")
            report.problems.append(str(exc))
            continue

        login = row["github_login"].strip() or None
        values = {
            "name": name,
            "email": email,
            "github_login": login,
            "github_url": f"https://github.com/{login}" if login else None,
            "source": "legacy_import",
            "profile": _legacy_profile(spec),
        }
        profile_path = root / row["github_profile"] if row.get("github_profile") else None
        if profile_path and profile_path.is_file():
            values["github_snapshot"] = _read_json(profile_path)

        applicant = session.scalar(select(Applicant).where(Applicant.reference == ref))
        if applicant is None:
            clash = session.scalar(
                select(Applicant).where(func.lower(Applicant.email) == email.lower())
            )
            if clash is not None:
                report.add("applicants", "failed")
                report.problems.append(f"{ref}: email already used by {clash.reference}")
                continue
            applicant = Applicant(reference=ref, status="submitted", **values)
            session.add(applicant)
            session.flush()
            report.add("applicants", "inserted")
        else:
            changed = any(getattr(applicant, k) != v for k, v in values.items())
            for k, v in values.items():
                setattr(applicant, k, v)
            report.add("applicants", "updated" if changed else "unchanged")

        # Resume: copy the rendered PDF into storage once.
        pdf = root / row["resume_pdf"] if row.get("resume_pdf") else None
        has_resume = any(d.document_type == "resume" for d in applicant.documents)
        if has_resume:
            report.add("documents", "unchanged")
        elif pdf and pdf.is_file():
            data = pdf.read_bytes()
            key = storage.save(data, prefix=f"resumes/{ref}", suffix=".pdf")
            applicant.documents.append(
                ApplicantDocument(
                    document_type="resume",
                    storage_key=key,
                    original_filename=pdf.name,
                    mime_type="application/pdf",
                    size_bytes=len(data),
                )
            )
            report.add("documents", "inserted")
        else:
            report.add("documents", "skipped")
            report.problems.append(f"{ref}: resume PDF not found ({row.get('resume_pdf')})")

        # Skills: the evidence agent's saved verdicts, resolved with resolve_profile.
        evidence_path = data_dir / "evidence" / f"{ref}.json"
        if not evidence_path.is_file():
            report.add("applicant_skills", "skipped")
            report.problems.append(f"{ref}: no evidence file; left as 'submitted'")
            continue
        evidence = _read_json(evidence_path)
        verdicts = [v for v in evidence.get("skills", []) if v.get("skill_id") in known_skills]
        claims = [
            {
                "canonical_skill": v["skill_id"],
                "claimed_level": v["claimed_level"],
                "evidence": [],
                "reasoning": f"Claimed level taken from the resume ({evidence.get('claims_source', 'spec')}).",
            }
            for v in verdicts
        ]
        resolved, unmapped = resolve_skills(claims, verdicts)
        # Manager-pinned skills are never re-imported, so they don't count as a change.
        rows = list(
            session.scalars(select(ApplicantSkill).where(ApplicantSkill.applicant_id == applicant.id))
        )
        pinned = {s.skill_id for s in rows if s.pinned}
        before = {
            (s.skill_id, s.final_level, s.verification_status) for s in rows if not s.pinned
        }
        after = {
            (s.skill_id, s.final_level, s.verification_status)
            for s in resolved
            if s.skill_id not in pinned
        }
        if before == after and applicant.status == "ready":
            report.add("applicant_skills", "unchanged")
        else:
            replace_applicant_skills(session, applicant, resolved)
            applicant.status = "ready"
            report.add("applicant_skills", "updated" if before else "inserted")
        if unmapped:
            report.problems.append(f"{ref}: unmapped skills ignored: {unmapped}")


def import_projects(session: Session, seed_path: Path, report: Report) -> None:
    seed = _read_json(seed_path)
    known_skills = set(session.scalars(select(Skill.id)))
    for item in seed.get("projects", []):
        name = (item.get("name") or "").strip()
        roles = item.get("roles") or []
        if not name or not roles:
            raise ImportDataError(f"seed project needs a name and roles: {item!r:.80}")
        for role in roles:
            for q in role.get("requirements", []):
                if q["skill_id"] not in known_skills:
                    raise ImportDataError(f"{name}/{role['name']}: unknown skill {q['skill_id']!r}")
        exists = session.scalar(select(Project).where(func.lower(Project.name) == name.lower()))
        if exists is not None:
            report.add("projects", "skipped")
            continue
        project = Project(name=name, description=item.get("description", ""), status="active")
        for position, role in enumerate(roles):
            project.roles.append(
                ProjectRole(
                    name=role["name"],
                    description=role.get("description", ""),
                    capacity=int(role["capacity"]),
                    position=position,
                    requirements=[
                        ProjectRoleSkill(
                            skill_id=q["skill_id"],
                            required_level=int(q["required_level"]),
                            requirement_type=q["requirement_type"],
                            weight=float(q.get("weight", 1.0)),
                        )
                        for q in role.get("requirements", [])
                    ],
                )
            )
            report.add("roles", "inserted")
        session.add(project)
        report.add("projects", "inserted")
    session.flush()


def verify(session: Session, data_dir: Path) -> list[str]:
    """Compare what landed in the database with the source files."""
    with (data_dir / "applicants.csv").open(newline="", encoding="utf-8") as handle:
        source_refs = {r["applicant_id"] for r in csv.DictReader(handle)}
    taxonomy = _read_json(RESOURCES / "taxonomy.json")["skills"]
    db_refs = set(
        session.scalars(select(Applicant.reference).where(Applicant.source == "legacy_import"))
    )
    with_resume = session.scalar(
        select(func.count(func.distinct(ApplicantDocument.applicant_id)))
        .join(Applicant, Applicant.id == ApplicantDocument.applicant_id)
        .where(
            ApplicantDocument.document_type == "resume",
            Applicant.source == "legacy_import",
        )
    )
    evidence_files = {p.stem for p in (data_dir / "evidence").glob("*.json")}
    ready = set(
        session.scalars(
            select(Applicant.reference).where(
                Applicant.source == "legacy_import", Applicant.status == "ready"
            )
        )
    )
    checks = [
        ("skills", len(taxonomy), session.scalar(select(func.count()).select_from(Skill))),
        ("legacy applicants", len(source_refs), len(db_refs & source_refs)),
        ("applicants with resume", len(source_refs), with_resume),
        ("applicants with skills", len(source_refs & evidence_files), len(ready & source_refs)),
    ]
    return [
        f"{'OK ' if want == got else 'MISMATCH'} {label}: source={want} db={got}"
        for label, want, got in checks
    ]


def run(data_dir: Path, *, skip_projects: bool = False) -> tuple[Report, list[str]]:
    report = Report()
    storage = LocalStorage(get_settings().storage_root)
    with session_scope() as session:
        inserted, updated = upsert_taxonomy(session, RESOURCES / "taxonomy.json")
        report.counts[("skills", "inserted")] += inserted
        report.counts[("skills", "updated")] += updated
    with session_scope() as session:
        import_applicants(session, data_dir, storage, report)
    if not skip_projects:
        with session_scope() as session:
            import_projects(session, RESOURCES / "seed_projects.json", report)
    with session_scope() as session:
        checks = verify(session, data_dir)
    return report, checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", type=Path, default=LEGACY_DATA)
    parser.add_argument("--skip-projects", action="store_true", help="do not import seed projects")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        report, checks = run(args.data_dir.resolve(), skip_projects=args.skip_projects)
    except ImportDataError as exc:
        log.error("import stopped: %s", exc)
        return 1
    for line in report.lines():
        print(line)
    for problem in report.problems:
        print(f"note: {problem}")
    for line in checks:
        print(line)
    failed = sum(c for (_, outcome), c in report.counts.items() if outcome == "failed")
    return 1 if failed or any(line.startswith("MISMATCH") for line in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
