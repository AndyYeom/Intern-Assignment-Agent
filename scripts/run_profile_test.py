from __future__ import annotations

import argparse
from pathlib import Path

from src.profile_agent.profile_graph import (
    ProfileConfigurationError,
    ProfileGraphState,
    evaluate_applicant,
    extract_documents,
    write_json_atomic,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the two-node applicant profile pipeline on one résumé PDF."
    )
    parser.add_argument("resume_pdf", type=Path, help="Path to the résumé PDF")
    parser.add_argument(
        "--applicant-id",
        help="Applicant ID; defaults to the PDF filename without its extension",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for extracted Markdown and profile JSON",
    )
    parser.add_argument("--ocr", action="store_true", help="Enable OCR for scanned PDFs")
    args = parser.parse_args()

    if not args.resume_pdf.is_file():
        parser.error(f"Résumé PDF does not exist: {args.resume_pdf}")
    if args.resume_pdf.suffix.lower() != ".pdf":
        parser.error(f"Résumé file must be a PDF: {args.resume_pdf}")

    applicant_id = args.applicant_id or args.resume_pdf.stem
    extracted_path = args.output_dir / f"{applicant_id}_extracted.md"
    profile_path = args.output_dir / f"{applicant_id}_profile.json"

    state: ProfileGraphState = {
        "applicant_id": applicant_id,
        "resume_path": str(args.resume_pdf),
        "portfolio_path": None,
        "enable_ocr": args.ocr,
    }
    extracted = extract_documents(state)
    state.update(extracted)
    write_markdown_path = extracted_path
    write_markdown_path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown_path.write_text(extracted["resume_text"] + "\n", encoding="utf-8")

    try:
        evaluated = evaluate_applicant(state)
    except ProfileConfigurationError as exc:
        raise SystemExit(
            f"{exc}\nCreate a .env file with LLM_GATEWAY_URL, "
            "LLM_GATEWAY_API_KEY, and LLM_MODEL, then run the command again."
        ) from exc
    write_json_atomic(profile_path, evaluated["profile"])

    print(f"Applicant ID: {applicant_id}")
    print(f"Extracted Markdown: {extracted_path}")
    print(f"Profile JSON: {profile_path}")
    print(f"Extracted characters: {len(extracted['resume_text'])}")
    print(f"Evaluated skills: {len(evaluated['profile'].skills)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
