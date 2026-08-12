from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str
    API_V1_STR: str
    MODEL_PATH: str

    GMAIL_CREDENTIALS_FILE: str
    GMAIL_TOKEN_FILE: str

    AUTO_GMAIL_DETECTION_ENABLED: bool = True
    GMAIL_POLL_INTERVAL_SECONDS: int = 60

    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str

    SESSION_SECRET_KEY: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()