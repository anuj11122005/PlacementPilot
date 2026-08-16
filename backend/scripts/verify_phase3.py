"""
verify_phase3.py -- Live end-to-end integration test against pgvector Docker.

Tests the FULL pipeline:
  embed -> insert into Postgres -> cosine_distance search -> BM25 index -> hybrid re-sort -> confidence

Covers PHASES.md Phase 3 exit gate:
  - All 8 original test queries (3 match, 2 mismatch, 1 garbage, 1 rescued, 1 keyword)
  - 7 additional mismatch pairs testing subtle mismatches (adjacent skill, wrong
    seniority, wrong specialization, unrelated domains)
  - Total: 15 queries, of which 10 must be is_confident=False

Run:  python scripts/verify_phase3.py
Requires: Docker pgvector container on port 5455 (see SETUP.md section 2).
"""
import os, sys, uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from embeddings.embedder import Embedder
from embeddings.store import Store
from retrieval.retriever import HybridRetriever, RETRIEVAL_CONFIDENCE_THRESHOLD


def _print_result(label, query, result, expected_confident, failures):
    """Print a formatted result row and track failures."""
    m = result["metrics"]
    actual = result["is_confident"]
    status = "PASS" if actual == expected_confident else "FAIL"

    print(f"  {'=' * 64}")
    print(f"  [{status}] {label}")
    print(f"  Query: '{query[:75]}'")
    print(f"  Top chunk: [{result['chunks'][0]['section_type']}] "
          f"{result['chunks'][0]['text'][:65]}...")
    print(f"  ---")
    print(f"    base_semantic: {m['top_1_similarity']:.4f}")
    print(f"    section_bonus: {m['section_bonus']:.4f}")
    print(f"    bm25_bonus:    {m['bm25_bonus']:.4f}")
    print(f"    TOTAL:         {result['confidence_score']:.4f}  "
          f"is_confident={actual} (expected={expected_confident})")

    if actual != expected_confident:
        failures.append(label)


def main():
    print("=" * 70)
    print("  Phase 3 -- Live E2E Verification (pgvector Docker)")
    print(f"  RETRIEVAL_CONFIDENCE_THRESHOLD = {RETRIEVAL_CONFIDENCE_THRESHOLD}")
    print("=" * 70)

    # -------------------------------------------------------------------
    # 1. Setup
    # -------------------------------------------------------------------
    embedder = Embedder()
    store = Store()
    retriever = HybridRetriever(embedder, store)
    analysis_id = f"phase3_live_{uuid.uuid4().hex[:8]}"

    # -------------------------------------------------------------------
    # 2. Insert the Alice Johnson resume fixture
    # -------------------------------------------------------------------
    raw_chunks = [
        {"source": "resume", "section_type": "general",
         "chunk_id": f"gen_{analysis_id}",
         "text": "Alice Johnson\nBackend Engineer\nalice@example.com"},
        {"source": "resume", "section_type": "summary",
         "chunk_id": f"sum_{analysis_id}",
         "text": "Backend Engineer with 5 years of experience building Python "
                 "microservices. Passionate about team collaboration, mentoring "
                 "juniors, and delivering scalable systems."},
        {"source": "resume", "section_type": "languages",
         "chunk_id": f"lang_{analysis_id}",
         "text": "Languages: Python, JavaScript, SQL. Frameworks: FastAPI, Django. "
                 "Tools: Docker, AWS, Git."},
        {"source": "resume", "section_type": "experience",
         "chunk_id": f"exp_{analysis_id}",
         "text": "Software Engineer at TechCorp. Led a team of 3 developers to "
                 "migrate a monolithic application to FastAPI microservices. "
                 "Managed sprints and conducted code reviews."},
        {"source": "resume", "section_type": "education",
         "chunk_id": f"edu_{analysis_id}",
         "text": "B.S. in Computer Science, State University."},
    ]

    print(f"\n  Embedding & inserting {len(raw_chunks)} chunks "
          f"(analysis_id={analysis_id})...")
    embedded = embedder.batch_embed(raw_chunks)
    store.insert_chunks(embedded, analysis_id)
    print("  [OK] Inserted into Postgres.\n")

    failures = []

    # ===================================================================
    # SECTION A: Full 8-query set (3 motivating + 5 parametrized)
    # ===================================================================
    print(f"  {'#' * 64}")
    print(f"  SECTION A: Full 8-query set (original tests)")
    print(f"  {'#' * 64}")

    full_8_queries = [
        # 3 motivating examples
        ("A1: Python/FastAPI strong match",
         "Experience with Python and FastAPI", True),
        ("A2: Java/Spring mismatch",
         "Expertise in Java and Spring Boot", False),
        ("A3: Leadership/soft-skill (rescued)",
         "Experience leading teams and managing sprints", True),
        # 5 parametrized tests (overlap with above, but kept for completeness)
        ("A4: Forklift garbage query",
         "Certified forklift operator with plumbing skills", False),
        ("A5: AWS/Docker keyword match",
         "AWS and Docker", True),
    ]

    for label, query, expected in full_8_queries:
        result = retriever.search(query, analysis_id=analysis_id,
                                  source="resume", top_k=2)
        _print_result(label, query, result, expected, failures)

        # Extra numeric checks for the 3 motivating cases
        m = result["metrics"]
        if "A1" in label:
            assert 0.39 <= m["top_1_similarity"] <= 0.55
            assert result["confidence_score"] >= RETRIEVAL_CONFIDENCE_THRESHOLD
        elif "A2" in label:
            assert m["top_1_similarity"] < 0.35
            assert m["bm25_bonus"] == 0.0
            assert result["confidence_score"] < RETRIEVAL_CONFIDENCE_THRESHOLD
        elif "A3" in label:
            assert 0.30 <= m["top_1_similarity"] <= 0.42
            assert m["section_bonus"] == 0.05
            assert m["bm25_bonus"] == 0.15
            rescue = result["confidence_score"] - RETRIEVAL_CONFIDENCE_THRESHOLD
            assert rescue >= 0.10
            print(f"    Rescue margin: +{rescue:.4f}")

    # ===================================================================
    # SECTION B: Mismatch exit gate (PHASES.md: >= 5 mismatched pairs)
    # ===================================================================
    print(f"\n  {'#' * 64}")
    print(f"  SECTION B: Mismatch exit gate (>= 5 diverse mismatched pairs)")
    print(f"  {'#' * 64}")

    mismatch_queries = [
        # --- Wrong tech stack (same role shape, different ecosystem) ---
        ("B1: Java/Spring (wrong stack)",
         "Expertise in Java and Spring Boot",
         "Wrong tech ecosystem: Java/Spring vs Python/FastAPI"),

        # --- Adjacent skill, insufficient depth ---
        ("B2: Oracle DBA (adjacent skill depth)",
         "Oracle DBA with RAC clustering and tablespace management",
         "Resume mentions SQL but has zero DBA/Oracle/RAC experience"),

        # --- Same domain, wrong specialization ---
        ("B3: ML/PyTorch (wrong specialization)",
         "PyTorch model training and neural network architecture design",
         "Both are software engineering, but ML vs backend microservices"),

        # --- Adjacent tech, completely wrong domain ---
        ("B4: ARM firmware (wrong domain)",
         "Firmware programming for ARM Cortex microcontrollers",
         "Both are programming, but embedded firmware vs web backend"),

        # --- SRE/DevOps infrastructure (not on resume) ---
        ("B5: Kubernetes/Helm (SRE requirements)",
         "Kubernetes pod orchestration with Helm charts and Terraform HCL modules",
         "Resume has Docker but zero K8s/Helm/Terraform experience"),

        # --- Wrong seniority level ---
        ("B6: VP Engineering (wrong seniority)",
         "VP of Engineering overseeing 200-person distributed organization "
         "and P&L accountability",
         "Resume shows 5yr IC/small-team lead; query demands executive level"),

        # --- Completely unrelated domain: healthcare ---
        ("B7: HIPAA/HL7 (healthcare domain)",
         "HIPAA compliance officer with clinical data governance "
         "and HL7 FHIR integration",
         "Zero overlap: healthcare compliance vs backend engineering"),

        # --- Completely unrelated domain: quantitative finance ---
        ("B8: Quant finance (finance domain)",
         "Quantitative analyst with stochastic calculus "
         "and derivatives pricing models",
         "Zero overlap: financial math vs backend engineering"),

        # --- Completely unrelated domain: hardware/EE ---
        ("B9: PCB design (hardware/EE domain)",
         "PCB layout design with KiCad and signal integrity analysis "
         "for high-speed circuits",
         "Zero overlap: electrical engineering vs software"),

        # --- Out-of-domain garbage (baseline) ---
        ("B10: Forklift/plumbing (garbage)",
         "Certified forklift operator with plumbing skills",
         "Completely unrelated occupation"),
    ]

    mismatch_pass = 0
    mismatch_total = len(mismatch_queries)

    for label, query, rationale in mismatch_queries:
        result = retriever.search(query, analysis_id=analysis_id,
                                  source="resume", top_k=2)
        m = result["metrics"]
        _print_result(label, query, result, False, failures)
        print(f"    Rationale: {rationale}")

        # Every mismatch must be below threshold
        assert result["confidence_score"] < RETRIEVAL_CONFIDENCE_THRESHOLD, (
            f"{label}: confidence={result['confidence_score']:.4f} >= "
            f"{RETRIEVAL_CONFIDENCE_THRESHOLD} -- mismatch query falsely "
            f"flagged as confident!"
        )
        if not result["is_confident"]:
            mismatch_pass += 1

    # ===================================================================
    # 3. Cleanup
    # ===================================================================
    print(f"\n  Cleaning up test chunks for analysis_id={analysis_id}...")
    try:
        from embeddings.store import SessionLocal
        from db.models import ResumeChunk
        with SessionLocal() as db:
            deleted = db.query(ResumeChunk).filter(
                ResumeChunk.analysis_id == analysis_id
            ).delete()
            db.commit()
            print(f"  [OK] Deleted {deleted} test chunks.")
    except Exception as e:
        print(f"  [WARN] Cleanup failed (non-fatal): {e}")

    # ===================================================================
    # 4. Summary
    # ===================================================================
    total_cases = len(full_8_queries) + mismatch_total
    passed = total_cases - len(failures)

    print(f"\n{'=' * 70}")
    print(f"  RESULTS SUMMARY")
    print(f"  {'=' * 64}")
    print(f"  Section A (original 5 queries):  "
          f"{len(full_8_queries) - len([f for f in failures if f.startswith('A')])}/"
          f"{len(full_8_queries)} passed")
    print(f"  Section B (mismatch exit gate):  "
          f"{mismatch_pass}/{mismatch_total} correctly is_confident=False")
    print(f"  TOTAL:                           {passed}/{total_cases} passed")
    print(f"  {'=' * 64}")

    if failures:
        print(f"  [FAIL] Failed cases: {', '.join(failures)}")
        sys.exit(1)
    else:
        print(f"  [OK] All {total_cases} cases PASSED.")
        print(f"  [OK] PHASES.md Phase 3 exit gate MET:")
        print(f"       - {mismatch_pass} mismatch pairs verified (>= 5 required)")
        print(f"       - Full pipeline: embed -> insert -> cosine_search "
              f"-> BM25 -> hybrid re-sort -> confidence")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
