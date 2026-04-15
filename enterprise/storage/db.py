from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from utils.config_handler import enterprise_conf


def _database_url() -> str:
    db_url = enterprise_conf.get("infra", {}).get("database_url", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL 未配置，无法启动企业级 Registry")
    return db_url


ENGINE = create_engine(_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)
