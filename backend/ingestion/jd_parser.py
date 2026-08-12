"""
JD (Job Description) parser — Phase 1 of the PlacementPilot ingestion pipeline.

Accepts plain text (pasted or pre-read from a file) and returns clean,
normalised text ready for chunking.

RULES compliance:
- Rule 5:  Never log raw JD text. Log character counts and metadata only.
- Rule 14: Errors fail loudly via ParsingError — never silently swallowed.

Design note: JDs are always passed as plain text (not as file uploads) in
Phase 1. File-based JD ingestion (e.g., .txt upload) can be added in Phase 6
when the API layer is built — the parser itself doesn't need to change.
"""

import logging
import re

from ingestion.exceptions import ParsingError

logger = logging.getLogger(__name__)

# A JD shorter than this is flagged as too short to analyse meaningfully.
# Value from ARCHITECTURE.md §5: "JD too short/vague → Flag JD as low-information."
# 50 chars is a floor that catches accidental empty pastes and one-line stubs
# while allowing very terse JDs through for manual review.
MINIMUM_JD_CHARS = 50


def parse_jd(text: str, min_chars: int = MINIMUM_JD_CHARS) -> str:
    """
    Parse and clean a raw job description string.

    Args:
        text:      Raw JD text (plain text, pasted or pre-read from a file).
        min_chars: Minimum character count after cleaning. Texts below this
                   threshold are rejected with a ParsingError so the caller
                   can surface an explicit "JD too short" message rather than
                   producing low-quality analysis silently.

    Returns:
        Cleaned, normalised text string.

    Raises:
        ParsingError: If the text is empty, whitespace-only, or shorter than
                      min_chars after cleaning.
    """
    if not isinstance(text, str):
        raise ParsingError(
            f"JD input must be a string, got {type(text).__name__}."
        )

    cleaned = _clean_text(text)

    logger.info("JD parsed: chars_raw=%d chars_clean=%d", len(text), len(cleaned))

    if not cleaned:
        raise ParsingError(
            "JD text is empty or contains only whitespace. "
            "Please paste or upload a non-empty job description."
        )

    if len(cleaned) < min_chars:
        raise ParsingError(
            f"JD text is too short ({len(cleaned)} chars after cleaning; "
            f"minimum is {min_chars}). "
            "The job description may be incomplete or too vague to analyse."
        )

    return cleaned


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean_text(text: str) -> str:
    """Normalise whitespace and remove non-printable characters from JD text."""
    # Strip null bytes and other control chars (keep newlines and tabs)
    text = re.sub(r"[^\x09\x0A\x0D\x20-\x7E\u00A0-\uFFFF]", " ", text)
    # Collapse horizontal whitespace runs
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ consecutive newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
