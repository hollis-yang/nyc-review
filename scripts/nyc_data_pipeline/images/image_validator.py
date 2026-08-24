from __future__ import annotations

from typing import Any

from ..providers.official_site import is_safe_public_url

OPEN_LICENSE_PREFIXES = ("CC0", "CC BY", "CC-BY", "PUBLIC DOMAIN")


def valid_image(record: dict[str, Any], *, merchant_specific: bool) -> bool:
    url = str(record.get("url") or record.get("displayUrl") or "")
    source_url = str(record.get("sourceUrl") or record.get("sourcePageUrl") or "")
    if not is_safe_public_url(url) or not is_safe_public_url(source_url):
        return False
    if merchant_specific:
        official_reference = (
            record.get("matchType") == "OFFICIAL_SITE_IMAGE"
            and record.get("usagePolicy") == "REMOTE_REFERENCE"
            and record.get("sourceName") == "Official website"
        )
        if not official_reference:
            license_name = str(record.get("licenseName") or "").upper()
            license_url = str(record.get("licenseUrl") or "")
            if not license_name.startswith(OPEN_LICENSE_PREFIXES) or not is_safe_public_url(license_url):
                return False
            if not (record.get("attribution") or record.get("authorName")):
                return False
        if not (record.get("externalId") or (record.get("name") and record.get("address"))):
            return False
    return True
