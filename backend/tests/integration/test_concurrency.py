"""SC-006: al menos 5 conversaciones simultáneas sin errores."""

import asyncio

from ..fakes import FakeLLMClient, Sleep, text_reply

JSON = {"Accept": "application/json"}


async def test_five_concurrent_conversations(client, fake_llm: FakeLLMClient):
    fake_llm.default = [Sleep(0.2), *text_reply("respuesta")]
    ids = [(await client.post("/api/v1/conversations")).json()["id"] for _ in range(5)]

    async def converse(conv_id: str):
        return await client.post(
            f"/api/v1/conversations/{conv_id}/messages", json={"content": "hola"}, headers=JSON
        )

    responses = await asyncio.gather(*(converse(conv_id) for conv_id in ids))
    assert [r.status_code for r in responses] == [200] * 5
    assert all(r.json()["assistant_message"]["content"] == "respuesta" for r in responses)
