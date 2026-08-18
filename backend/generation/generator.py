import os
import json
import logging
from typing import Dict, Any

from groq import Groq, APIError, APITimeoutError, RateLimitError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/gpt-oss-120b"

class GroundedGenerator:
    """
    Generation layer that takes retrieved chunks and generates a gap analysis
    plus interview questions. Strictly bounded by the retrieved context.
    """

    REFUSAL_STRING = "Not enough context to evaluate this."

    def __init__(self, model: str = DEFAULT_MODEL, temperature: float = 0.1):
        self.model = model
        self.temperature = temperature
        # Initialize Groq client. Requires GROQ_API_KEY in environment.
        try:
            self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        except Exception as e:
            logger.error(f"Failed to initialize Groq client: {e}")
            self.client = None

    def generate(self, query: str, retrieval_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate gap analysis and interview questions based on the retrieved chunks.
        If the retriever is not confident, skips the LLM and returns the refusal string.
        """
        # 1. Confidence Gate (Bypass LLM completely if context is poor)
        if not retrieval_result.get("is_confident", False):
            logger.info("Retrieval confidence low. Bypassing LLM and returning refusal.")
            return {
                "gap_summary": self.REFUSAL_STRING,
                "improvement_suggestions": [],
                "questions": []
            }

        if not self.client:
            raise RuntimeError("Groq client not initialized. Is GROQ_API_KEY set?")

        # 2. Prepare context from retrieved chunks
        chunks = retrieval_result.get("chunks", [])
        context_texts = []
        for i, chunk in enumerate(chunks):
            # Include section type to give the LLM structural context
            context_texts.append(f"--- Chunk {i+1} [{chunk.get('section_type', 'unknown')}] ---\n{chunk.get('text', '')}")
        
        context_block = "\n\n".join(context_texts)

        # 3. Construct the prompt
        system_prompt = (
            "You are an expert technical interviewer and recruiter. Your task is to perform a gap analysis "
            "between a candidate's resume context and a specific job requirement query.\n\n"
            "CRITICAL RULE: You must answer STRICTLY using the provided context. You may not use outside knowledge "
            "to guess or infer a candidate's skills. If the provided context does not contain enough information to "
            f"evaluate the query, you must respond EXACTLY with: \"{self.REFUSAL_STRING}\" in the gap_summary field, "
            "and empty lists for the other fields.\n\n"
            "Output MUST be in valid JSON format with the following keys:\n"
            "- \"gap_summary\": A concise evaluation of how well the candidate meets the requirement based on context.\n"
            "- \"improvement_suggestions\": A list of strings suggesting how the candidate could bridge the gap (based on context).\n"
            "- \"questions\": A list of 5 to 20 role-specific interview questions to probe this specific requirement.\n\n"
            "FEW-SHOT EXAMPLE (Refusal):\n"
            "Query: 'Experience with Kubernetes and Terraform'\n"
            "Context:\n--- Chunk 1 [summary] ---\nBackend engineer with 5 years experience in Python and Django.\n"
            "Output:\n"
            "{\n"
            f"  \"gap_summary\": \"{self.REFUSAL_STRING}\",\n"
            "  \"improvement_suggestions\": [],\n"
            "  \"questions\": []\n"
            "}"
        )

        user_prompt = f"Query: '{query}'\n\nContext:\n{context_block}\n\nEvaluate the query based ONLY on the context."

        # 4. Call LLM
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            
            # Parse JSON
            parsed = json.loads(content)
            
            gap_summary = parsed.get("gap_summary", self.REFUSAL_STRING)
            improvements = parsed.get("improvement_suggestions", [])
            questions = parsed.get("questions", [])

            # 5. Post-Generation Verification
            if gap_summary != self.REFUSAL_STRING:
                from generation.verifier import ClaimVerifier
                verifier = ClaimVerifier()
                v_result = verifier.verify(gap_summary, chunks)
                
                if not v_result.get("is_grounded", True):
                    logger.warning(f"Verifier flagged ungrounded claim. Reasoning: {v_result.get('reasoning')}")
                    parsed["is_flagged_by_verifier"] = True
                    corrected = v_result.get("corrected_gap_summary", "").strip()
                    
                    if not corrected or corrected == self.REFUSAL_STRING:
                        logger.warning("Correction was empty or malformed. Falling back to Option A (Hard Refusal).")
                        gap_summary = self.REFUSAL_STRING
                        improvements = []
                        questions = []
                    else:
                        gap_summary = corrected
            
            return {
                "gap_summary": gap_summary,
                "improvement_suggestions": improvements,
                "questions": questions,
                "is_flagged_by_verifier": parsed.get("is_flagged_by_verifier", False),
                "verifier_reasoning": v_result.get("reasoning", "") if 'v_result' in locals() else ""
            }

        except (APIError, APITimeoutError, RateLimitError) as e:
            # Rule 14: Fail loudly
            logger.error(f"Groq API Error: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"LLM returned malformed JSON: {content}")
            raise ValueError(f"Failed to parse LLM JSON output: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during generation: {e}")
            raise
