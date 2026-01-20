from pydantic import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "OpenSourceResearchPlatform"
    app_version: str = "0.1.0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Database
    database_url: str = "postgresql+psycopg2://postgres:postgres@postgres:5432/postgres"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # MinIO / S3
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket_raw: str = "raw-documents"
    minio_bucket_text: str = "text-documents"
    minio_bucket_chunks: str = "chunks"

    # Auth
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours

    # LLM / OpenAI
    openai_api_key: str = ""  # Set via env var
    embedding_model: str = "text-embedding-ada-002"
    embedding_dimensions: int = 1536

    # Document Processing
    chunk_size_tokens: int = 600
    chunk_overlap_tokens: int = 100

    # Alert Engine
    alert_lookback_days: int = 90

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
