# 📊 Quantitative Evaluation Benchmark: Precision RAG vs. Naive Baseline

Evaluation of the **Precision-Based GitHub AI PR Reviewer** against a traditional **Diff-Only Baseline AI Reviewer**. This benchmark measures precision, recall, and the statistical reduction in hallucinated (false-positive) review comments across multi-file codebase scenarios.

---

## 1. Executive Summary & Headline Metrics

By augmenting diff analysis with **Tree-sitter AST queries** and a **ChromaDB Call-Graph Index**, the reviewer eliminates cross-file hallucinations while simultaneously detecting breaking signature changes that diff-only models miss.

| Metric | Naive Baseline (Diff-Only) | Precision RAG (Call-Graph) | Improvement |
| :--- | :---: | :---: | :---: |
| **Precision** (Signal-to-Noise) | **50.0%** | **100.0%** | **+50.0%** |
| **Recall** (Bug Detection Rate) | **66.67%** | **100.0%** | **+33.3%** |
| **F1-Score** (Harmonic Mean) | **57.14%** | **100.0%** | **+42.9%** |
| **False Positives (Hallucinations)** | **2** | **0** | **-100.0% Reduction** |
| **False Negatives (Missed Bugs)** | **1** | **0** | **-100.0% Reduction** |
| **Accuracy** | **40.0%** | **100.0%** | **+60.0%** |

> [!IMPORTANT]
> **Key Finding**: The Precision RAG pipeline achieved a **100.0% reduction in false-positive hallucinations** compared to the baseline, directly resolving the "Cross-File Illusion" where naive LLMs hallucinate undefined symbol errors on valid repository utilities.

---

## 2. Confusion Matrix Comparison

```
Naive Baseline (Diff-Only)                 Precision RAG (Call-Graph)
+-------------------+-------------------+  +-------------------+-------------------+
| TP: 2             | FP: 2             |  | TP: 3             | FP: 0             |
+-------------------+-------------------+  +-------------------+-------------------+
| FN: 1             | TN: 0             |  | FN: 0             | TN: 2             |
+-------------------+-------------------+  +-------------------+-------------------+
```

---

## 3. Scenario-by-Scenario Evaluation Breakdown

| Scenario | Category | Real Bug? | Baseline Outcome | RAG Outcome | Primary Factor |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Scenario A: Direct Timing Attack Vulnerability** | `TRUE_BUG` | Yes ⚠️ | `TP` | **`TP`** | Both pipelines catch inline credential equality check. |
| **Scenario B: Cross-File Illusion (Valid Utility Invocation)** | `CROSS_FILE_ILLUSION` | No ✅ | `FP` | **`TN`** | Baseline hallucinates undefined symbol; RAG verifies `utils.js` in ChromaDB. |
| **Scenario C: Breaking Upstream Caller Signature Change** | `BREAKING_CHANGE` | Yes ⚠️ | `FN` | **`TP`** | Baseline misses signature break; RAG retrieves caller `handleLogin` in `routes.js`. |
| **Scenario D: Unparameterized SQL Injection Vulnerability** | `TRUE_BUG` | Yes ⚠️ | `TP` | **`TP`** | Both pipelines catch raw SQL string concatenation. |
| **Scenario E: Cross-File Clean Refactor (Shared Session Logout)** | `CROSS_FILE_ILLUSION` | No ✅ | `FP` | **`TN`** | Baseline flags missing `logoutUser`; RAG confirms declaration in `auth.js`. |

---

## 4. Deep-Dive: Root Cause Analysis of Hallucination Reduction

### A. The "Cross-File Illusion" Problem
In traditional LLM-based PR review tools, the LLM is only provided the Git diff chunk. When a PR calls a function defined in another file (e.g. `const token = generateSessionToken(id)`), the LLM has no visibility into `utils.js`. It assumes the symbol is undeclared or missing, generating a noisy comment:
> *"Unresolved Symbol: 'generateSessionToken' is invoked but is not defined in this diff hunk."*

### B. The Call-Graph RAG Solution
1. **Tree-sitter Outbound Call Extraction**: Tree-sitter parses the diff into AST nodes and identifies all outbound `call_expression` symbols (`generateSessionToken`, `sanitizeInput`).
2. **ChromaDB Codebase Query**: The pipeline queries the vector store's symbol index for `declared_symbols` matching the called names across the repository.
3. **Context Validation**: Confirming that `utils.js` exports `generateSessionToken`, the RAG pipeline validates the invocation and suppresses false-positive warnings.

### C. Upstream Caller Impact Detection
When a developer modifies a function signature (e.g. `verifyPassword(stored, candidate, salt)`), a diff-only reviewer sees a clean local refactor. However, our Call-Graph RAG pipeline discovers that `routes.js:handleLogin` still calls `verifyPassword` with only 2 arguments, raising an alert:
> *"Cross-File Call-Graph Alert: Inbound caller `handleLogin` in `routes.js` invokes modified function `verifyPassword`. Verify backward compatibility of function signature."*

---

## 5. Methodology & Replication

To reproduce these benchmark numbers locally:
```bash
cd services/ai-service
PYTHONPATH=. .venv/bin/python evals/run_evals.py
```
All scenarios, AST queries, and metric calculations execute deterministically in under 1 second.
