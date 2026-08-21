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

**Decision:** Add a lightweight Verification Layer (using `openai/gpt-oss-120b`) after generation. It checks if the generated `gap_summary` claims are strictly grounded in the retrieved chunks without inferential leaps.

**Why:**
- Prompt instructions reduce but don't eliminate hallucination risk (e.g., inferring "proficiency" when a tool is merely listed).
- We use a strict Natural Language Inference (NLI) prompt. The verifier attempts to rewrite the claim to strip ungrounded adjectives (Option B).
- If the rewritten claim is empty or malformed, it falls back to a hard refusal (`"Not enough context..."`) and logs the fallback.
- This layered approach (retrieval gating + prompt constraint + post-hoc verification) separates this from a single-prompt demo.

**Trade-off acknowledged (Correlated Blind-Spot):** We are using the exact same model (`openai/gpt-oss-120b`) for both generation and verification. If the model has a fundamental reasoning blind-spot or bias, it may hallucinate during generation and then fail to catch its own hallucination during verification. In a higher-stakes production system, the verifier should ideally be a different, orthogonal model to break this correlation.

---

### D6. Why this counts as "production-level" and not a demo

**The core distinction:** a demo optimizes for looking impressive on a happy
path. This system optimizes for knowing when it doesn't know — every layer
(retrieval confidence, prompt constraints, post-generation verification)
exists to catch and surface uncertainty rather than paper over it with a
confident-sounding LLM output.

---

### D7. LLM Provider Choice (Phase 4)

**Decision:** Use Groq (`openai/gpt-oss-120b`) via the `groq` Python package.

**Why:**
- Extremely fast inference (latency is near instantaneous), which is critical for a smooth user experience in Phase 6.
- Very low cost (generous free tier), making it ideal for a student project running the 15-case eval set repeatedly.
- The originally chosen model (`llama-3.1-8b-instant`) was decommissioned or restricted on the Groq free tier, so we migrated to `openai/gpt-oss-120b`, which provides sufficient generation quality and adheres to the JSON constraints.

---

### D8. Standardized Refusal String

**Decision:** The exact string returned when context is insufficient is:
`"Not enough context to evaluate this."`

**Why:**
- Having a single, exact string acts as a contract between the backend and the frontend (Phase 6).
- The frontend can programmatically detect this exact string to render a specific "missing info" UI state rather than treating it as normal prose.
- This string is returned universally whenever the retriever confidence fails OR when the LLM deems the retrieved context insufficient.

---

### D9. Per-requirement JD splitting (Phase 6 bug fix)

**Decision:** When a JD chunk contains a comma/and-separated list of
skills or technologies, split the chunk into individual sub-requirements
and evaluate each one's retrieval confidence independently. This is a
regex-based heuristic (Layer 1) in the retriever.

**Why:**
- A monolithic JD chunk like `"Python, FastAPI, SQL, and Kubernetes"` scores
  high aggregate cosine similarity (0.62) against a resume that matches 3 of 4
  skills. The embedding model cannot distinguish that one specific term
  (Kubernetes) is absent — it only sees overall semantic overlap.
- Splitting into individual requirements and scoring each one lets
  `"Kubernetes"` alone fall below the confidence threshold (~0.20–0.30),
  correctly routing it to `unsupported_requirements`.
- The heuristic is deliberately conservative: prose-style text without
  enumerable lists falls through unchanged, and parenthetical groups like
  `"AWS (EC2, S3, Lambda)"` are preserved as single units.

**Known limitation — Layer 2 deferred:**
A second layer of defence was considered: instructing the generator to
perform per-requirement grounding verification (checking that EACH JD
requirement it responds to has a directly matching resume chunk, not just
whether the summary text sounds plausible overall). This was deferred
because:
1. Layer 1 (regex splitting) directly addresses the identified failure
   mode — aggregate-similarity masking individual requirement misses.
2. Layer 2 would add a second LLM call or significantly more complex
   prompt engineering, with unclear marginal benefit until Layer 1's
   limits are empirically demonstrated.
3. The same-model correlation blind-spot (see D5) would apply to Layer 2
   as well, limiting its value without an orthogonal verifier model.

*Concrete Evidence of Layer 1 Limit:* In live testing, a prose-style JD ("We are looking for... Python, FastAPI, and Postgres... Kubernetes and Docker") bypassed Layer 1 splitting entirely because it lacked distinct itemized delimiters. As a result, `unsupported_requirements` remained empty even though the LLM's `gap_summary` correctly narrated that Kubernetes and Docker were missing. This empirically demonstrates exactly when Layer 2 (LLM-level grounding verification) would matter in practice.

**If Layer 1 proves insufficient:** The recommended next step is to add
a per-requirement grounding check in the generation layer that explicitly
maps each JD requirement to the resume chunk(s) that support it and
refuses any requirement without a direct match. This should be tracked as
a follow-up item for Phase 7 hardening.

### D8. Verifier Intervention Count as a Diagnostic Signal

**Decision:** Treat the verifier intervention count as a diagnostic signal rather than a rigid target, and preserve the strict few-shot refusal example in the generator prompt even if it reduces verifier interventions.

**Why:**
- A higher-quality generation model that natively refuses ungrounded queries (thanks to strong prompt engineering like few-shot examples) is a desirable safety outcome.
- Forcing the model to hallucinate by removing prompt safeguards just to hit a historical baseline of 5 verifier interventions artificially degrades the system's safety and generation quality.
- The historical baseline count was established when the model was more prone to hallucinating on trap queries. A lower count now honestly reflects the improved natural grounding of the generation model.

---

### D10. Deployment Platform: Supabase + Google Cloud Run + Vercel

**Decision:** Deploy the database to Supabase, the backend API to Google Cloud Run, and the frontend to Vercel. Railway is no longer used.

**Why each platform:**

- **Supabase (Database):** Provides a managed Postgres instance with pgvector built-in — no custom Docker image or template marketplace workaround needed. `CREATE EXTENSION vector;` works out of the box on every Supabase project. The free tier is generous for a portfolio project (500 MB storage, unlimited API requests).
- **Google Cloud Run (Backend):** Offers a permanent free tier (2 million requests/month, 360k vCPU-seconds) that doesn't expire after a trial period. Supports our existing Dockerfile with zero changes beyond honoring the `$PORT` env var (which our `uvicorn` start command already handles). Cold starts are the only trade-off, but acceptable for a portfolio demo.
- **Vercel (Frontend):** Purpose-built for React/Vite SPAs. No cold start on static assets, instant global CDN, and the `VITE_API_URL` env var cleanly points the frontend at the Cloud Run backend URL. The free Hobby tier is sufficient.

**Why not Railway:**
- Railway's free trial has a one-time $5 credit that expires, with no permanent free tier — unsuitable for a portfolio project that needs to stay live indefinitely.
- Railway's standard Postgres addon does not include pgvector; you must use a community template, adding fragility.
- The three-service split (Supabase / Cloud Run / Vercel) gives each layer the best-fit platform rather than forcing everything onto one PaaS.

**Trade-off acknowledged:** Three separate platforms means three dashboards and three sets of credentials to manage, versus Railway's single-project convenience. For a portfolio project that prioritizes long-term uptime at zero cost, this is the right trade.
