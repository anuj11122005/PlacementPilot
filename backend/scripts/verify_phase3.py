import os
import sys
import uuid
import logging
from pathlib import Path

# Add backend to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.chunker import chunk_text
from embeddings.embedder import Embedder
from embeddings.store import Store
from retrieval.retriever import HybridRetriever

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("verify_phase3")

def run_verification():
    logger.info("Starting Phase 3 Verification (Retrieval Layer)...")
    
    embedder = Embedder()
    store = Store()
    retriever = HybridRetriever(embedder, store)
    
    # We will simulate a JD for a "Senior Python Developer"
    jd_queries = [
        "Experience building scalable backend services with Python and FastAPI",
        "Proficiency in AWS deployment (EC2, S3) and Docker containerization",
        "Ability to lead teams, mentor juniors, and manage sprints effectively",
        "Strong understanding of PostgreSQL and database optimization"
    ]
    
    # We will test 5 completely mismatched candidates
    mismatched_candidates = [
        {
            "name": "Frontend React Specialist",
            "text": "Professional Summary\nHighly skilled Frontend Developer with 6 years of experience in React, Vue, and Angular. Passionate about UI/UX design and responsive web apps.\nTechnical Skills\nJavaScript, TypeScript, CSS, HTML, React, Redux."
        },
        {
            "name": "Java Spring Boot Enterprise Developer",
            "text": "Summary\nEnterprise Java Developer focusing on legacy banking systems. Experienced in Spring Boot, Oracle DB, and SOAP APIs.\nExperience\nDeveloped monolithic banking applications using Java 8 and Spring MVC."
        },
        {
            "name": "Data Analyst (Excel / Tableau)",
            "text": "Profile\nData Analyst with a background in finance. Expert in building Tableau dashboards, writing complex Excel macros, and business intelligence reporting.\nSkills\nExcel, Tableau, PowerBI, basic SQL."
        },
        {
            "name": "Marketing Manager",
            "text": "Objective\nResults-driven Marketing Manager specializing in SEO, content creation, and digital ad campaigns.\nExperience\nLed digital marketing campaigns that increased conversion by 20%. Managed a budget of $500k."
        },
        {
            "name": "Embedded C++ Systems Engineer",
            "text": "Summary\nLow-level systems engineer. Expert in C and C++ for embedded IoT devices. Firmware development, RTOS, and hardware debugging.\nSkills\nC, C++, Assembly, FreeRTOS, Oscilloscopes."
        }
    ]
    
    passed_evals = 0
    total_evals = len(mismatched_candidates) * len(jd_queries)
    
    for candidate in mismatched_candidates:
        logger.info(f"\n--- Testing Candidate: {candidate['name']} ---")
        analysis_id = f"eval_{uuid.uuid4().hex[:8]}"
        
        # 1. Chunk and Embed Candidate
        raw_chunks = chunk_text(candidate["text"], source="resume")
        for idx, c in enumerate(raw_chunks):
            c["chunk_id"] = f"{analysis_id}_{idx}"
            
        embedded_chunks = embedder.batch_embed(raw_chunks)
        store.insert_chunks(embedded_chunks, analysis_id)
        
        # 2. Run JD queries against the candidate
        candidate_passed = True
        for query in jd_queries:
            result = retriever.search(query, analysis_id=analysis_id, source="resume", top_k=2)
            is_confident = result["is_confident"]
            conf_score = result["confidence_score"]
            
            logger.info(f"Query: '{query[:40]}...' | Confident: {is_confident} (Score: {conf_score:.3f})")
            
            if is_confident:
                logger.error(f"  -> FAIL: System hallucinated a confident match for this mismatched candidate!")
                candidate_passed = False
            else:
                passed_evals += 1
                
        if candidate_passed:
            logger.info(f"Candidate '{candidate['name']}' correctly rejected across all queries.")
            
    logger.info(f"\nPhase 3 Verification Complete: {passed_evals}/{total_evals} mismatched queries correctly rejected.")
    
    if passed_evals == total_evals:
        logger.info("SUCCESS: The retrieval layer reliably rejects mismatched context!")
    else:
        logger.error("FAILURE: The retrieval layer is too lenient.")
        sys.exit(1)

if __name__ == "__main__":
    run_verification()
