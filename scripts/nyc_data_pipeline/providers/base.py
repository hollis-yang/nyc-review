from __future__ import annotations

from dataclasses import dataclass

from ..schemas import FieldObservation, SourceMatch


@dataclass(frozen=True)
class ProviderResult:
    matches: tuple[SourceMatch, ...] = ()
    observations: tuple[FieldObservation, ...] = ()
