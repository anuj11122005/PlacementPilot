"""
Resume parser — Phase 1 of the PlacementPilot ingestion pipeline.

Accepts PDF or DOCX file paths and returns clean extracted text.

RULES compliance:
- Rule 5:  Never log raw resume text. Log file path and metadata only.
- Rule 14: Errors fail loudly via ParsingError — never silently swallowed.

Out of scope (Phase 2+): OCR for image-only PDFs, language detection,
multi-column layout normalisation.
"""

import logging
import re
from pathlib import Path

import pdfplumber
from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from ingestion.exceptions import ParsingError

logger = logging.getLogger(__name__)

# Supported file extensions
_SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


def parse_resume(file_path: str | Path) -> str:
    """
    Parse a resume file (PDF or DOCX) and return clean extracted text.

    Args:
        file_path: Absolute or relative path to the resume file.

    Returns:
        Cleaned text string with normalised whitespace.

    Raises:
        ParsingError: If the file cannot be parsed — including image-only PDFs,
                      malformed DOCX, missing file, or unsupported extension.
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    logger.info("Parsing resume: path=%s extension=%s", path.name, ext)

    if not path.exists():
        raise ParsingError(f"File not found: {path}")

    if ext not in _SUPPORTED_EXTENSIONS:
        raise ParsingError(
            f"Unsupported file type '{ext}'. Supported: {sorted(_SUPPORTED_EXTENSIONS)}"
        )

    if ext == ".pdf":
        text = _parse_pdf(path)
    else:
        text = _parse_docx(path)

    cleaned = _clean_text(text)
    logger.info(
        "Resume parsed successfully: path=%s chars=%d", path.name, len(cleaned)
    )
    return cleaned


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_pdf(path: Path) -> str:
    """Extract text from a PDF using pdfplumber.

    Raises ParsingError if the file cannot be opened or yields no text
    (which is the signature of a scanned / image-only PDF).
    """
    try:
        with pdfplumber.open(path) as pdf:
            pages_text = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages_text.append(page_text)
            raw = "\n".join(pages_text)
    except Exception as exc:
        # pdfplumber raises various low-level exceptions for corrupt files.
        # We wrap them all so callers get a single typed exception to handle.
        raise ParsingError(f"Could not open or read PDF '{path.name}': {exc}") from exc

    if not raw.strip():
        raise ParsingError(
            f"No extractable text found in '{path.name}'. "
            "This is likely a scanned or image-only PDF. "
            "OCR support is not available in Phase 1."
        )

    return raw


def _parse_docx(path: Path) -> str:
    """Extract text from a DOCX using python-docx.

    Raises ParsingError if the file is malformed or cannot be opened.
    """
    try:
        doc = Document(str(path))
    except PackageNotFoundError as exc:
        raise ParsingError(
            f"Malformed or unreadable DOCX file '{path.name}': {exc}"
        ) from exc
    except Exception as exc:
        raise ParsingError(
            f"Could not open DOCX '{path.name}': {exc}"
        ) from exc

    paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
    raw = "\n".join(paragraphs)

    if not raw.strip():
        raise ParsingError(
            f"No text content found in DOCX '{path.name}'. The file may be empty."
        )

    return raw


def _clean_text(text: str) -> str:
    """Normalise whitespace and remove non-printable characters."""
    # Replace null bytes and control chars (except newlines/tabs)
    text = re.sub(r"[^\x09\x0A\x0D\x20-\x7E\u00A0-\uFFFF]", " ", text)
    # Collapse runs of spaces/tabs (but preserve newlines for section detection)
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ consecutive newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
