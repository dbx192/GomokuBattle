import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gomoku.db")
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "5"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "100"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
DB_COMMAND_TIMEOUT = int(os.getenv("DB_COMMAND_TIMEOUT", "30"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() == "true"
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "5"))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(
    os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300")
)
SECRET_KEY = os.getenv("SECRET_KEY", "gomoku-battle-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7
