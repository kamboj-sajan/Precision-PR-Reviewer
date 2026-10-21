import logging
import hashlib
import os
from typing import Dict, Any, List, Optional
import numpy as np
import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from app.config import get_settings
from app.rag.ast_chunker import chunk_file_by_ast

logger = logging.getLogger(__name__)

class PrecisionEmbeddingFunction(EmbeddingFunction[Documents]):
    """
    Deterministic, zero-dependency embedding function for precision code retrieval.
    Computes normalized token projections without requiring external model downloads,
    ensuring 100% offline reliability in air-gapped / CI / container environments.
    """
    def __init__(self, dim: int = 128):
        self.dim = dim

    @classmethod
    def name(cls) -> str:
        return "precision_embedding"

    def get_config(self) -> Dict[str, Any]:
        return {"dim": self.dim}

    @classmethod
    def build_from_config(cls, config: Dict[str, Any]) -> "PrecisionEmbeddingFunction":
        return cls(dim=config.get("dim", 128))

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = []
        for doc in input:
            vec = np.zeros(self.dim, dtype=np.float32)
            words = doc.lower().split()
            for w in words:
                h = int(hashlib.md5(w.encode('utf-8')).hexdigest(), 16)
                idx = h % self.dim
                vec[idx] += 1.0
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            embeddings.append(vec.tolist())
        return embeddings

class ChromaManager:
    """
    Manages connections to the ChromaDB vector database.
    Supports HTTP connection for Docker Compose deployments
    and local persistent client for standalone development.
    Handles architectural guidelines and cross-file call-graph codebase indexing.
    """
    def __init__(self):
        self.settings = get_settings()
        self.client = None
        self.collection = None
        self.connection_type = "uninitialized"
        self.embedding_fn = PrecisionEmbeddingFunction()

    def initialize(self):
        # 1. Attempt connection via HTTP to standalone ChromaDB container
        try:
            logger.info(f"[ChromaDB] Connecting to HTTP client at {self.settings.CHROMA_HOST}:{self.settings.CHROMA_PORT}...")
            http_client = chromadb.HttpClient(
                host=self.settings.CHROMA_HOST,
                port=self.settings.CHROMA_PORT,
                settings=ChromaSettings(anonymized_telemetry=False)
            )
            http_client.heartbeat()
            self.client = http_client
            self.connection_type = f"http://{self.settings.CHROMA_HOST}:{self.settings.CHROMA_PORT}"
            logger.info("[ChromaDB] Connected via HTTP successfully.")
        except Exception as e:
            logger.warning(f"[ChromaDB] HTTP connection failed ({e}). Falling back to local PersistentClient.")
            self.client = chromadb.PersistentClient(
                path="./chroma_data",
                settings=ChromaSettings(anonymized_telemetry=False)
            )
            self.connection_type = "local_persistent"

        # 2. Initialize target knowledge collection with precision embedding function
        self.collection = self.client.get_or_create_collection(
            name=self.settings.CHROMA_COLLECTION,
            embedding_function=self.embedding_fn,
            metadata={"description": "Precision PR Reviewer architectural rules and codebase call graph"}
        )

        # 3. Seed initial precision review guidelines if empty
        self._seed_default_guidelines()

    def _seed_default_guidelines(self):
        """Pre-populate vector store with precision coding & security guidelines."""
        try:
            count = self.collection.count()
            if count == 0:
                logger.info("[ChromaDB] Collection is empty. Seeding default precision review guidelines...")
                docs = [
                    "Security Rule #101: Never use standard equality (=== or ==) to verify passwords, tokens, or hashes. Always use crypto.timingSafeEqual to prevent side-channel timing attacks.",
                    "Performance Rule #201: Avoid N+1 query antipatterns. Batch database fetches with $in operators or DataLoader rather than executing queries inside loops.",
                    "Input Validation Rule #301: All external inputs, query parameters, and webhook payloads must be strictly validated with schema validators before processing.",
                    "Error Handling Rule #401: Never expose stack traces or raw database query errors in public API HTTP responses. Sanitize internal exceptions before returning.",
                    "Memory & Concurrency Rule #501: Ensure background asynchronous tasks handle unhandled promise rejections and clean up persistent event listeners."
                ]
                metadatas = [
                    {"category": "SECURITY", "rule_id": "SEC-101", "severity": "CRITICAL", "item_type": "guideline"},
                    {"category": "PERFORMANCE", "rule_id": "PERF-201", "severity": "WARNING", "item_type": "guideline"},
                    {"category": "INPUT_VALIDATION", "rule_id": "VAL-301", "severity": "WARNING", "item_type": "guideline"},
                    {"category": "ERROR_HANDLING", "rule_id": "ERR-401", "severity": "WARNING", "item_type": "guideline"},
                    {"category": "CONCURRENCY", "rule_id": "CONC-501", "severity": "INFO", "item_type": "guideline"}
                ]
                ids = [f"guideline_{i+1}" for i in range(len(docs))]

                self.collection.add(
                    documents=docs,
                    metadatas=metadatas,
                    ids=ids
                )
                logger.info(f"[ChromaDB] Seeded {len(docs)} precision guidelines successfully.")
        except Exception as err:
            logger.error(f"[ChromaDB] Error seeding guidelines: {err}")

    def index_repository(self, repo_path: str) -> Dict[str, Any]:
        """
        Phase 2: Reads a repository directory, chunks code files using AST chunker,
        extracts declared_symbols and called_symbols, and stores them in ChromaDB.
        """
        if not self.collection:
            self.initialize()

        logger.info(f"[ChromaDB] Indexing repository at: {repo_path}")
        allowed_extensions = {".js", ".jsx", ".ts", ".tsx", ".py"}
        ignored_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", "dist", "build"}

        all_chunks = []
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in allowed_extensions:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, repo_path)
                    try:
                        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                        file_chunks = chunk_file_by_ast(rel_path, content)
                        all_chunks.extend(file_chunks)
                    except Exception as e:
                        logger.warning(f"[ChromaDB] Could not index {rel_path}: {e}")

        if not all_chunks:
            logger.info("[ChromaDB] No code chunks found to index in repository.")
            return {"indexed_chunks": 0, "status": "empty"}

        docs = []
        metas = []
        ids = []

        for chunk in all_chunks:
            chunk_id = f"code:{chunk.file_path}:{chunk.name}:{chunk.start_line}"
            doc_text = f"// File: {chunk.file_path} | Scope: {chunk.name} ({chunk.node_type})\n{chunk.code}"

            declared_str = ",".join(chunk.declared_symbols)
            called_str = ",".join(chunk.called_symbols)

            metadata = {
                "file_path": chunk.file_path,
                "name": chunk.name,
                "node_type": chunk.node_type,
                "start_line": int(chunk.start_line),
                "end_line": int(chunk.end_line),
                "declared_symbols": declared_str,
                "called_symbols": called_str,
                "item_type": "codebase_symbol"
            }

            docs.append(doc_text)
            metas.append(metadata)
            ids.append(chunk_id)

        # Upsert chunks into ChromaDB
        self.collection.upsert(
            documents=docs,
            metadatas=metas,
            ids=ids
        )
        logger.info(f"[ChromaDB] Indexed {len(all_chunks)} code chunks from repository into vector store.")
        return {
            "indexed_chunks": len(all_chunks),
            "files_processed": len(set(c.file_path for c in all_chunks)),
            "status": "success"
        }

    def find_inbound_callers(self, symbol_name: str, exclude_file: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Cross-File Call-Graph Query:
        Finds all chunks in other files where called_symbols contains the target symbol_name.
        """
        if not self.collection:
            self.initialize()

        if not symbol_name or symbol_name == "anonymous":
            return []

        try:
            results = self.collection.get(
                where_document={"$contains": symbol_name}
            )

            callers: List[Dict[str, Any]] = []
            ids = results.get("ids", [])
            metadatas = results.get("metadatas", [])
            documents = results.get("documents", [])

            for i in range(len(ids)):
                meta = metadatas[i] if i < len(metadatas) else {}
                file_path = meta.get("file_path", "")

                if exclude_file:
                    norm_exclude = os.path.basename(exclude_file)
                    norm_file = os.path.basename(file_path)
                    if norm_file == norm_exclude:
                        continue

                called_symbols = [s.strip() for s in meta.get("called_symbols", "").split(",") if s.strip()]
                if symbol_name in called_symbols:
                    callers.append({
                        "id": ids[i],
                        "file_path": file_path,
                        "caller_name": meta.get("name"),
                        "node_type": meta.get("node_type"),
                        "start_line": meta.get("start_line"),
                        "end_line": meta.get("end_line"),
                        "code": documents[i] if i < len(documents) else "",
                        "called_symbol": symbol_name
                    })

            logger.info(f"[ChromaDB Call-Graph] Found {len(callers)} inbound callers for symbol '{symbol_name}'.")
            return callers
        except Exception as e:
            logger.error(f"[ChromaDB Call-Graph] Error querying inbound callers: {e}")
            return []

    def query_similar_context(self, query_text: str, n_results: int = 3):
        """RAG Query: Retrieve top-k relevant guidelines matching the code diff."""
        if not self.collection:
            self.initialize()

        try:
            count = self.collection.count()
            if count == 0:
                return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

            results = self.collection.query(
                query_texts=[query_text],
                n_results=min(n_results, count)
            )
            return results
        except Exception as e:
            logger.error(f"[ChromaDB] Query error: {e}")
            return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

    def get_health_status(self):
        try:
            item_count = self.collection.count() if self.collection else 0
            return {
                "status": "connected",
                "type": self.connection_type,
                "collection": self.settings.CHROMA_COLLECTION,
                "item_count": item_count
            }
        except Exception as e:
            return {
                "status": "degraded",
                "type": self.connection_type,
                "error": str(e)
            }

chroma_manager = ChromaManager()
