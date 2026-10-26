"""Repositorio de conversaciones sobre SQLite (librería estándar)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

import anyio.to_thread

from ia_gateway.storage.repository import (
    AttachmentRecord,
    ConversationRecord,
    MessageRecord,
    NewAttachment,
    NewMessage,
    NewToolInvocation,
    ToolInvocationRecord,
)

T = TypeVar("T")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_expires ON conversations(expires_at);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('complete', 'incomplete', 'error')),
    error_code TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (conversation_id, seq)
);

CREATE TABLE IF NOT EXISTS tool_invocations (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    assistant_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    arguments TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'error', 'rejected')),
    result TEXT,
    error TEXT,
    duration_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type IN ('image/png', 'image/jpeg', 'image/webp')),
    size_bytes INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    text TEXT NOT NULL,
    truncated INTEGER NOT NULL CHECK (truncated IN (0, 1)),
    ocr_duration_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""

_MESSAGE_COLUMNS = (
    "m.*, a.message_id AS a_message_id, a.filename AS a_filename, a.media_type AS a_media_type, "
    "a.size_bytes AS a_size_bytes, a.width AS a_width, a.height AS a_height, a.text AS a_text, "
    "a.truncated AS a_truncated, a.ocr_duration_ms AS a_ocr_duration_ms, "
    "a.created_at AS a_created_at"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ts(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _dumps(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _loads(value: str | None) -> Any:
    return None if value is None else json.loads(value)


class SqliteConversationRepository:
    def __init__(
        self,
        path: str | Path,
        retention: timedelta,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._path = Path(path)
        self._retention = retention
        self._clock = clock

    # --- infraestructura -------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        def work() -> T:
            conn = self._connect()
            try:
                with conn:
                    return fn(conn)
            finally:
                conn.close()

        return await anyio.to_thread.run_sync(work)

    async def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

        def setup(conn: sqlite3.Connection) -> None:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA)

        await self._run(setup)

    async def ping(self) -> None:
        await self._run(lambda conn: conn.execute("SELECT 1").fetchone())

    # --- conversaciones --------------------------------------------------------------

    @staticmethod
    def _conversation(row: sqlite3.Row) -> ConversationRecord:
        return ConversationRecord(
            id=row["id"],
            created_at=_dt(row["created_at"]),
            last_activity_at=_dt(row["last_activity_at"]),
            expires_at=_dt(row["expires_at"]),
        )

    async def create_conversation(self) -> ConversationRecord:
        now = self._clock()
        record = ConversationRecord(
            id=str(uuid.uuid4()),
            created_at=now,
            last_activity_at=now,
            expires_at=now + self._retention,
        )

        def insert(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO conversations (id, created_at, last_activity_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (record.id, _ts(now), _ts(now), _ts(record.expires_at)),
            )

        await self._run(insert)
        return record

    async def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        now = _ts(self._clock())

        def select(conn: sqlite3.Connection) -> ConversationRecord | None:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ? AND expires_at > ?",
                (conversation_id, now),
            ).fetchone()
            return self._conversation(row) if row else None

        return await self._run(select)

    async def delete_conversation(self, conversation_id: str) -> None:
        await self._run(
            lambda conn: conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        )

    async def delete_expired(self) -> int:
        now = _ts(self._clock())
        return await self._run(
            lambda conn: (
                conn.execute("DELETE FROM conversations WHERE expires_at <= ?", (now,)).rowcount
            )
        )

    # --- mensajes --------------------------------------------------------------------

    @staticmethod
    def _attachment(row: sqlite3.Row) -> AttachmentRecord | None:
        if row["a_message_id"] is None:
            return None
        return AttachmentRecord(
            message_id=row["a_message_id"],
            filename=row["a_filename"],
            media_type=row["a_media_type"],
            size_bytes=row["a_size_bytes"],
            width=row["a_width"],
            height=row["a_height"],
            text=row["a_text"],
            truncated=bool(row["a_truncated"]),
            ocr_duration_ms=row["a_ocr_duration_ms"],
            created_at=_dt(row["a_created_at"]),
        )

    @classmethod
    def _message(cls, row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            id=row["id"],
            conversation_id=row["conversation_id"],
            seq=row["seq"],
            role=row["role"],
            content=row["content"],
            status=row["status"],
            created_at=_dt(row["created_at"]),
            error_code=row["error_code"],
            tool_calls=_loads(row["tool_calls"]),
            tool_name=row["tool_name"],
            model=row["model"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            attachment=cls._attachment(row),
        )

    async def add_message(
        self,
        conversation_id: str,
        message: NewMessage,
        attachment: NewAttachment | None = None,
    ) -> MessageRecord:
        if attachment is not None and message.role != "user":
            raise ValueError("solo los mensajes del usuario pueden llevar un adjunto")
        now = self._clock()
        message_id = message.id or str(uuid.uuid4())
        attachment_record = (
            None
            if attachment is None
            else AttachmentRecord(
                message_id=message_id,
                filename=attachment.filename,
                media_type=attachment.media_type,
                size_bytes=attachment.size_bytes,
                width=attachment.width,
                height=attachment.height,
                text=attachment.text,
                truncated=attachment.truncated,
                ocr_duration_ms=attachment.ocr_duration_ms,
                created_at=_dt(_ts(now)),
            )
        )

        def insert(conn: sqlite3.Connection) -> MessageRecord:
            (seq,) = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            conn.execute(
                "INSERT INTO messages (id, conversation_id, seq, role, content, status, "
                "error_code, tool_calls, tool_name, model, prompt_tokens, completion_tokens, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    conversation_id,
                    seq,
                    message.role,
                    message.content,
                    message.status,
                    message.error_code,
                    _dumps(message.tool_calls),
                    message.tool_name,
                    message.model,
                    message.prompt_tokens,
                    message.completion_tokens,
                    _ts(now),
                ),
            )
            if attachment_record is not None:
                a = attachment_record
                conn.execute(
                    "INSERT INTO attachments (message_id, filename, media_type, size_bytes, "
                    "width, height, text, truncated, ocr_duration_ms, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        a.message_id,
                        a.filename,
                        a.media_type,
                        a.size_bytes,
                        a.width,
                        a.height,
                        a.text,
                        int(a.truncated),
                        a.ocr_duration_ms,
                        _ts(now),
                    ),
                )
            conn.execute(
                "UPDATE conversations SET last_activity_at = ?, expires_at = ? WHERE id = ?",
                (_ts(now), _ts(now + self._retention), conversation_id),
            )
            return MessageRecord(
                id=message_id,
                conversation_id=conversation_id,
                seq=seq,
                role=message.role,
                content=message.content,
                status=message.status,
                created_at=_dt(_ts(now)),
                error_code=message.error_code,
                tool_calls=message.tool_calls,
                tool_name=message.tool_name,
                model=message.model,
                prompt_tokens=message.prompt_tokens,
                completion_tokens=message.completion_tokens,
                attachment=attachment_record,
            )

        return await self._run(insert)

    async def list_messages(self, conversation_id: str) -> list[MessageRecord]:
        def select(conn: sqlite3.Connection) -> list[MessageRecord]:
            rows = conn.execute(
                f"SELECT {_MESSAGE_COLUMNS} FROM messages m "
                "LEFT JOIN attachments a ON a.message_id = m.id "
                "WHERE m.conversation_id = ? ORDER BY m.seq",
                (conversation_id,),
            ).fetchall()
            return [self._message(row) for row in rows]

        return await self._run(select)

    async def delete_message(self, message_id: str) -> None:
        await self._run(
            lambda conn: conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        )

    # --- invocaciones de herramientas ------------------------------------------------

    async def add_tool_invocation(
        self, conversation_id: str, invocation: NewToolInvocation
    ) -> ToolInvocationRecord:
        now = self._clock()
        record = ToolInvocationRecord(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            assistant_message_id=invocation.assistant_message_id,
            tool_name=invocation.tool_name,
            arguments=invocation.arguments,
            status=invocation.status,
            duration_ms=invocation.duration_ms,
            created_at=now,
            result=invocation.result,
            error=invocation.error,
        )

        def insert(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO tool_invocations (id, conversation_id, assistant_message_id, "
                "tool_name, arguments, status, result, error, duration_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    conversation_id,
                    record.assistant_message_id,
                    record.tool_name,
                    _dumps(record.arguments) or "null",
                    record.status,
                    _dumps(record.result),
                    record.error,
                    record.duration_ms,
                    _ts(now),
                ),
            )

        await self._run(insert)
        return record

    async def list_tool_invocations(self, conversation_id: str) -> list[ToolInvocationRecord]:
        def select(conn: sqlite3.Connection) -> list[ToolInvocationRecord]:
            rows = conn.execute(
                "SELECT * FROM tool_invocations WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()
            return [
                ToolInvocationRecord(
                    id=row["id"],
                    conversation_id=row["conversation_id"],
                    assistant_message_id=row["assistant_message_id"],
                    tool_name=row["tool_name"],
                    arguments=_loads(row["arguments"]),
                    status=row["status"],
                    duration_ms=row["duration_ms"],
                    created_at=_dt(row["created_at"]),
                    result=_loads(row["result"]),
                    error=row["error"],
                )
                for row in rows
            ]

        return await self._run(select)
