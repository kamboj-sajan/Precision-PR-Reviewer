import os
import pytest
from fastapi.testclient import TestClient
from app.rag.ast_chunker import map_diff_to_ast_scopes, chunk_file_by_ast
from app.db.chroma_client import PrecisionEmbeddingFunction, chroma_manager
from app.models.schemas import PRReviewRequest
from app.rag.pipeline import rag_pipeline
from app.services.reviewer import reviewer_service
from app.main import app

client = TestClient(app)

def test_ast_chunker_javascript():
    diff_js = """--- a/src/auth.js
+++ b/src/auth.js
@@ -10,6 +10,8 @@
 function handleLogin(req, res) {
-  return false;
+  return true;
 }
"""
    scopes = map_diff_to_ast_scopes("src/auth.js", diff_js)
    assert len(scopes) >= 1
    assert scopes[0]["name"] == "handleLogin"
    assert scopes[0]["node_type"] == "function_declaration"

def test_ast_chunker_python():
    diff_py = """--- a/src/service.py
+++ b/src/service.py
@@ -10,6 +10,8 @@
 def calculate_metrics(data: list):
-    pass
+    return sum(data)
"""
    scopes = map_diff_to_ast_scopes("src/service.py", diff_py)
    assert len(scopes) >= 1
    assert scopes[0]["name"] == "calculate_metrics"
    assert scopes[0]["node_type"] == "function_definition"

def test_precision_embedding_function():
    emb_fn = PrecisionEmbeddingFunction(dim=64)
    docs = ["Security rule for token validation", "Database indexing optimization"]
    vectors = emb_fn(docs)
    assert len(vectors) == 2
    assert len(vectors[0]) == 64
    assert len(vectors[1]) == 64
    assert emb_fn.name() == "precision_embedding"
    assert emb_fn.get_config() == {"dim": 64}

def test_fastapi_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["healthy", "degraded"]
    assert "rag_pipeline_status" in data

def test_fastapi_review_pipeline_detects_timing_attack():
    diff_vulnerable = """--- a/src/auth.js
+++ b/src/auth.js
@@ -20,6 +20,8 @@
 function checkPassword(user, password) {
-  return bcrypt.compare(password, user.hash);
+  // Vulnerable timing attack
+  return user.password === password;
 }
"""
    payload = {
        "pr_id": 77,
        "repository": "security/test-repo",
        "commit_sha": "testsha123",
        "title": "Update password verification",
        "author": "tester",
        "diff": diff_vulnerable
    }
    response = client.post("/api/v1/review", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    review = data["review"]
    assert review["verdict"] == "REQUEST_CHANGES"
    assert len(review["comments"]) >= 1
    critical_comments = [c for c in review["comments"] if c["severity"] == "CRITICAL"]
    assert len(critical_comments) >= 1
    assert "timing" in critical_comments[0]["comment"].lower()

def test_cross_file_call_graph_rag():
    """
    Phase 2 Cross-File Call-Graph Test:
    1. Indexes mock_repo (utils.js, auth.js, routes.js).
    2. Submits a diff modifying verifyPassword in auth.js.
    3. Asserts that the retrieved RAG context successfully pulls in the caller
       (handleLogin in routes.js) via Tree-sitter AST queries and ChromaDB.
    """
    mock_repo_dir = os.path.join(os.path.dirname(__file__), "mock_repo")
    assert os.path.exists(mock_repo_dir), f"mock_repo directory not found at {mock_repo_dir}"

    # Index mock repository into ChromaDB
    chroma_manager.initialize()
    index_stats = chroma_manager.index_repository(mock_repo_dir)
    assert index_stats["indexed_chunks"] >= 3
    assert index_stats["files_processed"] == 3

    # Diff modifying verifyPassword in auth.js
    diff_auth_change = """--- a/auth.js
+++ b/auth.js
@@ -3,6 +3,8 @@
 function verifyPassword(storedPassword, candidatePassword) {
-    // Vulnerable string comparison
-    return storedPassword === candidatePassword;
+    // Upgraded crypto-safe comparison
+    return crypto.timingSafeEqual(Buffer.from(storedPassword), Buffer.from(candidatePassword));
 }
"""

    pipeline_result = rag_pipeline.execute(
        pr_id=202,
        repository="org/callgraph-demo",
        commit_sha="sha998877",
        title="Refactor auth.verifyPassword implementation",
        author="alice",
        diff=diff_auth_change
    )

    # 1. Assert inbound callers were retrieved
    inbound_callers = pipeline_result.get("inbound_callers", [])
    assert len(inbound_callers) >= 1, "Failed to retrieve any inbound callers for modified function"

    # 2. Assert that routes.js (calling verifyPassword inside handleLogin) was specifically retrieved
    routes_callers = [
        c for c in inbound_callers
        if "routes.js" in c["file_path"] and c["caller_name"] == "handleLogin"
    ]
    assert len(routes_callers) == 1, f"Expected handleLogin from routes.js, found: {inbound_callers}"

    caller_record = routes_callers[0]
    assert caller_record["called_symbol"] == "verifyPassword"
    assert "handleLogin" in caller_record["code"]

    # 3. Assert assembled prompt contains the Cross-File Inbound Callers section with routes.js
    prompt_text = pipeline_result.get("assembled_prompt", "")
    assert "CROSS-FILE INBOUND CALLERS" in prompt_text
    assert "routes.js" in prompt_text
    assert "handleLogin" in prompt_text

    # 4. Assert review service produces cross-file warning comment
    req = PRReviewRequest(
        pr_id=202,
        repository="org/callgraph-demo",
        commit_sha="sha998877",
        title="Refactor auth.verifyPassword implementation",
        author="alice",
        diff=diff_auth_change
    )
    review_resp = reviewer_service.review_pull_request(req)
    assert review_resp.success is True
    cross_file_comments = [
        c for c in review_resp.review.comments
        if "Cross-File Call-Graph Alert" in c.comment and "routes.js" in c.comment
    ]
    assert len(cross_file_comments) >= 1, "Expected review service to alert on cross-file caller impact"

def test_evaluation_benchmark_harness():
    """
    Phase 3: Quantitative Evaluation Benchmark Suite Test.
    Ensures that Precision RAG strictly outperforms the naive baseline
    with a significant reduction in false positives (hallucinations).
    """
    from evals.run_evals import run_evaluation
    results = run_evaluation()
    assert results["rag_metrics"]["precision"] > results["base_metrics"]["precision"]
    assert results["rag_counts"]["FP"] < results["baseline_counts"]["FP"]
    assert results["fp_reduction"] >= 50.0

AUTH_DIFF = "--- a/src/auth.js\n+++ b/src/auth.js\n@@ -10,2 +10,2 @@\n function check(a, b) {\n-  return safeEqual(a, b);\n+  return a.password === b;\n }\n"

def _stub_llm_client(monkeypatch, create):
    from types import SimpleNamespace
    from app.services.llm_reviewer import llm_reviewer
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm_reviewer, "_client", client)
    monkeypatch.setattr(reviewer_service.settings, "MOCK_LLM_MODE", False)

def test_llm_review_path_parses_structured_output(monkeypatch):
    """
    With MOCK_LLM_MODE off, the reviewer sends the assembled RAG prompt to the
    OpenAI-compatible API and maps the structured JSON response onto the review schema.
    """
    import json
    from types import SimpleNamespace

    canned = {
        "summary": "Timing-unsafe comparison introduced.",
        "verdict": "REQUEST_CHANGES",
        "confidence_score": 1.4,
        "comments": [{
            "file_path": "src/auth.js",
            "line_number": 11,
            "severity": "CRITICAL",
            "category": "SECURITY",
            "comment": "Use crypto.timingSafeEqual.",
            "suggested_code": ""
        }]
    }
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            model="openai/gpt-oss-120b",
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10),
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps(canned)))]
        )

    _stub_llm_client(monkeypatch, fake_create)
    request = PRReviewRequest(pr_id=7, repository="acme/app", commit_sha="abc123", title="Auth change", diff=AUTH_DIFF)
    response = reviewer_service.review_pull_request(request)

    assert "### GIT DIFF UNDER REVIEW:" in captured["messages"][0]["content"]
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert response.review.verdict == "REQUEST_CHANGES"
    assert response.review.confidence_score == 1.0
    assert response.review.comments[0].line_number == 11
    assert response.review.comments[0].suggested_code is None

def test_llm_failure_falls_back_to_rule_engine(monkeypatch):
    """A failed LLM call (e.g. diff over the free-tier token limit) still yields the rule-based review."""
    def failing_create(**kwargs):
        raise RuntimeError("diff is too large for the model's tokens-per-minute limit")

    _stub_llm_client(monkeypatch, failing_create)
    request = PRReviewRequest(pr_id=8, repository="acme/app", commit_sha="abc123", title="Auth change", diff=AUTH_DIFF)
    response = reviewer_service.review_pull_request(request)

    assert response.review.summary.startswith("AI review unavailable (diff is too large")
    assert any(c.category == "SECURITY" for c in response.review.comments)
