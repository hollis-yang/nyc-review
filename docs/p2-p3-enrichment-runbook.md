# P2/P3 Merchant Enrichment and Image Runbook

P2/P3 adds a deterministic enrichment layer on top of the P8 real-only merchant identities. It does not change Redis Lua seckill, RabbitMQ order delivery, translation, multi-Agent orchestration, RAG, MCP, or user-generated content.

## What is included

- `p11_p2_p3_shop_enrichment.sql` adds resolved contact/status/rating/price fields, source matches, field observations, and richer image metadata.
- `scripts/nyc_data_pipeline` keeps network fetches separate from deterministic matching, resolution, report generation, and import-bundle generation.
- Provider adapters accept OSM tags, official-site JSON-LD, a pinned FSQ OS/licensed snapshot, NYC DOHMH grades, and licensed merchant-specific image snapshots.
- The public UI displays resolved results directly. Match score and field source remain internal; image credits are retained in `image_credits.json` for legal attribution.
- Deterministic platform review scores, price estimates, mock review threads, and category image fallbacks remain available. The coverage report never counts those fallbacks as externally observed fields.

## 1. Generate the balanced 360-shop pilot

```bash
python3 -m scripts.nyc_data_pipeline \
  --bundle data/generated/nyc-real-medium \
  --output data/generated/nyc-real-p2-p3-pilot \
  --osm data/sources/osm-nyc-enrichment-pilot-2026-08-24.json \
  --dohmh data/sources/nyc-open-data-restaurants-2026-08-23.json \
  --merchant-images data/sources/wikimedia-merchant-images-pilot-2026-08-24.json \
  --pilot-per-type 60

python3 scripts/mock-data-generator/validate_dataset.py \
  data/generated/nyc-real-p2-p3-pilot
```

The pilot selects 60 merchants per top-level category and round-robins across all five boroughs.

## 2. Refresh the fields that P8's old OSM normalizer omitted

The fetch reads only the OSM identities already selected by P8 and writes a pinned snapshot. It does not mutate MySQL.

```bash
python3 -m scripts.nyc_data_pipeline.fetch_osm_enrichment \
  --shops data/generated/nyc-real-medium/shops.json \
  --output data/sources/osm-nyc-enrichment-2026-08-24.json
```

Run the enrichment pipeline with that snapshot instead of the old identity snapshot. OSM `opening_hours`, phone, website, reservation, Wikidata, Wikimedia Commons and direct image tags are retained.

## 3. Optional official-site and provider snapshots

After the first enrichment pass has populated websites, fetch a bounded LocalBusiness JSON-LD snapshot:

```bash
python3 -m scripts.nyc_data_pipeline.fetch_official_sites \
  --shops data/generated/nyc-real-p2-p3-pass1/shops.json \
  --output data/sources/official-site-jsonld-2026-08-24.json \
  --limit 500
```

The fetcher rejects localhost, private/link-local IPs, non-HTTP URLs, unsafe redirects, oversized bodies and non-HTML responses. Re-run the pipeline with `--official-sites`.

`--fsq-os` accepts a pinned local export with `records`. Each record may contain `externalId`, `name`, `address`, coordinates, phone/website, hours, rating/ratingCount, price/priceRange and status. No API key is required by the pipeline itself.

`--merchant-images` accepts pinned, merchant-matched image rows with `externalId` (preferred), URL, source page, author/attribution, license name and license URL. An image without an open license or a strict merchant match is rejected; the category fallback remains.

For the relaxed image policy, discover remote image references from each matched merchant website:

```bash
python3 -m scripts.nyc_data_pipeline.fetch_official_site_images \
  --shops data/generated/nyc-real-p2-p3-pilot/shops.json \
  --output data/sources/official-site-merchant-images-pilot-2026-08-24.json \
  --limit 360 \
  --workers 12
```

This policy prefers LocalBusiness JSON-LD, Open Graph and social preview images, then a sufficiently large page image. It records a remote reference and official source page without claiming that the image has an open license. Private-network targets, unsafe redirects, tracking pixels and legacy comma-delimited URL conflicts are rejected. Pass the pinned result with `--official-site-images`; licensed Wikimedia images still take priority and category images remain the final fallback.

The balanced 360-shop trial attempted 178 valid merchant websites and found 114 URLs that actually returned image content. Together with the licensed Wikimedia set, unique merchant-specific image coverage rose from 10 shops (2.78%) to 119 shops (33.06%).

## 4. Generate the complete 5,000-shop bundle

```bash
python3 -m scripts.nyc_data_pipeline \
  --bundle data/generated/nyc-real-medium \
  --output data/generated/nyc-real-p2-p3-full \
  --osm data/sources/osm-nyc-enrichment-2026-08-24.json \
  --dohmh data/sources/nyc-open-data-restaurants-2026-08-23.json \
  --merchant-images data/sources/wikimedia-merchant-images-2026-08-24.json \
  --official-site-images data/sources/official-site-merchant-images-2026-08-24.json

python3 scripts/mock-data-generator/validate_dataset.py \
  data/generated/nyc-real-p2-p3-full
```

Add optional snapshot arguments only after the corresponding pinned snapshot has been collected. The result still has 100% display fallback coverage, and `enrichment_report.json` separates licensed images, official-site remote references and category fallbacks.

## 5. Deferred final import

Per the project plan, do not import or rebuild full Qdrant until the final integration phase. At that time, stop the application and run:

```bash
mysql -u root -p nyc_review < src/main/resources/db/p11_p2_p3_shop_enrichment.sql
mysql -u root -p nyc_review < data/generated/nyc-real-p2-p3-full/mysql_import.sql
redis-cli --pipe < data/generated/nyc-real-p2-p3-full/redis_seed.resp
redis-cli DEL cache:shopType:list
```

Then rebuild the matching P7 neighborhood projection and Qdrant collection from the same `dataVersion` and `datasetSha256`. Never combine the P2/P3 MySQL bundle with an older map or Qdrant scope.

## 6. Safe verification

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts.nyc_data_pipeline.test_pipeline -v

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts/mock-data-generator/test_generate.py

uv run --project agent-service pytest agent-service/tests -q
cd nyc-review-web && npm run build
```

The pipeline and CI tests never require live network access. Network is used only by explicit fetch commands; generation always consumes pinned files.
