import httpx
from fastapi import FastAPI

from app.api.routes import router


async def test_persisted_run_routes_require_a_valid_owner_session_header():
    application = FastAPI()
    application.include_router(router)
    requests = [
        ("POST", "/v1/agent/runs", {"json": {"query": "Dinner in Midtown"}}),
        ("GET", "/v1/agent/runs", {}),
        ("GET", "/v1/agent/runs/run-id", {}),
        ("GET", "/v1/agent/runs/run-id/trace", {}),
        ("GET", "/v1/agent/runs/run-id/events", {}),
        ("POST", "/v1/agent/runs/run-id/cancel", {}),
        ("POST", "/v1/agent/runs/run-id/actions/action-id/approve", {}),
        ("POST", "/v1/agent/runs/run-id/actions/action-id/reject", {}),
    ]

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for method, path, kwargs in requests:
            response = await client.request(method, path, **kwargs)
            assert response.status_code == 422
            assert any(
                error["loc"] == ["header", "x-agent-session"]
                for error in response.json()["detail"]
            )

        too_short = await client.post(
            "/v1/agent/runs",
            headers={"x-agent-session": "short"},
            json={"query": "Dinner in Midtown"},
        )
        assert too_short.status_code == 422
