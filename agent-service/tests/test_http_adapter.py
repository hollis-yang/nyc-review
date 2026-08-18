import json

from app.domain.models import UserConstraints
from app.tools.services import GeneratedNycShopToolService, HttpShopToolService


def test_http_adapter_preserves_spring_nyc_enrichment_and_data_version():
    candidate = HttpShopToolService._to_candidate(
        {
            "shopId": 17,
            "name": "Fixture Cafe",
            "category": "Cafes & Desserts",
            "subcategoryId": 7,
            "subcategory": "Coffee Shop",
            "borough": "Manhattan",
            "neighborhood": "Midtown",
            "address": "17 Broadway, Manhattan, NY 10018",
            "description": "A fictional coffee shop.",
            "latitude": 40.7549,
            "longitude": -73.984,
            "avgPriceCents": 2400,
            "priceLevel": 2,
            "score": 4.7,
            "comments": 12,
            "distanceMeters": 850,
            "timezone": "America/New_York",
            "dataVersion": "nyc-mock-v1",
            "tags": ["quiet", "wheelchair_accessible"],
            "businessHours": [
                {
                    "dayOfWeek": 1,
                    "closed": False,
                    "openTime": "07:00:00",
                    "closeTime": "19:00:00",
                    "closesNextDay": False,
                }
            ],
        }
    )

    assert candidate.shop_id == 17
    assert candidate.subcategory == "Coffee Shop"
    assert candidate.borough == "Manhattan"
    assert candidate.data_version == "nyc-mock-v1"
    assert candidate.business_hours[0].day_of_week == 1
    assert candidate.tags == ["quiet", "wheelchair_accessible"]


async def test_generated_adapter_marks_tag_relaxation_instead_of_returning_empty(tmp_path):
    shops = [
        {
            "id": 1,
            "name": "Vegan Fixture",
            "typeId": 1,
            "subcategoryId": 1,
            "neighborhood": "Midtown",
            "borough": "Manhattan",
            "address": "1 Broadway",
            "description": "Fixture",
            "x": -73.98,
            "y": 40.75,
            "avgPriceCents": 4_000,
            "priceLevel": 2,
            "score": 45,
            "comments": 2,
            "timezone": "America/New_York",
            "dataVersion": "test-v1",
            "tags": ["vegan_options"],
        },
        {
            "id": 2,
            "name": "Quiet Fixture",
            "typeId": 1,
            "subcategoryId": 1,
            "neighborhood": "Midtown",
            "borough": "Manhattan",
            "address": "2 Broadway",
            "description": "Fixture",
            "x": -73.99,
            "y": 40.76,
            "avgPriceCents": 4_500,
            "priceLevel": 2,
            "score": 44,
            "comments": 2,
            "timezone": "America/New_York",
            "dataVersion": "test-v1",
            "tags": ["quiet"],
        },
    ]
    (tmp_path / "shops.json").write_text(json.dumps(shops), encoding="utf-8")
    service = GeneratedNycShopToolService(tmp_path)

    result = await service.search(
        UserConstraints(
            query="Quiet vegan dinner in Midtown",
            category="Food & Dining",
            neighborhood="Midtown",
            desired_tags=["quiet", "vegan_options"],
        )
    )

    assert len(result.candidates) == 2
    assert result.relaxed_constraints == ["desired_tags"]
    assert "closest alternatives" in result.warnings[0]
