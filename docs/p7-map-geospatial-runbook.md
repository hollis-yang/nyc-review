# P7 Map Geospatial Data Runbook

P7 把地图查询从 20 个生成器友好区域名扩展为官方 NYC 2020 Neighborhood Tabulation Area（NTA）边界、商户点位和按类别预聚合数据。本 Runbook 只覆盖数据层；地图接口、缩放分层和 React 交互使用这里定义的表契约。

## 1. 数据来源与固定版本

边界来自 NYC Department of City Planning 发布的 [2020 Neighborhood Tabulation Areas](https://data.cityofnewyork.us/City-Government/2020-Neighborhood-Tabulation-Areas-NTAs-/9nt8-h7nd)。仓库将以下信息固定在 `data/sources/nyc-nta-2020-26b.manifest.json`：

- Dataset ID：`9nt8-h7nd`
- 版本：`26b`
- 修订日期：`2026-05-28`
- Feature 数：`262`
- 原始 GeoJSON 大小：`4,589,305` bytes
- SHA-256：`4a036c53ce665a73954f260ef4f3a8c49f33d75fb2fc859fe0baf92f4b7f8af8`

NTA 是用于统计报告的中等粒度地理单元，不是纽约社区名称的唯一官方定义。`NTAType=9` 还包含机场、大型公园等特殊非住宅区域，因此 UI 可以显示友好名称，但聚类主键必须使用稳定的 `nta2020` code。

原始 4.6 MB polygon 不提交到仓库。下载器只接受上述固定字节数与 SHA；如果上游数据变化会直接失败，必须人工审核并更新 manifest，而不是静默换版本：

```bash
python3 scripts/mock-data-generator/nyc_nta.py fetch \
  --output data/sources/nyc-nta-2020-26b.geojson

python3 scripts/mock-data-generator/nyc_nta.py validate \
  --input data/sources/nyc-nta-2020-26b.geojson
```

## 2. 数据表契约

先应用幂等迁移：

```bash
mysql -u root -p nyc_review < src/main/resources/db/p9_p7_map_geospatial.sql
```

迁移只增加数据结构，不分配、删除或覆盖商户：

- `tb_neighborhood`：262 个官方 NTA、中心点、bbox、完整 `MULTIPOLYGON SRID 4326` 和来源版本/hash。
- `tb_shop_map_location`：每个 dataVersion/shopId 的 `POINT SRID 4326`、NTA code 和分配方法；即使未匹配 NTA 也保留点位。
- `tb_neighborhood_shop_count`：按 dataVersion、NTA、typeId 的官方社区聚合。
- `tb_borough_shop_count`：按 Borough、typeId 聚合全部商户，同时记录 assigned/unassigned；低缩放不会丢失未匹配商户。
- `tb_map_data_import`：数据集、shopId 和 NTA 快照的哈希以及质量计数。
- `tb_neighborhood_alias`：官方名称和旧 friendly area 的显示兼容关系，不参与点位归属。
- `tb_shop.neighborhood_code`：官方 NTA 外键值；`tb_shop.area` 保持原值，避免改变 Agent 对 `Midtown` 等现有约束的语义。

P7 表显式使用与旧 `tb_shop` 一致的 `utf8mb4_general_ci`。迁移也会自动修复由旧版 P9 在 MySQL 8.4 下创建成 `utf8mb4_0900_ai_ci` 的现有 P7 表；否则跨表比较 `data_version` 会报 MySQL 1267。该转换只影响 P7 派生表的字符列，不修改商户、评论或订单数据。

API 应遵守以下读取边界：

- `zoom <= 10`：读取 `tb_borough_shop_count`，总数包含全部商户。
- `zoom 11–14`：读取 `tb_neighborhood_shop_count JOIN tb_neighborhood`；未归属点按 Borough 合并为明确的 “Other locations” 聚合，不得静默隐藏。
- `zoom >= 15`：使用 `MBRIntersects` 空间索引预筛选 bbox，再以 `ST_Longitude`/`ST_Latitude` 精确过滤并连接 `tb_shop`；未归属商户仍可显示为单点。
- 类别筛选使用 `type_id IN (...)` 后求和，不能先返回全类别数量再由前端估算。

## 3. 为当前 2,000 家数据生成派生导入包

生成器首先验证 `shops.json` 和 `import_manifest.json` 的 dataVersion、shopId 清单和 SHA，再执行官方 polygon point-in-polygon。它不连接数据库：

```bash
python3 scripts/mock-data-generator/build_neighborhood_import.py \
  --dataset data/generated/nyc-medium-hybrid \
  --nta-snapshot data/sources/nyc-nta-2020-26b.geojson \
  --output data/generated/nyc-medium-hybrid/p7_neighborhood_import.sql
```

当前 `nyc-hybrid-v1` 的固定结果应为：

```text
POINT_IN_POLYGON = 1855
UNASSIGNED        = 145
NYC_OPEN_DATA     = 60 assigned / 0 unassigned
MOCK              = 1795 assigned / 145 unassigned
```

145 个未匹配记录都是生成器随机偏移后落在 NTA polygon 外的 Mock 点。导入包明确标记为 `UNASSIGNED`，保留其原始 `area` 和经纬度，不使用最近社区或旧 area 强行伪造官方归属。真实来源商户默认必须 100% 匹配，否则构建失败；只有经过人工核查后才能显式传入 `--allow-real-unassigned`。

确认目标为可替换的本地开发库并停止 Spring/Agent 后，再执行派生导入包：

```bash
mysql -u root -p nyc_review \
  < data/generated/nyc-medium-hybrid/p7_neighborhood_import.sql
```

不要为该命令添加 `--force`。导入包会在任何持久写入前核对 P6 的 active dataset hash，以及目标库中全部 shopId、类别、坐标、Borough、friendly area 和来源类型；任一不匹配都会通过 MySQL `CHECK` 约束失败关闭。这个 SQL 可重复执行，只替换同一 dataVersion 的派生位置与计数；不会修改评论、优惠券、订单、Redis 或 Qdrant。

如果曾使用旧版 P9 并在导入时看到 `ERROR 1267 Illegal mix of collations`，不要清库或重导 P6。未使用 `--force` 时，本次 P7 的 InnoDB 写入会随失败连接回滚。先重新执行修订后的 `p9_p7_map_geospatial.sql`，再重新执行同一个派生导入包即可；下载 NTA 快照和重新生成 SQL 都不是必需步骤。

## 4. Docker Compose

`docker-compose.p4.yml` 已切换到 `nyc-medium-hybrid`，并在空 MySQL volume 初始化时自动应用 P7 schema。NTA polygon 和 point-in-polygon 导入包仍需显式生成，以便 hash 变化必须经过人工审核。

新环境推荐分两步启动：

```bash
docker compose -f docker-compose.p4.yml up -d --wait mysql redis redis-seed rabbitmq qdrant

docker compose -f docker-compose.p4.yml exec -T mysql \
  sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" nyc_review' \
  < data/generated/nyc-medium-hybrid/p7_neighborhood_import.sql

docker compose -f docker-compose.p4.yml up -d spring agent-service web
```

Docker init SQL 只会在空 MySQL volume 上运行。已有 volume 必须单独执行 `p9_p7_map_geospatial.sql`，然后执行 P7 派生导入包；不要为了触发 init script 删除有效 volume。

## 5. 只读验收

```sql
SELECT COUNT(*) AS neighborhoods,
       COUNT(DISTINCT source_sha256) AS source_hashes
FROM tb_neighborhood
WHERE active = 1;

SELECT assignment_method, COUNT(*)
FROM tb_shop_map_location
WHERE data_version = 'nyc-hybrid-v1'
GROUP BY assignment_method;

SELECT s.source_type,
       ml.assignment_method,
       COUNT(*)
FROM tb_shop AS s
JOIN tb_shop_map_location AS ml
  ON ml.shop_id = s.id AND ml.data_version = s.data_version
WHERE s.data_version = 'nyc-hybrid-v1'
GROUP BY s.source_type, ml.assignment_method;

SELECT SUM(shop_count) AS all_borough_shops,
       SUM(assigned_count) AS nta_assigned,
       SUM(unassigned_count) AS nta_unassigned
FROM tb_borough_shop_count
WHERE data_version = 'nyc-hybrid-v1';

SELECT data_version, shop_count, assigned_count, unassigned_count,
       nta_source_version, nta_source_sha256, active
FROM tb_map_data_import
ORDER BY imported_at DESC;
```

预期：`neighborhoods=262`、来源 hash 只有一个、Borough 总数为 `2000`、assigned 为 `1855`、unassigned 为 `145`，且所有 `NYC_OPEN_DATA` 均为 `POINT_IN_POLYGON`。

运行离线测试：

```bash
python3 -m unittest scripts/mock-data-generator/test_generate.py
python3 scripts/mock-data-generator/validate_dataset.py \
  data/generated/nyc-medium-hybrid
```

测试不会连接 MySQL、Redis 或外部 API。只有 `nyc_nta.py fetch` 会访问 NYC Open Data。

## 6. 地图 API 验收

完成迁移和派生导入、重启 Spring 后，API 不需要登录 token。低缩放应返回五区聚合：

```bash
curl -sS -G http://127.0.0.1:8081/shop/map \
  --data-urlencode 'west=-74.30' \
  --data-urlencode 'south=40.45' \
  --data-urlencode 'east=-73.65' \
  --data-urlencode 'north=40.95' \
  --data-urlencode 'zoom=10' \
  | python3 -m json.tool
```

Neighborhood 聚合与多类别筛选：

```bash
curl -sS -G http://127.0.0.1:8081/shop/map \
  --data-urlencode 'west=-74.05' \
  --data-urlencode 'south=40.68' \
  --data-urlencode 'east=-73.90' \
  --data-urlencode 'north=40.88' \
  --data-urlencode 'zoom=12' \
  --data-urlencode 'typeIds=1,2' \
  | python3 -m json.tool
```

放大后的商户点位：

```bash
curl -sS -G http://127.0.0.1:8081/shop/map \
  --data-urlencode 'west=-74.01' \
  --data-urlencode 'south=40.73' \
  --data-urlencode 'east=-73.96' \
  --data-urlencode 'north=40.78' \
  --data-urlencode 'zoom=16' \
  --data-urlencode 'typeIds=1' \
  | python3 -m json.tool
```

依次检查：`mode` 为 `BOROUGH_CLUSTERS`、`NEIGHBORHOOD_CLUSTERS`、`SHOP_MARKERS`；`dataVersion` 为 `nyc-hybrid-v1`；类别聚合含 `countsByType`；商户点位不包含完整评论、营业时间等重字段。对全 NYC bbox 使用 `zoom=15` 时超过 500 家会返回 `tooDense=true` 的 Neighborhood 聚合，不会返回任意截断的 500 个 Marker。缺少 `west` 等必填参数应返回 HTTP 400；未导入 P7 projection 时返回 HTTP 503，而不是伪装成空地图。

## 7. 前端验收

```bash
cd nyc-review-web
npm run dev
```

打开 `/map` 后检查：

- 缩放 8–10 只显示 Borough 数量，11–14 显示 Neighborhood 数量，15 以上显示每家商户。
- 顶部六个类别可单选或多选；选择 “All” 会移除类别过滤。
- 拖动、缩放和快速切换类别时只保留最后一次请求结果，失败会清空旧结果并提供 Retry。
- 点击聚合气泡会逐级放大；点击商户可查看轻量摘要并进入详情页。
- `lat`、`lng`、`zoom`、`types` 会写入 URL，刷新后保持视野与筛选。
- 默认英文、中文模式以及 390 px 移动端宽度均无溢出；未匹配 NTA 的 Mock 点显示为本地化的 “Other locations / 其他位置”。

## 8. 自动化回归

```bash
python3 -m unittest scripts/mock-data-generator/test_generate.py
uv run --project agent-service pytest agent-service/tests -q
mvn clean -Dtest='!NycReviewApplicationTests' test
cd nyc-review-web && npm run build
```

`NycReviewApplicationTests` 仍包含数据库与 Redis 数据构造逻辑，不要在承载有效数据的环境执行。真实 MySQL 验收后，可对 detail 查询执行 `EXPLAIN`，应看到 `tb_shop_map_location.idx_shop_map_location` 被 `MBRIntersects` 纳入候选索引；具体执行计划会随数据分布变化。
