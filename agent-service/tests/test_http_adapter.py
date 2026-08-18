from app.tools.services import HttpShopToolService


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
