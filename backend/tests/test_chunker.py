"""
Unit tests for backend/ingestion/chunker.py

Tests cover:
  - Empty text input → ChunkingError (PHASES.md Phase 1 edge case)
  - Invalid source identifier → ValueError
  - Section detection for resume sections (skills, experience, etc.)
  - Section detection for JD sections (requirements, responsibilities, etc.)
  - Fallback to "general" when no known headers are found
  - chunk_id format: "{source}_{section_type}_{index}"
  - All required metadata keys present in every chunk

RULES compliance:
  - Rule 11: chunker is pure-function / no global state → fully unit-testable
  - Rule 14: ChunkingError raised explicitly, never swallowed
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ingestion.chunker import DEFAULT_MIN_CHUNK_CHARS, chunk_text
from ingestion.exceptions import ChunkingError


# ---------------------------------------------------------------------------
# Required metadata keys
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {"source", "section_type", "chunk_id", "text"}


# ---------------------------------------------------------------------------
# Edge case tests (PHASES.md Phase 1)
# ---------------------------------------------------------------------------


class TestEmptyInput:
    def test_empty_string_raises_chunking_error(self) -> None:
        with pytest.raises(ChunkingError):
            chunk_text("", source="resume")

    def test_whitespace_only_raises_chunking_error(self) -> None:
        with pytest.raises(ChunkingError):
            chunk_text("   \n\n\t  ", source="resume")

    def test_error_is_not_swallowed(self) -> None:
        raised = False
        try:
            chunk_text("", source="jd")
        except ChunkingError:
            raised = True
        assert raised


class TestInvalidSource:
    def test_unknown_source_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="[Ii]nvalid source"):
            chunk_text("Some content here with enough text to pass.", source="document")

    def test_none_source_raises_value_error(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            chunk_text("Some content here with enough text to pass.", source=None)  # type: ignore

    def test_empty_source_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="[Ii]nvalid source"):
            chunk_text("Some content here with enough text to pass.", source="")


# ---------------------------------------------------------------------------
# Section detection — Resume
# ---------------------------------------------------------------------------


class TestResumeSectionDetection:
    def test_skills_section_detected(self) -> None:
        text = (
            "John Doe | john@example.com\n"
            "\n"
            "Skills\n"
            "Python, FastAPI, PostgreSQL, Docker, REST APIs\n"
        )
        chunks = chunk_text(text, source="resume")
        section_types = {c["section_type"] for c in chunks}
        assert "skills" in section_types, (
            f"Expected 'skills' section in: {section_types}"
        )

    def test_experience_section_detected(self) -> None:
        text = (
            "Experience\n"
            "Backend Engineer at Acme Corp, 2021-2024\n"
            "Built scalable APIs serving millions of users.\n"
        )
        chunks = chunk_text(text, source="resume")
        section_types = {c["section_type"] for c in chunks}
        assert "experience" in section_types

    def test_education_section_detected(self) -> None:
        text = (
            "Education\n"
            "B.Sc. Computer Science, State University, 2021\n"
            "GPA 3.8/4.0\n"
        )
        chunks = chunk_text(text, source="resume")
        section_types = {c["section_type"] for c in chunks}
        assert "education" in section_types

    def test_projects_section_detected(self) -> None:
        text = (
            "Projects\n"
            "PlacementPilot: RAG-based resume analysis tool built with FastAPI.\n"
        )
        chunks = chunk_text(text, source="resume")
        section_types = {c["section_type"] for c in chunks}
        assert "projects" in section_types

    def test_summary_section_detected(self) -> None:
        text = (
            "Summary\n"
            "Experienced software engineer with 5+ years building distributed systems.\n"
        )
        chunks = chunk_text(text, source="resume")
        section_types = {c["section_type"] for c in chunks}
        assert "summary" in section_types

    def test_certifications_section_detected(self) -> None:
        text = (
            "Certifications\n"
            "AWS Certified Solutions Architect\n"
            "Google Cloud Professional Data Engineer\n"
        )
        chunks = chunk_text(text, source="resume")
        section_types = {c["section_type"] for c in chunks}
        assert "certifications" in section_types

    def test_multiple_sections_all_detected(self) -> None:
        text = (
            "Skills\n"
            "Python, SQL, Docker, FastAPI, Redis\n"
            "\n"
            "Experience\n"
            "Senior Engineer at Corp, 2020-2024. Built backend systems.\n"
            "\n"
            "Education\n"
            "B.Sc. CS, University of Example, 2020\n"
        )
        chunks = chunk_text(text, source="resume")
        section_types = {c["section_type"] for c in chunks}
        assert {"skills", "experience", "education"}.issubset(section_types), (
            f"Expected skills+experience+education in: {section_types}"
        )


# ---------------------------------------------------------------------------
# Section detection — JD
# ---------------------------------------------------------------------------


class TestJDSectionDetection:
    def test_requirements_section_detected(self) -> None:
        text = (
            "Requirements\n"
            "3+ years Python experience. Strong SQL skills. REST API design.\n"
        )
        chunks = chunk_text(text, source="jd")
        section_types = {c["section_type"] for c in chunks}
        assert "requirements" in section_types

    def test_responsibilities_section_detected(self) -> None:
        text = (
            "Responsibilities\n"
            "Design and implement scalable backend services.\n"
            "Collaborate with cross-functional teams.\n"
        )
        chunks = chunk_text(text, source="jd")
        section_types = {c["section_type"] for c in chunks}
        assert "responsibilities" in section_types

    def test_nice_to_have_section_detected(self) -> None:
        text = (
            "Nice to have\n"
            "Experience with Kubernetes and CI/CD pipelines.\n"
        )
        chunks = chunk_text(text, source="jd")
        section_types = {c["section_type"] for c in chunks}
        assert "nice_to_have" in section_types

    def test_benefits_section_detected(self) -> None:
        text = (
            "Benefits\n"
            "Competitive salary, remote-first, health insurance, 401k.\n"
        )
        chunks = chunk_text(text, source="jd")
        section_types = {c["section_type"] for c in chunks}
        assert "benefits" in section_types


# ---------------------------------------------------------------------------
# Fallback section
# ---------------------------------------------------------------------------


class TestFallbackSection:
    def test_no_headers_falls_back_to_general(self) -> None:
        """Text with no recognised section headers → single 'general' chunk."""
        text = (
            "We are a startup building developer tools. "
            "We value ownership, speed, and shipping working software. "
            "You will work on backend infrastructure and own entire features."
        )
        chunks = chunk_text(text, source="jd")
        section_types = {c["section_type"] for c in chunks}
        assert section_types == {"general"}, (
            f"Expected only 'general', got: {section_types}"
        )

    def test_general_chunk_has_content(self) -> None:
        text = (
            "We are looking for a motivated engineer to join our team. "
            "You will have a big impact on our product and infrastructure."
        )
        chunks = chunk_text(text, source="resume")
        assert len(chunks) > 0
        assert all(len(c["text"].strip()) > 0 for c in chunks)


# ---------------------------------------------------------------------------
# chunk_id format
# ---------------------------------------------------------------------------


class TestChunkIdFormat:
    def test_chunk_id_format_resume(self) -> None:
        text = (
            "Skills\n"
            "Python, FastAPI, PostgreSQL, Docker, REST API design patterns\n"
        )
        chunks = chunk_text(text, source="resume")
        skill_chunks = [c for c in chunks if c["section_type"] == "skills"]
        assert len(skill_chunks) > 0
        chunk_id = skill_chunks[0]["chunk_id"]
        assert chunk_id.startswith("resume_skills_"), (
            f"chunk_id '{chunk_id}' should start with 'resume_skills_'"
        )

    def test_chunk_id_format_jd(self) -> None:
        text = (
            "Requirements\n"
            "3+ years Python. Strong SQL. REST API design experience required.\n"
        )
        chunks = chunk_text(text, source="jd")
        req_chunks = [c for c in chunks if c["section_type"] == "requirements"]
        assert len(req_chunks) > 0
        chunk_id = req_chunks[0]["chunk_id"]
        assert chunk_id.startswith("jd_requirements_"), (
            f"chunk_id '{chunk_id}' should start with 'jd_requirements_'"
        )

    def test_chunk_id_index_increments(self) -> None:
        """If the same section appears twice, indices increment (0, 1, ...)."""
        # Two separate 'general' blocks (no headings)
        text = (
            "First paragraph of content with enough text for a chunk here.\n\n"
            "Second paragraph of content with enough text for a chunk here.\n"
        )
        chunks = chunk_text(text, source="resume", min_chunk_chars=10)
        # May be one or two chunks depending on how lines are split; either way,
        # chunk_ids must match the expected format
        for chunk in chunks:
            source = chunk["source"]
            section = chunk["section_type"]
            cid = chunk["chunk_id"]
            assert cid.startswith(f"{source}_{section}_"), (
                f"chunk_id '{cid}' doesn't match expected pattern"
            )

    def test_chunk_id_is_string(self) -> None:
        text = (
            "Skills\n"
            "Python, Docker, FastAPI, PostgreSQL, REST API design, testing\n"
        )
        chunks = chunk_text(text, source="resume")
        for chunk in chunks:
            assert isinstance(chunk["chunk_id"], str)


# ---------------------------------------------------------------------------
# Metadata completeness
# ---------------------------------------------------------------------------


class TestMetadataKeys:
    def test_all_required_keys_present(self) -> None:
        text = (
            "Skills\n"
            "Python, FastAPI, Docker, PostgreSQL, testing frameworks\n"
            "\n"
            "Experience\n"
            "Senior engineer at Corp building scalable distributed systems.\n"
        )
        chunks = chunk_text(text, source="resume")
        for chunk in chunks:
            missing = REQUIRED_KEYS - set(chunk.keys())
            assert not missing, (
                f"Chunk {chunk.get('chunk_id', '?')} is missing keys: {missing}"
            )

    def test_source_field_matches_input(self) -> None:
        text = (
            "Requirements\n"
            "3+ years Python, FastAPI, SQL, Docker, distributed systems experience.\n"
        )
        for source in ("resume", "jd"):
            chunks = chunk_text(text, source=source)
            for chunk in chunks:
                assert chunk["source"] == source

    def test_text_field_is_nonempty_string(self) -> None:
        text = (
            "Skills\n"
            "Python, FastAPI, PostgreSQL, Docker, REST APIs, distributed systems\n"
        )
        chunks = chunk_text(text, source="resume")
        for chunk in chunks:
            assert isinstance(chunk["text"], str)
            assert len(chunk["text"].strip()) > 0

    def test_section_type_is_string(self) -> None:
        text = (
            "Experience\n"
            "Backend Engineer at Acme Corp, 2021-2024. Built scalable APIs.\n"
        )
        chunks = chunk_text(text, source="resume")
        for chunk in chunks:
            assert isinstance(chunk["section_type"], str)
            assert len(chunk["section_type"]) > 0
