from __future__ import annotations

import operator
from typing import Annotated, NotRequired, TypedDict

from app.domain.models import (
    AgentRunRequest,
    CandidateSet,
    EvidencePack,
    ItineraryDraft,
    UserConstraints,
    VerificationReport,
)


class AgentState(TypedDict):
    request: AgentRunRequest
    constraints: NotRequired[UserConstraints]
    candidates: NotRequired[CandidateSet]
    evidence: NotRequired[EvidencePack]
    itinerary: NotRequired[ItineraryDraft]
    verification: NotRequired[VerificationReport]
    summary: NotRequired[str]
    events: Annotated[list[str], operator.add]
