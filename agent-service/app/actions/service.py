from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.domain.models import (
    AgentActionProposal,
    AgentActionType,
    AgentRunResponse,
)
from app.tools.catalog import require_model_tool


class ActionGateway(Protocol):
    async def preferences(self, authorization: str) -> dict[str, Any]: ...

    async def available_vouchers(self, shop_id: int, authorization: str) -> list[dict]: ...

    async def execute(
        self,
        run_id: str,
        action: AgentActionProposal,
        authorization: str,
    ) -> dict[str, Any]: ...


class InMemoryActionGateway:
    async def preferences(self, authorization: str) -> dict[str, Any]:
        return {}

    async def available_vouchers(self, shop_id: int, authorization: str) -> list[dict]:
        return []

    async def execute(
        self,
        run_id: str,
        action: AgentActionProposal,
        authorization: str,
    ) -> dict[str, Any]:
        return {
            "actionId": action.action_id,
            "actionType": action.action_type.value,
            "status": "completed",
            "adapter": "memory",
        }


class HttpActionGateway:
    def __init__(
        self,
        base_url: str,
        *,
        fallback_authorization: str = "",
    ):
        self._base_url = base_url.rstrip("/")
        self._fallback_authorization = fallback_authorization

    def _headers(self, authorization: str) -> dict[str, str]:
        value = authorization or self._fallback_authorization
        return {"authorization": value} if value else {}

    async def available_vouchers(self, shop_id: int, authorization: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.get(
                f"{self._base_url}/voucher/list/{shop_id}",
                headers=self._headers(authorization),
            )
            response.raise_for_status()
        body = response.json()
        return list(body.get("data") or []) if body.get("success", True) else []

    async def preferences(self, authorization: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.get(
                f"{self._base_url}/internal/agent/actions/preferences",
                headers=self._headers(authorization),
            )
            response.raise_for_status()
        body = response.json()
        data = body.get("data") if body.get("success", False) else None
        return data if isinstance(data, dict) else {}

    async def execute(
        self,
        run_id: str,
        action: AgentActionProposal,
        authorization: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                f"{self._base_url}/internal/agent/actions/execute",
                headers=self._headers(authorization),
                json={
                    "runId": run_id,
                    "actionId": action.action_id,
                    "actionType": action.action_type.value,
                    "payload": action.payload,
                },
            )
            response.raise_for_status()
        body = response.json()
        if not body.get("success", False):
            raise RuntimeError(body.get("errorMsg") or "Spring rejected the approved action.")
        data = body.get("data")
        return data if isinstance(data, dict) else {"value": data}


class AgentActionService:
    def __init__(self, gateway: ActionGateway):
        self._gateway = gateway

    async def preferences(self, authorization: str) -> dict[str, Any]:
        if not authorization:
            return {}
        try:
            return await self._gateway.preferences(authorization)
        except (httpx.HTTPError, RuntimeError, ValueError):
            return {}

    async def available_vouchers(self, shop_id: int, authorization: str = "") -> list[dict]:
        try:
            return await self._gateway.available_vouchers(shop_id, authorization)
        except (httpx.HTTPError, RuntimeError, ValueError):
            return []

    async def propose(
        self,
        run_id: str,
        result: AgentRunResponse,
        authorization: str,
    ) -> list[AgentActionProposal]:
        candidates = result.candidates.candidates
        if not candidates:
            return []

        first = candidates[0]
        proposals = [
            self._proposal(
                run_id,
                AgentActionType.FAVORITE_SHOP,
                str(candidate.shop_id),
                title=f"Favorite {candidate.name}",
                description="Add this shop to your saved places after confirmation.",
                payload={"shopId": candidate.shop_id, "shopName": candidate.name},
            )
            for candidate in candidates
        ]
        if result.itinerary.stops:
            proposals.append(
                self._proposal(
                    run_id,
                    AgentActionType.SAVE_ITINERARY,
                    "recommended",
                    title="Save this itinerary",
                    description="Keep the verified stops and estimates in your account.",
                    payload={
                        "title": "NYC AI Guide itinerary",
                        "shopIds": [stop.shop_id for stop in result.itinerary.stops],
                        "itinerary": result.itinerary.model_dump(mode="json"),
                    },
                )
            )

        try:
            vouchers = await self._gateway.available_vouchers(first.shop_id, authorization)
        except (httpx.HTTPError, RuntimeError, ValueError):
            vouchers = []
        standard = next((item for item in vouchers if int(item.get("type", -1)) == 0), None)
        seckill = next((item for item in vouchers if int(item.get("type", -1)) == 1), None)
        if standard and standard.get("id") is not None:
            proposals.append(
                self._proposal(
                    run_id,
                    AgentActionType.CLAIM_STANDARD_VOUCHER,
                    str(standard["id"]),
                    title="Claim the standard voucher",
                    description="Create a normal voucher order after you approve it.",
                    payload={
                        "shopId": first.shop_id,
                        "shopName": first.name,
                        "voucherId": int(standard["id"]),
                    },
                )
            )
        if seckill and seckill.get("id") is not None:
            payload: dict[str, Any] = {
                "shopId": first.shop_id,
                "shopName": first.name,
                "voucherId": int(seckill["id"]),
            }
            begin_time = seckill.get("beginTime")
            if begin_time:
                try:
                    payload["remindAt"] = (
                        datetime.fromisoformat(str(begin_time)) - timedelta(minutes=10)
                    ).isoformat()
                except ValueError:
                    pass
            proposals.append(
                self._proposal(
                    run_id,
                    AgentActionType.CREATE_SECKILL_REMINDER,
                    str(seckill["id"]),
                    title="Create a flash-sale reminder",
                    description="Save a reminder only. The flash-sale purchase stays manual.",
                    payload=payload,
                )
            )
        return proposals

    async def execute(
        self,
        run_id: str,
        action: AgentActionProposal,
        authorization: str,
    ) -> dict[str, Any]:
        policy = require_model_tool(action.action_type.value)
        if not policy.requires_confirmation:
            raise PermissionError("Write actions must require explicit user confirmation.")
        return await self._gateway.execute(run_id, action, authorization)

    @staticmethod
    def _proposal(
        run_id: str,
        action_type: AgentActionType,
        target: str,
        *,
        title: str,
        description: str,
        payload: dict[str, Any],
    ) -> AgentActionProposal:
        policy = require_model_tool(action_type.value)
        return AgentActionProposal(
            action_id=str(uuid5(NAMESPACE_URL, f"nyc-review:{run_id}:{action_type.value}:{target}")),
            action_type=action_type,
            title=title,
            description=description,
            risk=policy.risk,
            payload=payload,
        )
