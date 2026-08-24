from __future__ import annotations

import unittest

from .images.image_matcher import ImageMatcher
from .fetch_official_site_images import extract_official_image_urls
from .matching import EntityMatcher
from .merge.field_resolver import FieldResolver
from .merge.hours_resolver import normalize_hours
from .pipeline import _deduplicate_observations
from .providers.official_site import extract_local_business_jsonld, is_safe_public_url
from .schemas import FieldObservation


class EntityMatcherTest(unittest.TestCase):
    def test_exact_external_id_wins(self) -> None:
        result = EntityMatcher().match(
            {"externalId": "osm:1", "name": "Cafe", "address": "1 Main St"},
            {"externalId": "osm:1", "name": "Renamed", "address": "Other"},
        )
        self.assertIsNotNone(result)
        self.assertEqual("EXTERNAL_ID", result.method)

    def test_borough_conflict_rejects_match(self) -> None:
        result = EntityMatcher().match(
            {"name": "Corner Cafe", "address": "1 Main St, NY 10001", "borough": "Manhattan"},
            {"name": "Corner Cafe", "address": "1 Main St, NY 10001", "borough": "Queens"},
        )
        self.assertIsNone(result)


class OfficialSiteTest(unittest.TestCase):
    def test_extracts_official_page_images_in_priority_order(self) -> None:
        html = '''
          <script type="application/ld+json">{
            "@type":"Restaurant", "name":"Example",
            "image":{"url":"/images/dining-room.jpg"}
          }</script>
          <meta property="og:image" content="https://cdn.example.com/social.jpg">
          <img src="/images/menu.jpg" width="800" height="600">
          <img src="/images/hero,w_1200.jpg" width="1200" height="800">
        '''
        result = extract_official_image_urls(html, "https://example.com/visit")
        self.assertEqual("https://example.com/images/dining-room.jpg", result[0])
        self.assertEqual("https://cdn.example.com/social.jpg", result[1])
        self.assertIn("https://example.com/images/hero%2Cw_1200.jpg", result)

    def test_extracts_local_business_json_ld(self) -> None:
        html = '''<script type="application/ld+json">{
          "@context":"https://schema.org", "@type":"Restaurant", "name":"Example",
          "telephone":"+1 212 555 0100", "priceRange":"$$"
        }</script>'''
        records = extract_local_business_jsonld(html)
        self.assertEqual("Example", records[0]["name"])
        self.assertEqual("$$", records[0]["priceRange"])

    def test_ssrf_targets_are_rejected(self) -> None:
        for url in (
            "http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data",
            "http://[::1]/", "file:///etc/passwd", "https://service.internal/data",
        ):
            self.assertFalse(is_safe_public_url(url), url)
        self.assertTrue(is_safe_public_url("https://example.com/restaurant"))


class ResolverTest(unittest.TestCase):
    def test_deduplicates_database_observation_key(self) -> None:
        first = FieldObservation(
            1, "website", "https://example.com", "OPENSTREETMAP", "osm:1",
            "2026-08-24T00:00:00Z", None, 1, 80, "v1",
        ).as_dict()
        duplicate = dict(first)
        duplicate["observedAt"] = "2026-08-24T01:00:00Z"
        result = _deduplicate_observations([first, duplicate])
        self.assertEqual(1, len(result))
        self.assertEqual("2026-08-24T01:00:00Z", result[0]["observedAt"])

    def test_resolves_higher_priority_observation(self) -> None:
        observations = [
            FieldObservation(1, "rating", 3.8, "HMDP_GENERATED", None, "2026-08-24T00:00:00Z", None, 1, 10, "v1").as_dict(),
            FieldObservation(1, "rating", 4.7, "OFFICIAL_SITE", "site:1", "2026-08-24T00:00:00Z", None, .91, 100, "v2").as_dict(),
            FieldObservation(1, "ratingCount", 214, "OFFICIAL_SITE", "site:1", "2026-08-24T00:00:00Z", None, .91, 100, "v2").as_dict(),
        ]
        result = FieldResolver(observations).resolve({"id": 1, "comments": 20, "priceLevel": 2})
        self.assertEqual(47, result.shop["score"])
        self.assertEqual(214, result.shop["ratingCount"])

    def test_normalizes_osm_hours(self) -> None:
        result = normalize_hours("Mo-Fr 09:00-18:00; Sa 10:00-14:00; Su off", 1)
        self.assertEqual(7, len(result))
        self.assertFalse(result[0]["closed"])
        self.assertTrue(result[6]["closed"])


class ImageMatcherTest(unittest.TestCase):
    def test_official_site_remote_reference_precedes_fallback(self) -> None:
        shops = [{"id": 1, "externalId": "osm:1", "name": "Cafe", "address": "1 Main St"}]
        fallback = [{
            "shopId": 1, "sortOrder": 1, "url": "https://images.example/fallback.jpg",
            "sourceUrl": "https://commons.wikimedia.org/wiki/File:Fallback.jpg",
            "sourceName": "Wikimedia Commons", "licenseName": "CC BY 4.0",
            "licenseUrl": "https://creativecommons.org/licenses/by/4.0/", "attribution": "A",
        }]
        merchant = {"records": [{
            "externalId": "osm:1", "url": "https://cafe.example/hero.jpg",
            "sourceUrl": "https://cafe.example/", "sourceName": "Official website",
            "attribution": "Cafe", "matchType": "OFFICIAL_SITE_IMAGE",
            "usagePolicy": "REMOTE_REFERENCE",
        }]}
        images, _ = ImageMatcher().assign(shops, fallback, merchant, "test-v1")
        self.assertEqual("OFFICIAL_SITE_IMAGE", images[0]["matchType"])
        self.assertEqual("CATEGORY_FALLBACK", images[1]["matchType"])

    def test_exact_licensed_image_precedes_fallback(self) -> None:
        shops = [{"id": 1, "externalId": "osm:1", "name": "Cafe", "address": "1 Main St"}]
        fallback = [{
            "shopId": 1, "sortOrder": 1, "url": "https://images.example/fallback.jpg",
            "sourceUrl": "https://commons.wikimedia.org/wiki/File:Fallback.jpg",
            "sourceName": "Wikimedia Commons", "licenseName": "CC BY 4.0",
            "licenseUrl": "https://creativecommons.org/licenses/by/4.0/", "attribution": "A",
        }]
        merchant = {"records": [{
            "externalId": "osm:1", "url": "https://images.example/merchant.jpg",
            "sourceUrl": "https://commons.wikimedia.org/wiki/File:Merchant.jpg",
            "sourceName": "Wikimedia Commons", "licenseName": "CC BY-SA 4.0",
            "licenseUrl": "https://creativecommons.org/licenses/by-sa/4.0/", "attribution": "B",
        }]}
        images, _ = ImageMatcher().assign(shops, fallback, merchant, "test-v1")
        self.assertEqual("MERCHANT_EXACT", images[0]["matchType"])
        self.assertTrue(images[0]["isPrimary"])


if __name__ == "__main__":
    unittest.main()
