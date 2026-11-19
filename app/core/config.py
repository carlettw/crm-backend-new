from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET = "change-me"
DEFAULT_SUPERADMIN_PASSWORD = "ChangeMe123"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # development | production. Productionda xavfsiz bo'lmagan sozlamalar bilan server ishga tushmaydi.
    environment: str = "development"

    # Supabase: Project Settings → Database → Connection string (Session pooler) dan olinadi
    database_url: str = "postgresql+asyncpg://postgres.PROJECT_REF:PAROL@aws-0-REGION.pooler.supabase.com:5432/postgres"
    db_ssl: bool = True  # Supabase SSL talab qiladi; lokal Postgres uchun false
    db_statement_cache: bool = True  # muammo bo'lsa DB_STATEMENT_CACHE=false
    secret_key: str = DEFAULT_SECRET
    # karta raqamlarini shifrlash kaliti (ixtiyoriy). Bo'sh bo'lsa SECRET_KEY dan hosil qilinadi.
    # Diqqat: kalit o'zgarsa, saqlangan kartalarni o'qib bo'lmaydi.
    card_encryption_key: str = ""
    # avvalgi karta kalitlari (vergul bilan) — faqat o'qish uchun; ishga tushishda yozuvlar yangi kalitga o'tkaziladi
    card_old_keys: str = ""
    # tashqi cron (/api/v1/cron/tick) uchun kalit. Bo'sh bo'lsa SECRET_KEY dan hosil qilinadi.
    cron_secret: str = ""
    # Telegram bot (BotFather bergan token). Bo'sh bo'lsa Telegram o'chirilgan.
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""   # ixtiyoriy: bo'sh bo'lsa getMe orqali olinadi
    telegram_poll_seconds: float = 3.0
    public_url: str = ""              # backend'ning ochiq manzili (webhook uchun); Render'da RENDER_EXTERNAL_URL o'zi beriladi
    render_external_url: str = ""
    certificates_enabled: bool = False  # sertifikatlash hozircha o'chirilgan (kod tayyor, yoqish: CERTIFICATES_ENABLED=true)
    frontend_url: str = ""            # xabarlardagi "Saytni ochish" tugmasi uchun
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"  # frontend manzillari (vergul bilan)
    auto_create_tables: bool = True  # dev; productionda False + `alembic upgrade head`
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    # login: shuncha muvaffaqiyatsiz urinishdan keyin username/IP vaqtincha bloklanadi
    login_max_attempts: int = 5
    login_lock_minutes: int = 15
    sentry_dsn: str = ""              # ixtiyoriy: xatolarni Sentry'ga yuborish
    log_level: str = "INFO"
    first_superadmin_phone: str = "+998900000000"
    first_superadmin_username: str = "superadmin"
    first_superadmin_password: str = DEFAULT_SUPERADMIN_PASSWORD

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("prod", "production")

    def check_production(self):
        """Productionda xavfli standart qiymatlar bilan ishga tushirmaslik."""
        if not self.is_production:
            return
        problems = []
        if self.secret_key == DEFAULT_SECRET or len(self.secret_key) < 32:
            problems.append("SECRET_KEY kamida 32 belgili tasodifiy qiymat bo'lishi kerak")
        if self.first_superadmin_password == DEFAULT_SUPERADMIN_PASSWORD or len(self.first_superadmin_password) < 10:
            problems.append("FIRST_SUPERADMIN_PASSWORD standart qiymatda yoki 10 belgidan qisqa")
        if self.auto_create_tables:
            problems.append("Productionda AUTO_CREATE_TABLES=false bo'lishi kerak (alembic ishlatiladi)")
        if problems:
            raise RuntimeError("Xavfsiz bo'lmagan sozlamalar: " + "; ".join(problems))


settings = Settings()
