"""
Naive Baseline Code Review Pipeline (Diff-Only).

This represents a traditional AI reviewer pipeline that reviews Pull Requests
by looking solely at the unified diff without repository awareness, AST call-graph,
or vector-retrieved contextual guidelines.
"""

import logging
import re
from typing import Dict, Any, List
from app.models.schemas import PrecisionComment, ReviewResult, PRReviewResponse
from app.rag.chunking_stub import parse_unified_diff

logger = logging.getLogger(__name__)

# Naive prompt without ChromaDB context or call-graph
BASELINE_PROMPT_TEMPLATE = """You are a Code Review Assistant reviewing a GitHub Pull Request.

### TARGET METADATA:
Repository: {repository}
PR #{pr_id}: {title}

### DIFF CONTENT:
{diff}

### REVIEW INSTRUCTIONS:
Analyze the provided diff in isolation. Identify any security issues, bugs, or undefined references.
"""

class NaiveBaselineReviewer:
    """
    Diff-Only Baseline Reviewer.
    Lacks whole-repository context and AST call-graph. Consequently:
    - Hallucinates 'undefined identifier' warnings on valid cross-file utility calls (False Positives).
    - Fails to detect cross-file breaking changes when function signatures change (False Negatives).
    """
    def __init__(self):
        pass

    def review(self, pr_id: int, repository: str, title: str, diff: str) -> Dict[str, Any]:
        logger.info(f"[Baseline Pipeline] Executing naive diff-only review for PR #{pr_id}")
        parsed_files = parse_unified_diff(diff)
        comments: List[PrecisionComment] = []
        verdict = "APPROVE"

        # Track declared identifiers within the diff itself
        declared_in_diff = set()
        for f in parsed_files:
            for hunk in f.hunks:
                for line in hunk.content:
                    if line.startswith("+") and not line.startswith("+++"):
                        code = line[1:].strip()
                        # Extract function declarations in diff
                        func_match = re.search(r"function\s+([a-zA-Z_][a-zA-Z0-9_]*)", code)
                        if func_match:
                            declared_in_diff.add(func_match.group(1))

        # Built-in or standard globals
        standard_builtins = {
            "require", "console", "module", "exports", "return", "if", "for",
            "while", "try", "catch", "throw", "res", "req", "json", "status",
            "trim", "replace", "split", "join", "Buffer", "Date", "Error"
        }
        credential_keywords = ["password", "token", "secret", "hash", "key", "auth"]

        for file_diff in parsed_files:
            target_path = file_diff.new_path or file_diff.old_path

            for hunk in file_diff.hunks:
                current_line = hunk.new_start

                for line in hunk.content:
                    if line.startswith("+") and not line.startswith("+++"):
                        code = line[1:].strip()

                        # 1. Inline Bug Detection: Timing Attack on Sensitive Credentials
                        if any(kw in code.lower() for kw in credential_keywords) and ("==" in code or "===" in code):
                            comments.append(
                                PrecisionComment(
                                    file_path=target_path,
                                    line_number=current_line,
                                    severity="CRITICAL",
                                    category="SECURITY",
                                    comment="Direct string equality comparison on sensitive credentials. Potential timing attack.",
                                    suggested_code="crypto.timingSafeEqual(Buffer.from(stored), Buffer.from(candidate));",
                                    context_snippet=code
                                )
                            )
                            verdict = "REQUEST_CHANGES"

                        # 2. Inline Bug Detection: SQL Injection
                        elif "query(" in code and ("$" in code or "+" in code) and "SELECT" in code.upper():
                            comments.append(
                                PrecisionComment(
                                    file_path=target_path,
                                    line_number=current_line,
                                    severity="CRITICAL",
                                    category="SECURITY",
                                    comment="Unparameterized SQL string concatenation detected.",
                                    suggested_code="db.query('SELECT * FROM users WHERE id = $1', [id]);",
                                    context_snippet=code
                                )
                            )
                            verdict = "REQUEST_CHANGES"

                        # 3. Naive Hallucination: Flags external function calls as undefined
                        # Because naive baseline cannot see other repository files, it speculates that
                        # external calls are missing imports or undefined functions (False Positive).
                        call_matches = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", code)
                        for callee in call_matches:
                            if (
                                callee not in standard_builtins
                                and callee not in declared_in_diff
                                and not code.startswith("//")
                                and not code.startswith("/*")
                                and "crypto." not in code
                                and "db." not in code
                            ):
                                comments.append(
                                    PrecisionComment(
                                        file_path=target_path,
                                        line_number=current_line,
                                        severity="WARNING",
                                        category="PRECISION",
                                        comment=f"Unresolved Symbol: '{callee}' is invoked but is not defined in this diff hunk. Verify import or declaration.",
                                        suggested_code=None,
                                        context_snippet=code
                                    )
                                )
                                verdict = "REQUEST_CHANGES"

                        current_line += 1
                    elif not line.startswith("-"):
                        current_line += 1

        summary = f"Naive Baseline Review completed. Evaluated diff in isolation without repository knowledge."
        return {
            "pipeline": "naive_baseline",
            "verdict": verdict,
            "comments": [c.model_dump() for c in comments],
            "total_comments": len(comments)
        }

baseline_reviewer = NaiveBaselineReviewer()
