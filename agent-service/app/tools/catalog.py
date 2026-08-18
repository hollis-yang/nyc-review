from dataclasses import dataclass

from app.domain.models import ToolRisk


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    risk: ToolRisk
    exposed_to_model: bool
    requires_confirmation: bool
    idempotent: bool


TOOL_POLICIES = {
    policy.name: policy
    for policy in (
        ToolPolicy("search_shops", ToolRisk.READ_ONLY, True, False, True),
        ToolPolicy("get_shop_detail", ToolRisk.READ_ONLY, True, False, True),
        ToolPolicy("get_shop_evidence", ToolRisk.READ_ONLY, True, False, True),
        ToolPolicy("get_available_vouchers", ToolRisk.READ_ONLY, True, False, True),
        ToolPolicy("calculate_route", ToolRisk.READ_ONLY, True, False, True),
        ToolPolicy("validate_itinerary", ToolRisk.READ_ONLY, True, False, True),
        ToolPolicy("favorite_shop", ToolRisk.REVERSIBLE_WRITE, True, True, True),
        ToolPolicy("save_itinerary", ToolRisk.REVERSIBLE_WRITE, True, True, True),
        ToolPolicy("claim_standard_voucher", ToolRisk.LIMITED_WRITE, True, True, True),
        ToolPolicy("create_seckill_reminder", ToolRisk.REVERSIBLE_WRITE, True, True, True),
        ToolPolicy("seckill_voucher", ToolRisk.MANUAL_ONLY, False, True, False),
    )
}


MODEL_TOOL_NAMES = frozenset(name for name, policy in TOOL_POLICIES.items() if policy.exposed_to_model)


def require_model_tool(name: str) -> ToolPolicy:
    policy = TOOL_POLICIES.get(name)
    if policy is None or not policy.exposed_to_model:
        raise PermissionError(f"Tool is not available to models: {name}")
    return policy
