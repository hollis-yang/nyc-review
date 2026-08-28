# P11.5 Official Image and Menu Price Runbook

P11.5 is an isolated checkpoint between P11 field enrichment and P12 RAG
quality. It deliberately contains only the two no-paid-API improvements accepted
for this phase:

- deepen merchant-image discovery on the merchant's own website; and
- derive a per-person or per-visit price from prices explicitly published on an
  official menu, service or pricing page.

Merchant identities remain the same 5,000 real-source records. Rating coverage
is not expanded in P11.5 because an official, free, reusable rating source was
not identified; generated platform ratings remain available to the product.

## 1. Refresh the fixed P11.5 snapshots

The P10/P11 bundle is the crawl input because it already contains the resolved
website field. The crawler revisits the home page and at most four same-site
menu, gallery, location, service or pricing pages. It also checks a bounded
sitemap set, responsive `srcset`, lazy image attributes, inline CSS images and
at most one PDF menu. Private-network addresses, unsafe redirects, oversized
responses, trackers, logos, broken images and undersized images are rejected.
One malformed site is skipped without stopping the batch.

```bash
python3 -m scripts.nyc_data_pipeline.fetch_official_site_deep \
  --shops data/generated/nyc-real-p10-p11-full/shops.json \
  --base-images data/sources/official-site-merchant-images-2026-08-24-full.json \
  --base-official-sites data/sources/official-site-jsonld-2026-08-24-full.json \
  --output-images data/sources/official-site-merchant-images-p11-5-2026-08-24-full.json \
  --output-official-sites data/sources/official-site-jsonld-menu-p11-5-2026-08-24-full.json \
  --limit 5000 \
  --workers 24
```

This is the only networked step. Image bytes are read only for validation and
are not stored or redistributed; the snapshot contains remote references.
Snapshots are written atomically after the entire crawl completes.

Price observations come from JSON-LD `Offer`/`MenuItem` values, visible dollar
prices on targeted pages, and text-bearing PDF menus. Unique observed prices
are reduced to a deterministic median and quartile range. Restaurant, cafe and
nightlife estimates apply a fixed category multiplier; service categories use
the median as a per-visit estimate. The UI receives only the resolved result,
not a confidence or provenance label.

## 2. Generate the isolated v4 bundle

```bash
python3 -m scripts.nyc_data_pipeline \
  --bundle data/generated/nyc-real-medium \
  --output data/generated/nyc-real-p11-5-full \
  --osm data/sources/osm-nyc-enrichment-2026-08-24.json \
  --dohmh data/sources/nyc-open-data-restaurants-2026-08-23.json \
  --official-sites data/sources/official-site-jsonld-menu-p11-5-2026-08-24-full.json \
  --merchant-images data/sources/wikimedia-merchant-images-2026-08-24.json \
  --official-site-images data/sources/official-site-merchant-images-p11-5-2026-08-24-full.json \
  --phase p11-5

python3 scripts/mock-data-generator/build_neighborhood_import.py \
  --dataset data/generated/nyc-real-p11-5-full \
  --nta-snapshot data/sources/nyc-nta-2020-26b.geojson \
  --output data/generated/nyc-real-p11-5-full/p7_neighborhood_import.sql

PYTHONDONTWRITEBYTECODE=1 python3 \
  scripts/mock-data-generator/validate_dataset.py \
  data/generated/nyc-real-p11-5-full
```

The P11.5 full validator retains every P10/P11 gate and additionally requires
merchant-specific image coverage above 1,772 shops, external price coverage
above 152 shops, at least one official-menu average price, and removal of
`avgPriceCents` from the internal synthetic-field list whenever an official
menu value wins.

Agent startup applies the same provenance distinction: synthetic reviews are
required for every shop, while the `images` synthetic disclosure is required
only for shops whose selected `shop_images.json` record is an illustrative
category fallback. Merchant-specific official/Wikidata images must not be
rejected by the older P8 all-illustrative-image assumption.

## 3. Regression tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts.nyc_data_pipeline.test_pipeline -v

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts/mock-data-generator/test_generate.py

uv run --project agent-service pytest agent-service/tests -q
mvn clean -Dtest='!NycReviewApplicationTests' test
cd nyc-review-web && npm run build
```

`NycReviewApplicationTests` remains excluded because it constructs database
and Redis data and is not container-isolated.

## 4. Promote the checkpoint manually

Generation never connects to MySQL or Redis. Before promotion, drain RabbitMQ
and `seckill:pending:orders`, stop Spring Boot and Agent Service, and back up the
development database as described in the P10/P11 runbook. Then import this
single matching checkpoint in order:

```bash
mysql -u root -p nyc_review \
  < data/generated/nyc-real-p11-5-full/mysql_import.sql

mysql -u root -p nyc_review \
  < data/generated/nyc-real-p11-5-full/p7_neighborhood_import.sql

redis-cli --pipe \
  < data/generated/nyc-real-p11-5-full/redis_seed.resp

redis-cli DEL cache:shopType:list
```

The main SQL clears the derived map rows, so the matching P7 SQL must always be
the final MySQL command. Clear only `login:token:*`, sign in again, and start
Agent Service with the new token, bundle and a new Qdrant path:

```bash
cd agent-service

NYC_REVIEW_AGENT_ADAPTER=http \
NYC_REVIEW_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN='<new-login-token>' \
NYC_REVIEW_AGENT_RAG_ADAPTER=qdrant \
NYC_REVIEW_AGENT_QDRANT_LOCATION=./.local/qdrant-p11-5 \
NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-real-p11-5-full \
NYC_REVIEW_AGENT_RAG_INDEX_BATCH_SIZE=128 \
NYC_REVIEW_AGENT_MODEL_PROVIDER=deepseek \
uv run uvicorn app.main:app --port 8090
```

## 5. Acceptance checks

```bash
mysql -u root -p nyc_review -e "
SELECT data_version, profile, dataset_sha256, shop_count, active
FROM tb_data_import ORDER BY imported_at DESC LIMIT 1;
SELECT COUNT(*) AS shops, COUNT(DISTINCT data_version) AS versions FROM tb_shop;
SELECT COUNT(DISTINCT shop_id) AS image_shops,
       COUNT(DISTINCT CASE WHEN image_type='MERCHANT_SPECIFIC' THEN shop_id END)
         AS merchant_image_shops
FROM tb_shop_image;
SELECT COUNT(*) AS map_locations FROM tb_shop_map_location;
SELECT field_name, COUNT(DISTINCT shop_id) AS shops
FROM tb_shop_field_observation
WHERE provider <> 'NYC_REVIEW_GENERATED'
  AND field_name IN ('rating','priceRangeText','avgPriceCents','phone','openingHours','reservationUrl')
GROUP BY field_name ORDER BY field_name;"
```

Expected checkpoint values:

- `dataVersion`: `nyc-real-v4-0f51676d-m20260824`
- `datasetSha256`: `3eb30998c46f493fd0528cfea8788188ab3e4d30821f1324f7e7d3b8a03d3234`
- 5,000 shops, one active version and 5,000 map locations
- 5,000 display-image shops and 1,871 merchant-specific image shops (37.42%)
- 918 shops with an external price; 844 with an official-menu-derived average
  price
- incidental deep-page gains: 22 external ratings, 3,290 phones, 2,837
  externally observed hours and 108 reservation URLs

Finally inspect Home, Map, Shop Detail and two AI Guide prompts. Verify that new
images render, the displayed per-person price changes for menu-backed shops,
map counts remain available, and the Agent starts against the v4 bundle before
accepting the checkpoint.
