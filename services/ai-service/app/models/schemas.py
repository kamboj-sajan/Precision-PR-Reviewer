from pydantic import BaseModel, Field
from typing import List, Optional

class PRReviewRequest(BaseModel):
    pr_id: int = Field(..., description="GitHub Pull Request Number")
    repository: str = Field(..., description="Repository full name, e.g. owner/repo")
    commit_sha: str = Field(..., description="Commit SHA being reviewed")
    title: Optional[str] = Field(default="", description="Pull Request title")
    author: Optional[str] = Field(default="unknown", description="PR author")
    diff: str = Field(..., description="Raw git unified diff content")

class PrecisionComment(BaseModel):
    file_path: str = Field(..., description="Target file path under review")
    line_number: int = Field(..., description="Specific line number in the new file")
    severity: str = Field(..., description="Severity level: INFO, WARNING, CRITICAL, SUGGESTION")
    category: str = Field(..., description="Issue category: SECURITY, PERFORMANCE, STYLE, PRECISION")
    comment: str = Field(..., description="Detailed review comment and rationale")
    suggested_code: Optional[str] = Field(default=None, description="Suggested replacement code")
    context_snippet: Optional[str] = Field(default=None, description="Surrounding code context")

class ReviewResult(BaseModel):
    summary: str = Field(..., description="High-level architectural summary of the changes")
    verdict: str = Field(..., description="Review outcome: APPROVE, REQUEST_CHANGES, COMMENT")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence score of the review")
    retrieved_context_count: int = Field(..., description="Number of RAG knowledge items retrieved")
    comments: List[PrecisionComment] = Field(default_factory=list, description="Targeted precision comments")

class PRReviewResponse(BaseModel):
    success: bool
    pr_id: int
    review: ReviewResult

class HealthResponse(BaseModel):
    status: str
    service: str = "ai-service"
    chroma_status: str
    collection_name: str
    collection_item_count: int
    rag_pipeline_status: str
