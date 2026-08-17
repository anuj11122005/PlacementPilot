import os
import json
import logging
from typing import List, Dict, Any
from groq import Groq

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/gpt-oss-120b"

class ClaimVerifier:
    """
    A strict fact-checker that verifies if a generated gap summary is grounded
    in the retrieved context chunks without any inferential leaps.
    """

    SYSTEM_PROMPT = """
You are a strict, pedantic Fact-Checker performing Natural Language Inference (NLI).
Your ONLY job is to determine if a generated Gap Summary is strictly grounded in the provided Context Chunks.

CRITICAL RULES:
1. No Inferential Leaps: If the context says "Frameworks: FastAPI", the summary MUST NOT say "proficiency in FastAPI" or "has experience with FastAPI". Being listed in a comma-separated list is NOT proof of proficiency. It merely "mentions FastAPI".
2. No Hallucinated Metrics: If the context says "Managed a team", the summary MUST NOT say "Managed a large team" or "Managed a team of 10".
3. No Hallucinated Timelines: If the context doesn't state how many years they used a tool, the summary must not assume it.

If the summary contains ungrounded claims, you must:
1. Set "is_grounded" to false.
2. Provide a clear "reasoning".
3. Provide a "corrected_gap_summary" that rewrites the summary to strip the ungrounded adjectives or leaps, keeping only what is explicitly supported.

Respond STRICTLY in JSON format with exactly these keys:
{
  "is_grounded": boolean,
  "reasoning": "string explaining exactly why",
  "corrected_gap_summary": "string of the rewritten summary, or empty if grounded"
}
"""

    def __init__(self, temperature: float = 0.0):
        # We use temperature 0.0 for deterministic NLI fact-checking.
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("Groq client not initialized. Is GROQ_API_KEY set?")
        self.client = Groq(api_key=api_key)
        self.temperature = temperature
        self.model = DEFAULT_MODEL

    def verify(self, gap_summary: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Verifies the gap_summary against the chunks.
        Returns the parsed JSON response.
        """
        # If the summary is already the refusal string, no need to verify it.
        # But we'll leave that check to the caller to save API calls.

        context_text = ""
        for i, chunk in enumerate(chunks):
            context_text += f"[{i+1}] ({chunk.get('section_type', 'unknown')}) {chunk.get('text', '')}\n"

        user_message = f"Context Chunks:\n{context_text}\n\nGap Summary to verify:\n{gap_summary}"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT.strip()},
                    {"role": "user", "content": user_message}
                ],
                temperature=self.temperature,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            result = json.loads(content)
            
            # Ensure keys exist
            if "is_grounded" not in result:
                result["is_grounded"] = True
            if "reasoning" not in result:
                result["reasoning"] = "No reasoning provided."
            if "corrected_gap_summary" not in result:
                result["corrected_gap_summary"] = gap_summary
                
            return result
            
        except Exception as e:
            logger.error(f"Verifier LLM call failed: {e}")
            # Fail closed or open? A verifier failure shouldn't necessarily gut the response,
            # but we'll return a safe fallback.
            return {
                "is_grounded": False,
                "reasoning": f"Verifier API error: {e}",
                "corrected_gap_summary": ""
            }
