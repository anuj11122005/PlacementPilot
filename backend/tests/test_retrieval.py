import os
import sys
import uuid
from pathlib import Path

# Add backend to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from embeddings.embedder import Embedder
from embeddings.store import Store
from retrieval.retriever import HybridRetriever

def test_retrieval_confidence():
    """
    Integration test for HybridRetriever.
    Inserts a specific set of chunks into the DB and tests queries against them.
    """
    embedder = Embedder()
    store = Store()
    retriever = HybridRetriever(embedder, store)
    
    analysis_id = f"test_run_{uuid.uuid4().hex[:8]}"
    
    # 1. Define Candidate Chunks (Python Backend Developer)
    raw_chunks = [
        {"source": "resume", "section_type": "general", "chunk_id": f"gen_{analysis_id}", 
         "text": "Alice Johnson\nBackend Engineer\nalice@example.com"},
        {"source": "resume", "section_type": "summary", "chunk_id": f"sum_{analysis_id}", 
         "text": "Backend Engineer with 5 years of experience building Python microservices. Passionate about team collaboration, mentoring juniors, and delivering scalable systems."},
        {"source": "resume", "section_type": "languages", "chunk_id": f"lang_{analysis_id}", 
         "text": "Languages: Python, JavaScript, SQL. Frameworks: FastAPI, Django. Tools: Docker, AWS, Git."},
        {"source": "resume", "section_type": "experience", "chunk_id": f"exp_{analysis_id}", 
         "text": "Software Engineer at TechCorp. Led a team of 3 developers to migrate a monolithic application to FastAPI microservices. Managed sprints and conducted code reviews."},
        {"source": "resume", "section_type": "education", "chunk_id": f"edu_{analysis_id}", 
         "text": "B.S. in Computer Science, State University."}
    ]
    
    # Embed and Insert
    embedded_chunks = embedder.batch_embed(raw_chunks)
    store.insert_chunks(embedded_chunks, analysis_id)
    
    try:
        # Define Test Cases: (Query, Expected_Confident)
        test_cases = [
            # 1. True Positive Technical (High Semantic, High BM25)
            ("Experience with Python and FastAPI", True),
            
            # 2. True Positive Soft Skill (Lower Semantic, but boosted by section weight)
            ("Experience leading teams and managing sprints", True),
            
            # 3. False Positive Technical (High semantic drift for 'Java', but 0 BM25)
            ("Expertise in Java and Spring Boot", False),
            
            # 4. Out-of-domain Garbage
            ("Certified forklift operator with plumbing skills", False),
            
            # 5. Exact match on a niche technical term (BM25 should boost)
            ("AWS and Docker", True)
        ]
        
        passed = 0
        for query, expected_confident in test_cases:
            result = retriever.search(query, analysis_id=analysis_id, source="resume", top_k=2)
            is_confident = result["is_confident"]
            conf_score = result["confidence_score"]
            metrics = result["metrics"]
            
            print(f"\nQuery: '{query}'")
            print(f"  Confidence: {conf_score:.3f} | Confident? {is_confident} (Expected: {expected_confident})")
            print(f"  Top Match: {result['chunks'][0]['section_type']} | Score: {result['chunks'][0]['similarity']:.3f} | BM25 Bonus: {metrics['bm25_bonus']}")
            
            if is_confident == expected_confident:
                passed += 1
            else:
                print("  => FAILED EXPECTATION!")
                
        print(f"\nPassed {passed}/{len(test_cases)} tests.")
        assert passed == len(test_cases), "Some retrieval tests failed!"
        
    finally:
        # Cleanup could be done here if needed (e.g., delete from DB by analysis_id)
        # For local testing, we'll leave it in or the user can wipe the DB.
        pass

if __name__ == "__main__":
    test_retrieval_confidence()
