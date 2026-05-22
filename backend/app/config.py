from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Locate .env relative to this file so pytest and uvicorn both find it
# regardless of the working directory.
# config.py lives at  <root>/backend/app/config.py
# .env lives at       <root>/.env
_ROOT_ENV = Path(__file__).parent.parent.parent / ".env"
_LOCAL_ENV = Path(".env")  # fallback for Docker / any CWD-based usage


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    environment: str = "development"

    model_config = SettingsConfigDict(
        env_file=[str(_ROOT_ENV), str(_LOCAL_ENV)],
        extra="ignore",
    )


settings = Settings()
