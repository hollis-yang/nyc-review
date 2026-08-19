import httpx

from app.config import Settings
from app.mcp.server import READ_ONLY_MCP_TOOL_NAMES, McpApiKeyMiddleware, mcp
from app.mcp.service import McpDomainService
from app.runtime import AgentRuntime


async def test_mcp_exports_only_catalogued_read_tools():
    names = {tool.name for tool in await mcp.list_tools()}

    assert names == READ_ONLY_MCP_TOOL_NAMES
    assert names == {
        "search_shops",
        "get_shop_detail",
        "get_shop_evidence",
        "get_available_vouchers",
        "calculate_route",
        "validate_itinerary",
    }
    assert "favorite_shop" not in names
    assert "claim_standard_voucher" not in names
    assert "seckill_voucher" not in names


async def test_mcp_domain_service_reuses_runtime_search_rag_route_and_verifier():
    runtime = await AgentRuntime.create(Settings(adapter="mock", rag_adapter="memory"))
    service = McpDomainService(runtime)
    try:
        search = await service.search_shops(
            query="Quiet dinner in Midtown",
            category="Food & Dining",
            neighborhood="Midtown",
            desired_tags=["quiet"],
        )
        shop_ids = [candidate["shop_id"] for candidate in search["candidates"][:2]]

        detail = await service.get_shop_detail(shop_ids[0])
        evidence = await service.get_shop_evidence(
            shop_id=shop_ids[0],
            query="quiet dinner evidence",
            desired_tags=["quiet"],
        )
        route = await service.calculate_route(shop_ids=shop_ids, party_size=2)
        validation = await service.validate_itinerary(
            shop_ids=shop_ids[:1],
            query="Quiet dinner in Midtown",
            category="Food & Dining",
            neighborhood="Midtown",
            desired_tags=["quiet"],
        )

        assert detail["shop_id"] == shop_ids[0]
        assert evidence["evidence"][0]["citations"]
        assert [stop["shop_id"] for stop in route["stops"]] == shop_ids
        assert validation["verification"]["valid"] is True
    finally:
        await runtime.close()


async def test_mcp_api_key_middleware_is_optional_and_constant_time_checked():
    async def downstream(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"ok":true}'})

    protected_transport = httpx.ASGITransport(
        app=McpApiKeyMiddleware(downstream, "p5-secret")
    )
    async with httpx.AsyncClient(
        transport=protected_transport,
        base_url="http://test",
    ) as protected:
        assert (await protected.get("/")).status_code == 401
        assert (
            await protected.get("/", headers={"Authorization": "Bearer wrong"})
        ).status_code == 401
        assert (
            await protected.get("/", headers={"Authorization": "Bearer p5-secret"})
        ).status_code == 200

    unprotected_transport = httpx.ASGITransport(app=McpApiKeyMiddleware(downstream, ""))
    async with httpx.AsyncClient(
        transport=unprotected_transport,
        base_url="http://test",
    ) as unprotected:
        assert (await unprotected.get("/")).status_code == 200
