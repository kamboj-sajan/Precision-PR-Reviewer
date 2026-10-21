"""
LLM-backed review engine.
Sends the assembled Call-Graph RAG prompt to any OpenAI-compatible chat API
(Groq by default; also Gemini, OpenRouter, GitHub Models, Ollama) and parses a structured review back.
Used when MOCK_LLM_MODE is false.
"""

import logging
from typing import List
import openai
from pydantic import BaseModel
from app.config import get_settings
from app.models.schemas import PrecisionComment

logger = logging.getLogger(__name__)

# JSON schema enforced through structured outputs (strict mode), so the response always parses
REVIEW_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "verdict": {"type": "string", "enum": ["APPROVE", "REQUEST_CHANGES", "COMMENT"]},
        "confidence_score": {"type": "number"},
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "line_number": {"type": "integer"},
                    "severity": {"type": "string", "enum": ["INFO", "WARNING", "CRITICAL", "SUGGESTION"]},
                    "category": {"type": "string", "enum": ["SECURITY", "PERFORMANCE", "STYLE", "PRECISION"]},
                    "comment": {"type": "string"},
                    "suggested_code": {"type": "string"},
                },
                "required": ["file_path", "line_number", "severity", "category", "comment", "suggested_code"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "verdict", "confidence_score", "comments"],
    "additionalProperties": False,
}

OUTPUT_INSTRUCTIONS = """
### OUTPUT FORMAT:
- `file_path` must be the new path of a file in the diff, exactly as it appears after `+++ b/`.
- `line_number` must be a line number in the NEW version of that file that falls inside one of the diff hunks; GitHub rejects comments on lines outside the diff.
- `suggested_code` is the exact replacement for that single line (it is rendered as a one-click GitHub suggestion), or an empty string when there is no drop-in replacement.
- `confidence_score` is between 0 and 1.
- Only report real problems. Do not flag symbols as undefined when the cross-file context shows where they are declared. If the diff is clean, return an empty `comments` list with verdict APPROVE.
"""


class LLMReview(BaseModel):
    summary: str
    verdict: str
    confidence_score: float
    comments: List[PrecisionComment]


class LLMReviewer:
    def __init__(self):
        self.settings = get_settings()
        self._client = None

    @property
    def client(self) -> openai.OpenAI:
        # Created lazily so mock mode and tests never need credentials
        if self._client is None:
            if not self.settings.LLM_API_KEY:
                raise RuntimeError("LLM_API_KEY is not set")
            # The SDK retries 429s itself, waiting for the provider's retry-after interval
            self._client = openai.OpenAI(base_url=self.settings.LLM_BASE_URL, api_key=self.settings.LLM_API_KEY)
        return self._client

    def review(self, assembled_prompt: str) -> LLMReview:
        logger.info(f"[LLM Reviewer] Requesting review from {self.settings.LLM_MODEL} at {self.settings.LLM_BASE_URL}")

        # reasoning_effort is only understood by reasoning models (e.g. gpt-oss); leave it blank for others
        optional_params = {}
        if self.settings.LLM_REASONING_EFFORT:
            optional_params["reasoning_effort"] = self.settings.LLM_REASONING_EFFORT

        try:
            response = self.client.chat.completions.create(
                model=self.settings.LLM_MODEL,
                # Kept modest: Groq's free tier counts input + requested output against ~8K tokens per minute
                max_completion_tokens=self.settings.LLM_MAX_OUTPUT_TOKENS,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "pr_review", "strict": True, "schema": REVIEW_OUTPUT_SCHEMA},
                },
                messages=[{"role": "user", "content": assembled_prompt + OUTPUT_INSTRUCTIONS}],
                **optional_params,
            )
        except openai.APIStatusError as e:
            if e.status_code == 413:
                raise RuntimeError("diff is too large for the model's tokens-per-minute limit") from e
            raise

        choice = response.choices[0]
        usage = response.usage
        logger.info(
            f"[LLM Reviewer] {response.model} finished ({choice.finish_reason}); "
            f"usage in={usage.prompt_tokens if usage else '?'} out={usage.completion_tokens if usage else '?'}"
        )

        if choice.finish_reason == "length":
            raise RuntimeError("review was cut off at LLM_MAX_OUTPUT_TOKENS")
        if not choice.message.content:
            raise RuntimeError(f"model returned no review content (finish_reason={choice.finish_reason})")

        review = LLMReview.model_validate_json(choice.message.content)
        review.confidence_score = min(max(review.confidence_score, 0.0), 1.0)
        for c in review.comments:
            c.suggested_code = c.suggested_code or None
        return review


llm_reviewer = LLMReviewer()
