from enterprise.storage.db import ENGINE
from enterprise.storage.models import Base


def init_storage() -> None:
    """创建所有 SQLAlchemy 声明的表；若已存在则跳过。"""
    Base.metadata.create_all(bind=ENGINE)
