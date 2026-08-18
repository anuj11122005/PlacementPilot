import logging
import re
from typing import Any

import numpy as np

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None

from embeddings.embedder import Embedder
from embeddings.store import Store

logger = logging.getLogger(__name__)

# Section weights: Soft skills (experience/summary) get a boost to their drop-off impact
SECTION_WEIGHTS = {
    "experience": 1.5,
    "summary": 1.5,
    "skills": 1.0,
    "languages": 1.0,
    "education": 1.0,
    "general": 1.0
}

# The minimum confidence score to consider the retrieval "grounded"
RETRIEVAL_CONFIDENCE_THRESHOLD = 0.40

# Maximum number of words a single item can have to be considered a
# "short skill/tool name" during requirement splitting.  Items longer
# than this are treated as prose fragments and the whole text is kept
# as a single requirement (conservative fall-through).
_MAX_ITEM_WORDS = 2


# ---------------------------------------------------------------------------
# Requirement-level splitting helpers
# ---------------------------------------------------------------------------

def _split_requirements(text: str) -> list[str]:
    """
    Conservatively split a JD chunk into individual requirements when
    it contains comma-separated or conjunction-joined skill/tool lists.

    Design goals:
    1. Prose-style text (no enumerable list) falls through unchanged.
    2. Parenthetical groups like "AWS (EC2, S3, Lambda)" are preserved
       as a single unit — commas inside parens are NOT split on.
    3. Only splits when every resulting item looks like a short skill
       name (<=_MAX_ITEM_WORDS words after stripping context words).
       If any item is too long, we fall through unchanged to avoid
       inventing fake requirements.

    Returns a list of requirement strings.  A single-element list means
    "no split was performed."
    """
    stripped = text.strip()
    if not stripped:
        return [text]

    # Step 1: Protect parenthetical groups by temporarily replacing them.
    # E.g. "AWS (EC2, S3, Lambda)" -> "AWS __PAREN_0__"
    paren_groups: list[str] = []

    def _replace_paren(match: re.Match) -> str:
        idx = len(paren_groups)
        paren_groups.append(match.group(0))  # full "(…)" including parens
        return f"__PAREN_{idx}__"

    protected = re.sub(r"\([^)]*\)", _replace_paren, stripped)

    # Step 2: Try to find a comma+and list pattern.
    # If there are no commas at all, check for a bare "X and Y" pattern.
    if "," not in protected:
        # Try bare "X and Y" (only if both sides are short)
        bare_match = re.split(r"\band\b", protected, maxsplit=1)
        if len(bare_match) == 2:
            left = bare_match[0].strip()
            right = bare_match[1].strip()
            # Only split if both sides are short skill-like items
            if (left and right
                    and len(left.split()) <= _MAX_ITEM_WORDS
                    and len(right.split()) <= _MAX_ITEM_WORDS):
                items = [_restore_parens(left, paren_groups),
                         _restore_parens(right, paren_groups)]
                return items
        # No list detected — fall through unchanged
        return [text]

    # Step 3: Split on commas (outside parens, which are already protected).
    raw_items = [s.strip() for s in protected.split(",")]

    # The last item may have a leading "and" — strip it.
    # E.g. ["Python", "FastAPI", "and Kubernetes"] -> strip "and" from last.
    cleaned_items: list[str] = []
    for item in raw_items:
        # Remove a leading "and " if present
        item_clean = re.sub(r"^\s*and\s+", "", item, count=1).strip()
        if item_clean:
            cleaned_items.append(item_clean)

    if len(cleaned_items) <= 1:
        # After cleaning we don't have multiple items — fall through
        return [text]

    # Step 4: Handle embedded skill lists within prose sentences.
    # Common pattern: "Looking for an engineer with Python, FastAPI, SQL,
    # and Kubernetes experience."
    # After comma-split the FIRST item is "Looking for an engineer with Python"
    # (too long) and the LAST item may have trailing words like "experience."
    # We try to extract the actual skill names from first/last items.
    first_item = cleaned_items[0]
    last_item = cleaned_items[-1]

    if len(first_item.split()) > _MAX_ITEM_WORDS:
        # The first item has leading context words. Try to extract the
        # trailing short skill name. Common patterns:
        #   "Looking for an engineer with Python" -> "Python"
        #   "Experience in React Native" -> "React Native"
        # We split on common prepositions/connectors and take the tail.
        tail = _extract_trailing_skill(first_item)
        if tail and len(tail.split()) <= _MAX_ITEM_WORDS:
            cleaned_items[0] = tail
        else:
            # Can't extract a skill from the first item — bail out
            logger.debug(
                f"Requirement splitting aborted: cannot extract skill "
                f"from first item '{first_item}'"
            )
            return [text]

    # Strip trailing context words from the last item (e.g. "Kubernetes experience." -> "Kubernetes")
    last_cleaned = _strip_trailing_context(last_item)
    if last_cleaned:
        cleaned_items[-1] = last_cleaned

    # Step 5: Validate that ALL items look like short skill/tool names.
    for item in cleaned_items:
        word_count = len(item.split())
        if word_count > _MAX_ITEM_WORDS:
            logger.debug(
                f"Requirement splitting aborted: item '{item}' has "
                f"{word_count} words (max {_MAX_ITEM_WORDS})"
            )
            return [text]

    # Step 6: Restore parenthetical groups and return.
    result = [_restore_parens(item, paren_groups) for item in cleaned_items]
    logger.debug(f"Split '{text[:60]}...' into {len(result)} sub-requirements: {result}")
    return result


def _restore_parens(text: str, paren_groups: list[str]) -> str:
    """Replace __PAREN_N__ placeholders with their original content."""
    for idx, original in enumerate(paren_groups):
        text = text.replace(f"__PAREN_{idx}__", original)
    return text


def _extract_trailing_skill(text: str) -> str | None:
    """
    Extract the trailing short skill name from a string that has leading
    context words (e.g. "Looking for an engineer with Python" -> "Python").
    Splits on common prepositions and connectors.
    """
    # Common words that immediately precede a skill list in a sentence
    splitters = [
        r"\bwith\b", r"\bin\b", r"\busing\b", r"\bfor\b", r"\bincluding\b",
        r"\bsuch as\b", r"\bexperience\b", r"\bknowledge of\b", r"\bproficient\b"
    ]
    
    # Try splitting by the connectives (case-insensitive)
    pattern = "|".join(splitters)
    parts = re.split(pattern, text, flags=re.IGNORECASE)
    
    if len(parts) > 1:
        # The last part should be the skill list start (e.g. " Python")
        tail = parts[-1].strip()
        # Clean up any trailing punctuation that isn't part of a skill name
        tail = re.sub(r"^[.:-]\s*", "", tail)
        if tail:
            return tail
            
    return None


def _strip_trailing_context(text: str) -> str:
    """
    Strip trailing context words from the end of a skill name
    (e.g. "Kubernetes experience." -> "Kubernetes").
    """
    # Common words that immediately follow a skill list in a sentence
    trailing_words = [
        r"\bexperience\.?$", r"\bskills\.?$", r"\bknowledge\.?$", 
        r"\bbackground\.?$", r"\bproficiency\.?$"
    ]
    
    clean_text = text.strip()
    for pattern in trailing_words:
        clean_text = re.sub(pattern, "", clean_text, flags=re.IGNORECASE).strip()
        
    # Remove any trailing punctuation if it's the end of a sentence
    clean_text = re.sub(r"[.!?]+$", "", clean_text).strip()
    
    return clean_text


class HybridRetriever:
    def __init__(self, embedder: Embedder, store: Store):
        self.embedder = embedder
        self.store = store
        if BM25Okapi is None:
            logger.warning("rank_bm25 is not installed. Sparse retrieval will be disabled.")

    def search(self, query: str, analysis_id: str, source: str = "resume", top_k: int = 5) -> dict[str, Any]:
        """
        Retrieves top-k chunks for a query using hybrid search (Semantic + BM25).
        Returns a dict containing the matched chunks, a confidence score, and a boolean is_confident flag.
        """
        # 1. Fetch all chunks to build BM25 index (in-memory, fast for a single resume)
        all_chunks = self.store.get_all_chunks(analysis_id, source)
        
        bm25 = None
        if all_chunks and BM25Okapi is not None:
            def tokenize(text: str) -> list[str]:
                # Remove punctuation and split by whitespace
                return re.sub(r'[^\w\s]', ' ', text.lower()).split()
                
            tokenized_corpus = [tokenize(chunk["text"]) for chunk in all_chunks]
            bm25 = BM25Okapi(tokenized_corpus)
            
        # 2. Dense Semantic Search
        query_embedding = self.embedder.model.encode(query).tolist()
        # Fetch more than top_k so we can calculate background noise (drop-off)
        fetch_limit = max(10, top_k + 5)
        semantic_results = self.store.search_similar_chunks(query_embedding, analysis_id, source, limit=fetch_limit)
        
        if not semantic_results:
            return {"chunks": [], "confidence_score": 0.0, "is_confident": False}
            
        # 3. Calculate Hybrid Scores for retrieved chunks
        tokenized_query = re.sub(r'[^\w\s]', ' ', query.lower()).split()
        
        for chunk in semantic_results:
            bm25_score = 0.0
            if bm25:
                # Find the index of this chunk in all_chunks
                # In production, we'd map chunk_id directly
                idx = next((i for i, c in enumerate(all_chunks) if c["chunk_id"] == chunk["chunk_id"]), -1)
                if idx != -1:
                    bm25_score = bm25.get_scores(tokenized_query)[idx]
            
            chunk["bm25_score"] = bm25_score
            # A simple normalization for BM25 (usually ranges 0 to 10 for short text)
            chunk["hybrid_score"] = chunk["similarity"] + min(bm25_score * 0.1, 0.3)
            
        # Re-sort by hybrid score
        semantic_results.sort(key=lambda x: x["hybrid_score"], reverse=True)
        top_results = semantic_results[:top_k]
        
        # 4. Compute Confidence (Section Weight + BM25 Bonus)
        top_1_score = top_results[0]["similarity"]
        top_chunk_section = top_results[0]["section_type"]
        
        # Base confidence is the semantic similarity
        confidence = top_1_score
        
        # Section Bonus: Soft skills often score lower semantically, give them a small boost
        section_bonus = 0.05 if top_chunk_section in ["experience", "summary"] else 0.0
        confidence += section_bonus
            
        # BM25 Bonus: Exact keyword match saves niche technical terms
        bm25_bonus = 0.15 if top_results[0]["bm25_score"] > 1.0 else 0.0
        
        # Fallback for very small corpora (e.g. 1-chunk resumes) where BM25 Okapi
        # IDF formula yields <= 0 for terms present in 100% of the documents.
        if bm25_bonus == 0.0 and len(query.split()) <= 3:
            if query.lower() in top_results[0]["text"].lower():
                bm25_bonus = 0.15
                
        confidence += bm25_bonus
        
        logger.debug(f"Query: '{query}' | Top Chunk: {top_chunk_section} | Top1: {top_1_score:.3f}")
        logger.debug(f"Section Bonus: {section_bonus:.3f} | BM25 Bonus: {bm25_bonus:.3f} | Final Conf: {confidence:.3f}")
        
        is_confident = confidence >= RETRIEVAL_CONFIDENCE_THRESHOLD
        
        return {
            "chunks": top_results,
            "confidence_score": confidence,
            "is_confident": is_confident,
            "metrics": {
                "top_1_similarity": top_1_score,
                "section_bonus": section_bonus,
                "bm25_bonus": bm25_bonus
            }
        }

    def search_jd_chunk(
        self,
        jd_text: str,
        analysis_id: str,
        source: str = "resume",
        top_k: int = 2,
    ) -> dict[str, Any]:
        """
        Evaluate a JD chunk against the resume, splitting multi-requirement
        chunks into individual sub-queries when a comma/and list is detected.

        Returns:
            {
                "supported": [
                    {"requirement": str, "retrieval_result": dict}, ...
                ],
                "unsupported": [str, ...],
                "all_confident_chunks": [chunk_dict, ...],
            }
        """
        sub_reqs = _split_requirements(jd_text)

        if len(sub_reqs) == 1:
            # No splitting — evaluate the whole chunk as before
            res = self.search(jd_text, analysis_id=analysis_id, source=source, top_k=top_k)
            if res["is_confident"]:
                return {
                    "supported": [{"requirement": jd_text, "retrieval_result": res}],
                    "unsupported": [],
                    "all_confident_chunks": res.get("chunks", []),
                }
            else:
                return {
                    "supported": [],
                    "unsupported": [jd_text],
                    "all_confident_chunks": [],
                }

        # Multiple sub-requirements: evaluate each independently
        supported = []
        unsupported = []
        all_chunks = []

        for req in sub_reqs:
            res = self.search(req, analysis_id=analysis_id, source=source, top_k=top_k)
            if res["is_confident"]:
                supported.append({"requirement": req, "retrieval_result": res})
                all_chunks.extend(res.get("chunks", []))
            else:
                unsupported.append(req)

        logger.info(
            f"JD chunk split into {len(sub_reqs)} sub-reqs: "
            f"{len(supported)} supported, {len(unsupported)} unsupported"
        )
        return {
            "supported": supported,
            "unsupported": unsupported,
            "all_confident_chunks": all_chunks,
        }
