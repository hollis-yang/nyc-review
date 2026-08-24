from __future__ import annotations

from typing import Any

from ..images.image_validator import valid_image


class WikimediaProvider:
    """Validates a pinned merchant-specific Commons snapshot before matching."""

    @staticmethod
    def records(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        return sorted(
            (
                record for record in snapshot.get("records") or []
                if isinstance(record, dict)
                and str(record.get("sourceName") or "").lower() == "wikimedia commons"
                and valid_image(record, merchant_specific=True)
            ),
            key=lambda item: (str(item.get("externalId") or ""), str(item.get("sourceUrl") or "")),
        )
