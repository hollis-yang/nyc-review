#!/usr/bin/env python3
"""Resolve OSM Wikidata/Commons references to licensed merchant image rows."""

from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .snapshots import write_json_atomic

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
LICENSE_PREFIXES = ("CC0", "CC BY", "CC-BY", "PUBLIC DOMAIN")


def fetch(shops: list[dict[str, Any]], osm_snapshot: dict[str, Any]) -> dict[str, Any]:
    shop_by_external = {str(shop.get("externalId")): shop for shop in shops}
    source_by_qid: dict[str, list[str]] = {}
    direct_files: dict[str, str] = {}
    for record in osm_snapshot.get("records") or []:
        external_id = str(record.get("externalId") or "")
        if external_id not in shop_by_external:
            continue
        tags = record.get("sourceTags") or {}
        qid = str(tags.get("wikidata") or "").upper()
        if re.fullmatch(r"Q\d+", qid):
            source_by_qid.setdefault(qid, []).append(external_id)
        commons = str(tags.get("wikimedia_commons") or "")
        if commons.lower().startswith("file:"):
            direct_files[external_id] = commons[5:]

    files_by_external = dict(direct_files)
    for offset in range(0, len(source_by_qid), 50):
        qids = sorted(source_by_qid)[offset: offset + 50]
        payload = _get_json(WIKIDATA_API, {
            "action": "wbgetentities", "ids": "|".join(qids), "props": "claims", "format": "json",
        })
        for qid in qids:
            claims = ((payload.get("entities") or {}).get(qid) or {}).get("claims") or {}
            filename = _p18_filename(claims.get("P18") or [])
            if filename:
                for external_id in source_by_qid[qid]:
                    files_by_external.setdefault(external_id, filename)

    info_by_filename: dict[str, dict[str, Any]] = {}
    filenames = sorted(set(files_by_external.values()))
    for offset in range(0, len(filenames), 40):
        batch = filenames[offset: offset + 40]
        payload = _get_json(COMMONS_API, {
            "action": "query", "titles": "|".join(f"File:{name}" for name in batch),
            "prop": "imageinfo", "iiprop": "url|mime|extmetadata|sha1|size", "iiurlwidth": "1200",
            "format": "json", "formatversion": "2",
        })
        for page in (payload.get("query") or {}).get("pages") or []:
            title = str(page.get("title") or "")
            image_info = (page.get("imageinfo") or [None])[0]
            if title.startswith("File:") and isinstance(image_info, dict):
                info_by_filename[title[5:]] = image_info

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    records = []
    for external_id, filename in sorted(files_by_external.items()):
        image_info = info_by_filename.get(filename)
        shop = shop_by_external[external_id]
        normalized = _normalize_image(image_info, filename) if image_info else None
        if normalized is None:
            continue
        records.append({
            "externalId": external_id, "name": shop.get("name"), "address": shop.get("address"),
            "borough": shop.get("borough"), "latitude": shop.get("y"), "longitude": shop.get("x"),
            "matchType": "OSM_WIKIMEDIA" if external_id in direct_files else "WIKIDATA_P18",
            "fetchedAt": fetched_at, "lastCheckedAt": fetched_at, **normalized,
        })
    return {
        "metadata": {
            "datasetId": "wikimedia-merchant-images", "datasetVersion": fetched_at[:10],
            "fetchedAt": fetched_at, "recordCount": len(records),
            "sourceName": "Wikimedia Commons", "sourceUrl": "https://commons.wikimedia.org/",
        },
        "records": records,
    }


def _get_json(endpoint: str, params: dict[str, str]) -> dict[str, Any]:
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "nyc-review-p2-p3-wikimedia/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _p18_filename(claims: list[dict[str, Any]]) -> str | None:
    for claim in claims:
        value = (((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value"))
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_image(image_info: dict[str, Any], filename: str) -> dict[str, Any] | None:
    if str(image_info.get("mime")) not in {"image/jpeg", "image/png", "image/webp"}:
        return None
    metadata = image_info.get("extmetadata") or {}
    license_name = _metadata(metadata, "LicenseShortName").upper()
    if not license_name.startswith(LICENSE_PREFIXES):
        return None
    license_url = _absolute_url(_metadata(metadata, "LicenseUrl"))
    attribution = _plain_text(_metadata(metadata, "Artist") or _metadata(metadata, "Credit"))
    url = image_info.get("thumburl") or image_info.get("url")
    if not url or not license_url or not attribution:
        return None
    encoded_title = urllib.parse.quote(filename.replace(" ", "_"), safe="()_',-.!~*")
    return {
        "url": url,
        "sourceUrl": f"https://commons.wikimedia.org/wiki/File:{encoded_title}",
        "sourceName": "Wikimedia Commons", "licenseName": license_name,
        "licenseUrl": license_url, "attribution": attribution,
        "width": image_info.get("thumbwidth") or image_info.get("width"),
        "height": image_info.get("thumbheight") or image_info.get("height"),
        "sourceSha1": image_info.get("sha1"),
    }


def _metadata(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key) or {}
    return str(value.get("value") or "") if isinstance(value, dict) else ""


def _plain_text(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())[:160]


def _absolute_url(value: str) -> str:
    return f"https:{value}" if value.startswith("//") else value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shops", type=Path, required=True)
    parser.add_argument("--osm", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.shops.open(encoding="utf-8") as handle:
        shops = json.load(handle)
    with args.osm.open(encoding="utf-8") as handle:
        osm_snapshot = json.load(handle)
    snapshot = fetch(shops, osm_snapshot)
    write_json_atomic(args.output, snapshot)
    print(json.dumps(snapshot["metadata"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
