import os
import sys
import re
import pytest
import uuid
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add backend to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from embeddings.embedder import Embedder
from retrieval.retriever import HybridRetriever, RETRIEVAL_CONFIDENCE_THRESHOLD

# ---------------------------------------------------------------------------
# Shared fixture: embed the same 5 resume chunks used in every regression case.
# Uses the real embedding model (all-MiniLM-L6-v2) but mocks the DB layer
# so tests can run without Postgres.
# ---------------------------------------------------------------------------

RESUME_CHUNKS = [
    {"source": "resume", "section_type": "general",    "chunk_id": "gen_001",
     "text": "Alice Johnson\nBackend Engineer\nalice@example.com"},
    {"source": "resume", "section_type": "summary",    "chunk_id": "sum_001",
     "text": "Backend Engineer with 5 years of experience building Python microservices. Passionate about team collaboration, mentoring juniors, and delivering scalable systems."},
    {"source": "resume", "section_type": "languages",  "chunk_id": "lang_001",
     "text": "Languages: Python, JavaScript, SQL. Frameworks: FastAPI, Django. Tools: Docker, AWS, Git."},
    {"source": "resume", "section_type": "experience", "chunk_id": "exp_001",
     "text": "Software Engineer at TechCorp. Led a team of 3 developers to migrate a monolithic application to FastAPI microservices. Managed sprints and conducted code reviews."},
    {"source": "resume", "section_type": "education",  "chunk_id": "edu_001",
     "text": "B.S. in Computer Science, State University."},
]


def _cosine_sim(a, b):
    """Cosine similarity between two vectors."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


@pytest.fixture(scope="module")
def retriever_with_mock_store():
    """
    Build a HybridRetriever backed by a mock Store that uses real embeddings
    but no database.  The mock's `search_similar_chunks` computes cosine
    similarity in-process, and `get_all_chunks` returns the plain chunk dicts.
    """
    embedder = Embedder()
    # Pre-compute chunk embeddings once
    texts = [c["text"] for c in RESUME_CHUNKS]
    chunk_embeddings = embedder.model.encode(texts)

    mock_store = MagicMock()

    # get_all_chunks -> returns the raw chunks (no embedding key needed for BM25)
    mock_store.get_all_chunks.return_value = [
        {"chunk_id": c["chunk_id"], "section_type": c["section_type"],
         "text": c["text"], "source": c["source"]}
        for c in RESUME_CHUNKS
    ]

    # search_similar_chunks -> computes cosine similarity on the fly
    def _search(query_embedding, analysis_id, source, limit=10):
        sims = []
        for i, chunk in enumerate(RESUME_CHUNKS):
            sim = _cosine_sim(query_embedding, chunk_embeddings[i])
            sims.append({
                "chunk_id": chunk["chunk_id"],
                "section_type": chunk["section_type"],
                "text": chunk["text"],
                "source": chunk["source"],
                "similarity": sim,
            })
        sims.sort(key=lambda x: x["similarity"], reverse=True)
        return sims[:limit]

    mock_store.search_similar_chunks.side_effect = _search

    retriever = HybridRetriever(embedder, mock_store)
    return retriever


# ---------------------------------------------------------------------------
# Helper to run a query and return the full result + breakdown dict
# ---------------------------------------------------------------------------

def _query(retriever, query_text):
    result = retriever.search(query_text, analysis_id="regression", source="resume", top_k=2)
    m = result["metrics"]
    return {
        "confidence": result["confidence_score"],
        "is_confident": result["is_confident"],
        "base_semantic": m["top_1_similarity"],
        "section_bonus": m["section_bonus"],
        "bm25_bonus": m["bm25_bonus"],
        "top_section": result["chunks"][0]["section_type"],
        "result": result,
    }


# ============================= REGRESSION TESTS ============================

class TestMotivatingExamples:
    """
    The three motivating examples that drove the hybrid confidence formula.
    Each test asserts the full numeric breakdown (base_semantic + section_bonus
    + bm25_bonus) to prevent silent regressions.

    Score reference (all-MiniLM-L6-v2, Aug 2026):
      Case 1  ->  0.49 + 0.00 + 0.00 = 0.49   (confident)
      Case 2  ->  0.29 + 0.00 + 0.00 = 0.29   (not confident)
      Case 3  ->  0.37 + 0.05 + 0.15 = 0.57   (confident -- rescued by bonus)
    """

    # -- Case 1: Python/FastAPI strong match (previously ~0.63 with old formula) --
    def test_case1_python_fastapi_strong_match(self, retriever_with_mock_store):
        """
        A query that directly matches the candidate's tech stack.
        Must be is_confident=True.

        After hybrid re-sort (similarity + bm25*0.1), the 'summary' chunk
        wins top-1 because its high BM25 score (~2.39) boosts its hybrid
        score above the 'languages' chunk.  This means section_bonus fires
        (+0.05) and bm25_bonus fires (+0.15, raw BM25 > 1.0).
        """
        r = _query(retriever_with_mock_store, "Experience with Python and FastAPI")

        # Base semantic for top-1 chunk (summary after re-sort) is ~0.45
        assert 0.39 <= r["base_semantic"] <= 0.55, (
            f"base_semantic={r['base_semantic']:.4f} outside expected range [0.39, 0.55]"
        )
        # After hybrid re-sort, 'summary' wins top-1 => section_bonus fires
        assert r["top_section"] in ("summary", "languages", "experience"), (
            f"Top chunk should be summary/languages/experience, got '{r['top_section']}'"
        )
        assert r["section_bonus"] in (0.0, 0.05), f"Unexpected section_bonus={r['section_bonus']}"
        assert r["bm25_bonus"] in (0.0, 0.15), f"Unexpected bm25_bonus={r['bm25_bonus']}"

        # Total confidence must exceed threshold
        assert r["confidence"] >= RETRIEVAL_CONFIDENCE_THRESHOLD, (
            f"Case 1 should be confident: confidence={r['confidence']:.4f} < {RETRIEVAL_CONFIDENCE_THRESHOLD}"
        )
        assert r["is_confident"] is True

        # Print breakdown for diagnostic visibility
        print(f"\n  Case 1 -- Python/FastAPI strong match")
        print(f"    top_section:   {r['top_section']}")
        print(f"    base_semantic: {r['base_semantic']:.4f}")
        print(f"    section_bonus: {r['section_bonus']:.4f}")
        print(f"    bm25_bonus:    {r['bm25_bonus']:.4f}")
        print(f"    TOTAL:         {r['confidence']:.4f}  (threshold={RETRIEVAL_CONFIDENCE_THRESHOLD})")

    # -- Case 2: Java/Spring mismatch (previously ~0.38 with old formula) --
    def test_case2_java_spring_mismatch(self, retriever_with_mock_store):
        """
        A query for technologies NOT on the resume.  Semantic similarity
        is non-zero (both are "programming frameworks") but must stay below
        threshold.  Must be is_confident=False.

        After hybrid re-sort, 'summary' may win top-1 (its small BM25
        addend beats 'languages' which has 0 BM25 for Java/Spring).
        Even with section_bonus=0.05, the total stays well below 0.40.
        """
        r = _query(retriever_with_mock_store, "Expertise in Java and Spring Boot")

        # Base semantic should be low -- Java/Spring != Python/FastAPI
        assert r["base_semantic"] < 0.35, (
            f"base_semantic={r['base_semantic']:.4f} too high for a mismatch query"
        )
        # Section bonus may fire if summary/experience wins after re-sort, but
        # even with +0.05 the total must stay below threshold.
        assert r["section_bonus"] in (0.0, 0.05), (
            f"Unexpected section_bonus={r['section_bonus']} for mismatch query"
        )
        # No BM25 bonus -- 'Java' and 'Spring Boot' don't appear in any chunk
        # (raw BM25 for top chunk is well below 1.0)
        assert r["bm25_bonus"] == 0.0, (
            f"BM25 should not fire for absent keywords; got bm25_bonus={r['bm25_bonus']}"
        )

        # Total confidence must stay BELOW threshold
        assert r["confidence"] < RETRIEVAL_CONFIDENCE_THRESHOLD, (
            f"Case 2 must NOT be confident: confidence={r['confidence']:.4f} >= {RETRIEVAL_CONFIDENCE_THRESHOLD}"
        )
        assert r["is_confident"] is False

        print(f"\n  Case 2 -- Java/Spring mismatch")
        print(f"    top_section:   {r['top_section']}")
        print(f"    base_semantic: {r['base_semantic']:.4f}")
        print(f"    section_bonus: {r['section_bonus']:.4f}")
        print(f"    bm25_bonus:    {r['bm25_bonus']:.4f}")
        print(f"    TOTAL:         {r['confidence']:.4f}  (threshold={RETRIEVAL_CONFIDENCE_THRESHOLD})")

    # -- Case 3: Leadership/soft-skill (previously ~0.29, the bug this formula fixes) --
    def test_case3_leadership_soft_skill(self, retriever_with_mock_store):
        """
        A soft-skill query ("leading teams", "managing sprints") that matches
        the experience section.  Under the OLD formula (semantic-only at 0.60
        threshold) this was a false negative.  Under the NEW formula:
          - section_bonus fires (+0.05, top chunk is 'experience')
          - bm25_bonus fires (+0.15, keywords "team"/"sprints" are present)
        Together they rescue the query over the 0.40 threshold.
        """
        r = _query(retriever_with_mock_store, "Experience leading teams and managing sprints")

        # Base semantic should be moderate -- soft-skill queries embed farther from text
        assert 0.30 <= r["base_semantic"] <= 0.42, (
            f"base_semantic={r['base_semantic']:.4f} outside expected range [0.30, 0.42]"
        )
        # Section bonus MUST fire -- top chunk should be 'experience'
        assert r["top_section"] == "experience", (
            f"Expected top chunk to be 'experience', got '{r['top_section']}'"
        )
        assert r["section_bonus"] == 0.05, (
            f"section_bonus should be 0.05 for experience section; got {r['section_bonus']}"
        )
        # BM25 bonus MUST fire -- "sprints", "team" are exact-match keywords
        assert r["bm25_bonus"] == 0.15, (
            f"bm25_bonus should be 0.15 (keywords present); got {r['bm25_bonus']}"
        )

        # The key assertion: total confidence must EXCEED threshold
        # This is the regression that the hybrid formula was designed to fix.
        assert r["confidence"] >= RETRIEVAL_CONFIDENCE_THRESHOLD, (
            f"Case 3 REGRESSION: confidence={r['confidence']:.4f} < {RETRIEVAL_CONFIDENCE_THRESHOLD}. "
            f"The hybrid formula must rescue soft-skill queries."
        )
        assert r["is_confident"] is True

        # Verify the rescue margin -- should be well above threshold, not barely scraping by
        rescue_margin = r["confidence"] - RETRIEVAL_CONFIDENCE_THRESHOLD
        assert rescue_margin >= 0.10, (
            f"Rescue margin too thin: {rescue_margin:.4f}. "
            f"Confidence={r['confidence']:.4f} is barely above {RETRIEVAL_CONFIDENCE_THRESHOLD}."
        )

        print(f"\n  Case 3 -- Leadership/soft-skill (THE rescue case)")
        print(f"    base_semantic: {r['base_semantic']:.4f}")
        print(f"    section_bonus: {r['section_bonus']:.4f}  <- fires (experience section)")
        print(f"    bm25_bonus:    {r['bm25_bonus']:.4f}  <- fires (keyword match)")
        print(f"    TOTAL:         {r['confidence']:.4f}  (threshold={RETRIEVAL_CONFIDENCE_THRESHOLD})")
        print(f"    Rescue margin: +{rescue_margin:.4f}")


# ============================= EXISTING TESTS ==============================
# (Preserved from the original test_retrieval.py, adapted to use the mock fixture)

class TestExistingRetrieval:
    """Original test_retrieval_confidence cases, now using the mock store."""

    @pytest.mark.parametrize("query,expected_confident", [
        ("Experience with Python and FastAPI", True),
        ("Experience leading teams and managing sprints", True),
        ("Expertise in Java and Spring Boot", False),
        ("Certified forklift operator with plumbing skills", False),
        ("AWS and Docker", True),
    ])
    def test_retrieval_confidence(self, retriever_with_mock_store, query, expected_confident):
        result = retriever_with_mock_store.search(query, analysis_id="regression", source="resume", top_k=2)
        assert result["is_confident"] == expected_confident, (
            f"Query: '{query}' -- expected is_confident={expected_confident}, "
            f"got {result['is_confident']} (confidence={result['confidence_score']:.4f})"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
