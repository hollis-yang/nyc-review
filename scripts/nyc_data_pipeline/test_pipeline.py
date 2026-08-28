from __future__ import annotations

import unittest

from .images.image_matcher import ImageMatcher
from .fetch_official_site_images import extract_official_image_urls
from .fetch_wikimedia_search_images import _name_match
from .fetch_official_site_deep import (
    _extra_image_candidates,
    _jsonld_prices,
    _price_stats,
    _target_links,
    _text_prices,
    extract_visible_contact_fields,
)
from .matching import EntityMatcher
from .merge.field_resolver import FieldResolver
from .merge.hours_resolver import normalize_hours
from .merge.price_resolver import price_level
from .merge.rating_resolver import count
from .pipeline import _deduplicate_observations
from .providers.official_site import OfficialSiteProvider, extract_local_business_jsonld, is_safe_public_url
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

    def test_wikimedia_name_search_requires_significant_merchant_tokens(self) -> None:
        self.assertTrue(_name_match("Dino's Pizzeria", "File:Dino's Pizzeria New York dining room.jpg"))
        self.assertTrue(_name_match("Eleven Madison Park", "File:Eleven Madison Park NYC exterior.jpg"))
        self.assertFalse(_name_match("Dino's Pizzeria", "File:Dino restaurant logo.svg"))
        self.assertFalse(_name_match("Eleven Madison Park", "File:Madison Square Park New York.jpg"))


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

    def test_excludes_logo_candidates(self) -> None:
        html = '''
          <script type="application/ld+json">{
            "@type":"Restaurant", "image":"/dining-room.jpg", "logo":"/brand-logo.png"
          }</script>
          <img src="/site-logo.png" width="1000" height="400" alt="Restaurant logo">
        '''
        result = extract_official_image_urls(html, "https://example.com/")
        self.assertEqual(["https://example.com/dining-room.jpg"], result)

    def test_excludes_logomark_candidates(self) -> None:
        html = '<img src="/assets/logomark.svg" width="1200" height="600">'
        self.assertEqual([], extract_official_image_urls(html, "https://example.com/"))

    def test_p13_accepts_card_sized_non_logo_merchant_photo(self) -> None:
        html = '<img src="/counter.jpg" width="260" height="160" alt="Cafe counter">'
        self.assertEqual(
            ["https://example.com/counter.jpg"],
            extract_official_image_urls(html, "https://example.com/"),
        )

    def test_extracts_local_business_json_ld(self) -> None:
        html = '''<script type="application/ld+json">{
          "@context":"https://schema.org", "@type":"Restaurant", "name":"Example",
          "telephone":"+1 212 555 0100", "priceRange":"$$"
        }</script>'''
        records = extract_local_business_jsonld(html)
        self.assertEqual("Example", records[0]["name"])
        self.assertEqual("$$", records[0]["priceRange"])

    def test_resolves_nested_official_fields_and_rating_scale(self) -> None:
        snapshot = {
            "metadata": {"fetchedAt": "2026-08-24T00:00:00Z", "datasetVersion": "2026-08-24"},
            "records": [{
                "externalId": "official-site:1", "name": "Example", "address": "1 Main St",
                "latitude": 40.75, "longitude": -73.98,
                "sourceUrl": "https://example.com", "jsonLd": {
                    "@type": "Restaurant",
                    "contactPoint": {"telephone": "+1 212 555 0100"},
                    "potentialAction": {"@type": "ReserveAction", "target": {"urlTemplate": "https://example.com/book"}},
                    "offers": {"lowPrice": 20, "highPrice": 40, "priceCurrency": "USD"},
                    "aggregateRating": {"ratingValue": 8, "bestRating": 10, "ratingCount": 42},
                },
            }],
        }
        result = OfficialSiteProvider().collect(
            [{"id": 1, "name": "Example", "address": "1 Main St", "y": 40.75, "x": -73.98}], snapshot,
        )
        values = {item.field_name: item.value for item in result.observations}
        self.assertEqual("+1 212 555 0100", values["phone"])
        self.assertEqual("https://example.com/book", values["reservationUrl"])
        self.assertEqual("$20-$40", values["priceRangeText"])
        self.assertEqual(4.0, values["rating"])

    def test_discovers_deep_pages_and_responsive_images(self) -> None:
        html = '''
          <a href="/menus/dinner.pdf">Dinner menu</a>
          <a href="/gallery">Photos</a>
          <a href="/privacy">Privacy</a>
          <picture><source srcset="/small.jpg 480w, /large.jpg 1200w"></picture>
          <div style="background-image:url('/dining-room.jpg')"></div>
        '''
        pages, pdfs = _target_links(html, "https://example.com", "https://example.com")
        self.assertEqual(["https://example.com/gallery"], pages)
        self.assertEqual(["https://example.com/menus/dinner.pdf"], pdfs)
        candidates = _extra_image_candidates(html, "https://example.com")
        urls = {item["url"] for item in candidates}
        self.assertIn("https://example.com/large.jpg", urls)
        self.assertIn("https://example.com/dining-room.jpg", urls)

    def test_derives_menu_prices_from_jsonld_and_visible_text(self) -> None:
        documents = [{
            "@type": "Menu",
            "hasMenuSection": [{
                "hasMenuItem": [
                    {"offers": {"price": "18", "priceCurrency": "USD"}},
                    {"offers": {"lowPrice": 22, "highPrice": 31, "priceCurrency": "USD"}},
                ],
            }],
        }]
        prices = _jsonld_prices(documents)
        prices.extend(_text_prices("Soup $9.50 Pasta $24 Wine $16"))
        self.assertEqual([18.0, 22.0, 31.0], prices[:3])
        stats = _price_stats(prices, 1, ["https://example.com/menu"])
        self.assertIsNotNone(stats)
        self.assertEqual("OFFICIAL_MENU_MEDIAN_BY_CATEGORY", stats["derivation"])
        self.assertGreater(stats["estimatedSpendCents"], stats["medianPriceCents"])

    def test_extracts_visible_first_party_contact_hours_and_booking(self) -> None:
        html = '''
          <a href="tel:+12125550100">Call</a>
          <a href="/reservations">Book a table</a>
          <div>Monday 9:00 AM - 5:30 PM</div>
          <div>Tuesday 10:00 AM to 6:00 PM</div>
        '''
        fields = extract_visible_contact_fields(html, "https://example.com/contact")
        self.assertEqual("+12125550100", fields["telephone"])
        self.assertEqual("https://example.com/reservations", fields["reservationUrl"])
        hours = {item["dayOfWeek"]: item for item in fields["openingHoursSpecification"]}
        self.assertEqual("09:00", hours["https://schema.org/Monday"]["opens"])
        self.assertEqual("17:30", hours["https://schema.org/Monday"]["closes"])
        self.assertEqual("18:00", hours["https://schema.org/Tuesday"]["closes"])

    def test_official_menu_stats_resolve_range_and_average_price(self) -> None:
        snapshot = {
            "metadata": {"fetchedAt": "2026-08-24T00:00:00Z", "datasetVersion": "2026-08-24"},
            "records": [{
                "externalId": "official-site:1", "name": "Example", "address": "1 Main St",
                "latitude": 40.75, "longitude": -73.98, "sourceUrl": "https://example.com",
                "jsonLd": {
                    "@type": "Restaurant", "name": "Example",
                    "menuPriceStats": {
                        "lowerPriceCents": 1800,
                        "upperPriceCents": 3200,
                        "estimatedSpendCents": 3400,
                    },
                },
            }],
        }
        result = OfficialSiteProvider().collect(
            [{"id": 1, "name": "Example", "address": "1 Main St", "y": 40.75, "x": -73.98}],
            snapshot,
        )
        values = {item.field_name: item.value for item in result.observations}
        self.assertEqual("$18-$32", values["priceRangeText"])
        self.assertEqual(3400, values["avgPriceCents"])

    def test_ssrf_targets_are_rejected(self) -> None:
        for url in (
            "http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data",
            "http://[::1]/", "file:///etc/passwd", "https://service.internal/data",
        ):
            self.assertFalse(is_safe_public_url(url), url)
        self.assertTrue(is_safe_public_url("https://example.com/restaurant"))


class ResolverTest(unittest.TestCase):
    def test_normalizes_official_price_ranges(self) -> None:
        self.assertEqual(2, price_level("$20-$40"))
        self.assertEqual(3, price_level("$$–$$$"))

    def test_normalizes_compact_rating_count(self) -> None:
        self.assertEqual(2300, count("2.3K"))

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
            FieldObservation(1, "rating", 3.8, "NYC_REVIEW_GENERATED", None, "2026-08-24T00:00:00Z", None, 1, 10, "v1").as_dict(),
            FieldObservation(1, "rating", 4.7, "OFFICIAL_SITE", "site:1", "2026-08-24T00:00:00Z", None, .91, 100, "v2").as_dict(),
            FieldObservation(1, "ratingCount", 214, "OFFICIAL_SITE", "site:1", "2026-08-24T00:00:00Z", None, .91, 100, "v2").as_dict(),
        ]
        result = FieldResolver(observations).resolve({"id": 1, "comments": 20, "priceLevel": 2})
        self.assertEqual(47, result.shop["score"])
        self.assertEqual(214, result.shop["ratingCount"])
        self.assertEqual(47, result.shop["externalScore"])
        self.assertEqual(214, result.shop["externalRatingCount"])
        self.assertEqual(20, result.shop["localReviewCount"])

    def test_resolves_official_menu_average_price(self) -> None:
        observation = FieldObservation(
            1, "avgPriceCents", 4200, "OFFICIAL_SITE", "site:1",
            "2026-08-24T00:00:00Z", None, .91, 100, "v2",
        ).as_dict()
        result = FieldResolver([observation]).resolve({
            "id": 1, "avgPriceCents": 2300, "comments": 20, "priceLevel": 2,
        })
        self.assertEqual(4200, result.shop["avgPriceCents"])
        self.assertEqual("OFFICIAL_SITE", result.resolved_providers["avgPriceCents"])

    def test_normalizes_osm_hours(self) -> None:
        result = normalize_hours("Mo-Fr 09:00-18:00; Sa 10:00-14:00; Su off", 1)
        self.assertEqual(7, len(result))
        self.assertFalse(result[0]["closed"])
        self.assertTrue(result[6]["closed"])

    def test_normalizes_single_schema_hours_object(self) -> None:
        result = normalize_hours({
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": "https://schema.org/Monday",
            "opens": "09:00:00",
            "closes": "18:00:00",
        }, 1)
        self.assertIsNotNone(result)
        self.assertFalse(result[0]["closed"])


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
        self.assertEqual(1, len(images))

    def test_snapshot_logomark_is_rejected_again_at_merge_time(self) -> None:
        shops = [{"id": 1, "externalId": "osm:1", "name": "Cafe", "address": "1 Main St"}]
        fallback = [{
            "shopId": 1, "sortOrder": 1, "url": "https://images.example/fallback.jpg",
            "sourceUrl": "https://commons.wikimedia.org/wiki/File:Fallback.jpg",
            "sourceName": "Wikimedia Commons", "licenseName": "CC BY 4.0",
            "licenseUrl": "https://creativecommons.org/licenses/by/4.0/", "attribution": "A",
        }]
        merchant = {"records": [{
            "externalId": "osm:1", "url": "https://cafe.example/assets/logomark.svg",
            "sourceUrl": "https://cafe.example/", "sourceName": "Official website",
            "matchType": "OFFICIAL_SITE_IMAGE", "usagePolicy": "REMOTE_REFERENCE",
        }]}
        images, _ = ImageMatcher().assign(shops, fallback, merchant, "test-v1")
        self.assertEqual("CATEGORY_FALLBACK", images[0]["matchType"])

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
