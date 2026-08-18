import pytest

from app.domain.models import ToolRisk
from app.tools.catalog import MODEL_TOOL_NAMES, TOOL_POLICIES, require_model_tool


def test_manual_seckill_is_never_exposed_to_models():
    policy = TOOL_POLICIES["seckill_voucher"]

    assert policy.risk is ToolRisk.MANUAL_ONLY
    assert policy.exposed_to_model is False
    assert "seckill_voucher" not in MODEL_TOOL_NAMES
    with pytest.raises(PermissionError):
        require_model_tool("seckill_voucher")


def test_standard_voucher_claim_requires_confirmation():
    policy = require_model_tool("claim_standard_voucher")

    assert policy.requires_confirmation is True
    assert policy.idempotent is True
