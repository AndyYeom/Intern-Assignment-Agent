"""Extract résumé PDFs into Markdown with Docling."""

from __future__ import annotations

import argparse
import os
import tempfile
from datetime import datetime
from pathlib import Path


class ResumeExtractionError(RuntimeError):
    """Raised when a résumé cannot be converted into meaningful Markdown."""


def _log(message: str) -> None:
    """Print a timestamped progress message."""
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def _create_converter(enable_ocr: bool):
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import (
        DocumentConverter,
        InputFormat,
        PdfFormatOption,
    )

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = enable_ocr
    pipeline_options.do_table_structure = False
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )


def extract_resume(
    pdf_path: str,
    output_path: str | None = None,
    enable_ocr: bool = False,
) -> str:
    """Convert a PDF résumé to Markdown and optionally save it as UTF-8."""
    input_path = Path(pdf_path)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input PDF does not exist: {input_path}")
    if input_path.suffix.lower() != ".pdf":
        raise ValueError(f"Input file must be a PDF: {input_path}")

    _log(f"OCR enabled: {enable_ocr}")
    try:
        _log("Before creating Docling converter")
        converter = _create_converter(enable_ocr)
        _log("After creating Docling converter")
        _log(f"Before converting PDF: {input_path}")
        result = converter.convert(str(input_path))
        _log("After converting PDF")
        _log("Before exporting Markdown")
        markdown = result.document.export_to_markdown()
        _log("After exporting Markdown")
    except Exception as exc:
        raise ResumeExtractionError(
            f"Failed to convert PDF '{input_path}': {exc}"
        ) from exc

    markdown = markdown.strip()
    if not markdown:
        raise ResumeExtractionError(
            f"No meaningful text was extracted from PDF: {input_path}"
        )

    if output_path is not None:
        destination = Path(output_path)
        if destination.suffix.lower() != ".md":
            raise ValueError(f"Output file must use the .md extension: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            _log(f"Before writing temporary Markdown file for: {destination}")
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=destination.parent,
                prefix=f".{destination.stem}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = temporary_file.name
                temporary_file.write(markdown + "\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
            _log(f"After writing output file: {destination}")
        finally:
            if temporary_path is not None:
                Path(temporary_path).unlink(missing_ok=True)

    return markdown


def main() -> None:
    """Run résumé extraction from the command line."""
    parser = argparse.ArgumentParser(description="Extract a résumé PDF to Markdown.")
    parser.add_argument("pdf_path", help="Path to the résumé PDF")
    parser.add_argument("--output", help="Optional Markdown output path")
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Enable OCR for scanned PDFs (disabled by default)",
    )
    args = parser.parse_args()

    markdown = extract_resume(args.pdf_path, args.output, enable_ocr=args.ocr)
    output_path = args.output or "(not saved)"
    print(f"Input filename: {Path(args.pdf_path).name}")
    print(f"Extracted characters: {len(markdown)}")
    print(f"Output path: {output_path}")
    print("Preview (first 500 characters):")
    print(markdown[:500])


if __name__ == "__main__":
    main()
