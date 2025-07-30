from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Redis settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    # Supabase settings
    SUPABASE_URL: str
    SUPABASE_KEY: str
    
    # Moralis settings
    MORALIS_API_KEY: str

    ACTIVE_TOKEN_EXPIRY: int = 3600  # 1 hour
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

# Create single instance
print("About to create Settings instance...")
settings = Settings()