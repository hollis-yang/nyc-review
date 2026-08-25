# P10/P11 Full Image and Merchant-Field Runbook

P10/P11 first builds one isolated 5,000-shop bundle. After validation, it may be
promoted once to the active development environment so the phase can be
visually accepted before P12. The previous database backup and Qdrant directory
remain the rollback point.

## Scope

- P10 visits every available merchant website, rejects unsafe redirects,
  trackers, logos, broken assets and undersized images, deduplicates a bounded
  content fingerprint, and retains one to three ranked remote references.
- P11 uses the same page response to pin the best merged LocalBusiness JSON-LD
  document. Phone, website, hours, reservation, rating/rating-count and price
  are resolved independently; the lower-priority deterministic values remain
  available when an official field is absent.
- Official-site images are remote references. The crawler reads only a bounded
  prefix for validation and never stores or redistributes the image bytes.

## 1. Refresh both fixed snapshots in one crawl

Use the P9 full bundle as the crawl input because it already contains the OSM
website field. Shops without a website are skipped and later receive their
category fallback.

```bash
python3 -m scripts.nyc_data_pipeline.fetch_official_site_images \
  --shops data/generated/nyc-real-p2-p3-full/shops.json \
  --output data/sources/official-site-merchant-images-2026-08-24-full.json \
  --official-sites-output data/sources/official-site-jsonld-2026-08-24-full.json \
  --limit 5000 \
  --workers 24
```

The command is the only networked part of this phase. Subsequent generation
and validation consume the pinned files and are reproducible offline.

## 2. Generate the isolated P10/P11 bundle

```bash
python3 -m scripts.nyc_data_pipeline \
  --bundle data/generated/nyc-real-medium \
  --output data/generated/nyc-real-p10-p11-full \
  --osm data/sources/osm-nyc-enrichment-2026-08-24.json \
  --dohmh data/sources/nyc-open-data-restaurants-2026-08-23.json \
  --official-sites data/sources/official-site-jsonld-2026-08-24-full.json \
  --merchant-images data/sources/wikimedia-merchant-images-2026-08-24.json \
  --official-site-images data/sources/official-site-merchant-images-2026-08-24-full.json
```

`manifest.json`, `enrichment_report.json`, `import_manifest.json`,
`mysql_import.sql` and `redis_seed.resp` are generated together and share the
same `nyc-real-v3-*` data version.

## 3. Rebuild and validate the map projection

```bash
python3 scripts/mock-data-generator/build_neighborhood_import.py \
  --dataset data/generated/nyc-real-p10-p11-full \
  --nta-snapshot data/sources/nyc-nta-2020-26b.geojson \
  --output data/generated/nyc-real-p10-p11-full/p7_neighborhood_import.sql

PYTHONDONTWRITEBYTECODE=1 python3 \
  scripts/mock-data-generator/validate_dataset.py \
  data/generated/nyc-real-p10-p11-full
```

The P10/P11 profile additionally fails validation when display coverage is not
100%, merchant-specific shop coverage is below 30%, a shop has more than three
images, external rating or price is zero, or P11 fails to improve phone/hours
over the P9 baseline.

## 4. Regression commands

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts.nyc_data_pipeline.test_pipeline -v

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  scripts/mock-data-generator/test_generate.py

uv run --project agent-service pytest agent-service/tests -q
cd hmdp-react && npm run build
```

## 5. Promote the checkpoint to the development environment

Do not repeat the non-idempotent historical P6 migration. This repository has
already applied `p10_p8_real_content.sql` and
`p11_p2_p3_shop_enrichment.sql`, so this checkpoint only replaces data.

First validate, drain RabbitMQ and the Redis pending-order index, then stop
Spring Boot and Agent Service:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  scripts/mock-data-generator/validate_dataset.py \
  data/generated/nyc-real-p10-p11-full

rabbitmqctl list_queues -p / name messages_ready messages_unacknowledged
redis-cli ZCARD seckill:pending:orders
```

Both RabbitMQ counts and the Redis count must be zero. When RabbitMQ runs in
Compose, execute the first check inside its container. Back up the development
database before replacement:

```bash
mkdir -p backups
mysqldump -u root -p --single-transaction --routines --triggers \
  hmdp_new > backups/hmdp_new_before_p10_p11_20260824.sql
```

With Spring and Agent Service stopped, import one matching bundle in this
order:

```bash
mysql -u root -p hmdp_new \
  < data/generated/nyc-real-p10-p11-full/mysql_import.sql

mysql -u root -p hmdp_new \
  < data/generated/nyc-real-p10-p11-full/p7_neighborhood_import.sql

redis-cli --pipe \
  < data/generated/nyc-real-p10-p11-full/redis_seed.resp

redis-cli DEL cache:shopType:list
```

`mysql_import.sql` intentionally clears all previous P7 derived rows. Therefore
`p7_neighborhood_import.sql` must be the **last MySQL command**. If the main
bundle is rerun for any reason, rerun the matching P7 SQL immediately afterward
and verify `tb_shop_map_location` before continuing to Redis/Qdrant acceptance.

The import replaces generated users and invalidates the meaning of old login
tokens. Remove only login-token keys and sign in again:

```bash
redis-cli --scan --pattern 'login:token:*' |
  while IFS= read -r key; do redis-cli DEL "$key"; done
```

Start Spring Boot, sign in and copy the new login token. Start Agent Service
with a new Qdrant path so the previous index remains available for rollback:

```bash
cd agent-service

HMDP_AGENT_ADAPTER=http \
HMDP_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
HMDP_AGENT_BACKEND_AUTH_TOKEN='<new-login-token>' \
HMDP_AGENT_RAG_ADAPTER=qdrant \
HMDP_AGENT_QDRANT_LOCATION=./.local/qdrant-p10-p11 \
HMDP_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-real-p10-p11-full \
HMDP_AGENT_RAG_INDEX_BATCH_SIZE=128 \
HMDP_AGENT_MODEL_PROVIDER=deepseek \
uv run uvicorn app.main:app --port 8090
```

Local Qdrant can print a large-collection warning at this scale; P15 replaces
it with Qdrant Server. A new path avoids both the old-index lock and destructive
replacement.

## 6. Checkpoint acceptance

Read-only database checks:

```bash
mysql -u root -p hmdp_new -e "
SELECT data_version, profile, dataset_sha256, shop_count, active
FROM tb_data_import ORDER BY imported_at DESC LIMIT 1;
SELECT COUNT(*) AS shops, COUNT(DISTINCT data_version) AS versions FROM tb_shop;
SELECT COUNT(DISTINCT shop_id) AS image_shops,
       COUNT(DISTINCT CASE WHEN image_type='MERCHANT_SPECIFIC' THEN shop_id END) AS merchant_image_shops
FROM tb_shop_image;
SELECT COUNT(*) AS map_locations FROM tb_shop_map_location;
SELECT field_name, COUNT(DISTINCT shop_id) AS shops
FROM tb_shop_field_observation
WHERE provider <> 'HMDP_GENERATED'
  AND field_name IN ('rating','priceRangeText','phone','openingHours','reservationUrl')
GROUP BY field_name ORDER BY field_name;"
```

Expected identity values are `nyc-real-v3-7577e407-m20260824`, 5,000 shops,
5,000 image shops, 1,772 merchant-image shops and 5,000 map locations. Finally,
open Home, Map, Shop Detail and AI Guide; verify new images/contact fields and
run one multi-Agent prompt before marking the checkpoint accepted.

## Reproduced result

The pinned 2026-08-24 input set produced:

- `dataVersion`: `nyc-real-v3-7577e407-m20260824`
- `datasetSha256`: `ef71def3a098390856ce79d54039497e6090d05b1e70ad641b1d1a17ddd68770`
- 5,000 real-source merchant identities and 100% display-image coverage
- 1,772 shops (35.44%) with merchant-specific images
- 21 shops with an external rating and rating-count, 152 with an external
  price, 3,278 with a phone, 2,831 with externally observed hours and 58 with
  a reservation URL
- 5,000/5,000 shops assigned to an NYC NTA neighborhood in the generated P7
  projection
