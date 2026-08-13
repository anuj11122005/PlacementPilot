import logging
import os
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import JDChunk, ResumeChunk

logger = logging.getLogger(__name__)

# Load environment variables from the project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set. Please set it in .env")

# Create engine and session maker
# Synchronous engine for now
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Store:
    """
    Handles inserting embedded chunks into the pgvector database.
    """
    def __init__(self) -> None:
        pass

    def insert_chunks(self, chunks: list[dict[str, Any]], analysis_id: str) -> None:
        """
        Inserts a list of embedded chunks into the appropriate tables based on their source.
        
        Expects chunks with keys: source, section_type, chunk_id, text, embedding.
        
        Rule 14 compliance: Fails loudly if chunks are malformed or DB insert fails.
        """
        if not chunks:
            return
            
        with SessionLocal() as db:
            try:
                for chunk in chunks:
                    source = chunk.get("source")
                    if not source:
                        raise ValueError(f"Chunk is missing 'source': {chunk.get('chunk_id')}")
                        
                    if source == "resume":
                        db_chunk = ResumeChunk(
                            analysis_id=analysis_id,
                            text=chunk["text"],
                            embedding=chunk["embedding"],
                            section_type=chunk["section_type"],
                            chunk_id=chunk["chunk_id"],
                            source=source
                        )
                    elif source == "jd":
                        db_chunk = JDChunk(
                            analysis_id=analysis_id,
                            text=chunk["text"],
                            embedding=chunk["embedding"],
                            section_type=chunk["section_type"],
                            chunk_id=chunk["chunk_id"],
                            source=source
                        )
                    else:
                        raise ValueError(f"Unknown source '{source}' for chunk_id '{chunk.get('chunk_id')}'")
                        
                    db.add(db_chunk)
                    
                db.commit()
                logger.info(f"Successfully inserted {len(chunks)} chunks for analysis_id={analysis_id}")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to insert chunks: {e}")
                raise RuntimeError(f"Database insertion failed: {e}") from e

    def search_similar_chunks(self, query_embedding: list[float], analysis_id: str, source: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Retrieves the most similar chunks to the query embedding for a specific analysis.
        
        Args:
            query_embedding: The embedding of the query string.
            analysis_id: The ID of the analysis to filter by.
            source: Either "resume" or "jd".
            limit: Maximum number of results to return.
            
        Returns:
            A list of dicts representing the matched chunks with a 'similarity' score.
        """
        with SessionLocal() as db:
            model = ResumeChunk if source == "resume" else JDChunk
            
            results = (
                db.query(model, model.embedding.cosine_distance(query_embedding).label("distance"))
                .filter(model.analysis_id == analysis_id)
                .order_by(model.embedding.cosine_distance(query_embedding))
                .limit(limit)
                .all()
            )
            
            return [
                {
                    "chunk_id": row[0].chunk_id,
                    "section_type": row[0].section_type,
                    "text": row[0].text,
                    "similarity": 1.0 - row.distance,
                    "source": row[0].source
                }
                for row in results
            ]
            
    def get_all_chunks(self, analysis_id: str, source: str) -> list[dict[str, Any]]:
        """Fetches all chunks for a given analysis_id and source."""
        with SessionLocal() as db:
            model = ResumeChunk if source == "resume" else JDChunk
            results = db.query(model).filter(model.analysis_id == analysis_id).all()
            return [
                {
                    "chunk_id": row.chunk_id,
                    "section_type": row.section_type,
                    "text": row.text,
                    "source": row.source
                }
                for row in results
            ]
