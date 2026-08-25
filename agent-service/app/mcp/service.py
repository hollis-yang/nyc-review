from __future__ import annotations

import asyncio
from typing import Any

from app.agents.nodes import VerifierAgent
from app.domain.models import CandidateSet, UserConstraints
from app.runtime import AgentRuntime


class McpDomainService:
    """Thin read-only facade over the same services used by the Agent workflow."""

    def __init__(self, runtime: AgentRuntime):
        if runtime.shop_service is None or runtime.rag_service is None:
            raise RuntimeError("Agent runtime does not have domain services.")
        self._runtime = runtime

    async def search_shops(
        self,
        *,
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
        constraints = self._constraints(
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
        candidate_pool = await self._runtime.shop_service.search(constraints)
        final_limit = self._runtime.settings.max_candidates if self._runtime.settings else 5
        candidates = await self._runtime.rag_service.rank_candidates(
            constraints,
            candidate_pool,
            limit=final_limit,
        )
        return candidates.model_dump(mode="json")

    async def get_shop_detail(self, shop_id: int) -> dict[str, Any]:
        self._validate_shop_id(shop_id)
        candidate = await self._runtime.shop_service.detail(shop_id)
        if candidate is None:
            raise ValueError(f"Shop {shop_id} was not found.")
        return candidate.model_dump(mode="json")

    async def get_shop_evidence(
        self,
        *,
        shop_id: int,
        query: str,
        desired_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        candidate = await self._required_candidate(shop_id)
        constraints = self._constraints(query=query, desired_tags=desired_tags)
        evidence = await self._runtime.rag_service.retrieve(
            constraints,
            CandidateSet(candidates=[candidate]),
        )
        return evidence.model_dump(mode="json")

    async def get_available_vouchers(self, shop_id: int) -> dict[str, Any]:
        self._validate_shop_id(shop_id)
        action_service = self._runtime.action_service
        vouchers = [] if action_service is None else await action_service.available_vouchers(shop_id)
        return {"shop_id": shop_id, "vouchers": vouchers}

    async def calculate_route(
        self,
        *,
        shop_ids: list[int],
        latitude: float = 40.7614,
        longitude: float = -73.9776,
        party_size: int = 1,
    ) -> dict[str, Any]:
        constraints = self._constraints(
            query="Calculate a route for the selected NYC shops.",
            latitude=latitude,
            longitude=longitude,
            party_size=party_size,
        )
        candidates = await self._candidate_set(shop_ids)
        itinerary = await self._runtime.itinerary_service.plan(constraints, candidates)
        return itinerary.model_dump(mode="json")

    async def validate_itinerary(
        self,
        *,
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
        constraints = self._constraints(
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
        candidates = await self._candidate_set(shop_ids)
        evidence, itinerary = await asyncio.gather(
            self._runtime.rag_service.retrieve(constraints, candidates),
            self._runtime.itinerary_service.plan(constraints, candidates),
        )
        update = await VerifierAgent().run(
            {
                "constraints": constraints,
                "candidates": candidates,
                "evidence": evidence,
                "itinerary": itinerary,
            }
        )
        return {
            "verification": update["verification"].model_dump(mode="json"),
            "itinerary": itinerary.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
        }

    async def _candidate_set(self, shop_ids: list[int]) -> CandidateSet:
        unique_ids = list(dict.fromkeys(shop_ids))
        if not unique_ids:
            raise ValueError("shop_ids must contain at least one shop ID.")
        if len(unique_ids) > 20:
            raise ValueError("shop_ids cannot contain more than 20 unique shop IDs.")
        for shop_id in unique_ids:
            self._validate_shop_id(shop_id)
        candidates = await asyncio.gather(
            *(self._runtime.shop_service.detail(shop_id) for shop_id in unique_ids)
        )
        missing = [
            shop_id
            for shop_id, candidate in zip(unique_ids, candidates, strict=True)
            if candidate is None
        ]
        if missing:
            raise ValueError("Unknown shop IDs: " + ", ".join(map(str, missing)))
        return CandidateSet(candidates=[candidate for candidate in candidates if candidate is not None])

    async def _required_candidate(self, shop_id: int):
        self._validate_shop_id(shop_id)
        candidate = await self._runtime.shop_service.detail(shop_id)
        if candidate is None:
            raise ValueError(f"Shop {shop_id} was not found.")
        return candidate

    @staticmethod
    def _validate_shop_id(shop_id: int) -> None:
        if shop_id <= 0:
            raise ValueError("shop_id must be a positive integer.")

    @staticmethod
    def _constraints(
        *,
        query: str,
        category: str | None = None,
        neighborhood: str | None = None,
        party_size: int = 1,
        budget_cents: int | None = None,
        desired_tags: list[str] | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        visit_time: str | None = None,
    ) -> UserConstraints:
        return UserConstraints(
            query=query,
            category=category,
            neighborhood=neighborhood,
            party_size=party_size,
            budget_cents=budget_cents,
            desired_tags=desired_tags or [],
            latitude=latitude,
            longitude=longitude,
            visit_time=visit_time,
        )
