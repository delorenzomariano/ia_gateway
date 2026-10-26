from datetime import UTC, datetime

from ia_gateway.chat.context import IMAGE_TEXT_INSTRUCTION, build_context
from ia_gateway.storage.repository import AttachmentRecord, MessageRecord

NOW = datetime(2026, 10, 24, tzinfo=UTC)


def attachment(text="Error 404: página no encontrada", truncated=False, filename="captura.png"):
    return AttachmentRecord(
        message_id="m",
        filename=filename,
        media_type="image/png",
        size_bytes=10,
        width=10,
        height=10,
        text=text,
        truncated=truncated,
        ocr_duration_ms=1,
        created_at=NOW,
    )


def msg(seq, role, content, status="complete", **kwargs) -> MessageRecord:
    return MessageRecord(
        id=f"m{seq}",
        conversation_id="c",
        seq=seq,
        role=role,
        content=content,
        status=status,
        created_at=NOW,
        **kwargs,
    )


def test_system_prompt_goes_first():
    ctx = build_context("Sos un asistente.", [msg(1, "user", "Hola")], budget=1000)
    assert [(m.role, m.content) for m in ctx] == [("system", "Sos un asistente."), ("user", "Hola")]


def test_error_messages_are_excluded_and_incomplete_included():
    history = [
        msg(1, "user", "uno"),
        msg(2, "assistant", "", status="error", error_code="LLM_TIMEOUT"),
        msg(3, "assistant", "parcial", status="incomplete"),
        msg(4, "user", "dos"),
    ]
    ctx = build_context("S", history, budget=1000)
    assert [m.content for m in ctx[1:]] == ["uno", "parcial", "dos"]


def test_budget_keeps_latest():
    history = [msg(i, "user" if i % 2 else "assistant", f"{i:02d}" * 5) for i in range(1, 11)]
    ctx = build_context("S", history, budget=35)
    # cada mensaje mide 10 caracteres: entran los 3 más recientes
    assert [m.content for m in ctx[1:]] == ["08" * 5, "09" * 5, "10" * 5]


def test_current_message_always_included_even_if_over_budget():
    history = [msg(1, "user", "viejo"), msg(2, "user", "x" * 100)]
    ctx = build_context("S", history, budget=10)
    assert [m.content for m in ctx[1:]] == ["x" * 100]


def test_tool_call_pairs_are_not_split():
    history = [
        msg(1, "user", "¿qué hora es?"),
        msg(2, "assistant", "", tool_calls=[{"name": "current_time", "arguments": {}}]),
        msg(3, "tool", '{"iso": "2026-10-24T12:00:00"}', tool_name="current_time"),
        msg(4, "assistant", "Son las 12."),
        msg(5, "user", "gracias"),
    ]
    # El presupuesto alcanza para "gracias" + "Son las 12." + el resultado de la herramienta,
    # pero no para la llamada: el par llamada/resultado se descarta completo.
    budget = len("gracias") + len("Son las 12.") + len('{"iso": "2026-10-24T12:00:00"}')
    ctx = build_context("S", history, budget=budget)
    roles = [m.role for m in ctx[1:]]
    assert "tool" not in roles
    assert [m.content for m in ctx[1:]] == ["Son las 12.", "gracias"]


def test_tool_calls_are_converted():
    history = [
        msg(1, "user", "hora"),
        msg(2, "assistant", "", tool_calls=[{"name": "current_time", "arguments": {"tz": "x"}}]),
        msg(3, "tool", "{}", tool_name="current_time"),
    ]
    ctx = build_context("S", history, budget=1000)
    assert ctx[2].tool_calls[0].name == "current_time"
    assert ctx[2].tool_calls[0].arguments == {"tz": "x"}
    assert ctx[3].tool_name == "current_time"


# --- imágenes (feature 002) -----------------------------------------------------------


def test_user_message_with_attachment_includes_delimited_text():
    history = [msg(1, "user", "¿Qué dice este error?", attachment=attachment())]
    ctx = build_context("S", history, budget=1000)
    assert ctx[1].content == (
        "¿Qué dice este error?\n\n"
        '[Texto extraído de la imagen "captura.png" (recortado: no)]\n'
        "<<<\nError 404: página no encontrada\n>>>"
    )


def test_empty_question_uses_default_and_truncation_is_marked():
    history = [msg(1, "user", "", attachment=attachment(text="abc", truncated=True))]
    ctx = build_context("S", history, budget=1000)
    assert ctx[1].content.startswith("Analizá el texto de la imagen adjunta.\n\n")
    assert "(recortado: sí)]" in ctx[1].content


def test_attachment_text_counts_for_the_budget():
    history = [
        msg(1, "user", "vieja", attachment=attachment(text="x" * 50)),
        msg(2, "assistant", "ok"),
        msg(3, "user", "nueva"),
    ]
    # "nueva" + "ok" entran; el mensaje con imagen mide 5 + 50 y queda afuera.
    ctx = build_context("S", history, budget=len("nueva") + len("ok") + 20)
    assert [m.content for m in ctx[1:]] == ["ok", "nueva"]


def test_image_instruction_only_when_an_attachment_is_selected():
    without = build_context("S", [msg(1, "user", "hola")], budget=1000)
    assert without[0].content == "S"

    with_image = build_context(
        "S", [msg(1, "user", "", attachment=attachment()), msg(2, "user", "y?")], budget=1000
    )
    assert with_image[0].content == f"S\n\n{IMAGE_TEXT_INSTRUCTION}"

    dropped = build_context(
        "S",
        [msg(1, "user", "", attachment=attachment(text="x" * 100)), msg(2, "user", "y?")],
        budget=10,
    )
    assert dropped[0].content == "S"
