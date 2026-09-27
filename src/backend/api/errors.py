"""Structured JSON errors. Clients never see stack traces or internals."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found.")


def _body(code: str, message: str, details: list | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"][1:]) or None, "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            _body("validation_error", "Some fields are invalid.", details), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            _body("internal_error", "Something went wrong. Please try again."), status_code=500
        )
