import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.models.schemas import PRReviewRequest, PRReviewResponse, HealthResponse
from app.db.chroma_client import chroma_manager
from app.services.reviewer import reviewer_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ai-service")
settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: connects to ChromaDB and seeds vectors on startup."""
    logger.info("Initializing AI/RAG Service and ChromaDB vector store...")
    try:
        chroma_manager.initialize()
        logger.info("ChromaDB vector store initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize ChromaDB during startup: {e}")
    yield
    logger.info("Shutting down AI/RAG Service...")

app = FastAPI(
    title="Precision GitHub AI PR Reviewer - AI/RAG Service",
    description="FastAPI service delivering Retrieval-Augmented Generation (RAG) code reviews with ChromaDB vector storage and Tree-sitter AST parsing hooks.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["Root"])
def root():
    return {
        "service": "Precision GitHub AI PR Reviewer - AI/RAG Service",
        "version": "1.0.0",
        "docs_url": "/docs",
        "health_url": "/health"
    }

@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health_check():
    """Probes ChromaDB connection, collection size, and pipeline readiness."""
    health_data = chroma_manager.get_health_status()
    return HealthResponse(
        status="healthy" if health_data.get("status") == "connected" else "degraded",
        chroma_status=health_data.get("status", "unknown"),
        collection_name=health_data.get("collection", settings.CHROMA_COLLECTION),
        collection_item_count=health_data.get("item_count", 0),
        rag_pipeline_status="ready"
    )

@app.post("/api/v1/review", response_model=PRReviewResponse, tags=["Review"])
def review_pull_request(request: PRReviewRequest):
    """
    Primary endpoint for precision PR reviews:
    Ingests git diff -> retrieves codebase rules via ChromaDB -> executes precision analysis -> returns line-anchored comments.
    """
    try:
        logger.info(f"Received review request for PR #{request.pr_id} on {request.repository}")
        response = reviewer_service.review_pull_request(request)
        return response
    except Exception as e:
        logger.error(f"Error processing PR review: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PR Review execution failed: {str(e)}"
        )

@app.get("/api/v1/knowledge", tags=["RAG Knowledge"])
def get_knowledge_base():
    """Inspect current precision guidelines indexed in ChromaDB."""
    try:
        if not chroma_manager.collection:
            chroma_manager.initialize()
        data = chroma_manager.collection.get()
        return {
            "collection": settings.CHROMA_COLLECTION,
            "count": len(data.get("ids", [])),
            "guidelines": [
                {
                    "id": data["ids"][i],
                    "document": data["documents"][i],
                    "metadata": data["metadatas"][i] if data.get("metadatas") else {}
                }
                for i in range(len(data.get("ids", [])))
            ]
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query knowledge base: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
