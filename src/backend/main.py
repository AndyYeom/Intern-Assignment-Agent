"""FastAPI application.

    uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import errors
from backend.api.routes_catalog import router as catalog_router
from backend.api.routes_manager import router as manager_router
from backend.api.routes_public import router as public_router
from backend.config import get_settings


def configure_logging(level: str) -> None:
    """Log to stdout so ECS/CloudWatch collects everything; no log files."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Utechia Intern Assignment API", version="0.1.0")
    origins = settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # Credentials are never sent (no auth yet); a wildcard origin stays valid.
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    if "*" in origins:
        logging.getLogger(__name__).warning("CORS allows any origin (CORS_ALLOWED_ORIGINS=*)")
    errors.install(app)
    app.include_router(public_router)
    app.include_router(manager_router)
    app.include_router(catalog_router)
    return app


app = create_app()
