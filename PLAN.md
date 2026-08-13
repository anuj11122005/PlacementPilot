# Plan — PlacementPilot

## 1. Goal

Ship a working, defensible RAG system that compares a resume against a JD,
returns a grounded gap analysis, and generates role-specific interview
questions — with an explicit "insufficient context" fallback instead of
hallucinated advice.

## 2. Milestones

### Milestone 1 — Core Pipeline (Week 1)
- [ ] Set up repo structure (`/backend`, `/frontend`, `/docs`)
- [ ] Resume parser (PDF/DOCX → clean text)
- [ ] JD parser (plain text → clean text)
- [ ] Section-aware chunking function
- [ ] Unit tests for parsing/chunking edge cases (empty file, scanned PDF, etc.)

### Milestone 2 — Embedding + Storage (Week 1–2)
- [ ] Choose and integrate embedding model
- [ ] Set up Postgres + pgvector locally (Docker)
- [ ] Write embedding + insert pipeline
- [ ] Basic similarity search test (sanity check retrieval quality manually)

### Milestone 3 — Retrieval Layer (Week 2)
- [ ] Implement top-k semantic retrieval
- [ ] Add BM25/keyword layer for exact skill matches
- [ ] Implement confidence scoring on retrieved results
- [ ] Define and tune the "insufficient context" threshold
- [ ] Test against deliberately mismatched resume/JD pairs (should refuse)

### Milestone 4 — Generation Layer (Week 2–3)
- [ ] Write system prompt with hard grounding constraint
- [ ] Add few-shot refusal example
- [ ] Integrate LLM API call with retrieved context only
- [ ] Generate: gap summary, improvement suggestions, 5–20 interview questions
- [ ] Test hallucination edge cases (vague JD, irrelevant resume, empty sections)

### Milestone 5 — Guardrail / Verifier (Week 3)
- [ ] Build post-generation claim-checking pass
- [ ] Flag/strip any claim not traceable to retrieved chunks
- [ ] Log flagged cases for manual review (this is your eval dataset)

### Milestone 6 — API + Frontend (Week 3–4)
- [ ] FastAPI endpoints (`/analyze`, `/questions`, `/analyze/{id}`)
- [ ] React upload UI
- [ ] Display gap analysis with confidence indicators
- [ ] Explicitly render "not enough context" sections (don't hide them)

### Milestone 7 — Production Hardening (Week 4)
- [ ] Dockerize backend + frontend
- [ ] Add logging/monitoring (structured logs, request IDs)
- [ ] Rate limiting on API
- [ ] Error handling for malformed uploads
- [ ] Deploy (Render/Railway/AWS) + environment config via `.env`
- [ ] Write eval script: run N known resume/JD pairs, check refusal rate and
      hallucination rate

### Milestone 8 — Polish & Portfolio (Week 4–5)
- [ ] README with architecture diagram + demo GIF
- [ ] Record short demo video
- [ ] Write up "what I'd do differently at scale" section
- [ ] Publish DECISIONS.md explaining embedding model, retrieval design, and
      guardrail choices (this is your interview cheat sheet)

## 3. Definition of Done

A resume/JD pair with **no real overlap** should reliably produce an
"insufficient context" style response rather than fabricated skill gaps.
This is the single most important test case for the whole project — build
it and check it constantly, not just at the end.

## 4. Stretch Goals (only after core is solid)
- Multi-JD comparison (compare one resume against several roles)
- Resume rewrite suggestions grounded in gap analysis
- Feedback loop: user marks a question/gap as "not relevant" → logged for
  future threshold tuning
