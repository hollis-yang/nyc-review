from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Protocol

import httpx

from app.domain.models import (
    BusinessHours,
    CandidateSet,
    EvidenceCitation,
    EvidencePack,
    ItineraryDraft,
    ItineraryStop,
    ShopCandidate,
    ShopEvidence,
    UserConstraints,
)
from app.request_context import request_authorization


class ShopToolService(Protocol):
    async def search(self, constraints: UserConstraints) -> CandidateSet: ...

    async def detail(self, shop_id: int) -> ShopCandidate | None: ...


class RagService(Protocol):
    async def retrieve(self, constraints: UserConstraints, candidates: CandidateSet) -> EvidencePack: ...


class ItineraryService(Protocol):
    async def plan(self, constraints: UserConstraints, candidates: CandidateSet) -> ItineraryDraft: ...


class MockShopToolService:
    """Development adapter used until the typed Spring Boot tool API is available."""

    async def search(self, constraints: UserConstraints) -> CandidateSet:
        base_lat = constraints.latitude or 40.7614
        base_lng = constraints.longitude or -73.9776
        desired = set(constraints.desired_tags)
        fixtures = [
            ShopCandidate(
                shop_id=101,
                name="Mock Mercer Table",
                category=constraints.category or "Food & Dining",
                neighborhood=constraints.neighborhood or "Midtown",
                latitude=base_lat + 0.002,
                longitude=base_lng - 0.001,
                avg_price_cents=4200,
                score=4.7,
                tags=sorted(desired | {"quiet", "vegan_options", "wheelchair_accessible"}),
            ),
            ShopCandidate(
                shop_id=102,
                name="Mock Hudson Kitchen",
                category=constraints.category or "Food & Dining",
                neighborhood=constraints.neighborhood or "Midtown",
                latitude=base_lat - 0.003,
                longitude=base_lng + 0.002,
                avg_price_cents=3600,
                score=4.5,
                tags=sorted(desired | {"good_for_groups", "vegan_options"}),
            ),
            ShopCandidate(
                shop_id=103,
                name="Mock Broadway Bistro",
                category=constraints.category or "Food & Dining",
                neighborhood=constraints.neighborhood or "Midtown",
                latitude=base_lat + 0.004,
                longitude=base_lng + 0.003,
                avg_price_cents=5500,
                score=4.8,
                tags=sorted(desired | {"date_night", "quiet"}),
            ),
        ]
        if constraints.budget_cents is not None:
            per_person = constraints.budget_cents // constraints.party_size
            fixtures = [shop for shop in fixtures if shop.avg_price_cents <= per_person]
        return CandidateSet(
            candidates=fixtures,
            applied_constraints=["category", "location", "budget", "desired_tags"],
            warnings=[] if fixtures else ["No mock candidates matched every hard constraint."],
        )

    async def detail(self, shop_id: int) -> ShopCandidate | None:
        candidates = await self.search(UserConstraints(query="shop detail"))
        return next(
            (candidate for candidate in candidates.candidates if candidate.shop_id == shop_id),
            None,
        )


class GeneratedNycShopToolService:
    """Read-only business-tool adapter over a generated NYC dataset."""

    CATEGORY_NAMES = {
        1: "Food & Dining",
        2: "Cafes & Desserts",
        3: "Bars & Nightlife",
        4: "Entertainment & Attractions",
        5: "Fitness & Wellness",
        6: "Beauty & Personal Care",
    }

    def __init__(self, data_directory: Path, max_candidates: int = 5):
        with (data_directory / "shops.json").open(encoding="utf-8") as handle:
            shops = json.load(handle)
        if not isinstance(shops, list):
            raise ValueError("Generated shops.json must contain a list.")
        self._shops: list[dict] = shops
        self._max_candidates = max_candidates
        hours_path = data_directory / "shop_business_hours.json"
        subcategories_path = data_directory / "shop_subcategories.json"
        self._hours_by_shop: dict[int, list[dict]] = {}
        if hours_path.is_file():
            with hours_path.open(encoding="utf-8") as handle:
                for item in json.load(handle):
                    self._hours_by_shop.setdefault(item["shopId"], []).append(item)
        self._subcategories: dict[int, dict] = {}
        if subcategories_path.is_file():
            with subcategories_path.open(encoding="utf-8") as handle:
                self._subcategories = {item["id"]: item for item in json.load(handle)}

    async def search(self, constraints: UserConstraints) -> CandidateSet:
        per_person_budget = (
            constraints.budget_cents // constraints.party_size
            if constraints.budget_cents is not None
            else None
        )
        required_tags = set(constraints.desired_tags)
        rows = []
        for shop in self._shops:
            category = self.CATEGORY_NAMES[shop["typeId"]]
            if constraints.category and category != constraints.category:
                continue
            if constraints.neighborhood and shop["neighborhood"] != constraints.neighborhood:
                continue
            if per_person_budget is not None and shop["avgPriceCents"] > per_person_budget:
                continue
            shop_tags = set(shop.get("tags") or [])
            tag_matches = len(required_tags.intersection(shop_tags))
            distance = (
                haversine_meters(
                    constraints.latitude,
                    constraints.longitude,
                    shop["y"],
                    shop["x"],
                )
                if constraints.latitude is not None and constraints.longitude is not None
                else None
            )
            rows.append((shop, category, distance, tag_matches, required_tags <= shop_tags))
        strict_rows = [row for row in rows if row[4]]
        relaxed_constraints: list[str] = []
        warnings: list[str] = []
        if required_tags and not strict_rows and rows:
            selected_rows = rows
            relaxed_constraints = ["desired_tags"]
            warnings = [
                "No shop matched every requested tag. Showing the closest alternatives for review."
            ]
        else:
            selected_rows = strict_rows if required_tags else rows
        selected_rows.sort(
            key=lambda item: (
                -item[3],
                item[2] if item[2] is not None else 0,
                -item[0]["score"],
            )
        )
        candidates = [
            self._to_candidate(shop, category, distance)
            for shop, category, distance, _, _ in selected_rows[: self._max_candidates]
        ]
        return CandidateSet(
            candidates=candidates,
            applied_constraints=["category", "neighborhood", "budget", "desired_tags"],
            relaxed_constraints=relaxed_constraints,
            warnings=(
                warnings
                if warnings
                else ([] if candidates else ["No generated NYC shops matched every hard constraint."])
            ),
        )

    async def detail(self, shop_id: int) -> ShopCandidate | None:
        shop = next((item for item in self._shops if item["id"] == shop_id), None)
        if shop is None:
            return None
        return self._to_candidate(shop, self.CATEGORY_NAMES[shop["typeId"]], None)

    def _to_candidate(
        self,
        shop: dict,
        category: str,
        distance_meters: int | None,
    ) -> ShopCandidate:
        return ShopCandidate(
            shop_id=shop["id"],
            name=shop["name"],
            category=category,
            neighborhood=shop["neighborhood"],
            latitude=shop["y"],
            longitude=shop["x"],
            avg_price_cents=shop["avgPriceCents"],
            score=shop["score"] / 10,
            tags=shop.get("tags") or [],
            source="nyc-generated",
            subcategory_id=shop.get("subcategoryId"),
            subcategory=(self._subcategories.get(shop.get("subcategoryId")) or {}).get("name"),
            borough=shop.get("borough"),
            address=shop.get("address"),
            description=shop.get("description"),
            price_level=shop.get("priceLevel"),
            comments=shop.get("comments"),
            distance_meters=distance_meters,
            timezone=shop.get("timezone"),
            data_version=shop.get("dataVersion"),
            business_hours=[
                BusinessHours(
                    day_of_week=item["dayOfWeek"],
                    closed=item["closed"],
                    open_time=item.get("openTime"),
                    close_time=item.get("closeTime"),
                    closes_next_day=item.get("closesNextDay", False),
                )
                for item in self._hours_by_shop.get(shop["id"], [])
            ],
        )


class HttpShopToolService:
    """Typed adapter for Spring Boot's restricted Agent Tool API."""

    CATEGORY_IDS = {
        "Food & Dining": 1,
        "Cafes & Desserts": 2,
        "Bars & Nightlife": 3,
        "Entertainment & Attractions": 4,
        "Fitness & Wellness": 5,
        "Beauty & Personal Care": 6,
    }

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 8.0,
        auth_token: str = "",
        max_candidates: int = 5,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._auth_token = auth_token
        self._max_candidates = max_candidates

    async def search(self, constraints: UserConstraints) -> CandidateSet:
        authorization = request_authorization.get() or self._auth_token
        headers = {"authorization": authorization} if authorization else {}
        payload = {
            # Natural language belongs to the Agent/RAG layer, not a literal shop-name LIKE filter.
            "query": None,
            "typeId": self.CATEGORY_IDS.get(constraints.category or ""),
            "neighborhood": constraints.neighborhood,
            "maxAvgPriceCents": (
                constraints.budget_cents // constraints.party_size
                if constraints.budget_cents is not None
                else None
            ),
            "latitude": constraints.latitude,
            "longitude": constraints.longitude,
            "requiredTags": constraints.desired_tags,
            "limit": self._max_candidates,
        }
        body = await self._post_search(payload, headers)
        candidates = [self._to_candidate(item) for item in body.get("data") or []]
        relaxed_constraints: list[str] = []
        warnings = list(body.get("warnings") or [])
        if not candidates and constraints.desired_tags:
            relaxed_payload = {**payload, "requiredTags": []}
            relaxed_body = await self._post_search(relaxed_payload, headers)
            candidates = [self._to_candidate(item) for item in relaxed_body.get("data") or []]
            if candidates:
                relaxed_constraints = ["desired_tags"]
                warnings.append(
                    "No shop matched every requested tag. Showing the closest alternatives for review."
                )
        applied = []
        for name, value in (
            ("category", constraints.category),
            ("neighborhood", constraints.neighborhood),
            ("budget", constraints.budget_cents),
            ("desired_tags", constraints.desired_tags),
        ):
            if value:
                applied.append(name)
        return CandidateSet(
            candidates=candidates,
            applied_constraints=applied,
            relaxed_constraints=relaxed_constraints,
            warnings=warnings,
        )

    async def detail(self, shop_id: int) -> ShopCandidate | None:
        authorization = request_authorization.get() or self._auth_token
        headers = {"authorization": authorization} if authorization else {}
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(
                f"{self._base_url}/internal/agent/tools/shops/{shop_id}",
                headers=headers,
            )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        item = response.json().get("data")
        return self._to_candidate(item) if isinstance(item, dict) else None

    async def _post_search(self, payload: dict, headers: dict[str, str]) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = None
            for attempt in range(2):
                try:
                    response = await client.post(
                        f"{self._base_url}/internal/agent/tools/shops/search",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    break
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == 1:
                        raise
            if response is None:
                raise RuntimeError("Shop tool did not return a response.")
        return response.json()

    @staticmethod
    def _to_candidate(item: dict) -> ShopCandidate:
        return ShopCandidate(
            shop_id=item["shopId"],
            name=item["name"],
            category=item.get("category") or "Unknown",
            neighborhood=item.get("neighborhood") or "Unknown",
            latitude=item["latitude"],
            longitude=item["longitude"],
            avg_price_cents=item.get("avgPriceCents") or 0,
            score=item.get("score") or 0,
            tags=item.get("tags") or [],
            source="hmdp-spring",
            subcategory_id=item.get("subcategoryId"),
            subcategory=item.get("subcategory"),
            borough=item.get("borough"),
            address=item.get("address"),
            description=item.get("description"),
            price_level=item.get("priceLevel"),
            comments=item.get("comments"),
            distance_meters=item.get("distanceMeters"),
            timezone=item.get("timezone"),
            data_version=item.get("dataVersion"),
            business_hours=[
                BusinessHours(
                    day_of_week=hours["dayOfWeek"],
                    closed=hours.get("closed", False),
                    open_time=hours.get("openTime"),
                    close_time=hours.get("closeTime"),
                    closes_next_day=hours.get("closesNextDay", False),
                )
                for hours in item.get("businessHours") or []
            ],
        )


class InMemoryRagService:
    """RAG contract adapter with explicit untrusted citations for workflow tests."""

    async def retrieve(self, constraints: UserConstraints, candidates: CandidateSet) -> EvidencePack:
        evidence = []
        for candidate in candidates.candidates:
            supported_tags = sorted(set(constraints.desired_tags) & set(candidate.tags))
            excerpt_tags = ", ".join(tag.replace("_", " ") for tag in supported_tags) or "overall experience"
            evidence.append(
                ShopEvidence(
                    shop_id=candidate.shop_id,
                    supported_tags=supported_tags,
                    citations=[
                        EvidenceCitation(
                            citation_id=f"mock-review-{candidate.shop_id}",
                            shop_id=candidate.shop_id,
                            content_type="shop_review",
                            excerpt=f"Mock first-party review evidence mentions {excerpt_tags}.",
                            source_id=f"review:{candidate.shop_id}",
                            created_at="2026-08-01T12:00:00Z",
                            untrusted_content=True,
                        )
                    ],
                )
            )
        return EvidencePack(evidence=evidence)


class HaversineItineraryService:
    async def plan(self, constraints: UserConstraints, candidates: CandidateSet) -> ItineraryDraft:
        origin_lat = constraints.latitude or 40.7614
        origin_lng = constraints.longitude or -73.9776
        stops = []
        for sequence, candidate in enumerate(candidates.candidates, start=1):
            distance = haversine_meters(origin_lat, origin_lng, candidate.latitude, candidate.longitude)
            stops.append(
                ItineraryStop(
                    shop_id=candidate.shop_id,
                    sequence=sequence,
                    estimated_cost_cents=candidate.avg_price_cents * constraints.party_size,
                    distance_meters=distance,
                )
            )
        total = min((stop.estimated_cost_cents for stop in stops), default=0)
        return ItineraryDraft(
            stops=stops,
            total_estimated_cost_cents=total,
            warnings=[] if stops else ["No itinerary could be produced."],
        )


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    earth_radius = 6_371_000
    first_latitude = math.radians(lat1)
    second_latitude = math.radians(lat2)
    latitude_delta = math.radians(lat2 - lat1)
    longitude_delta = math.radians(lng2 - lng1)
    value = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(first_latitude) * math.cos(second_latitude) * math.sin(longitude_delta / 2) ** 2
    )
    return round(earth_radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value)))
