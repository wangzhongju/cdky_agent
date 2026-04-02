from sqlalchemy import create_engine    #! sqlalchemy库：数据库工具包 和 对象关系映射
from sqlalchemy.orm import sessionmaker
from utils.config_handler import enterprise_conf


def _database_url() -> str:
    """读取数据库地址；如果缺失则在启动阶段尽早失败。"""
    db_url = enterprise_conf.get("infra", {}).get("database_url", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL 未配置，无法启动企业级 Registry")
    return db_url


ENGINE = create_engine(_database_url(), pool_pre_ping=True)                    #! 负责连接数据库，类似数据库连接池
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)    #! 操作数据库的入口，所有增删查改都通过它


"""
!关于 sqlalchemy 库的介绍  Python 世界最强数据库工具（ORM + SQL 构建器）
1. Engine（引擎）
    负责连接数据库，类似数据库连接池
    create_engine
2. Session（会话）
    操作数据库的入口
    sessionmaker
3. Model（模型）
    把表映射成 Python 类  一张表 = 一个类   见 models.py
4. 创建表
    Base.metadata.create_all(engine)  见 init_db.py

ORM 与 Core
用 Python 类操作数据库（像操作对象一样）
写接近 SQL 的表达式（更灵活、更底层）

TODO models.py 中定义的四张表，分别在 skill_repository.py task_repository.py  cost.py  audit.py 中封装有插入与更新，还可以完善删除等操作
"""