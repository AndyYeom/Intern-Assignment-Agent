from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, TypedDict

import httpx
from dotenv import load_dotenv
from langchain_core.output_parsers import PydanticOutputParser
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph

from src.profile_agent.pdf_extractor import ResumeExtractionError, extract_resume
from src.profile_agent.profile_models import ApplicantProfile, ApplicantSkill, SkillEvidence
from src.profile_agent.profile_prompts import (
    build_correction_prompt,
    build_profile_prompt,
)


class ProfileConfigurationError(RuntimeError):
    """Raised when the gateway environment is missing required configuration."""


class ProfileValidationError(ValueError):
    """Raised when input data fails document or graph validation."""


class ApplicantEvaluationError(RuntimeError):
    """Raised when the gateway or model output cannot be used to form a profile."""


environment_file = Path(".env")
if not environment_file.is_file():
    environment_file = Path(".env.example")
load_dotenv(dotenv_path=environment_file, override=False)


def _required_gateway_settings() -> tuple[str, str, str]:
    gateway_url = os.getenv("LLM_GATEWAY_URL")
    gateway_api_key = os.getenv("LLM_GATEWAY_API_KEY")
    llm_model = os.getenv("LLM_MODEL")
    missing = [
        name
        for name, value in {
            "LLM_GATEWAY_URL": gateway_url,
            "LLM_GATEWAY_API_KEY": gateway_api_key,
            "LLM_MODEL": llm_model,
        }.items()
        if not value or not str(value).strip()
    ]
    if missing:
        raise ProfileConfigurationError(
            "Missing required gateway configuration: " + ", ".join(missing)
        )
    return gateway_url.strip(), gateway_api_key.strip(), llm_model.strip()


def create_profile_llm() -> ChatOllama:
    gateway_url, gateway_api_key, llm_model = _required_gateway_settings()
    return ChatOllama(
        model=llm_model,
        base_url=gateway_url,
        temperature=0.0,
        num_predict=6000,
        client_kwargs={"headers": {"X-API-Key": gateway_api_key}},
    )


class ProfileGraphState(TypedDict, total=False):
    applicant_id: str | None
    resume_path: str
    portfolio_path: str | None
    enable_ocr: bool
    resume_text: str
    portfolio_text: str
    llm_factory: Callable[[], Any]
    profile: ApplicantProfile


def _extract_text_content(message: Any) -> str:
    if message is None:
        return ""
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts: list[str] = []
        for block in message:
            if isinstance(block, str):
                parts.append(block)
                continue
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
                if isinstance(text, list):
                    nested = "".join(
                        piece.get("text", "") if isinstance(piece, dict) else str(piece)
                        for piece in text
                    )
                    parts.append(nested)
                continue
            if hasattr(block, "text"):
                inner_text = getattr(block, "text")
                if isinstance(inner_text, str):
                    parts.append(inner_text)
        return "".join(parts)
    if hasattr(message, "content"):
        return _extract_text_content(message.content)
    return str(message)


def _clean_json_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip()
        cleaned = cleaned.strip()
    return cleaned


def _extract_portfolio_text(portfolio_path: str | None) -> str:
    if portfolio_path is None or not str(portfolio_path).strip():
        return ""
    path = Path(portfolio_path)
    if not path.is_file():
        raise ProfileValidationError(f"Portfolio file does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            return extract_resume(str(path), enable_ocr=False)
        except ResumeExtractionError as exc:
            raise ProfileValidationError(f"Portfolio PDF extraction failed: {path}") from exc
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8")
    raise ProfileValidationError(
        f"Unsupported portfolio format: {path.suffix or 'no extension'} for {path}. "
        "Supported formats: .pdf, .md, .txt"
    )


def extract_documents(state: ProfileGraphState) -> dict[str, Any]:
    resume_path = state.get("resume_path")
    if not resume_path:
        raise ProfileValidationError("A résumé PDF path is required.")
    pdf_path = Path(resume_path)
    if not pdf_path.is_file():
        raise ProfileValidationError(f"Résumé PDF does not exist: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ProfileValidationError(f"Résumé file must be a PDF: {pdf_path}")

    enable_ocr = bool(state.get("enable_ocr", False))
    try:
        resume_text = extract_resume(str(pdf_path), enable_ocr=enable_ocr)
    except (ResumeExtractionError, FileNotFoundError, ValueError) as exc:
        raise ProfileValidationError(f"Failed to extract résumé PDF: {pdf_path}") from exc
    if not resume_text or not resume_text.strip():
        raise ProfileValidationError(f"Extracted résumé is empty or whitespace-only: {pdf_path}")

    portfolio_text = _extract_portfolio_text(state.get("portfolio_path"))
    return {"resume_text": resume_text, "portfolio_text": portfolio_text}


def _is_transient_gateway_error(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in {401, 403}:
        return False
    if status_code == 413:
        raise ApplicantEvaluationError(
            "The gateway rejected the request because the prompt was too large for the model. "
            "Reduce the résumé or portfolio size before retrying."
        ) from exc
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        if status_code is not None and status_code >= 500:
            return True
        if status_code == 429:
            return True
        return status_code in {400, 408, 409}
    if isinstance(exc, (httpx.NetworkError, httpx.ReadError)):
        return True
    message = str(exc).lower()
    if "too large" in message or "payload too large" in message:
        raise ApplicantEvaluationError(
            "The gateway rejected the request because the prompt was too large. "
            "The résumé or portfolio content must be reduced before retrying."
        ) from exc
    return False


def _invoke_with_retries(llm: Any, prompt: str, *, max_attempts: int = 3) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return llm.invoke(prompt)
        except Exception as exc:
            last_error = exc
            if not _is_transient_gateway_error(exc):
                message = f"Gateway request failed: {type(exc).__name__}: {exc}"
                if getattr(getattr(exc, "response", None), "status_code", None) in {401, 403}:
                    message = (
                        "Gateway authentication failed: the API key was rejected or missing. "
                        f"HTTP {getattr(exc.response, 'status_code', 'unknown')}"
                    )
                raise ApplicantEvaluationError(message) from exc
            if attempt == max_attempts:
                raise ApplicantEvaluationError(
                    f"Gateway request failed after {max_attempts} attempts: {type(exc).__name__}"
                ) from exc
            time.sleep(0.25 * attempt)
    if last_error is not None:
        raise ApplicantEvaluationError(f"Gateway request failed: {last_error}") from last_error
    raise ApplicantEvaluationError("Gateway request failed.")


def _parse_profile_text(raw_text: str, applicant_id: str, *, llm: Any, resume_text: str, portfolio_text: str, format_instructions: str) -> ApplicantProfile:
    parser = PydanticOutputParser(pydantic_object=ApplicantProfile)
    previous_text = raw_text
    for attempt in range(3):
        try:
            cleaned = _clean_json_text(previous_text)
            profile = parser.parse(cleaned)
            if profile.applicant_id != applicant_id:
                raise ValueError("Response applicant_id does not match the requested applicant ID")
            return profile
        except Exception as exc:
            if attempt >= 2:
                raise ApplicantEvaluationError(
                    "JSON validation failed after maximum retries: " + str(exc)
                ) from exc
            previous_text = _extract_text_content(
                _invoke_with_retries(
                    llm,
                    build_correction_prompt(
                        applicant_id,
                        resume_text,
                        portfolio_text,
                        previous_text,
                        str(exc),
                        format_instructions,
                    ),
                )
            )
    raise ApplicantEvaluationError("Applicant evaluation failed after retries.")


def evaluate_applicant(state: ProfileGraphState, llm_factory: Callable[[], Any] | None = None) -> dict[str, Any]:
    resume_text = state.get("resume_text", "")
    portfolio_text = state.get("portfolio_text", "")
    if not resume_text or not resume_text.strip():
        raise ProfileValidationError("Cannot evaluate an empty résumé.")

    applicant_id = (state.get("applicant_id") or "unknown-applicant").strip()
    if not applicant_id:
        applicant_id = "unknown-applicant"

    factory = llm_factory if llm_factory is not None else state.get("llm_factory") or create_profile_llm
    llm = factory()
    parser = PydanticOutputParser(pydantic_object=ApplicantProfile)
    format_instructions = parser.get_format_instructions()
    raw_prompt = build_profile_prompt(applicant_id, resume_text, portfolio_text, format_instructions)
    response = _invoke_with_retries(llm, raw_prompt)
    content = _extract_text_content(response)
    profile = _parse_profile_text(content, applicant_id, llm=llm, resume_text=resume_text, portfolio_text=portfolio_text, format_instructions=format_instructions)
    return {"profile": profile}


def evaluate_resume(
    resume_path: str | Path,
    applicant_id: str | None = None,
    portfolio_path: str | Path | None = None,
    enable_ocr: bool = False,
    llm_factory: Callable[[], Any] | None = None,
) -> ApplicantProfile:
    extracted = extract_documents({
        "applicant_id": applicant_id,
        "resume_path": str(Path(resume_path)),
        "portfolio_path": str(portfolio_path) if portfolio_path is not None else None,
        "enable_ocr": enable_ocr,
    })
    state: ProfileGraphState = {
        "applicant_id": applicant_id or "unknown-applicant",
        "resume_path": str(Path(resume_path)),
        "portfolio_path": str(portfolio_path) if portfolio_path is not None else None,
        "enable_ocr": enable_ocr,
        "resume_text": extracted["resume_text"],
        "portfolio_text": extracted["portfolio_text"],
    }
    if llm_factory is not None:
        state["llm_factory"] = llm_factory
    return evaluate_applicant(state, llm_factory=llm_factory)["profile"]


def write_json_atomic(target_path: str | Path, payload: ApplicantProfile | dict[str, Any] | str) -> None:
    destination = Path(target_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, ApplicantProfile):
        text = payload.model_dump_json(indent=2)
    elif isinstance(payload, dict):
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    else:
        text = str(payload)
    handle, temp_path = tempfile.mkstemp(
        dir=str(destination.parent),
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as write_handle:
            write_handle.write(text)
            write_handle.write("\n")
            write_handle.flush()
            os.fsync(write_handle.fileno())
        os.replace(temp_path, destination)
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise


def _build_graph() -> StateGraph:
    builder = StateGraph(ProfileGraphState)
    builder.add_node("extract_documents", extract_documents)
    builder.add_node(
        "evaluate_applicant",
        lambda state: evaluate_applicant(state, llm_factory=state.get("llm_factory")),
    )
    builder.add_edge(START, "extract_documents")
    builder.add_edge("extract_documents", "evaluate_applicant")
    builder.add_edge("evaluate_applicant", END)
    return builder


profile_graph = _build_graph().compile()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate an applicant profile from a résumé PDF.")
    parser.add_argument("resume_pdf", help="Path to the résumé PDF")
    parser.add_argument("--applicant-id", default=None, help="Optional applicant ID for the profile output")
    parser.add_argument("--portfolio", help="Optional portfolio file (.pdf, .md, .txt)")
    parser.add_argument("--ocr", action="store_true", help="Enable OCR for scanned PDFs")
    parser.add_argument("--output", help="Optional output JSON path")
    args = parser.parse_args(argv)

    resume_path = Path(args.resume_pdf)
    if not resume_path.is_file():
        print(f"ERROR: Résumé file does not exist: {resume_path}", file=sys.stderr)
        return 1
    if resume_path.suffix.lower() != ".pdf":
        print(f"ERROR: Résumé file must be a PDF: {resume_path}", file=sys.stderr)
        return 1

    try:
        profile = evaluate_resume(
            resume_path=resume_path,
            applicant_id=args.applicant_id,
            portfolio_path=args.portfolio,
            enable_ocr=args.ocr,
        )
        if args.output:
            write_json_atomic(args.output, profile)
            print(f"Wrote applicant profile to {args.output}", file=sys.stderr)
        else:
            print(profile.model_dump_json(indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
