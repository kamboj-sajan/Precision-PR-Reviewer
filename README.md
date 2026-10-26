# 🔍 Precision-Based GitHub AI PR Reviewer
### *Autonomous Cross-File Call-Graph RAG Architecture for Code Reviews*

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Node.js](https://img.shields.io/badge/Node.js-22.x-339933?logo=nodedotjs&logoColor=white)](https://nodejs.org/)
[![LangChain](https://img.shields.io/badge/LangChain-0.3+-1C3C3C?logo=langchain&logoColor=white)](https://langchain.com/)
[![Tree-sitter](https://img.shields.io/badge/Tree--sitter-AST--Queries-4B8BBE?logo=python&logoColor=white)](https://tree-sitter.github.io/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_Store-FF6F00?logoColor=white)](https://www.trychroma.com/)
[![MongoDB](https://img.shields.io/badge/MongoDB-7.0-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose_Ready-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![Tests](https://img.shields.io/badge/Tests-Passing_100%25-brightgreen)](https://github.com/kamboj-sajan/Precision-PR-Reviewer)

---

## 📌 Executive Summary

Traditional LLM-based code reviewers inspect Git diff hunks in complete isolation. This diff-only approach suffers from two critical failure modes:
1. **The "Cross-File Illusion" (High False Positives)**: When a PR invokes utility functions or classes declared in untouched files, naive LLMs hallucinate that the symbols are missing or undeclared, spamming pull requests with phantom warnings.
2. **Missing Upstream Impact (High False Negatives)**: When a PR modifies a function signature, diff-only reviewers cannot see downstream callers across untouched files, missing breaking changes.

The **Precision-Based GitHub AI PR Reviewer** solves this by coupling **Tree-sitter AST queries** with **ChromaDB Call-Graph Indexing**. It dynamically discovers inbound callers and validates cross-file symbol definitions, delivering line-anchored reviews with **zero hallucinations** and **100% bug recall** on benchmark evaluations.

---

## 📊 Benchmark & Quantitative Evaluation

We evaluated our Cross-File Call-Graph RAG pipeline against a traditional Diff-Only Baseline LLM Reviewer across standardized Pull Request scenarios (`evals/dataset.json`).

### Headline Metrics

| Metric | Naive Baseline (Diff-Only) | Precision RAG (Call-Graph) | Delta / Impact |
| :--- | :---: | :---: | :---: |
| **Precision** (Signal-to-Noise) | **50.0%** | **100.0%** | **+50.0%** |
| **Recall** (Bug Detection Rate) | **66.67%** | **100.0%** | **+33.3%** |
| **F1-Score** (Harmonic Mean) | **57.14%** | **100.0%** | **+42.9%** |
| **False Positives (Hallucinations)** | **2** | **0** | **-100.0% (Zero Hallucinations)** |
| **False Negatives (Missed Bugs)** | **1** | **0** | **-100.0% (Zero Missed Regressions)** |
| **Overall Accuracy** | **40.0%** | **100.0%** | **+60.0%** |

### Confusion Matrix

```
Naive Baseline (Diff-Only)                 Precision RAG (Call-Graph)
+-------------------+-------------------+  +-------------------+-------------------+
| True Pos:  2      | False Pos: 2      |  | True Pos:  3      | False Pos: 0      |
+-------------------+-------------------+  +-------------------+-------------------+
| False Neg: 1      | True Neg:  0      |  | False Neg: 0      | True Neg:  2      |
+-------------------+-------------------+  +-------------------+-------------------+
```

### Scenario Breakdown

| Scenario | Type | Ground Truth | Baseline Outcome | Precision RAG Outcome | Technical Determinant |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **A: Direct Timing Attack** | `TRUE_BUG` | Bug ⚠️ | `TP` | **`TP`** | Both pipelines catch `===` comparison on credentials. |
| **B: Cross-File Illusion** | `CROSS_FILE_ILLUSION` | Clean ✅ | `FP` *(Hallucination)* | **`TN`** | Baseline hallucinates missing symbol; RAG resolves definition in `utils.js`. |
| **C: Breaking Signature Change** | `BREAKING_CHANGE` | Bug ⚠️ | `FN` *(Missed Bug)* | **`TP`** | Baseline misses signature break; RAG retrieves caller `handleLogin` in `routes.js`. |
| **D: SQL Injection** | `TRUE_BUG` | Bug ⚠️ | `TP` | **`TP`** | Both pipelines detect raw SQL concatenation in query builder. |
| **E: Shared Session Refactor** | `CROSS_FILE_ILLUSION` | Clean ✅ | `FP` *(Hallucination)* | **`TN`** | Baseline flags missing declaration; RAG confirms `logoutUser` in `auth.js`. |

---

## 🏗️ 4-Tier Microservice Architecture

```
                                  +------------------------------------+
                                  |     GitHub PR Webhook Event        |
                                  +-----------------+------------------+
                                                    |
                                                    v
                                  +------------------------------------+
                                  |  Integration Service (:3000)       |
                                  |  - Express.js                      |
                                  |  - Octokit Line-Level Reviewer     |
                                  |  - Mongoose Audit Engine           |
                                  +-----------------+------------------+
                                                    |
                                                    | HTTP POST /api/v1/review
                                                    v
                                  +------------------------------------+
                                  |     AI / RAG Service (:8000)       |
                                  |  - FastAPI (Python 3.11)           |
                                  |  - Tree-sitter AST Chunker         |
                                  |  - LangChain Prompt Assembler      |
                                  +---------+----------------+---------+
                                            |                |
                       1. Vector Retrieval  |                | 2. Audit Logging
                                            v                v
                  +----------------------------+   +----------------------------+
                  |      ChromaDB (:8001)      |   |       MongoDB (:27017)     |
                  |  - Vector Store & Rules    |   |  - Review Sessions         |
                  |  - Call-Graph Symbol Index |   |  - Webhook Audits          |
                  +----------------------------+   +----------------------------+
```

### RAG Data Flow Lifecycle
1. **Webhook Ingestion**: Express verifies the `X-Hub-Signature-256` HMAC on a `pull_request` event (`opened`, `synchronize`, `reopened`), records the delivery in MongoDB (a unique index on GitHub's `X-GitHub-Delivery` ID drops redeliveries), queues the job on Amazon SQS, and answers `202` immediately — GitHub abandons deliveries after 10 seconds.
2. **Review Worker**: The `review-worker` service long-polls SQS. A message is deleted only after the review is posted; failures are retried with backoff and moved to a dead-letter queue after 3 attempts. Each posted review carries a hidden delivery marker, so an at-least-once redelivery never posts the same review twice.
3. **Diff Extraction**: The patch is fetched via Octokit (or taken from the webhook payload in local simulations).
4. **AST Boundary & Call Extraction**: Tree-sitter parses the diff into AST scopes and extracts outbound S-expression function calls (`(call_expression ...)`).
5. **Call-Graph Inbound Retrieval**: If a function declaration is modified, ChromaDB queries find all inbound callers in other files.
6. **Architectural Guideline Retrieval**: ChromaDB matches semantic security/performance guidelines against modified code hunks.
7. **Precision Prompt Assembly**: LangChain unifies the retrieved context, AST scopes, and diff into a structured prompt.
8. **Line-Anchored Output & 1-Click Suggestions**: Comments are posted via Octokit with native GitHub ` ```suggestion ` blocks.

---

## ⚡ Key Features

- **AST-Aware Syntax Chunking**: Eliminates arbitrary line splits using Tree-sitter (`tree-sitter-python`, `tree-sitter-javascript`) to isolate functions, methods, and classes.
- **Cross-File Call-Graph Inbound Querying**: Dynamically discovers when modified functions break contracts in untouched files across the repository.
- **Interactive 1-Click GitHub Suggestions**: Produces native GitHub suggestion blocks so maintainers can apply suggested code fixes directly in the PR UI.
- **Zero-Dependency Vector Embeddings**: Features an air-gapped deterministic projection function (`PrecisionEmbeddingFunction`), running with zero model download latency in CI/CD containers.
- **Fail-Safe Non-Blocking Database**: Express handles database disconnections gracefully (`bufferCommands: false`), ensuring webhooks never block even during container startup lag.
- **Automated Quantitative Benchmark Suite**: Includes a built-in evaluation harness (`run_evals.py`) to verify precision, recall, and hallucination reduction on demand.

---

## 🛠️ Tech Stack

| Domain | Technologies |
| :--- | :--- |
| **Integration Service** | Node.js (ESM), Express.js, Octokit Rest (`@octokit/rest`), Mongoose ODM, Axios |
| **AI / RAG Service** | Python 3.11+, FastAPI, Uvicorn, LangChain Core, Pydantic v2 |
| **AST & Parsing** | Tree-sitter 0.26+, `tree-sitter-javascript`, `tree-sitter-python` |
| **Vector Database** | ChromaDB (Vector Store & Symbol Metadata Index) |
| **Document Database** | MongoDB 7.0 (PR Session Auditing & History) |
| **Orchestration** | Docker, Docker Compose, Multi-stage Alpine/Slim Dockerfiles |
| **Testing & Verification** | Pytest, Node Test Runner (`node:test`), Custom Evaluation Harness |

---

## 🌐 Port Allocations

| Service | Container Port | Host Port | Purpose |
| :--- | :---: | :---: | :--- |
| **Integration Service** | `3000` | `3000` | Webhook listener, Octokit reviewer, review history |
| **AI / RAG Service** | `8000` | `8000` | FastAPI RAG review pipeline, AST chunker |
| **ChromaDB** | `8000` | `8001` | Vector database *(Host mapped to 8001 to prevent collision with FastAPI)* |
| **MongoDB** | `27017` | `27017` | Document database for review session audits |

---

## 📂 Project Directory Structure

```
precision-pr-reviewer/
├── .env.example                               # Unified root environment template
├── .gitignore                                 # Production gitignore (secrets & volumes guarded)
├── docker-compose.yml                         # 4-service container orchestration
├── README.md                                  # Enterprise documentation & benchmark report
├── scripts/
│   ├── simulate_webhook.sh                    # End-to-end webhook test script
│   └── test_rag_pipeline.py                   # Direct Python AI service tester
│
└── services/
    ├── integration-service/                   # Node.js + Express Integration Microservice
    │   ├── Dockerfile                         # Node 20 alpine multi-stage container
    │   ├── package.json                       # Dependencies & npm test scripts
    │   ├── test/server.test.js                # Native node:test suite (2/2 passing)
    │   └── src/
    │       ├── server.js                      # Express HTTP server with 25MB body limit
    │       ├── config/db.js                   # Resilient Mongoose connection manager
    │       ├── config/octokit.js              # Octokit client & line-level suggestion submitter
    │       ├── controllers/webhookController.js# PR event extraction & RAG dispatching
    │       ├── models/ReviewSession.js        # Mongoose audit model for PR reviews
    │       ├── routes/webhookRoutes.js        # Webhook & review history endpoints
    │       ├── routes/healthRoutes.js         # Service & dependency healthcheck
    │       └── services/aiServiceClient.js    # Axios client communicating with FastAPI
    │
    └── ai-service/                            # Python + FastAPI RAG Microservice
        ├── Dockerfile                         # Python 3.11 slim container
        ├── requirements.txt                   # FastAPI, LangChain, ChromaDB, Tree-sitter
        ├── tests/
        │   ├── test_ai_service.py             # Pytest suite with benchmark assertions (7/7 passing)
        │   └── mock_repo/                     # Mock multi-file repository (auth.js, routes.js, utils.js)
        ├── evals/
        │   ├── dataset.json                   # 5 ground-truth PR evaluation scenarios
        │   ├── run_evals.py                   # Quantitative evaluation engine
        │   └── benchmark_results.md           # Auto-generated markdown benchmark report
        └── app/
            ├── main.py                        # FastAPI entrypoint, lifespan & routes
            ├── config.py                      # Pydantic v2 application settings
            ├── db/chroma_client.py            # ChromaManager (indexing, inbound callers, embeddings)
            ├── models/schemas.py              # Pydantic request/response models
            ├── rag/
            │   ├── ast_chunker.py             # Tree-sitter S-expression query engine
            │   ├── chunking_stub.py           # Unified diff hunk parser & syntax contracts
            │   ├── pipeline.py                # LangChain Precision Call-Graph RAG pipeline
            │   └── baseline.py                # Naive Diff-Only baseline pipeline
            └── services/reviewer.py           # Precision review orchestrator
```

---

## 🚀 Quickstart & Installation

### Option 1: Docker Compose (One-Command Deployment)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/kamboj-sajan/Precision-PR-Reviewer.git
   cd Precision-PR-Reviewer
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   ```
   For a real deployment, set these in `.env`:

   | Variable | Purpose |
   | :--- | :--- |
   | `GITHUB_WEBHOOK_SECRET` | **Required.** Must match the secret configured on the GitHub webhook; unsigned or mis-signed deliveries are rejected with `401`. |
   | `GITHUB_TOKEN` | Token with pull request read/write access. Left unset, reviews are generated but not posted to GitHub. |
   | `MOCK_LLM_MODE` | `true` (default) uses the built-in rule engine. `false` sends the assembled Call-Graph RAG prompt to an LLM; if that call fails (e.g. a diff too large for a free tier), the rule-based review is posted instead. |
   | `LLM_API_KEY` | Needed when `MOCK_LLM_MODE=false`. Free Groq keys come from [console.groq.com](https://console.groq.com/keys). |
   | `LLM_BASE_URL` | Any OpenAI-compatible chat API (default Groq: `https://api.groq.com/openai/v1`). |
   | `LLM_MODEL` | Model used for reviews (default `openai/gpt-oss-120b`). It must support `json_schema` structured outputs. |
   | `SQS_QUEUE_URL` | Amazon SQS queue for review jobs, consumed by `review-worker`. Unset, reviews run in the background inside the webhook service with the same retry budget. |
   | `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Credentials for an IAM user limited to `SendMessage`, `ReceiveMessage`, `DeleteMessage`, `ChangeMessageVisibility` and `GetQueueAttributes` on that queue. |

3. **Launch all 4 microservices:**
   ```bash
   docker compose up --build
   ```

4. **Verify service health:**
   ```bash
   # Integration Service Probe
   curl http://localhost:3000/health

   # AI / RAG Service Probe
   curl http://localhost:8000/health
   ```

---

### Option 2: Native Local Development

#### Prerequisites
- Node.js >= 22.x
- Python >= 3.11

#### 1. Integration Service (Node.js)
```bash
cd services/integration-service
npm install
npm run dev
```

#### 2. AI / RAG Service (Python)
```bash
cd services/ai-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🧪 Testing & Benchmark Replication

### 1. Run Quantitative Benchmark Harness
```bash
cd services/ai-service
PYTHONPATH=. .venv/bin/python evals/run_evals.py
```

### 2. Run Python Automated Tests (Pytest)
```bash
cd services/ai-service
PYTHONPATH=. .venv/bin/pytest tests/test_ai_service.py -v
```
*Result: 7/7 tests pass in < 1 second.*

### 3. Run Node.js Integration Tests
```bash
cd services/integration-service
npm test
```
*Result: 2/2 tests pass in < 300ms.*

### 4. End-to-End GitHub Webhook Simulation
```bash
./scripts/simulate_webhook.sh http://localhost:3000/api/webhook
```

