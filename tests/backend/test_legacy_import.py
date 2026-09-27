"""The legacy import against the real data/ directory (read-only)."""

from sqlalchemy import func, select

from backend import legacy_import
from backend.db import session_scope
from backend.db.models import (
    Applicant,
    ApplicantDocument,
    ApplicantSkill,
    Project,
    ProjectRole,
)


def _counts():
    with session_scope() as s:
        return {
            "applicants": s.scalar(select(func.count()).select_from(Applicant)),
            "documents": s.scalar(select(func.count()).select_from(ApplicantDocument)),
            "skills": s.scalar(select(func.count()).select_from(ApplicantSkill)),
            "projects": s.scalar(select(func.count()).select_from(Project)),
            "roles": s.scalar(select(func.count()).select_from(ProjectRole)),
        }


def test_import_matches_sources_and_is_idempotent(db):
    data_dir = legacy_import.LEGACY_DATA
    report, checks = legacy_import.run(data_dir)
    assert all(c.startswith("OK") for c in checks), checks
    first = _counts()
    assert first["applicants"] == 100 and first["documents"] == 100
    assert first["projects"] >= 1 and first["roles"] >= first["projects"]
    assert report.counts[("applicants", "inserted")] == 100

    report, checks = legacy_import.run(data_dir)
    assert _counts() == first
    assert report.counts[("applicants", "inserted")] == 0
    assert report.counts[("applicants", "unchanged")] == 100
    assert report.counts[("projects", "skipped")] == first["projects"]


def test_every_imported_applicant_is_ready_with_a_resume(db):
    legacy_import.run(legacy_import.LEGACY_DATA)
    with session_scope() as s:
        applicants = s.scalars(select(Applicant)).all()
        assert {a.status for a in applicants} == {"ready"}
        assert all(any(d.document_type == "resume" for d in a.documents) for a in applicants)
        assert all(a.github_snapshot for a in applicants)


def test_reimport_ignores_applications_submitted_through_the_api(db):
    """Deploys re-run the import; new applicants must not break its checks."""
    legacy_import.run(legacy_import.LEGACY_DATA)
    with session_scope() as s:
        a = Applicant(reference="app-new", name="New", email="new@example.com", source="application")
        a.documents.append(
            ApplicantDocument(
                document_type="resume", storage_key="k", original_filename="cv.pdf",
                mime_type="application/pdf", size_bytes=1,
            )
        )
        s.add(a)
    _, checks = legacy_import.run(legacy_import.LEGACY_DATA)
    assert all(c.startswith("OK") for c in checks), checks
