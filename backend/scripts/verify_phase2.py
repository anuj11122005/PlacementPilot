import logging
import os
import sys
from pathlib import Path

# Add backend to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.resume_parser import parse_resume
from ingestion.chunker import chunk_text
from embeddings.embedder import Embedder
from embeddings.store import Store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_verification():
    logger.info("Starting Phase 2 verification...")

    # 1. Parsing
    fixture_path = Path(os.path.dirname(__file__)) / "../tests/fixtures/realistic_resume.docx"
    if not fixture_path.exists():
        logger.error(f"Fixture not found: {fixture_path}")
        sys.exit(1)

    logger.info(f"Parsing resume: {fixture_path.name}")
    parsed_text = parse_resume(fixture_path)
    logger.info(f"Parsed {len(parsed_text)} characters.")

    # 2. Chunking
    logger.info("Chunking text...")
    chunks = chunk_text(parsed_text, source="resume")
    
    import uuid
    run_id = str(uuid.uuid4())[:8]
    for chunk in chunks:
        chunk["chunk_id"] = f"{chunk['chunk_id']}_{run_id}"
        
    section_types = [c["section_type"] for c in chunks]
    logger.info(f"Generated {len(chunks)} chunks. Section types: {section_types}")

    if not chunks:
        logger.error("No chunks generated! Aborting.")
        sys.exit(1)

    # 3. Embedding
    logger.info("Initializing Embedder and embedding chunks...")
    embedder = Embedder()
    
    chunks = embedder.batch_embed(chunks)
    
    # 4. Storage
    logger.info("Initializing Store and inserting chunks into DB...")
    store = Store()
    store.insert_chunks(chunks, analysis_id="verify_run_01")
    logger.info("Chunks successfully stored in the database.")
    
    # 5. Retrieval Verification
    queries = [
        "Senior Python Developer with FastAPI and Docker experience",
        "Expertise in Java, Spring Boot, and Oracle DB",
        "Experience leading teams and managing sprints"
    ]
    
    for query in queries:
        logger.info(f"\n--- Testing retrieval with query: '{query}' ---")
        query_embedding = embedder.model.encode(query).tolist()
        results = store.search_similar_chunks(query_embedding, source="resume", limit=2)
        
        logger.info("Retrieval Results:")
        for res in results:
            logger.info(f" - [{res['chunk_id']}] Score: {res['similarity']:.4f} | Section: {res['section_type']} | Text snippet: {res['text'][:80]}...")
            
    logger.info("\nVerification complete!")

if __name__ == "__main__":
    run_verification()
