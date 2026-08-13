# Decisions — PlacementPilot

A running log of key design decisions and their rationale. This doubles as
your interview prep sheet — every entry here should be something you can
defend out loud.

---

### D1. Vector store: pgvector over Pinecone

**Decision:** Use pgvector (Postgres extension).

**Why:**
- Self-hostable and free, important for a portfolio project with no funding
- Keeps vector data alongside relational metadata (users, analyses,
  timestamps) in one database — simpler ops than syncing two systems
- Good enough performance at this project's scale (not millions of vectors)

**Trade-off acknowledged:** Pinecone would offer better scaling and managed
infra out of the box. If this were a real product processing millions of
resumes, Pinecone (or a managed alternative) becomes more attractive. This
is a scale-appropriate choice, not a "best in the abstract" choice.

---

### D2. Embedding model choice

**Decision:** `sentence-transformers/all-MiniLM-L6-v2` (local, open-source).

**Why:**
- Resumes and JDs are natural language, not code or structured data — a
  general-purpose sentence embedding model is well-suited.
- Prioritized cost/latency for a student project over marginal accuracy
  gains from larger hosted models. It runs locally for free and is extremely fast.
- Pairs naturally with self-hosted pgvector, avoiding
  external API dependency for this layer completely.

**Trade-off acknowledged:** Larger/domain-tuned embedding models may better
capture nuanced skill phrasing (e.g., "led a team" vs "managed people").
Worth revisiting if eval results show retrieval misses on paraphrased
skills.

---

### D3. Hybrid retrieval (semantic + BM25)

**Decision:** Combine dense semantic search with sparse keyword (BM25)
retrieval.

**Why:**
- Semantic embeddings can drift on exact tool/skill names, especially
  uncommon ones (e.g., specific frameworks, certifications)
- BM25 guarantees exact-term overlap isn't missed
- This is a well-known production RAG pattern, not just semantic search
  alone

---

### D4. Confidence threshold gates LLM call

**Decision:** If retrieval similarity scores fall below a defined threshold, skip the LLM call entirely and return "not enough context." Instead of a flat absolute threshold (e.g. >0.6), we use a **stable additive confidence score** combined with section-based weighting.

**Confidence Formula:**
`confidence = Top_1_Semantic_Score + (0.05 if section in ['summary', 'experience'] else 0.0) + (0.15 if BM25_Exact_Match else 0.0)`
*Threshold:* `>= 0.40`

**Why:**
- A flat threshold fails because dense models (like `all-MiniLM`) artificially inflate scores for dense technical keyword overlaps (false positives) while scoring nuanced soft-skill descriptions lower (e.g., leadership experience).
- **Additive Scoring:** We use the absolute top score as the base, but we dynamically boost it if the chunk comes from a soft-skill section where the baseline similarity is naturally lower.
- **BM25 Bonus:** Exact keyword matches bypass the need for a high semantic score, saving niche technical terms from being falsely rejected.
- We initially experimented with a relative drop-off threshold (comparing top score to background noise), but it proved too erratic for very short resumes (<= 2 chunks) where background noise is undefined or inflated. The additive categorical approach provides robust, predictable confidence scores.
- This deterministic gating is cheaper than calling the LLM and removes it as a single point of failure for hallucination.

---

### D5. Post-generation verifier layer

**Decision:** Add a lightweight verification pass after generation, checking
that claims map back to retrieved chunks.

**Why:**
- Prompt instructions reduce but don't eliminate hallucination risk
- A second, narrower check (is this claim grounded — yes/no) is a much
  easier task for a model than "generate a perfect gap analysis," and thus
  more reliable
- This layered approach (retrieval gating + prompt constraint + post-hoc
  verification) is what separates this from a single-prompt demo

---

### D6. Why this counts as "production-level" and not a demo

**The core distinction:** a demo optimizes for looking impressive on a happy
path. This system optimizes for knowing when it doesn't know — every layer
(retrieval confidence, prompt constraints, post-generation verification)
exists to catch and surface uncertainty rather than paper over it with a
confident-sounding LLM output.
