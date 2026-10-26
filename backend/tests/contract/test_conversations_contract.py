"""Contrato de los endpoints de US1 (modo JSON) contra contracts/openapi.yaml."""

import uuid

from ia_gateway.ocr.base import OcrHealth

from ..images import image_payload
from .schema_utils import assert_matches_schema

JSON = {"Accept": "application/json"}


async def _create(client) -> dict:
    response = await client.post("/api/v1/conversations")
    assert response.status_code == 201
    return response.json()


async def test_create_conversation(client):
    response = await client.post("/api/v1/conversations")
    assert response.status_code == 201
    assert "X-Correlation-ID" in response.headers
    assert_matches_schema(response.json(), "Conversation")


async def test_get_conversation(client):
    conv = await _create(client)
    await client.post(
        f"/api/v1/conversations/{conv['id']}/messages", json={"content": "Hola"}, headers=JSON
    )
    response = await client.get(f"/api/v1/conversations/{conv['id']}")
    assert response.status_code == 200
    body = response.json()
    assert_matches_schema(body, "ConversationWithMessages")
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["generation_in_progress"] is False


async def test_get_unknown_conversation_returns_404(client):
    response = await client.get(f"/api/v1/conversations/{uuid.uuid4()}")
    assert response.status_code == 404
    body = response.json()
    assert_matches_schema(body, "ErrorResponse")
    assert body["error"]["code"] == "CONVERSATION_NOT_FOUND"


async def test_delete_conversation_is_idempotent(client):
    conv = await _create(client)
    first = await client.delete(f"/api/v1/conversations/{conv['id']}")
    second = await client.delete(f"/api/v1/conversations/{conv['id']}")
    assert (first.status_code, second.status_code) == (204, 204)
    assert (await client.get(f"/api/v1/conversations/{conv['id']}")).status_code == 404


async def test_send_message_json(client):
    conv = await _create(client)
    response = await client.post(
        f"/api/v1/conversations/{conv['id']}/messages", json={"content": "  Hola  "}, headers=JSON
    )
    assert response.status_code == 200
    body = response.json()
    assert_matches_schema(body, "SendMessageResponse")
    assert body["user_message"]["content"] == "Hola"
    assert body["assistant_message"]["content"] == "Hola, soy un asistente."
    assert body["assistant_message"]["status"] == "complete"


async def test_send_message_to_unknown_conversation(client):
    response = await client.post(
        f"/api/v1/conversations/{uuid.uuid4()}/messages", json={"content": "Hola"}, headers=JSON
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


async def _assert_validation_error(response) -> None:
    assert response.status_code == 422
    body = response.json()
    assert_matches_schema(body, "ErrorResponse")
    assert body["error"]["code"] == "VALIDATION_ERROR"


async def test_send_message_rejects_blank_content(client):
    conv = await _create(client)
    url = f"/api/v1/conversations/{conv['id']}/messages"
    await _assert_validation_error(await client.post(url, json={"content": ""}, headers=JSON))
    await _assert_validation_error(await client.post(url, json={"content": "   "}, headers=JSON))


async def test_send_message_rejects_too_long_content(client):
    conv = await _create(client)
    url = f"/api/v1/conversations/{conv['id']}/messages"
    response = await client.post(url, json={"content": "x" * 4001}, headers=JSON)
    await _assert_validation_error(response)
    ok = await client.post(url, json={"content": "x" * 4000}, headers=JSON)
    assert ok.status_code == 200


async def test_send_message_rejects_extra_fields(client):
    conv = await _create(client)
    url = f"/api/v1/conversations/{conv['id']}/messages"
    response = await client.post(url, json={"content": "Hola", "history": []}, headers=JSON)
    await _assert_validation_error(response)


async def test_send_message_with_image_json(client, fake_ocr):
    fake_ocr.queue_text("Error 404")
    conv = await _create(client)
    response = await client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"content": "¿Qué dice?", "image": image_payload()},
        headers=JSON,
    )
    assert response.status_code == 200
    body = response.json()
    assert_matches_schema(body, "SendMessageResponse")
    attachment = body["user_message"]["attachment"]
    assert attachment["filename"] == "captura.png"
    assert attachment["media_type"] == "image/png"
    assert attachment["size_bytes"] > 0
    assert attachment["text"] == "Error 404"
    assert attachment["truncated"] is False
    assert body["assistant_message"].get("attachment") is None


async def test_send_message_with_image_and_no_content(client):
    conv = await _create(client)
    response = await client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"image": image_payload()},
        headers=JSON,
    )
    assert response.status_code == 200
    assert_matches_schema(response.json(), "SendMessageResponse")
    assert response.json()["user_message"]["content"] == ""


async def test_send_message_without_image_or_content(client):
    conv = await _create(client)
    url = f"/api/v1/conversations/{conv['id']}/messages"
    await _assert_validation_error(await client.post(url, json={}, headers=JSON))
    await _assert_validation_error(await client.post(url, json={"image": None}, headers=JSON))


async def test_send_message_rejects_unknown_image_fields(client):
    conv = await _create(client)
    url = f"/api/v1/conversations/{conv['id']}/messages"
    image = {**image_payload(), "url": "http://x"}
    await _assert_validation_error(await client.post(url, json={"image": image}, headers=JSON))
    bad_type = {**image_payload(), "media_type": "image/gif"}
    await _assert_validation_error(await client.post(url, json={"image": bad_type}, headers=JSON))


async def test_messages_without_image_have_null_attachment(client):
    conv = await _create(client)
    body = (
        await client.post(
            f"/api/v1/conversations/{conv['id']}/messages", json={"content": "Hola"}, headers=JSON
        )
    ).json()
    assert body["user_message"].get("attachment") is None
    assert_matches_schema(body, "SendMessageResponse")


async def test_health(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert_matches_schema(body, "Health")
    assert body["status"] == "ok"
    assert body["checks"]["llm"]["model_available"] is True
    assert body["checks"]["ocr"] == {"status": "ok", "languages": ["eng", "spa"]}


async def test_health_degraded_when_ocr_fails(client, fake_ocr):
    fake_ocr.health_result = OcrHealth(ok=False, detail="falta spa", languages=["eng"])
    response = await client.get("/api/v1/health")
    assert response.status_code == 503
    body = response.json()
    assert_matches_schema(body, "Health")
    assert body["status"] == "degraded"
    assert body["checks"]["ocr"] == {"status": "error", "detail": "falta spa", "languages": ["eng"]}
    assert body["checks"]["llm"]["status"] == "ok"


async def test_health_with_ocr_disabled(client, settings, fake_ocr):
    settings.ocr_enabled = False
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert_matches_schema(body, "Health")
    assert body["status"] == "ok"
    assert body["checks"]["ocr"]["status"] == "disabled"
    assert fake_ocr.health_calls == 0


async def test_image_error_bodies_match_contract(client, fake_ocr):
    conv = await _create(client)
    url = f"/api/v1/conversations/{conv['id']}/messages"
    fake_ocr.queue_text("")
    no_text = await client.post(url, json={"image": image_payload()}, headers=JSON)
    invalid = await client.post(
        url, json={"image": {**image_payload(), "data": "####"}}, headers=JSON
    )
    for response, code in ((no_text, "IMAGE_NO_TEXT"), (invalid, "IMAGE_INVALID")):
        assert_matches_schema(response.json(), "ErrorResponse")
        assert response.json()["error"]["code"] == code
