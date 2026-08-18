from __future__ import annotations

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


class CandidateSet(BaseModel):
    candidates: list[ShopCandidate]
    applied_constraints: list[str] = Field(default_factory=list)
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


class AgentRunResponse(BaseModel):
    mode: AgentMode
    status: RunStatus
    candidates: CandidateSet
    evidence: EvidencePack
    itinerary: ItineraryDraft
    verification: VerificationReport
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)
