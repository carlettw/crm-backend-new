from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase: Project Settings → Database → Connection string (Session pooler) dan olinadi
    database_url: str = "postgresql+asyncpg://postgres.PROJECT_REF:PAROL@aws-0-REGION.pooler.supabase.com:5432/postgres"
    db_ssl: bool = True  # Supabase SSL talab qiladi; lokal Postgres uchun false
    secret_key: str = "change-me"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"  # frontend manzillari (vergul bilan)
    auto_create_tables: bool = True  # dev; productionda False + `alembic upgrade head`
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    first_superadmin_phone: str = "+998900000000"
    first_superadmin_username: str = "superadmin"
    first_superadmin_password: str = "ChangeMe123"


settings = Settings()
