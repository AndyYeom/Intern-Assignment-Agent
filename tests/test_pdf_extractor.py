from pathlib import Path

import pytest

from src.profile_agent import pdf_extractor


def test_extract_resume_rejects_missing_and_non_pdf(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        pdf_extractor.extract_resume(str(tmp_path / "missing.pdf"))

    text_file = tmp_path / "resume.txt"
    text_file.write_text("not a PDF", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a PDF"):
        pdf_extractor.extract_resume(str(text_file))


def test_extract_resume_creates_markdown_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_file = tmp_path / "resume.pdf"
    pdf_file.write_bytes(b"%PDF-test")
    output_file = tmp_path / "nested" / "resume.md"

    class FakeDocument:
        def export_to_markdown(self) -> str:
            return "# Ada Lovelace\n\n- Python"

    class FakeResult:
        document = FakeDocument()

    class FakeConverter:
        def convert(self, path: str) -> FakeResult:
            assert path == str(pdf_file)
            return FakeResult()

    monkeypatch.setattr(
        pdf_extractor,
        "_create_converter",
        lambda enable_ocr: FakeConverter(),
    )

    extracted = pdf_extractor.extract_resume(str(pdf_file), str(output_file))

    assert extracted == "# Ada Lovelace\n\n- Python"
    assert output_file.read_text(encoding="utf-8") == extracted + "\n"
