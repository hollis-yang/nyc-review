import json

import httpx

from app.domain.models import AgentRunCreateRequest
from app.model_gateway import HeuristicModelGateway, OpenAICompatibleModelGateway


async def test_heuristic_gateway_extracts_natural_language_constraints():
    extraction = await HeuristicModelGateway().extract_constraints(
        AgentRunCreateRequest(
            query="Quiet vegan dinner in Midtown for 2 under $120",
        )
    )

    assert extraction.constraints.category == "Food & Dining"
    assert extraction.constraints.neighborhood == "Midtown"
    assert extraction.constraints.party_size == 2
    assert extraction.constraints.budget_cents == 12_000
    assert extraction.constraints.desired_tags == ["quiet", "vegan_options"]
    assert extraction.provider == "heuristic"


async def test_model_gateway_uses_controlled_fallback_when_api_is_unavailable(monkeypatch):
    async def fail_post(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail_post)
    gateway = OpenAICompatibleModelGateway(
        provider="deepseek",
        base_url="https://api.deepseek.com/v1",
        api_key="test-key",
        model="deepseek-chat",
        fallback=HeuristicModelGateway(),
    )

    extraction = await gateway.extract_constraints(
        AgentRunCreateRequest(query="An accessible cafe in Chelsea")
    )

    assert extraction.fallback_used is True
    assert extraction.provider == "heuristic"
    assert extraction.constraints.category == "Cafes & Desserts"
    assert extraction.constraints.neighborhood == "Chelsea"
    assert "wheelchair_accessible" in extraction.constraints.desired_tags


async def test_model_gateway_preserves_explicit_user_hints(monkeypatch):
    captured_request_body = {}
    response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "query": "ignored",
                                "category": "Food & Dining",
                                "party_size": 1,
                                "desired_tags": ["quiet"],
                            }
                        )
                    }
                }
            ]
        },
    )

    async def fake_post(*args, **kwargs):
        captured_request_body.update(kwargs["json"])
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    extraction = await OpenAICompatibleModelGateway(
        provider="deepseek",
        base_url="https://api.deepseek.com/v1",
        api_key="test-key",
        model="deepseek-chat",
    ).extract_constraints(
        AgentRunCreateRequest(
            query="Find somewhere for us",
            category="Bars & Nightlife",
            party_size=4,
            desired_tags=["late_night"],
        )
    )

    assert extraction.provider == "deepseek"
    assert "max_tokens" not in captured_request_body
    assert extraction.constraints.query == "Find somewhere for us"
    assert extraction.constraints.category == "Bars & Nightlife"
    assert extraction.constraints.party_size == 4
    assert extraction.constraints.desired_tags == ["late_night", "quiet"]


async def test_model_gateway_normalizes_model_tag_aliases(monkeypatch):
    response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "query": "ignored",
                                "party_size": 2,
                                "desired_tags": ["vegan", "accessible", "outdoor"],
                            }
                        )
                    }
                }
            ]
        },
    )

    async def fake_post(*args, **kwargs):
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    extraction = await OpenAICompatibleModelGateway(
        provider="deepseek",
        base_url="https://api.deepseek.com/v1",
        api_key="test-key",
        model="deepseek-chat",
    ).extract_constraints(AgentRunCreateRequest(query="Vegan and accessible outdoor dinner"))

    assert extraction.constraints.desired_tags == [
        "outdoor_seating",
        "vegan_options",
        "wheelchair_accessible",
    ]
