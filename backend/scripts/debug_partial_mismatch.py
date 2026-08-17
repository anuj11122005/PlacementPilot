"""
Debug script: replays the exact partial-mismatch test case and dumps
retrieval score breakdowns for every JD chunk, including per-requirement
splitting.

Resume: backend/tests/fixtures/valid_resume.pdf
JD:     "Looking for a backend engineer with Python, FastAPI, SQL, and Kubernetes experience."

Usage:
  cd backend
  venv\\Scripts\\python scripts\\debug_partial_mismatch.py
"""

import os
import sys
import uuid

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Ensure we can import project modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", ".env"))

from ingestion.resume_parser import parse_resume
from ingestion.jd_parser import parse_jd
from ingestion.chunker import chunk_text
from embeddings.embedder import Embedder
from embeddings.store import Store
from retrieval.retriever import (
    HybridRetriever, RETRIEVAL_CONFIDENCE_THRESHOLD, _split_requirements
)

# ---------- Setup ----------
RESUME_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures", "valid_resume.pdf")
JD_TEXT = "Looking for a backend engineer with Python, FastAPI, SQL, and Kubernetes experience."

print("=" * 90)
print("PARTIAL MISMATCH DEBUG -- Per-Requirement Retrieval Score Breakdown")
print("=" * 90)
print(f"Threshold: {RETRIEVAL_CONFIDENCE_THRESHOLD}")
print()

# 1. Parse
resume_text = parse_resume(RESUME_PATH)
parsed_jd = parse_jd(JD_TEXT)

print(f"Resume text ({len(resume_text)} chars): {resume_text[:200]}...")
print()

# 2. Chunk
analysis_id = str(uuid.uuid4())
resume_chunks = chunk_text(resume_text, source="resume")
jd_chunks = chunk_text(parsed_jd, source="jd")

for c in resume_chunks:
    c["chunk_id"] = f"{analysis_id}_{c['chunk_id']}"
for c in jd_chunks:
    c["chunk_id"] = f"{analysis_id}_{c['chunk_id']}"

print(f"Resume chunks ({len(resume_chunks)}):")
for rc in resume_chunks:
    print(f"  [{rc['section_type']}] {rc['text'][:100]}")
print()

print(f"JD chunks ({len(jd_chunks)}):")
for jc in jd_chunks:
    print(f"  [{jc['section_type']}] {jc['text'][:100]}")
print()

# 3. Embed & Store
embedder = Embedder()
store = Store()
embedded_resume = embedder.batch_embed(resume_chunks)
store.insert_chunks(embedded_resume, analysis_id)

# 4. Show splitting analysis first
print("-" * 90)
print("STEP 1: Requirement Splitting Analysis")
print("-" * 90)
for jc in jd_chunks:
    sub_reqs = _split_requirements(jc["text"])
    print(f"  Original: \"{jc['text']}\"")
    if len(sub_reqs) == 1:
        print(f"  Split:    [no split -- single requirement]")
    else:
        print(f"  Split:    {sub_reqs} ({len(sub_reqs)} sub-requirements)")
    print()

# 5. Retrieve using search_jd_chunk -- full per-requirement breakdown
retriever = HybridRetriever(embedder, store)

print("-" * 90)
print("STEP 2: Per-Requirement Retrieval Scores")
print("-" * 90)
print(f"{'Requirement':<40} | {'Sem':>5} | {'Sec':>5} | {'BM25':>5} | {'Final':>6} | Pass?")
print("-" * 90)

all_gradeable = []
all_unsupported = []

for jc in jd_chunks:
    jd_result = retriever.search_jd_chunk(jc["text"], analysis_id=analysis_id, source="resume", top_k=2)
    
    # Print supported requirements
    for sup in jd_result.get("supported", []):
        req = sup["requirement"]
        res = sup["retrieval_result"]
        metrics = res.get("metrics", {})
        sem_score = metrics.get("top_1_similarity", 0.0)
        sec_bonus = metrics.get("section_bonus", 0.0)
        bm25_bonus = metrics.get("bm25_bonus", 0.0)
        final = res["confidence_score"]
        
        text_display = req[:38]
        print(f"  {text_display:<38} | {sem_score:5.3f} | {sec_bonus:5.3f} | {bm25_bonus:5.3f} | {final:6.3f} | [PASS]")
        
        # Show top matched chunks
        for i, ch in enumerate(res["chunks"][:2]):
            print(f"    Top-{i+1}: [{ch['section_type']}] sim={ch['similarity']:.3f} \"{ch['text'][:70]}\"")
        
        all_gradeable.append(req)
    
    # Print unsupported requirements
    for unsup in jd_result.get("unsupported", []):
        # Run individual search to get the score (for display)
        res = retriever.search(unsup, analysis_id=analysis_id, source="resume", top_k=2)
        metrics = res.get("metrics", {})
        sem_score = metrics.get("top_1_similarity", 0.0)
        sec_bonus = metrics.get("section_bonus", 0.0)
        bm25_bonus = metrics.get("bm25_bonus", 0.0)
        final = res["confidence_score"]
        
        text_display = unsup[:38]
        print(f"  {text_display:<38} | {sem_score:5.3f} | {sec_bonus:5.3f} | {bm25_bonus:5.3f} | {final:6.3f} | [FAIL]")
        
        for i, ch in enumerate(res["chunks"][:2]):
            print(f"    Top-{i+1}: [{ch['section_type']}] sim={ch['similarity']:.3f} \"{ch['text'][:70]}\"")
        
        all_unsupported.append(unsup)
    
    print()

print("=" * 90)
print(f"RESULTS")
print("=" * 90)
print(f"  Gradeable ({len(all_gradeable)}):   {all_gradeable}")
print(f"  Unsupported ({len(all_unsupported)}): {all_unsupported}")
print()

# Verify the fix
kubernetes_in_unsupported = any("kubernetes" in u.lower() for u in all_unsupported)
python_in_gradeable = any("python" in g.lower() for g in all_gradeable)

if kubernetes_in_unsupported and python_in_gradeable:
    print("  [OK] FIX VERIFIED: Kubernetes correctly in unsupported, Python correctly gradeable.")
else:
    if not kubernetes_in_unsupported:
        print("  [FAIL] Kubernetes is NOT in unsupported -- fix did not work!")
    if not python_in_gradeable:
        print("  [FAIL] Python is NOT in gradeable -- regression detected!")

print()
print("Done.")
