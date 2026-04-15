from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import asc, func, select

from enterprise.storage.db import SessionLocal
from enterprise.storage.models import ChatMessageRecord
from harness.engine.messages import ConversationMessage, ToolCall


class MessageRepository:
    def append(self, session_id: str, message: ConversationMessage) -> ChatMessageRecord:
        with SessionLocal() as session:
            current = session.scalar(
                select(func.max(ChatMessageRecord.sequence)).where(ChatMessageRecord.session_id == session_id)
            )
            next_sequence = int(current or 0) + 1
            row = ChatMessageRecord(
                session_id=session_id,
                sequence=next_sequence,
                role=message.role,
                content=message.content,
                tool_calls=json.dumps([tool.model_dump(mode="json") for tool in message.tool_calls], ensure_ascii=False),
                tool_call_id=message.tool_call_id or "",
                name=message.name or "",
                created_at=datetime.utcnow(),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def list_by_session(self, session_id: str) -> list[ConversationMessage]:
        with SessionLocal() as session:
            stmt = (
                select(ChatMessageRecord)
                .where(ChatMessageRecord.session_id == session_id)
                .order_by(asc(ChatMessageRecord.sequence))
            )
            rows = session.scalars(stmt).all()
            messages: list[ConversationMessage] = []
            for row in rows:
                payload = json.loads(row.tool_calls or "[]")
                messages.append(
                    ConversationMessage(
                        role=row.role,
                        content=row.content,
                        tool_calls=[ToolCall.model_validate(item) for item in payload],
                        tool_call_id=row.tool_call_id or None,
                        name=row.name or None,
                    )
                )
            return messages
