from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    serper_api_key: str
    request_timeout: int = 30
    max_results: int = 20
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"

settings = Settings() 