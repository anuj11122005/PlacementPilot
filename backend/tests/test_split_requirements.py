"""
Unit tests for _split_requirements() — the heuristic that splits
multi-skill JD chunks into individual requirements.

Covers the three critical edge cases:
1. Prose-style text with no enumerable list -> falls through unchanged
2. Nested parenthetical items like "AWS (EC2, S3, Lambda)" -> preserved
3. Normal comma+and skill list -> correctly split
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from retrieval.retriever import _split_requirements


class TestSplitRequirements:
    """Tests for the _split_requirements heuristic."""

    # ------------------------------------------------------------------
    # Edge case (a): Prose-style JD text with NO enumerable list.
    # Must fall through unchanged (single-element list returned).
    # ------------------------------------------------------------------

    def test_prose_style_no_list(self):
        """Pure prose with no commas or conjunctions -> no split."""
        text = "designed and shipped production ML systems at scale"
        result = _split_requirements(text)
        assert result == [text], (
            f"Prose text should fall through unchanged, got {result}"
        )

    def test_prose_long_sentence(self):
        """A long descriptive sentence -> no split."""
        text = (
            "Build scalable distributed systems that handle "
            "millions of requests per day with high availability"
        )
        result = _split_requirements(text)
        assert result == [text]

    def test_prose_with_comma_but_long_items(self):
        """Commas in prose where items are too long to be skill names."""
        text = (
            "Designed microservices handling high traffic, "
            "built resilient data pipelines for real-time analytics"
        )
        result = _split_requirements(text)
        assert result == [text], (
            f"Items are too long (>5 words) to be skill names, should not split: {result}"
        )

    def test_prose_and_conjunction_long(self):
        """'and' conjunction in prose where both sides are long."""
        text = (
            "Experience building large-scale data platforms and "
            "designing fault-tolerant distributed architectures"
        )
        result = _split_requirements(text)
        assert result == [text]

    # ------------------------------------------------------------------
    # Edge case (b): Nested/parenthetical items.
    # Commas inside parens must NOT be split on. The parenthetical group
    # stays as a single unit.
    # ------------------------------------------------------------------

    def test_nested_parens_preserved(self):
        """'AWS (EC2, S3, Lambda) and CI/CD' -> 2 items, not 4."""
        text = "AWS (EC2, S3, Lambda) and CI/CD"
        result = _split_requirements(text)
        assert result == ["AWS (EC2, S3, Lambda)", "CI/CD"], (
            f"Should split into 2 items preserving parens, got {result}"
        )

    def test_multiple_paren_groups(self):
        """Multiple parenthetical groups in a comma list."""
        text = "AWS (EC2, S3), Docker (Compose, Swarm), and Kubernetes"
        result = _split_requirements(text)
        assert result == ["AWS (EC2, S3)", "Docker (Compose, Swarm)", "Kubernetes"], (
            f"Should preserve both paren groups, got {result}"
        )

    def test_single_paren_no_split(self):
        """A single item with parens and no list -> no split."""
        text = "AWS (EC2, S3, Lambda)"
        result = _split_requirements(text)
        assert result == [text], (
            f"Single item with parens should not split, got {result}"
        )

    # ------------------------------------------------------------------
    # Normal case: comma+and skill list -> correctly split
    # ------------------------------------------------------------------

    def test_comma_and_list(self):
        """Standard 'A, B, C, and D' pattern."""
        text = "Python, FastAPI, SQL, and Kubernetes"
        result = _split_requirements(text)
        assert result == ["Python", "FastAPI", "SQL", "Kubernetes"], (
            f"Should split into 4 items, got {result}"
        )

    def test_comma_list_no_and(self):
        """Comma list without trailing 'and'."""
        text = "Python, Java, Go"
        result = _split_requirements(text)
        assert result == ["Python", "Java", "Go"]

    def test_two_items_with_and(self):
        """Bare 'X and Y' with short items."""
        text = "Docker and Kubernetes"
        result = _split_requirements(text)
        assert result == ["Docker", "Kubernetes"]

    def test_multi_word_skills(self):
        """Multi-word skill names that are still short enough."""
        text = "React Native, Node.js, and GraphQL"
        result = _split_requirements(text)
        assert result == ["React Native", "Node.js", "GraphQL"]

    # ------------------------------------------------------------------
    # Boundary / degenerate cases
    # ------------------------------------------------------------------

    def test_empty_string(self):
        """Empty string -> falls through unchanged."""
        result = _split_requirements("")
        assert result == [""]

    def test_single_word(self):
        """Single word -> no split."""
        result = _split_requirements("Python")
        assert result == ["Python"]

    def test_whitespace_only(self):
        """Whitespace-only -> falls through unchanged."""
        text = "   "
        result = _split_requirements(text)
        assert result == [text]

    def test_mixed_short_and_long_items(self):
        """If even ONE item is too long, entire split is aborted."""
        text = (
            "Python, experience building highly scalable systems, Docker"
        )
        result = _split_requirements(text)
        assert result == [text], (
            f"Should abort split because middle item is too long, got {result}"
        )
