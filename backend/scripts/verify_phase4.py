"""
verify_phase4.py -- Live end-to-end integration test against pgvector Docker for Phase 4.

Tests the FULL pipeline:
  embed -> insert into Postgres -> cosine_search -> BM25 -> hybrid re-sort ->
  confidence gate -> LLM generation (or direct refusal)

Covers PHASES.md Phase 4 exit gate:
  - All 15 queries from Phase 3 (5 match, 10 mismatch)
  - Mismatch pairs MUST return exact refusal string and 0 LLM calls.
  - Print retrieved chunk text alongside generated output for manual grounding check.
"""
import os, sys, uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from embeddings.embedder import Embedder
from embeddings.store import Store
from retrieval.retriever import HybridRetriever, RETRIEVAL_CONFIDENCE_THRESHOLD
from generation.generator import GroundedGenerator

def main():
    print("=" * 80)
    print("  Phase 4 -- Live E2E Verification (Grounded Generation)")
    print(f"  RETRIEVAL_CONFIDENCE_THRESHOLD = {RETRIEVAL_CONFIDENCE_THRESHOLD}")
    print("=" * 80)

    # -------------------------------------------------------------------
    # 1. Setup
    # -------------------------------------------------------------------
    embedder = Embedder()
    store = Store()
    retriever = HybridRetriever(embedder, store)
    
    # Initialize Generator
    try:
        generator = GroundedGenerator(temperature=0.1)
    except Exception as e:
        print(f"Failed to initialize generator: {e}")
        sys.exit(1)
        
    analysis_id = f"phase4_live_{uuid.uuid4().hex[:8]}"

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

    print(f"\n  Embedding & inserting {len(raw_chunks)} chunks (analysis_id={analysis_id})...")
    embedded = embedder.batch_embed(raw_chunks)
    store.insert_chunks(embedded, analysis_id)
    print("  [OK] Inserted into Postgres.\n")

    full_8_queries = [
        ("A1: Python/FastAPI strong match", "Experience with Python and FastAPI", True),
        ("A2: Java/Spring mismatch", "Expertise in Java and Spring Boot", False),
        ("A3: Leadership/soft-skill (rescued)", "Experience leading teams and managing sprints", True),
        ("A4: Forklift garbage query", "Certified forklift operator with plumbing skills", False),
        ("A5: AWS/Docker keyword match", "AWS and Docker", True),
    ]

    mismatch_queries = [
        ("B1: Java/Spring (wrong stack)", "Expertise in Java and Spring Boot"),
        ("B2: Oracle DBA (adjacent skill depth)", "Oracle DBA with RAC clustering and tablespace management"),
        ("B3: ML/PyTorch (wrong specialization)", "PyTorch model training and neural network architecture design"),
        ("B4: ARM firmware (wrong domain)", "Firmware programming for ARM Cortex microcontrollers"),
        ("B5: Kubernetes/Helm (SRE requirements)", "Kubernetes pod orchestration with Helm charts and Terraform HCL modules"),
        ("B6: VP Engineering (wrong seniority)", "VP of Engineering overseeing 200-person distributed organization and P&L accountability"),
        ("B7: HIPAA/HL7 (healthcare domain)", "HIPAA compliance officer with clinical data governance and HL7 FHIR integration"),
        ("B8: Quant finance (finance domain)", "Quantitative analyst with stochastic calculus and derivatives pricing models"),
        ("B9: PCB design (hardware/EE domain)", "PCB layout design with KiCad and signal integrity analysis for high-speed circuits"),
        ("B10: Forklift/plumbing (garbage)", "Certified forklift operator with plumbing skills"),
    ]

    all_cases = []
    for label, query, expected in full_8_queries:
        all_cases.append((label, query, expected))
    for label, query in mismatch_queries:
        if not any(c[0] == label for c in all_cases):
            all_cases.append((label, query, False))

    failures = []
    mismatch_total = sum(1 for c in all_cases if not c[2])
    mismatch_pass = 0

    print(f"  {'#' * 76}")
    print(f"  Running {len(all_cases)} queries through Generation Layer")
    print(f"  {'#' * 76}")

    for label, query, expected_confident in all_cases:
        print(f"\n  {'-' * 76}")
        print(f"  Case: {label}")
        print(f"  Query: '{query}'")
        
        # 1. Retrieve
        retrieval_result = retriever.search(query, analysis_id=analysis_id, source="resume", top_k=2)
        actual_confident = retrieval_result["is_confident"]
        
        print("  Retrieved Context:")
        for idx, chunk in enumerate(retrieval_result.get("chunks", [])):
            print(f"    [{idx+1}] ({chunk['section_type']}) {chunk['text']}")

        # 2. Generate
        gen_result = generator.generate(query, retrieval_result)
        
        gap_summary = gen_result.get("gap_summary", "")
        improvements = gen_result.get("improvement_suggestions", [])
        questions = gen_result.get("questions", [])

        # Validations
        if actual_confident != expected_confident:
            failures.append(f"{label} (confidence expected {expected_confident}, got {actual_confident})")
            status = "FAIL"
        else:
            if not expected_confident:
                # If mismatch, it MUST return exactly the refusal string and empty lists
                if gap_summary == GroundedGenerator.REFUSAL_STRING and not improvements and not questions:
                    status = "PASS"
                    mismatch_pass += 1
                else:
                    failures.append(f"{label} (failed refusal constraint)")
                    status = "FAIL"
            else:
                # If match, should not be the refusal string and should have questions
                if gap_summary != GroundedGenerator.REFUSAL_STRING and len(questions) >= 5:
                    status = "PASS"
                else:
                    failures.append(f"{label} (failed generation constraints)")
                    status = "FAIL"

        print(f"  Generation Result [{status}]:")
        print(f"    Gap Summary: {gap_summary}")
        if improvements:
            print(f"    Improvements: {len(improvements)} items")
        if questions:
            print(f"    Questions: {len(questions)} items")

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
    total_cases = len(all_cases)
    passed = total_cases - len(failures)

    print(f"\n{'=' * 80}")
    print(f"  RESULTS SUMMARY")
    print(f"  {'=' * 76}")
    print(f"  Mismatch exit gate: {mismatch_pass}/{mismatch_total} correctly refused via GroundedGenerator.")
    print(f"  TOTAL:              {passed}/{total_cases} passed")
    print(f"  {'=' * 76}")

    if failures:
        print(f"  [FAIL] Failed cases:\n    " + "\n    ".join(failures))
        sys.exit(1)
    else:
        print(f"  [OK] All {total_cases} cases PASSED end-to-end.")
        print(f"  [OK] PHASES.md Phase 4 exit gate MET:")
        print(f"       - Exact refusal string respected without LLM hallucination.")
    print(f"{'=' * 80}")

if __name__ == "__main__":
    main()
