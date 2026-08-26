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
            "neighborhood": "Midtown-Times Square",
            "address": "17 Broadway, Manhattan, NY 10018",
            "description": "A fictional coffee shop.",
            "latitude": 40.7549,
            "longitude": -73.984,
            "avgPriceCents": 2400,
            "priceLevel": 2,
            "score": 4.7,
            "comments": 12,
            "localReviewCount": 12,
            "localScore": 4.6,
            "ratingCount": 214,
            "externalRatingCount": 214,
            "externalScore": 4.7,
            "priceRangeText": "$$",
            "phone": "+1 212 555 0100",
            "website": "https://fixture.example",
            "reservationUrl": "https://fixture.example/reserve",
            "businessStatus": "OPERATIONAL",
            "healthGrade": "A",
            "distanceMeters": 850,
            "timezone": "America/New_York",
            "sourceType": "NYC_OPEN_DATA",
            "externalId": "43nn-pn8j:123",
            "sourceName": "DOHMH New York City Restaurant Inspection Results",
            "sourceUrl": "https://data.cityofnewyork.us/d/43nn-pn8j",
            "sourceFetchedAt": "2026-08-23T14:25:30Z",
            "syntheticFields": ["reviews", "prices"],
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
    assert candidate.source_type == "NYC_OPEN_DATA"
    assert candidate.external_id == "43nn-pn8j:123"
    assert candidate.synthetic_fields == ["reviews", "prices"]
    assert candidate.rating_count == 214
    assert candidate.local_review_count == 12
    assert candidate.local_score == 4.6
    assert candidate.external_rating_count == 214
    assert candidate.external_score == 4.7
    assert candidate.price_range_text == "$$"
    assert candidate.website == "https://fixture.example"
    assert candidate.business_status == "OPERATIONAL"
    assert candidate.health_grade == "A"
    assert candidate.business_hours[0].day_of_week == 1
    assert candidate.tags == ["quiet", "wheelchair_accessible"]


def test_http_adapter_preserves_unknown_price_and_score_as_null():
    candidate = HttpShopToolService._to_candidate(
        {
            "shopId": 18,
            "name": "Real Unknown-Price Fixture",
            "category": "Beauty & Personal Care",
            "neighborhood": "Astoria",
            "latitude": 40.7644,
            "longitude": -73.9235,
            "avgPriceCents": None,
            "score": None,
            "sourceType": "OVERTURE",
            "dataVersion": "nyc-real-v1",
        }
    )

    assert candidate.avg_price_cents is None
    assert candidate.score is None


async def test_generated_adapter_marks_tag_relaxation_instead_of_returning_empty(tmp_path):
    shops = [
        {
            "id": 1,
            "name": "Vegan Fixture",
            "typeId": 1,
            "subcategoryId": 1,
            "neighborhood": "Midtown-Times Square",
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


async def test_generated_adapter_never_relaxes_wheelchair_accessibility(tmp_path):
    shops = [
        {
            "id": 1,
            "name": "Accessible Indoor Cafe",
            "typeId": 2,
            "subcategoryId": 1,
            "neighborhood": "Astoria",
            "borough": "Queens",
            "address": "1 Test Avenue",
            "description": "Fixture",
            "x": -73.92,
            "y": 40.76,
            "score": 45,
            "timezone": "America/New_York",
            "dataVersion": "test-v1",
            "tags": ["wheelchair_accessible"],
        },
        {
            "id": 2,
            "name": "Outdoor Stairs Cafe",
            "typeId": 2,
            "subcategoryId": 1,
            "neighborhood": "Astoria",
            "borough": "Queens",
            "address": "2 Test Avenue",
            "description": "Fixture",
            "x": -73.91,
            "y": 40.77,
            "score": 48,
            "timezone": "America/New_York",
            "dataVersion": "test-v1",
            "tags": ["outdoor_seating"],
        },
    ]
    (tmp_path / "shops.json").write_text(json.dumps(shops), encoding="utf-8")
    service = GeneratedNycShopToolService(tmp_path, max_candidates=10)

    result = await service.search(
        UserConstraints(
            query="Wheelchair-accessible cafes in Astoria with outdoor seating",
            category="Cafes & Desserts",
            neighborhood="Astoria",
            desired_tags=["wheelchair_accessible", "outdoor_seating"],
        )
    )

    assert [candidate.shop_id for candidate in result.candidates] == [1]
    assert result.relaxed_constraints == ["desired_tags"]
    assert result.retrieval_metadata["hardDesiredTags"] == ["wheelchair_accessible"]
