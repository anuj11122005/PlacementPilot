# Architecture — PlacementPilot

## 1. Overview

PlacementPilot is a RAG-based resume-to-JD gap analysis system. It compares a
candidate's resume against a target job description, retrieves only relevant
grounded context, and generates a gap analysis plus role-specific interview
questions — refusing to answer when retrieved context is insufficient.

Core design principle: **the LLM is not allowed to reason beyond retrieved
context.** Every claim the LLM makes must be traceable to a retrieved chunk.

## 2. High-Level Flow

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐
│   Resume    │     │     JD      │     │   (Upload)   │
│  (PDF/DOCX) │     │   (Text)    │     │              │
└──────┬──────┘     └──────┬──────┘     └──────────────┘
       │                   │
       ▼                   ▼
┌─────────────────────────────────┐
│         Parsing & Chunking       │
│  - section-aware chunking        │
│  - metadata tagging (source,     │
│    section_type)                 │
└──────────────┬────────────────────┘
               ▼
┌─────────────────────────────────┐
│          Embedding Layer         │
│  (sentence-embedding model)      │
└──────────────┬────────────────────┘
               ▼
┌─────────────────────────────────┐
│        Vector Store (pgvector)   │
│  - resume_chunks                 │
│  - jd_chunks                     │
└──────────────┬────────────────────┘
               ▼
┌─────────────────────────────────┐
│      Hybrid Retriever            │
│  - semantic similarity (top-k)   │
│  - keyword/BM25 for exact skill  │
│    name matches                  │
│  - confidence threshold check    │
└──────────────┬────────────────────┘
               ▼
        ┌──────┴──────┐
        │  Confidence  │
        │   below      │
        │  threshold?  │──Yes──▶ Return "Not enough context" (no LLM call)
        └──────┬───────┘
               │ No
               ▼
┌─────────────────────────────────┐
│      Grounded Generation (LLM)   │
│  - system prompt enforces        │
│    context-only answers          │
│  - few-shot example of refusal   │
│    behavior                      │
└──────────────┬────────────────────┘
               ▼
┌─────────────────────────────────┐
│      Post-Generation Verifier    │
│  - checks output claims against  │
│    retrieved chunks              │
│  - flags ungrounded statements   │
└──────────────┬────────────────────┘
               ▼
┌─────────────────────────────────┐
│           Output                 │
│  - Skill gap analysis            │
│  - Improvement suggestions       │
│  - 5–20 role-specific interview  │
│    questions                     │
└─────────────────────────────────┘
```

## 3. Components

### 3.1 Ingestion Service
- Accepts PDF/DOCX resumes and plain-text JDs
- Extracts text (e.g., `pdfplumber` / `python-docx`)
- Cleans text (strip headers/footers, normalize whitespace)
- Splits into section-aware chunks: `skills`, `experience`, `education`,
  `requirements`, `responsibilities`
- Each chunk stored with metadata: `{source: resume|jd, section_type, chunk_id}`

### 3.2 Embedding Layer
- Converts each chunk into a dense vector
- Model choice documented in `ARCHITECTURE.md §6`
- Batched embedding calls to reduce latency

### 3.3 Vector Store
- **pgvector** (Postgres extension) — chosen for being self-hostable, cheap,
  and queryable alongside relational metadata (users, sessions, history)
- Two logical collections: `resume_chunks`, `jd_chunks`
- Cosine similarity search with metadata filters

### 3.4 Retriever
- **Hybrid retrieval**: dense (semantic) + sparse (keyword/BM25)
  - Semantic search alone can miss exact skill-name matches (e.g., "React" vs
    "ReactJS" vs "React.js" may embed close, but rare/niche tools can drift)
  - BM25 catches literal term overlap as a safety net
- Retrieves top-k chunks from JD requirements, matched against resume content
- Computes a **retrieval confidence score** per query (based on similarity
  distribution) — this score gates whether the LLM is even called

### 3.5 Generation Layer (LLM)
- Receives ONLY the retrieved chunks as context — never the raw full
  resume/JD
- System prompt hard constraint: *"Answer strictly using the provided
  context. If the context does not contain enough information, respond
  exactly with: 'Not enough context to evaluate this.' Do not guess."*
- Few-shot examples included in the prompt showing the refusal pattern

### 3.6 Post-Generation Verifier (Guardrail)
- Lightweight check (rule-based or second LLM pass) comparing generated
  claims against the retrieved chunk set
- Ungrounded claims are stripped or the response is downgraded to
  "insufficient context" for that section
- This is the layer that separates a demo from a production system

### 3.7 API Layer
- REST endpoints:
  - `POST /analyze` — accepts resume + JD, returns gap analysis
  - `GET /analyze/{id}` — retrieve past analysis
  - `POST /questions` — generate interview questions for a role
- Stateless compute layer; all persistent state in Postgres/pgvector

### 3.8 Frontend
- Upload UI for resume + JD
- Displays gap analysis, confidence indicators per claim, and interview
  question list
- Explicitly surfaces "insufficient context" sections instead of hiding them

## 4. Data Model (simplified)

```
users(id, email, created_at)
analyses(id, user_id, resume_id, jd_id, status, created_at)
resume_chunks(id, analysis_id, text, embedding, section_type)
jd_chunks(id, analysis_id, text, embedding, section_type)
analysis_results(id, analysis_id, gap_summary, questions[], is_flagged_by_verifier)
unsupported_requirements(id, analysis_id, jd_chunk_text)
```

## 5. Failure Modes & Handling

| Failure Mode | Handling |
|---|---|
| Low retrieval confidence | Skip LLM call, return "not enough context" |
| LLM hallucinates beyond context | Post-generation verifier flags/strips claim |
| Ambiguous skill match (e.g., abbreviations) | Hybrid retrieval (BM25 + semantic) |
| Malformed/unparsable resume | Return explicit parsing error, don't silently degrade |
| JD too short/vague | Flag JD as low-information before running analysis |

## 6. Embedding Model Choice

Documented separately with rationale in `DECISIONS.md`. Summary: a
general-purpose, cost-efficient sentence embedding model was chosen because
resumes/JDs are natural language (not code), and the project prioritizes
low latency/cost over marginal accuracy gains from larger models.

## 7. Tech Stack Summary

| Layer | Choice |
|---|---|
| Backend | Python (FastAPI) |
| Vector DB | pgvector (Postgres) |
| Embeddings | Sentence-embedding model (see DECISIONS.md) |
| LLM | Claude / GPT via API |
| Frontend | React |
| Deployment | Docker + cloud host (Render/Railway/AWS) |
