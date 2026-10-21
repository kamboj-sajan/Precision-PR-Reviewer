from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8001
    CHROMA_COLLECTION: str = "codebase_knowledge"
    MOCK_LLM_MODE: bool = True
    # Any OpenAI-compatible chat API; defaults target Groq's free tier
    LLM_BASE_URL: str = "https://api.groq.com/openai/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "openai/gpt-oss-120b"
    LLM_MAX_OUTPUT_TOKENS: int = 4000
    LLM_REASONING_EFFORT: str = "medium"
    LOG_LEVEL: str = "info"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

@lru_cache()
def get_settings() -> Settings:
    return Settings()
