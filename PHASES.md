# Phases — PlacementPilot

This breaks the build into distinct phases, each with a clear goal, entry
criteria, deliverables, and an exit gate. Unlike `PLAN.md` (which tracks
tasks/milestones), this file defines **when you're actually allowed to move
to the next phase** — don't skip a gate just because a task list is checked
off.

---

## Phase 0 — Setup & Foundations

**Goal:** Repo, environment, and tooling ready to build on.

**Entry criteria:** None (starting point).

**Deliverables:**
- GitHub repo initialized and connected locally ✅ (done)
- `.gitignore` includes `.env`, `venv/`, `node_modules/`, `__pycache__/`
- `.env.example` committed (no real secrets)
- Postgres + pgvector running locally via Docker
- Backend (FastAPI) and frontend (React) skeletons run with a "hello world"

**Exit gate:** You can run backend and frontend locally, and the DB accepts
a test vector insert/query.

---

## Phase 1 — Ingestion & Chunking

**Goal:** Turn raw resume/JD files into clean, structured, section-tagged
text chunks.

**Entry criteria:** Phase 0 complete.

**Deliverables:**
- Resume parser (PDF/DOCX → text)
- JD parser (plain text/paste → text)
- Section-aware chunking (skills, experience, requirements, etc.)
- Metadata tagging per chunk (`source`, `section_type`, `chunk_id`)
- Unit tests: empty file, scanned/image-only PDF, malformed DOCX, very short
  JD

**Exit gate:** Given 5 varied real resumes and 5 JDs, chunking produces
clean, correctly-tagged output with no silent failures (errors surface,
not swallowed).

---

## Phase 2 — Embedding & Storage

**Goal:** Chunks are embedded and retrievable from the vector store.

**Entry criteria:** Phase 1 complete.

**Deliverables:**
- Embedding model integrated (see `DECISIONS.md` D2)
- Batched embedding pipeline (resume_chunks, jd_chunks tables)
- pgvector schema finalized (see `ARCHITECTURE.md §4`)
- Manual sanity check: query a known skill, confirm relevant chunks return

**Exit gate:** You can embed a resume + JD pair and manually verify (by
eyeballing results) that semantically similar chunks are retrieved
correctly.

---

## Phase 3 — Retrieval Layer

**Goal:** Reliable, confidence-scored retrieval — including knowing when
retrieval *shouldn't* trust itself.

**Entry criteria:** Phase 2 complete.

**Deliverables:**
- Top-k semantic retrieval implemented
- BM25/keyword fallback layer implemented
- Retrieval confidence scoring defined and tuned
- `RETRIEVAL_CONFIDENCE_THRESHOLD` set based on real test data, not guessed
- Test suite: deliberately mismatched resume/JD pairs must produce low
  confidence scores

**Exit gate:** On the "no real overlap" eval pair (see `PLAN.md §3`),
retrieval confidence falls below threshold reliably — verified across at
least 5 mismatched pairs, not just one.

---

## Phase 4 — Grounded Generation

**Goal:** LLM produces gap analysis and interview questions using only
retrieved context, with explicit refusal when appropriate.

**Entry criteria:** Phase 3 complete.

**Deliverables:**
- System prompt with hard grounding constraint + few-shot refusal example
- LLM integration (context-only, never raw resume/JD)
- Gap analysis + 5–20 role-specific interview question generation
- Standardized refusal string defined and used consistently

**Exit gate:** Across the full eval set (strong match, partial match, no
overlap, malformed input, vague JD), the LLM refuses correctly on the "no
overlap" and "vague JD" cases at least 9/10 runs.

---

## Phase 5 — Guardrail / Verification Layer

**Goal:** Catch and strip any ungrounded claim that slips past generation.

**Entry criteria:** Phase 4 complete.

**Deliverables:**
- Post-generation verifier (rule-based or second LLM pass)
- Ungrounded claims flagged/stripped automatically
- Logging of flagged cases (for eval dataset growth — see Phase 7)

**Exit gate:** Run 20 generations across the eval set; verifier catches
and correctly flags any manually-identified ungrounded claim, with false
positive rate low enough not to gut valid answers (define and record this
rate in `DECISIONS.md`).

---

## Phase 6 — API & Frontend

**Goal:** A usable end-to-end product, not just a backend pipeline.

**Entry criteria:** Phase 5 complete.

**Deliverables:**
- REST endpoints (`/analyze`, `/questions`, `/analyze/{id}`)
- React upload UI for resume + JD
- Gap analysis displayed with per-claim confidence indicators
- "Not enough context" sections rendered explicitly, not hidden or
  softened

**Exit gate:** A non-technical person (friend, classmate) can upload a
resume + JD and understand the output without you explaining it.

---

## Phase 7 — Production Hardening

**Goal:** The system behaves correctly outside your own machine and your
own test cases.

**Entry criteria:** Phase 6 complete.

**Deliverables:**
- Dockerized backend + frontend
- Structured logging (request IDs, no raw PII in logs — see `RULES.md §2`)
- Rate limiting on API endpoints
- Graceful error handling for malformed uploads, API timeouts, LLM failures
- Deployed to a live environment (Render/Railway/AWS)
- `scripts/run_eval.py` runs the full eval set and reports refusal
  accuracy + hallucination rate

**Exit gate:** The deployed (not local) version passes the full eval set,
and a cold-start user (no dev environment) can use it end-to-end.

---

## Phase 8 — Polish & Portfolio

**Goal:** The project is legible and defensible to someone who's never seen
it before — a recruiter, interviewer, or open-source visitor.

**Entry criteria:** Phase 7 complete.

**Deliverables:**
- README polished with architecture diagram + demo GIF/video
- `DECISIONS.md` fully filled in (no placeholders left)
- Short write-up: "what I'd change at scale" (shows engineering maturity
  beyond the project's current size)
- Eval results (refusal accuracy, hallucination rate) published in README
  or a `RESULTS.md`

**Exit gate:** You can walk a stranger through the project in under 5
minutes using only the README, and answer "how did you control
hallucinations" without notes.

---

## Phase Summary Table

| Phase | Focus | Exit Gate Signal |
|---|---|---|
| 0 | Setup | Local dev environment runs |
| 1 | Ingestion | Clean, tagged chunks from real files |
| 2 | Embedding/Storage | Retrieval returns sensible matches |
| 3 | Retrieval | Confidence correctly flags mismatches |
| 4 | Generation | LLM refuses correctly on bad input |
| 5 | Guardrails | Verifier catches ungrounded claims |
| 6 | API/Frontend | A stranger can use it unaided |
| 7 | Hardening | Deployed version passes eval set |
| 8 | Polish | You can defend it in 5 minutes, no notes |

**Rule of thumb:** if you can't demonstrate a phase's exit gate with a real
example, you're not done with that phase — regardless of how much code is
written.
