import logging
from typing import Any

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# The embedding model we use. (384 dimensions)
MODEL_NAME = "all-MiniLM-L6-v2"

class Embedder:
    """
    Wraps the sentence-transformer model to provide batched text embeddings.
    """
    
    def __init__(self, model_name: str = MODEL_NAME) -> None:
        """
        Initializes the sentence transformer model.
        This downloads the model weights on the first run.
        """
        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        
    def batch_embed(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Generates embeddings for a batch of chunks.
        
        Expects chunks with a 'text' key.
        Returns the same chunks but with an added 'embedding' key (list of floats).
        
        Rule 14 compliance: Fails loudly if chunks are malformed or embedding fails.
        """
        if not chunks:
            return []
            
        texts = []
        for i, chunk in enumerate(chunks):
            if "text" not in chunk:
                raise KeyError(f"Chunk at index {i} is missing 'text' key: {chunk}")
            texts.append(chunk["text"])
            
        try:
            logger.debug(f"Generating embeddings for {len(texts)} chunks")
            # encode returns a numpy array, we convert to list for easy insertion to pgvector
            embeddings = self.model.encode(texts, show_progress_bar=False)
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise RuntimeError(f"Embedding generation failed: {e}") from e
            
        enriched_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            enriched_chunk = chunk.copy()
            # Convert numpy array to list of floats
            enriched_chunk["embedding"] = embedding.tolist()
            enriched_chunks.append(enriched_chunk)
            
        return enriched_chunks
