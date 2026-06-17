from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from config import DATABASE_URL, DB_POOL_MAX, DB_POOL_TIMEOUT, DB_COMMAND_TIMEOUT


normalized_database_url = DATABASE_URL
if (
    normalized_database_url.startswith("postgresql://")
    and "+psycopg" not in normalized_database_url
):
    normalized_database_url = normalized_database_url.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


engine_kwargs = {
    "pool_pre_ping": True,
}

if "sqlite" in normalized_database_url:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_size"] = DB_POOL_MAX
    engine_kwargs["max_overflow"] = 0
    engine_kwargs["pool_timeout"] = DB_POOL_TIMEOUT
    if normalized_database_url.startswith("postgresql"):
        engine_kwargs["connect_args"] = {
            "options": f"-c statement_timeout={DB_COMMAND_TIMEOUT * 1000}"
        }

engine = create_engine(normalized_database_url, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import user, game, room

    Base.metadata.create_all(bind=engine)
