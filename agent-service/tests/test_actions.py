from app.actions.service import AgentActionService, InMemoryActionGateway
from app.domain.models import (
    AgentMode,
    AgentRunResponse,
    CandidateSet,
    EvidencePack,
    ItineraryDraft,
    RunStatus,
    ShopCandidate,
    VerificationReport,
)


class VoucherGateway(InMemoryActionGateway):
    async def available_vouchers(self, shop_id: int, authorization: str) -> list[dict]:
        return [
            {"id": shop_id * 10, "type": 0},
            {"id": shop_id * 10 + 1, "type": 1, "beginTime": "2026-09-01T12:00:00"},
        ]


async def test_actions_include_vouchers_for_every_recommended_shop():
    candidates = [
        ShopCandidate(
            shop_id=shop_id,
            name=f"Shop {shop_id}",
            category="Food & Dining",
            neighborhood="Midtown",
            latitude=40.75,
            longitude=-73.98,
        )
        for shop_id in (11, 22)
    ]
    response = AgentRunResponse(
        mode=AgentMode.MULTI,
        status=RunStatus.WAITING_CONFIRMATION,
        candidates=CandidateSet(candidates=candidates),
        evidence=EvidencePack(evidence=[]),
        itinerary=ItineraryDraft(stops=[]),
        verification=VerificationReport(valid=True),
        summary="Two recommendations",
    )

    actions = await AgentActionService(VoucherGateway()).propose("run-1", response, "token")

    favorites = [action for action in actions if action.action_type.value == "favorite_shop"]
    claims = [action for action in actions if action.action_type.value == "claim_standard_voucher"]
    reminders = [
        action for action in actions if action.action_type.value == "create_seckill_reminder"
    ]
    assert {action.payload["shopId"] for action in favorites} == {11, 22}
    assert {action.payload["shopId"] for action in claims} == {11, 22}
    assert {action.payload["shopId"] for action in reminders} == {11, 22}
