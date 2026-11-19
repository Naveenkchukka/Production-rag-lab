"""Typed application settings loaded from the environment and local .env file."""

from functools import lru_cache
from uuid import UUID

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    rag_db_host: str = "127.0.0.1"
    rag_db_port: int = 5432
    rag_db_name: str = "rag"
    rag_db_user: str = "rag_runtime"
    rag_db_password: SecretStr
    openai_api_key: SecretStr
    rag_embedding_model: str = "text-embedding-3-small"
    rag_embedding_dimensions: int = 512
    rag_answer_model: str = "gpt-6-luna"
    rag_max_output_tokens: int = 1800
    rag_organization_id: UUID = UUID("819e5ef7-fb19-4b82-8c50-b9f44e93fa9b")
    rag_ingestor_user_id: UUID = UUID("10000000-0000-4000-8000-000000000004")


@lru_cache
def get_settings() -> Settings:
    return Settings()
