import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from ia_gateway.storage.repository import NewAttachment, NewMessage, NewToolInvocation
from ia_gateway.storage.sqlite import SqliteConversationRepository


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def repo(tmp_path, clock):
    repository = SqliteConversationRepository(
        tmp_path / "data" / "test.db", retention=timedelta(hours=24), clock=clock
    )
    await repository.initialize()
    return repository


async def test_create_conversation_sets_expiration(repo, clock):
    conv = await repo.create_conversation()
    assert conv.created_at == clock.now
    assert conv.expires_at == clock.now + timedelta(hours=24)


async def test_seq_is_increasing_and_activity_updates_expiration(repo, clock):
    conv = await repo.create_conversation()
    clock.advance(hours=1)
    first = await repo.add_message(conv.id, NewMessage(role="user", content="hola"))
    clock.advance(hours=1)
    second = await repo.add_message(conv.id, NewMessage(role="assistant", content="¡hola!"))
    assert (first.seq, second.seq) == (1, 2)

    updated = await repo.get_conversation(conv.id)
    assert updated is not None
    assert updated.last_activity_at == clock.now
    assert updated.expires_at == clock.now + timedelta(hours=24)

    messages = await repo.list_messages(conv.id)
    assert [m.content for m in messages] == ["hola", "¡hola!"]


async def test_message_fields_roundtrip(repo):
    conv = await repo.create_conversation()
    saved = await repo.add_message(
        conv.id,
        NewMessage(
            role="assistant",
            content="",
            status="error",
            error_code="LLM_TIMEOUT",
            tool_calls=[{"name": "current_time", "arguments": {}}],
            model="qwen3:4b",
            prompt_tokens=10,
            completion_tokens=5,
        ),
    )
    [loaded] = await repo.list_messages(conv.id)
    assert loaded == saved
    assert loaded.tool_calls == [{"name": "current_time", "arguments": {}}]


async def test_expired_conversation_is_not_returned(repo, clock):
    conv = await repo.create_conversation()
    clock.advance(hours=24)
    assert await repo.get_conversation(conv.id) is None


async def test_delete_expired_cascades(repo, clock):
    old = await repo.create_conversation()
    msg = await repo.add_message(old.id, NewMessage(role="assistant", content="x"))
    await repo.add_tool_invocation(
        old.id,
        NewToolInvocation(
            assistant_message_id=msg.id,
            tool_name="current_time",
            arguments={},
            status="ok",
            duration_ms=1,
            result={"iso": "x"},
        ),
    )
    clock.advance(hours=25)
    fresh = await repo.create_conversation()

    assert await repo.delete_expired() == 1
    assert await repo.list_messages(old.id) == []
    assert await repo.list_tool_invocations(old.id) == []
    assert await repo.get_conversation(fresh.id) is not None


async def test_delete_conversation_is_idempotent(repo):
    conv = await repo.create_conversation()
    await repo.delete_conversation(conv.id)
    await repo.delete_conversation(conv.id)
    assert await repo.get_conversation(conv.id) is None


async def test_data_survives_reopening(tmp_path, clock):
    path = tmp_path / "persist.db"
    first = SqliteConversationRepository(path, retention=timedelta(hours=24), clock=clock)
    await first.initialize()
    conv = await first.create_conversation()
    await first.add_message(conv.id, NewMessage(role="user", content="sigo acá"))

    second = SqliteConversationRepository(path, retention=timedelta(hours=24), clock=clock)
    await second.initialize()
    assert await second.get_conversation(conv.id) is not None
    assert [m.content for m in await second.list_messages(conv.id)] == ["sigo acá"]


# --- adjuntos (feature 002) -----------------------------------------------------------


def _attachment(**overrides) -> NewAttachment:
    values = {
        "filename": "captura.png",
        "media_type": "image/png",
        "size_bytes": 1234,
        "width": 800,
        "height": 200,
        "text": "Hola mundo",
        "truncated": True,
        "ocr_duration_ms": 42,
    }
    values.update(overrides)
    return NewAttachment(**values)


async def test_attachment_roundtrip(repo, clock):
    conv = await repo.create_conversation()
    saved = await repo.add_message(
        conv.id, NewMessage(role="user", content=""), attachment=_attachment()
    )
    await repo.add_message(conv.id, NewMessage(role="assistant", content="Dice hola"))

    user, assistant = await repo.list_messages(conv.id)
    assert user == saved
    assert user.content == ""
    assert user.attachment is not None
    assert user.attachment.message_id == user.id
    assert user.attachment.filename == "captura.png"
    assert user.attachment.media_type == "image/png"
    assert (user.attachment.size_bytes, user.attachment.width, user.attachment.height) == (
        1234,
        800,
        200,
    )
    assert user.attachment.text == "Hola mundo"
    assert user.attachment.truncated is True
    assert user.attachment.ocr_duration_ms == 42
    assert user.attachment.created_at == clock.now
    assert assistant.attachment is None


async def test_attachment_rejects_unknown_media_type(repo):
    conv = await repo.create_conversation()
    with pytest.raises(sqlite3.IntegrityError):
        await repo.add_message(
            conv.id,
            NewMessage(role="user", content="x"),
            attachment=_attachment(media_type="image/gif"),
        )
    # La transacción se revierte: tampoco queda el mensaje.
    assert await repo.list_messages(conv.id) == []


async def test_attachment_only_for_user_messages(repo):
    conv = await repo.create_conversation()
    with pytest.raises(ValueError):
        await repo.add_message(
            conv.id, NewMessage(role="assistant", content="x"), attachment=_attachment()
        )


async def test_attachments_cascade_on_delete_and_expiration(repo, clock):
    conv = await repo.create_conversation()
    await repo.add_message(conv.id, NewMessage(role="user", content="a"), attachment=_attachment())
    await repo.delete_conversation(conv.id)

    old = await repo.create_conversation()
    await repo.add_message(old.id, NewMessage(role="user", content="b"), attachment=_attachment())
    clock.advance(hours=25)
    assert await repo.delete_expired() == 1

    def count(conn: sqlite3.Connection) -> int:
        return conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]

    assert await repo._run(count) == 0


async def test_database_from_feature_001_gets_attachments_table(tmp_path, clock):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE conversations (id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
            last_activity_at TEXT NOT NULL, expires_at TEXT NOT NULL);
        CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL
            REFERENCES conversations(id) ON DELETE CASCADE, seq INTEGER NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL, error_code TEXT,
            tool_calls TEXT, tool_name TEXT, model TEXT, prompt_tokens INTEGER,
            completion_tokens INTEGER, created_at TEXT NOT NULL, UNIQUE (conversation_id, seq));
        """
    )
    conn.close()

    repo = SqliteConversationRepository(path, retention=timedelta(hours=24), clock=clock)
    await repo.initialize()
    conv = await repo.create_conversation()
    await repo.add_message(conv.id, NewMessage(role="user", content=""), attachment=_attachment())
    [message] = await repo.list_messages(conv.id)
    assert message.attachment is not None
