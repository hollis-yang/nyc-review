from __future__ import annotations

import hmac
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings as FastMcpSettings
from starlette.types import ASGIApp, Receive, Scope, Send

from app.domain.models import ToolRisk
from app.mcp.service import McpDomainService
from app.runtime import AgentRuntime
from app.tools.catalog import TOOL_POLICIES

READ_ONLY_MCP_TOOL_NAMES = frozenset(
    name for name, policy in TOOL_POLICIES.items() if policy.risk == ToolRisk.READ_ONLY
)

# mcp 1.27 leaves the generic lifespan annotation unresolved on Python 3.13.
# Rebuilding once before FastMCP constructs its settings removes the startup
# warning and lets pydantic-settings validate environment sources normally.
FastMcpSettings.model_rebuild()

mcp = FastMCP(
    name="HMDP NYC Read-Only",
    instructions=(
        "Read-only NYC local-life tools backed by the same Spring, RAG, route and verification "
        "services as AI Guide. Merchant identities carry traceable real-data provenance; seeded "
        "reviews are explicitly synthetic and must never be presented as real customer testimony. "
        "Never claim, favorite, save or purchase on a user's behalf."
    ),
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)

_domain_service: McpDomainService | None = None


def bind_runtime(runtime: AgentRuntime) -> None:
    global _domain_service
    _domain_service = McpDomainService(runtime)


def unbind_runtime() -> None:
    global _domain_service
    _domain_service = None


def _service() -> McpDomainService:
    if _domain_service is None:
        raise RuntimeError("MCP domain service is not ready.")
    return _domain_service


@mcp.tool(name="search_shops")
async def search_shops(
    query: str,
    category: str | None = None,
    neighborhood: str | None = None,
    party_size: int = 1,
    budget_cents: int | None = None,
    desired_tags: list[str] | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    visit_time: str | None = None,
) -> dict[str, Any]:
    """Search typed NYC shops with provenance; unknown source-backed fields remain null."""
    return await _service().search_shops(
        query=query,
        category=category,
        neighborhood=neighborhood,
        party_size=party_size,
        budget_cents=budget_cents,
        desired_tags=desired_tags,
        latitude=latitude,
        longitude=longitude,
        visit_time=visit_time,
    )


@mcp.tool(name="get_shop_detail")
async def get_shop_detail(shop_id: int) -> dict[str, Any]:
    """Get one real shop profile; unverified price, tags or business hours can be null or empty."""
    return await _service().get_shop_detail(shop_id)


@mcp.tool(name="get_shop_evidence")
async def get_shop_evidence(
    shop_id: int,
    query: str,
    desired_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Retrieve cited RAG evidence; synthetic review threads are flagged and remain untrusted."""
    return await _service().get_shop_evidence(
        shop_id=shop_id,
        query=query,
        desired_tags=desired_tags,
    )


@mcp.tool(name="get_available_vouchers")
async def get_available_vouchers(shop_id: int) -> dict[str, Any]:
    """List HMDP demo vouchers without claiming or purchasing any voucher."""
    return await _service().get_available_vouchers(shop_id)


@mcp.tool(name="calculate_route")
async def calculate_route(
    shop_ids: list[int],
    latitude: float = 40.7614,
    longitude: float = -73.9776,
    party_size: int = 1,
) -> dict[str, Any]:
    """Calculate read-only routes; cost is null when no source-backed price is available."""
    return await _service().calculate_route(
        shop_ids=shop_ids,
        latitude=latitude,
        longitude=longitude,
        party_size=party_size,
    )


@mcp.tool(name="validate_itinerary")
async def validate_itinerary(
    shop_ids: list[int],
    query: str,
    category: str | None = None,
    neighborhood: str | None = None,
    party_size: int = 1,
    budget_cents: int | None = None,
    desired_tags: list[str] | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    visit_time: str | None = None,
) -> dict[str, Any]:
    """Verify an itinerary against evidence, hours, budget, category, area and desired tags."""
    return await _service().validate_itinerary(
        shop_ids=shop_ids,
        query=query,
        category=category,
        neighborhood=neighborhood,
        party_size=party_size,
        budget_cents=budget_cents,
        desired_tags=desired_tags,
        latitude=latitude,
        longitude=longitude,
        visit_time=visit_time,
    )


class McpApiKeyMiddleware:
    """Optional local service-key gate for Streamable HTTP MCP deployments."""

    def __init__(self, app: ASGIApp, api_key: str):
        self._app = app
        self._api_key = api_key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._api_key or scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self._app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        provided = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
        expected = f"Bearer {self._api_key}"
        if hmac.compare_digest(provided, expected):
            await self._app(scope, receive, send)
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"error":"Unauthorized MCP client"}',
            }
        )
