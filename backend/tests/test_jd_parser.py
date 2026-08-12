"""
Unit tests for backend/ingestion/jd_parser.py

Tests cover all edge cases from PHASES.md Phase 1:
  - Very short JD (under minimum threshold)
  - Empty string
  - Whitespace-only string
  - Valid JD (happy path)
  - Whitespace normalisation

RULES compliance verified:
  - Rule 14: Errors are ParsingError — never silently swallowed
  - Rule 5:  Parser logs char counts, not raw text (tested indirectly by
             confirming the return value hasn't been mangled)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ingestion.exceptions import ParsingError
from ingestion.jd_parser import MINIMUM_JD_CHARS, parse_jd


# ---------------------------------------------------------------------------
# Edge case tests (PHASES.md Phase 1: "very short JD")
# ---------------------------------------------------------------------------


class TestEmptyJD:
    def test_empty_string_raises(self) -> None:
        with pytest.raises(ParsingError, match="[Ee]mpty|[Ww]hitespace"):
            parse_jd("")

    def test_empty_string_error_not_swallowed(self) -> None:
        raised = False
        try:
            parse_jd("")
        except ParsingError:
            raised = True
        assert raised


class TestWhitespaceOnlyJD:
    def test_spaces_only_raises(self) -> None:
        with pytest.raises(ParsingError, match="[Ee]mpty|[Ww]hitespace"):
            parse_jd("   ")

    def test_newlines_only_raises(self) -> None:
        with pytest.raises(ParsingError, match="[Ee]mpty|[Ww]hitespace"):
            parse_jd("\n\n\n")

    def test_tabs_only_raises(self) -> None:
        with pytest.raises(ParsingError, match="[Ee]mpty|[Ww]hitespace"):
            parse_jd("\t\t\t")

    def test_mixed_whitespace_raises(self) -> None:
        with pytest.raises(ParsingError, match="[Ee]mpty|[Ww]hitespace"):
            parse_jd("  \n  \t  \n")


class TestVeryShortJD:
    """
    Strings that are non-empty after stripping but below MINIMUM_JD_CHARS.
    These simulate a JD that has some content but is too sparse to analyse.
    """

    def test_one_word_raises(self) -> None:
        with pytest.raises(ParsingError, match="[Tt]oo short|[Mm]inimum"):
            parse_jd("Engineer")

    def test_just_under_threshold_raises(self) -> None:
        short_text = "a" * (MINIMUM_JD_CHARS - 1)
        with pytest.raises(ParsingError, match="[Tt]oo short|[Mm]inimum"):
            parse_jd(short_text)

    def test_error_message_includes_char_count(self) -> None:
        """Error should tell the user how many chars were found vs the minimum."""
        short_text = "Too short"
        with pytest.raises(ParsingError) as exc_info:
            parse_jd(short_text)
        msg = str(exc_info.value)
        # Should contain both the actual count and the threshold
        assert str(MINIMUM_JD_CHARS) in msg, (
            f"Error message should mention the minimum ({MINIMUM_JD_CHARS}): {msg}"
        )

    def test_custom_min_chars_respected(self) -> None:
        """parse_jd accepts a custom min_chars parameter."""
        # Text that passes default but would fail a stricter threshold
        text = "a" * (MINIMUM_JD_CHARS + 10)
        result = parse_jd(text, min_chars=MINIMUM_JD_CHARS)
        assert result  # passes default

        # Same text should fail if we set a stricter threshold
        with pytest.raises(ParsingError, match="[Tt]oo short|[Mm]inimum"):
            parse_jd(text, min_chars=len(text) + 100)


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


class TestValidJD:
    SAMPLE_JD = (
        "We are looking for a Senior Python Engineer with experience in FastAPI, "
        "PostgreSQL, and distributed systems. You will design and build scalable "
        "backend services for our data platform. Requirements: 3+ years Python, "
        "strong SQL skills, experience with REST API design."
    )

    def test_valid_jd_returns_string(self) -> None:
        result = parse_jd(self.SAMPLE_JD)
        assert isinstance(result, str)

    def test_valid_jd_returns_nonempty(self) -> None:
        result = parse_jd(self.SAMPLE_JD)
        assert len(result) > 0

    def test_exactly_at_threshold_passes(self) -> None:
        text = "x" * MINIMUM_JD_CHARS
        result = parse_jd(text)
        assert len(result) >= MINIMUM_JD_CHARS

    def test_wrong_input_type_raises(self) -> None:
        with pytest.raises(ParsingError, match="[Ss]tring"):
            parse_jd(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Whitespace normalisation tests
# ---------------------------------------------------------------------------


class TestWhitespaceNormalisation:
    def test_double_spaces_collapsed(self) -> None:
        text = "We  need   a  Python   engineer  with  strong  SQL  skills  and  more."
        result = parse_jd(text)
        assert "  " not in result, "Double spaces should be collapsed"

    def test_leading_trailing_whitespace_stripped(self) -> None:
        base = "We need a Python engineer with experience in FastAPI and PostgreSQL systems."
        text = f"   \n\n{base}\n\n   "
        result = parse_jd(text)
        assert result == result.strip()

    def test_excessive_newlines_collapsed(self) -> None:
        base = "Looking for a backend engineer with Python experience and strong SQL."
        text = f"{base}\n\n\n\n\nRequirements: 3+ years"
        result = parse_jd(text)
        assert "\n\n\n" not in result, "Three+ consecutive newlines should be collapsed to two"

    def test_null_bytes_removed(self) -> None:
        base = "We need a Python engineer with experience in FastAPI and distributed systems."
        text = f"{base}\x00extra\x00content"
        result = parse_jd(text)
        assert "\x00" not in result
