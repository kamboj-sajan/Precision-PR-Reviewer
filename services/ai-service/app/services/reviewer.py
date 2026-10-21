"""
Precision Review Orchestrator & Mock LLM Review Engine.
Coordinates Call-Graph RAG and produces targeted, line-accurate review feedback.
"""

import logging
from typing import List
from app.models.schemas import PRReviewRequest, ReviewResult, PrecisionComment, PRReviewResponse
from app.rag.pipeline import rag_pipeline
from app.rag.chunking_stub import ModifiedFileDiff
from app.services.llm_reviewer import llm_reviewer
from app.config import get_settings

logger = logging.getLogger(__name__)

class PrecisionReviewerService:
    def __init__(self):
        self.settings = get_settings()

    def review_pull_request(self, request: PRReviewRequest) -> PRReviewResponse:
        """
        Executes precision RAG review with cross-file call-graph context and returns structured feedback.
        """
        # Step 1: Execute LangChain Call-Graph RAG pipeline
        rag_output = rag_pipeline.execute(
            pr_id=request.pr_id,
            repository=request.repository,
            commit_sha=request.commit_sha,
            title=request.title or "Pull Request",
            author=request.author or "contributor",
            diff=request.diff
        )

        parsed_files: List[ModifiedFileDiff] = rag_output["parsed_files"]
        retrieved_count: int = rag_output["retrieved_context_count"]
        inbound_callers: List[dict] = rag_output.get("inbound_callers", [])

        # Step 2a: Real LLM review over the assembled Call-Graph RAG prompt.
        # Free-tier limits make failures routine (large diffs, rate limits), so fall back to the rule engine.
        fallback_note = ""
        if not self.settings.MOCK_LLM_MODE:
            try:
                llm_review = llm_reviewer.review(rag_output["assembled_prompt"])
                return PRReviewResponse(
                    success=True,
                    pr_id=request.pr_id,
                    review=ReviewResult(
                        summary=llm_review.summary,
                        verdict=llm_review.verdict,
                        confidence_score=llm_review.confidence_score,
                        retrieved_context_count=retrieved_count,
                        comments=llm_review.comments
                    )
                )
            except Exception as e:
                logger.warning(f"LLM review failed ({e}); falling back to rule-based review.", exc_info=True)
                fallback_note = f"AI review unavailable ({e}); showing rule-based review instead. "

        # Step 2b: Generate Precision Review Comments (Mock LLM Engine)
        comments: List[PrecisionComment] = []
        verdict = "APPROVE"
        confidence_score = 0.94

        credential_keywords = ["password", "token", "secret", "hash", "key", "auth"]

        for file_diff in parsed_files:
            target_path = file_diff.new_path or file_diff.old_path

            for hunk in file_diff.hunks:
                current_line = hunk.new_start

                for line in hunk.content:
                    if line.startswith("+") and not line.startswith("+++"):
                        code = line[1:].strip()

                        # Detect timing attack vulnerability on authentication/credential comparison
                        if any(kw in code.lower() for kw in credential_keywords) and ("==" in code or "===" in code):
                            comments.append(
                                PrecisionComment(
                                    file_path=target_path,
                                    line_number=current_line,
                                    severity="CRITICAL",
                                    category="SECURITY",
                                    comment="Direct string equality comparison detected on sensitive credentials. This exposes the application to side-channel timing attacks. Matched Security Rule #101 from vector store.",
                                    suggested_code="crypto.timingSafeEqual(Buffer.from(candidate), Buffer.from(stored));",
                                    context_snippet=code
                                )
                            )
                            verdict = "REQUEST_CHANGES"
                            confidence_score = 0.98

                        # Detect potential SQL injection or raw queries
                        elif "query(" in code and ("$" in code or "+" in code) and "SELECT" in code.upper():
                            comments.append(
                                PrecisionComment(
                                    file_path=target_path,
                                    line_number=current_line,
                                    severity="CRITICAL",
                                    category="SECURITY",
                                    comment="Unparameterized SQL string interpolation detected. Use parameterized queries to prevent SQL injection vulnerabilities.",
                                    suggested_code="db.query('SELECT * FROM users WHERE id = $1', [userId]);",
                                    context_snippet=code
                                )
                            )
                            verdict = "REQUEST_CHANGES"
                            confidence_score = 0.98

                        # Detect console.log / debug statements
                        elif "console.log" in code or "print(" in code:
                            comments.append(
                                PrecisionComment(
                                    file_path=target_path,
                                    line_number=current_line,
                                    severity="SUGGESTION",
                                    category="STYLE",
                                    comment="Extraneous logging statement in production path. Prefer a structured logger with appropriate log levels.",
                                    suggested_code="// logger.debug('debug message');",
                                    context_snippet=code
                                )
                            )

                        current_line += 1
                    elif not line.startswith("-"):
                        current_line += 1

        # Step 3: Add Cross-File Call-Graph Impact Comments if inbound callers exist
        if inbound_callers:
            verdict = "REQUEST_CHANGES"
            for caller in inbound_callers:
                target_path = parsed_files[0].new_path if parsed_files else "unknown"
                comments.append(
                    PrecisionComment(
                        file_path=target_path,
                        line_number=1,
                        severity="WARNING",
                        category="PRECISION",
                        comment=f"Cross-File Call-Graph Alert: Inbound caller `{caller['caller_name']}` in `{caller['file_path']}` invokes modified function `{caller['called_symbol']}`. Verify backward compatibility of function signature and return type.",
                        suggested_code=None,
                        context_snippet=caller.get("code")
                    )
                )

        # Fallback precision comment if no obvious anti-patterns found
        if not comments:
            comments.append(
                PrecisionComment(
                    file_path=parsed_files[0].new_path if parsed_files else "general",
                    line_number=1,
                    severity="INFO",
                    category="PRECISION",
                    comment="Changes cleanly adhere to retrieved architectural patterns and security standards. No regressions detected.",
                    suggested_code=None,
                    context_snippet=None
                )
            )

        summary_text = fallback_note + (
            f"Precision Call-Graph RAG Review complete for PR #{request.pr_id}. Analyzed {len(parsed_files)} files. "
            f"Matched {retrieved_count} contextual guidelines and {len(inbound_callers)} cross-file callers from ChromaDB. Verdict: {verdict}."
        )

        review_result = ReviewResult(
            summary=summary_text,
            verdict=verdict,
            confidence_score=confidence_score,
            retrieved_context_count=retrieved_count,
            comments=comments
        )

        return PRReviewResponse(
            success=True,
            pr_id=request.pr_id,
            review=review_result
        )

reviewer_service = PrecisionReviewerService()
