from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentMode(StrEnum):
    SINGLE = "single"
    MULTI = "multi"


class RunStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    TOOL_RUNNING = "tool_running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolRisk(StrEnum):
    READ_ONLY = "read_only"
    REVERSIBLE_WRITE = "reversible_write"
    LIMITED_WRITE = "limited_write"
    MANUAL_ONLY = "manual_only"


class AgentActionType(StrEnum):
    FAVORITE_SHOP = "favorite_shop"
    SAVE_ITINERARY = "save_itinerary"
    CLAIM_STANDARD_VOUCHER = "claim_standard_voucher"
    CREATE_SECKILL_REMINDER = "create_seckill_reminder"


class AgentActionStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


class UserConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2_000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    neighborhood: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=80)
    party_size: int = Field(default=1, ge=1, le=50)
    budget_cents: int | None = Field(default=None, ge=0, le=10_000_000)
    desired_tags: list[str] = Field(default_factory=list, max_length=20)
    visit_time: str | None = None


class BusinessHours(BaseModel):
    day_of_week: int = Field(ge=1, le=7)
    closed: bool = False
    open_time: str | None = None
    close_time: str | None = None
    closes_next_day: bool = False


class ShopCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_id: int = Field(gt=0)
    name: str
    category: str
    neighborhood: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    avg_price_cents: int = Field(ge=0)
    score: float = Field(ge=0, le=5)
    tags: list[str] = Field(default_factory=list)
    source: str = "hmdp"
    subcategory_id: int | None = None
    subcategory: str | None = None
    borough: str | None = None
    address: str | None = None
    description: str | None = None
    price_level: int | None = Field(default=None, ge=1, le=4)
    comments: int | None = Field(default=None, ge=0)
    distance_meters: int | None = Field(default=None, ge=0)
    timezone: str | None = None
    data_version: str | None = None
    business_hours: list[BusinessHours] = Field(default_factory=list)


class CandidateSet(BaseModel):
    candidates: list[ShopCandidate]
    applied_constraints: list[str] = Field(default_factory=list)
    relaxed_constraints: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvidenceCitation(BaseModel):
    citation_id: str
    shop_id: int = Field(gt=0)
    content_type: str
    excerpt: str = Field(max_length=600)
    source_id: str
    created_at: str | None = None
    untrusted_content: bool = True


class ShopEvidence(BaseModel):
    shop_id: int = Field(gt=0)
    supported_tags: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    citations: list[EvidenceCitation] = Field(default_factory=list)


class EvidencePack(BaseModel):
    evidence: list[ShopEvidence]


class ItineraryStop(BaseModel):
    shop_id: int = Field(gt=0)
    sequence: int = Field(ge=1)
    estimated_cost_cents: int = Field(ge=0)
    distance_meters: int | None = Field(default=None, ge=0)


class ItineraryDraft(BaseModel):
    stops: list[ItineraryStop]
    total_estimated_cost_cents: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


class VerificationIssue(BaseModel):
    code: str
    message: str
    shop_id: int | None = None


class VerificationReport(BaseModel):
    valid: bool
    issues: list[VerificationIssue] = Field(default_factory=list)
    verified_shop_ids: list[int] = Field(default_factory=list)


class AgentRunRequest(BaseModel):
    mode: AgentMode = AgentMode.MULTI
    constraints: UserConstraints


class AgentRunCreateRequest(BaseModel):
    """Natural-language entry point used by the product UI.

    Optional fields are user-provided hints. The model gateway extracts the rest
    from ``query`` and the resulting ``UserConstraints`` remains the only object
    shared by workflow nodes.
    """

    model_config = ConfigDict(extra="forbid")

    mode: AgentMode = AgentMode.MULTI
    query: str = Field(min_length=1, max_length=2_000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    neighborhood: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=80)
    party_size: int | None = Field(default=None, ge=1, le=50)
    budget_cents: int | None = Field(default=None, ge=0, le=10_000_000)
    desired_tags: list[str] = Field(default_factory=list, max_length=20)
    visit_time: str | None = None


class AgentRunResponse(BaseModel):
    mode: AgentMode
    status: RunStatus
    candidates: CandidateSet
    evidence: EvidencePack
    itinerary: ItineraryDraft
    verification: VerificationReport
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunEvent(BaseModel):
    sequence: int = Field(ge=1)
    event: str
    agent: str | None = None
    status: str
    message: str
    created_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class AgentTraceSpan(BaseModel):
    span_id: str
    run_id: str
    operation: str
    agent: str | None = None
    kind: str = "agent"
    status: str
    started_at: datetime
    duration_ms: float = Field(ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AgentActionProposal(BaseModel):
    action_id: str
    action_type: AgentActionType
    title: str
    description: str
    risk: ToolRisk
    status: AgentActionStatus = AgentActionStatus.PROPOSED
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentRunCreated(BaseModel):
    run_id: str
    status: RunStatus
    stream_url: str


class AgentRunSnapshot(BaseModel):
    run_id: str
    mode: AgentMode
    query: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    events: list[AgentRunEvent] = Field(default_factory=list)
    actions: list[AgentActionProposal] = Field(default_factory=list)
    result: AgentRunResponse | None = None
    error: str | None = None
