import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gomoku.db")
SECRET_KEY = os.getenv("SECRET_KEY", "gomoku-battle-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7
