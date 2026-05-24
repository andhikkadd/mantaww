from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    discord_webhook_url: Optional[str] = Field(None, validation_alias="DISCORD_WEBHOOK_URL")
    min_score: int = Field(4, validation_alias="MIN_SCORE")
    max_items: int = Field(10, validation_alias="MAX_ITEMS")
    run_secret: Optional[str] = Field(None, validation_alias="RUN_SECRET")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings: Optional[Settings] = None

def get_settings() -> Settings:
    global settings
    if settings is None:
        settings = Settings()
    return settings
