import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # App Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///c:/Users/Admin/dumbo-tron/brain_farm.db"
    
    # Security
    ENCRYPTION_KEY: str = "3k89gHJKasdfjkl_1234567890abcdefghijklm="  # Fallback base64 key
    
    # WorldQuant BRAIN API Configuration
    BRAIN_API_URL: str = "https://api.worldquantbrain.com"
    
    # Mock settings
    MOCK_MODE: bool = False  # Overridden by UI checkbox; False = use real BRAIN API
    
    # LLM Settings (for LLM formula optimization and assistant)
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
