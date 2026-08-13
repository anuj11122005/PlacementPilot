# Rules — PlacementPilot

Non-negotiable engineering rules for this project. These exist because the
core value proposition of PlacementPilot is trustworthiness, not just
functionality. Breaking these rules turns this back into a demo.

## 1. Grounding Rules

1. **The LLM never sees the raw resume or JD.** Only retrieved chunks are
   passed as context. No exceptions, even for "small" JD texts.
2. **The LLM must refuse when context is insufficient.** The exact refusal
   string is standardized (see `PROMPTS.md` if added later) so it can be
   detected and rendered distinctly in the UI — not folded silently into
   prose.
3. **No claim in the output may be untraceable to a retrieved chunk.** If the
   verifier can't map a claim back to context, it is stripped or the section
   is downgraded to "insufficient context."
4. **Retrieval confidence gates generation.** If similarity scores fall below
   the defined threshold, the LLM is not called at all for that section —
   this is cheaper and more reliable than hoping the LLM refuses on its own.

## 2. Data Handling Rules

5. Resumes and JDs may contain PII. Do not log raw resume/JD text in
   plaintext logs. Log chunk IDs and metadata only.
6. Uploaded files are deleted or expired after a defined retention window
   (define this explicitly before going to production — don't leave it
   implicit).
7. No resume/JD data is used to fine-tune or train any model without
   explicit user consent.

## 3. Prompt Engineering Rules

8. Every system prompt change must be tested against the "no real overlap"
   test case (see `PLAN.md §3`) before merging.
9. Few-shot examples in the prompt must include at least one explicit
   refusal example — this anchors the model's default behavior.
10. Do not increase `top_k` retrieval purely to "give the model more to work
    with" — more low-relevance context increases hallucination risk. Tune
    `top_k` against eval results, not intuition.

## 4. Code Quality Rules

11. All retrieval and generation functions must be unit-testable in
    isolation (no hidden global state, no untestable side effects).
12. Every PR touching the retrieval or generation layer must include before/
    after outputs on the standard eval set.
13. No hardcoded API keys or secrets — use environment variables, and add
    `.env` to `.gitignore` immediately (do this before your next commit).
14. Errors must fail loudly in development and gracefully (with a clear
    user-facing message) in production. Never silently swallow parsing or
    API errors.

## 5. Evaluation Rules

15. Maintain a fixed eval set of resume/JD pairs, including:
    - Strong match (real overlap)
    - Partial match
    - No overlap (should trigger refusal)
    - Malformed/garbled resume text
    - Very short/vague JD
16. Track two core metrics over time: **refusal accuracy** (does it refuse
    when it should) and **hallucination rate** (any ungrounded claims in
    accepted answers). Both must be checked before any prompt or retrieval
    change is merged.

## 6. Git / Repo Hygiene

17. Branch naming: `feature/...`, `fix/...`, `docs/...`
18. Commit messages describe *why*, not just *what* (e.g. "Add BM25 fallback
    to reduce missed exact skill matches" not "update retriever.py")
19. `main` branch should always be deployable. Feature work happens on
    branches, merged via PR.
