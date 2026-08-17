"""
PlacementPilot — FastAPI application entry point.

Phase 6 API Layer with full pipeline integration.
"""

import os
import uuid
import tempfile
import logging
from typing import List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from pythonjsonlogger import jsonlogger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from db.models import Analysis
from embeddings.store import SessionLocal, Store
from embeddings.embedder import Embedder
from retrieval.retriever import HybridRetriever
from generation.generator import GroundedGenerator
from ingestion.resume_parser import parse_resume
from ingestion.jd_parser import parse_jd
from ingestion.chunker import chunk_text
from ingestion.exceptions import ChunkingError
from schemas import AnalysisResponse, HealthResponse

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(correlation_id)s %(message)s')
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)

class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        record.correlation_id = correlation_id.get()
        return True

logger.addFilter(CorrelationIdFilter())

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="PlacementPilot API",
    description="RAG-based resume-to-JD gap analysis with strict fact-checking.",
    version="0.1.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Global instances initialized at startup
embedder = None
store = None
retriever = None
generator = None

@app.on_event("startup")
def startup_event():
    global embedder, store, retriever, generator
    try:
        from dotenv import load_dotenv
        load_dotenv()
        embedder = Embedder()
        store = Store()
        retriever = HybridRetriever(embedder, store)
        generator = GroundedGenerator(temperature=0.1)
        logger.info("Startup complete. All components initialized.")
    except OperationalError as e:
        logger.error(f"Database connection failed during startup: {e}")
    except Exception as e:
        logger.error(f"Failed to initialize components during startup: {e}")

@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health_check():
    """Liveness check."""
    return {"status": "ok", "service": "placementpilot-backend"}

@app.post("/analyze", response_model=AnalysisResponse)
@limiter.limit("100/minute") # High limit to allow eval script to run fully
async def analyze_resume_jd(
    request: Request,
    resume: UploadFile = File(...),
    jd_text: str = Form(...),
    db: Session = Depends(get_db)
):
    if not generator or not retriever:
        raise HTTPException(status_code=500, detail="Backend components not initialized (Missing GROQ_API_KEY?)")
    
    analysis_id_uuid = uuid.uuid4()
    analysis_id = str(analysis_id_uuid)
    logger.info(f"Starting analysis {analysis_id}. Resume filename: {resume.filename}")
    
    # 1. Parse Resume
    temp_dir = tempfile.gettempdir()
    safe_filename = resume.filename if resume.filename else "upload.pdf"
    temp_path = os.path.join(temp_dir, f"{analysis_id}_{safe_filename}")
    
    try:
        content = await resume.read()
        with open(temp_path, "wb") as f:
            f.write(content)
        resume_text = parse_resume(temp_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse resume: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    # 2. Parse JD
    try:
        parsed_jd = parse_jd(jd_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse JD: {e}")
        
    # 3. Chunking
    try:
        resume_chunks = chunk_text(resume_text, source="resume")
        jd_chunks = chunk_text(parsed_jd, source="jd")
        
        for c in resume_chunks:
            c["chunk_id"] = f"{analysis_id}_{c['chunk_id']}"
        for c in jd_chunks:
            c["chunk_id"] = f"{analysis_id}_{c['chunk_id']}"
            
        logger.info(f"Chunking complete: {len(resume_chunks)} resume chunks, {len(jd_chunks)} JD chunks.")
            
    except ChunkingError as e:
        logger.warning(f"ChunkingError for analysis {analysis_id}: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to process document format. Please ensure it is a valid text-based PDF or DOCX.")
        
    # 4. Embed & Store Resume
    try:
        embedded_resume = embedder.batch_embed(resume_chunks)
        store.insert_chunks(embedded_resume, analysis_id)
        logger.info(f"Stored {len(embedded_resume)} embedded chunks in Postgres for {analysis_id}.")
    except OperationalError as e:
        logger.error(f"Postgres connection error for {analysis_id}: {e}")
        raise HTTPException(status_code=503, detail="Database connection failed. Please try again later.")
    except Exception as e:
        logger.error(f"Failed to store resume chunks for {analysis_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal processing error.")
    
    # 5. JD Chunk Evaluation (with per-requirement splitting)
    gradeable_jd_texts = []
    gradeable_resume_chunks = []
    unsupported_requirements = []
    
    for jc in jd_chunks:
        try:
            jd_result = retriever.search_jd_chunk(
                jc["text"], analysis_id=analysis_id, source="resume", top_k=2
            )
            # Collect supported requirements and their resume chunks
            for sup in jd_result.get("supported", []):
                gradeable_jd_texts.append(sup["requirement"])
            gradeable_resume_chunks.extend(jd_result.get("all_confident_chunks", []))
            # Collect unsupported requirements
            unsupported_requirements.extend(jd_result.get("unsupported", []))
        except Exception as e:
            logger.error(f"Retrieval failed for JD chunk: {e}")
            unsupported_requirements.append(jc["text"])
            
    # Deduplicate retrieved resume chunks by chunk_id
    seen_chunk_ids = set()
    deduped_resume_chunks = []
    for rc in gradeable_resume_chunks:
        cid = rc.get("chunk_id")
        if cid not in seen_chunk_ids:
            seen_chunk_ids.add(cid)
            deduped_resume_chunks.append(rc)
            
    # 6. Generation & Verification
    if not gradeable_jd_texts:
        # Fast path refusal if zero chunks met confidence
        gap_summary = GroundedGenerator.REFUSAL_STRING
        improvements = []
        questions = []
        is_flagged = False
    else:
        query_text = "Target Requirements:\n" + "\n".join([f"- {t}" for t in gradeable_jd_texts])
        synthetic_retrieval = {
            "is_confident": True,
            "chunks": deduped_resume_chunks
        }
        try:
            gen_result = generator.generate(query_text, synthetic_retrieval)
            gap_summary = gen_result.get("gap_summary", GroundedGenerator.REFUSAL_STRING)
            improvements = gen_result.get("improvement_suggestions", [])
            questions = gen_result.get("questions", [])
            is_flagged = gen_result.get("is_flagged_by_verifier", False)
            logger.info(f"Generation complete for {analysis_id}. Flagged: {is_flagged}")
        except Exception as e:
            logger.error(f"Generation layer error for {analysis_id}: {e}")
            raise HTTPException(status_code=503, detail="LLM Provider is currently unavailable or timed out.")
            
    # 7. Save Analysis to DB
    try:
        new_analysis = Analysis(
            id=analysis_id_uuid,
            status="completed",
            gap_summary=gap_summary,
            improvement_suggestions=improvements,
            questions=questions,
            is_flagged_by_verifier=is_flagged,
            unsupported_requirements=unsupported_requirements
        )
        db.add(new_analysis)
        db.commit()
        db.refresh(new_analysis)
    except OperationalError as e:
        db.rollback()
        logger.error(f"Database operational error saving analysis {analysis_id}: {e}")
        raise HTTPException(status_code=503, detail="Database connection failed. Please try again later.")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save analysis {analysis_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save analysis results.")
        
    return new_analysis

@app.get("/analyze/{id}", response_model=AnalysisResponse)
def get_analysis(id: uuid.UUID, db: Session = Depends(get_db)):
    analysis = db.query(Analysis).filter(Analysis.id == id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis
