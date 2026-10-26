import httpx

from ia_gateway.main import create_app


async def test_correlation_id_is_generated(client):
    response = await client.get("/api/v1/no-existe")
    correlation_id = response.headers["X-Correlation-ID"]
    assert correlation_id
    assert response.json()["error"]["correlation_id"] == correlation_id


async def test_valid_incoming_correlation_id_is_reused(client):
    response = await client.get("/api/v1/no-existe", headers={"X-Correlation-ID": "abc-123"})
    assert response.headers["X-Correlation-ID"] == "abc-123"


async def test_invalid_incoming_correlation_id_is_replaced(client):
    invalid = "no valido; <script>" + "x" * 80
    response = await client.get("/api/v1/no-existe", headers={"X-Correlation-ID": invalid})
    assert response.headers["X-Correlation-ID"] != invalid


async def test_unknown_route_uses_uniform_error_format(client):
    response = await client.get("/api/v1/no-existe")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert set(error) >= {"code", "message", "correlation_id"}


async def test_client_outside_allowed_networks_is_denied(settings, fake_llm):
    app = create_app(settings, llm_client=fake_llm)
    transport = httpx.ASGITransport(app=app, client=("8.8.8.8", 4000))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as outsider:
            response = await outsider.post("/api/v1/conversations")
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "ACCESS_DENIED"
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]


async def test_cors_preflight_rejects_unlisted_origin(client):
    response = await client.options(
        "/api/v1/conversations",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


async def test_cors_preflight_accepts_listed_origin(client):
    response = await client.options(
        "/api/v1/conversations",
        headers={"Origin": "http://localhost:8000", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8000"
