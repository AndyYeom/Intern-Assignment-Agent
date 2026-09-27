"""Health checks and the public application endpoints."""

import logging
import re
import uuid
from typing import Annotated

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import repositories as repo
from backend.api import schemas as s
from backend.api.deps import db_session, storage
from backend.api.errors import ApiError, not_found
from backend.config import get_settings
from backend.db.models import Applicant, ApplicantDocument
from backend.services.processing import process_applicant
from backend.storage import Storage

log = logging.getLogger(__name__)
router = APIRouter()

GITHUB_URL = re.compile(r"^https?://(www\.)?github\.com/(?P<login>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/?$")
PUBLIC_MESSAGES = {
    "submitted": "Your application has been received.",
    "processing": "We are reviewing your application.",
    "ready": "Your application has been reviewed and is awaiting project matching.",
    "failed": "Your application has been received. Our team will review it manually.",
}


@router.get("/health", response_model=s.Health, tags=["health"])
def health() -> s.Health:
    """Liveness: the process is up. No dependencies are checked (ECS/ALB health check)."""
    return s.Health(status="ok")


@router.get("/ready", response_model=s.Ready, tags=["health"])
def ready(session: Annotated[Session, Depends(db_session)]) -> s.Ready:
    """Readiness: the database answers a trivial query."""
    try:
        session.execute(text("SELECT 1"))
        return s.Ready(status="ok", database=True)
    except Exception:
        log.warning("readiness check: database unavailable")
        raise ApiError(503, "database_unavailable", "Database is unavailable.") from None


def _field_error(field: str, message: str) -> ApiError:
    return ApiError(422, "validation_error", "Some fields are invalid.", [{"field": field, "message": message}])


@router.post(
    "/api/applications", response_model=s.ApplicationCreated, status_code=201, tags=["applications"]
)
async def create_application(
    background: BackgroundTasks,
    session: Annotated[Session, Depends(db_session)],
    store: Annotated[Storage, Depends(storage)],
    name: Annotated[str, Form(min_length=1, max_length=200)],
    email: Annotated[str, Form(max_length=320)],
    github_url: Annotated[str, Form(max_length=300)],
    resume: Annotated[UploadFile, File()],
    portfolio_url: Annotated[str | None, Form(max_length=500)] = None,
) -> s.ApplicationCreated:
    try:
        email = validate_email(email.strip(), check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise _field_error("email", str(exc)) from None
    match = GITHUB_URL.match(github_url.strip())
    if not match:
        raise _field_error("github_url", "Enter a GitHub profile URL like https://github.com/username.")
    portfolio_url = (portfolio_url or "").strip() or None
    if portfolio_url and not re.match(r"^https?://\S+$", portfolio_url):
        raise _field_error("portfolio_url", "Enter a full URL starting with https://.")

    limit = get_settings().max_upload_bytes
    data = await resume.read(limit + 1)
    if len(data) > limit:
        raise _field_error("resume", f"Resume must be at most {limit // (1024 * 1024)} MB.")
    if not data.startswith(b"%PDF-"):
        raise _field_error("resume", "Resume must be a PDF file.")
    if repo.get_applicant_by_email(session, email):
        raise ApiError(409, "duplicate_email", "An application with this email already exists.")

    applicant_id = uuid.uuid4()
    reference = f"app-{applicant_id.hex[:12]}"
    key = store.save(data, prefix=f"resumes/{reference}", suffix=".pdf")
    applicant = Applicant(
        id=applicant_id,
        reference=reference,
        name=name.strip(),
        email=email,
        github_url=f"https://github.com/{match['login']}",
        github_login=match["login"],
        portfolio_url=portfolio_url,
        status="submitted",
        source="application",
    )
    applicant.documents.append(
        ApplicantDocument(
            document_type="resume",
            storage_key=key,
            original_filename=(resume.filename or "resume.pdf")[:255],
            mime_type="application/pdf",
            size_bytes=len(data),
        )
    )
    session.add(applicant)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        store.delete(key)
        raise ApiError(409, "duplicate_email", "An application with this email already exists.") from None
    log.info("application submitted applicant=%s", reference)
    background.add_task(process_applicant, applicant_id)
    return s.ApplicationCreated(id=applicant_id, status="submitted")


@router.get("/api/applications/{applicant_id}", response_model=s.ApplicationPublic, tags=["applications"])
def get_application(
    applicant_id: uuid.UUID, session: Annotated[Session, Depends(db_session)]
) -> s.ApplicationPublic:
    applicant = session.get(Applicant, applicant_id)
    if applicant is None:
        raise not_found("Application")
    return s.ApplicationPublic(
        id=applicant.id,
        name=applicant.name,
        status=applicant.status,
        submitted_at=applicant.created_at,
        message=PUBLIC_MESSAGES[applicant.status],
    )
