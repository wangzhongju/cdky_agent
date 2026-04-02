from sqlalchemy import create_engine    #! 数据库工具包 和 对象关系映射
from sqlalchemy.orm import sessionmaker
from utils.config_handler import enterprise_conf


def _database_url() -> str:
    """读取数据库地址；如果缺失则在启动阶段尽早失败。"""
    db_url = enterprise_conf.get("infra", {}).get("database_url", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL 未配置，无法启动企业级 Registry")
    return db_url


ENGINE = create_engine(_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)
