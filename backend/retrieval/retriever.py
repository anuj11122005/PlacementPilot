import logging
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
            import re
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
        import re
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
        if top_chunk_section in ["experience", "summary"]:
            confidence += 0.05
            
        # BM25 Bonus: Exact keyword match saves niche technical terms
        bm25_bonus = 0.15 if top_results[0]["bm25_score"] > 1.0 else 0.0
        confidence += bm25_bonus
        
        logger.debug(f"Query: '{query}' | Top Chunk: {top_chunk_section} | Top1: {top_1_score:.3f}")
        logger.debug(f"BM25 Bonus: {bm25_bonus:.3f} | Final Conf: {confidence:.3f}")
        
        is_confident = confidence >= RETRIEVAL_CONFIDENCE_THRESHOLD
        
        return {
            "chunks": top_results,
            "confidence_score": confidence,
            "is_confident": is_confident,
            "metrics": {
                "top_1_similarity": top_1_score,
                "bm25_bonus": bm25_bonus
            }
        }
