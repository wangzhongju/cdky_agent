from __future__ import annotations

"""
演示：SQLAlchemy ORM + Repository 模式（与本工程 storage 层同风格）。

对照工程：
- enterprise/storage/models.py
- enterprise/storage/task_repository.py
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class TaskRecord(Base):
    __tablename__ = "demo_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class TaskRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def create_task(self, task_id: str, goal: str) -> None:
        with self.session_factory() as session:
            row = TaskRecord(
                task_id=task_id,
                goal=goal,
                status="PENDING",
                retry_count=0,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(row)
            session.commit()

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        with self.session_factory() as session:
            stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
            return session.scalars(stmt).first()

    def update_status(self, task_id: str, status: str) -> None:
        with self.session_factory() as session:
            stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
            row = session.scalars(stmt).first()
            if not row:
                return
            row.status = status
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()

    def increment_retry(self, task_id: str) -> int:
        with self.session_factory() as session:
            stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
            row = session.scalars(stmt).first()
            if not row:
                return 0
            row.retry_count += 1
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()
            return row.retry_count


if __name__ == "__main__":
    # 用 sqlite 文件演示，避免依赖外部数据库
    engine = create_engine("sqlite:///library_playground/demo_repo.db", echo=False)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    repo = TaskRepository(SessionLocal)
    repo.create_task(task_id="t-001", goal="生成使用报告")
    print("[create] t-001")

    row = repo.get_task("t-001")
    print(f"[query] status={row.status} retry={row.retry_count}")

    repo.update_status("t-001", "RUNNING")
    retry = repo.increment_retry("t-001")
    row = repo.get_task("t-001")
    print(f"[update] status={row.status} retry={retry} updated_at={row.updated_at.isoformat()}")
