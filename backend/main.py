"""
PlacementPilot — FastAPI application entry point.

Phase 6 API Layer with full pipeline integration.
"""

import os
import uuid
import tempfile
import logging
from typing import List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

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

app = FastAPI(
    title="PlacementPilot API",
    description="RAG-based resume-to-JD gap analysis with strict fact-checking.",
    version="0.1.0",
)

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
    except Exception as e:
        logger.error(f"Failed to initialize components during startup: {e}")

@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health_check():
    """Liveness check."""
    return {"status": "ok", "service": "placementpilot-backend"}

@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_resume_jd(
    resume: UploadFile = File(...),
    jd_text: str = Form(...),
    db: Session = Depends(get_db)
):
    if not generator or not retriever:
        raise HTTPException(status_code=500, detail="Backend components not initialized (Missing GROQ_API_KEY?)")
    
    analysis_id_uuid = uuid.uuid4()
    analysis_id = str(analysis_id_uuid)
    
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
            
    except ChunkingError as e:
        raise HTTPException(status_code=400, detail=f"Chunking failed: {e}")
        
    # 4. Embed & Store Resume
    try:
        embedded_resume = embedder.batch_embed(resume_chunks)
        store.insert_chunks(embedded_resume, analysis_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to store resume chunks: {e}")
    
    # 5. JD Chunk Evaluation
    gradeable_jd_texts = []
    gradeable_resume_chunks = []
    unsupported_requirements = []
    
    for jc in jd_chunks:
        # Perform retrieval
        try:
            res = retriever.search(jc["text"], analysis_id=analysis_id, source="resume", top_k=2)
            if res["is_confident"]:
                gradeable_jd_texts.append(jc["text"])
                gradeable_resume_chunks.extend(res.get("chunks", []))
            else:
                unsupported_requirements.append(jc["text"])
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
        except Exception as e:
            logger.error(f"Generation layer error: {e}")
            raise HTTPException(status_code=500, detail=f"Generation failed: {e}")
            
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save analysis: {e}")
        
    return new_analysis

@app.get("/analyze/{id}", response_model=AnalysisResponse)
def get_analysis(id: uuid.UUID, db: Session = Depends(get_db)):
    analysis = db.query(Analysis).filter(Analysis.id == id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis
