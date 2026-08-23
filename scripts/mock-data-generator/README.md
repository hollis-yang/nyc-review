# NYC Mock Data Generator

生成可重复的 NYC 本地生活 Mock 数据。生成器只写入显式指定的输出目录，不连接 MySQL、Redis 或模型服务，因此生成动作本身不会修改正在运行的环境。

```bash
python3 scripts/mock-data-generator/generate.py \
  --profile small \
  --output /tmp/hmdp-nyc-small
```

支持的 Profile：

- `small`：36 家商户，用于单元测试和 Testcontainers。
- `demo`：250 家商户，用于产品演示和 Agent Eval。
- `medium`：2,000 家商户、16,000 条评论，用于更接近真实规模的演示和数据质量测试。
- `load`：20,000 家商户，用于按需压测，不应提交生成结果。

默认随机种子为 `20260817`。输出中的 `manifest.json` 记录 Profile、种子、数据版本、记录数量和每个文件的 SHA-256，可用于确认导入数据是否一致。

除业务 JSON 外，生成器还会输出：

- `mysql_import.sql`：首次运行时把当前传统业务表归档为 `legacy_hangzhou_tb_*`，然后事务化替换为 NYC 数据。重复导入同一数据集是安全的。
- `redis_seed.resp`：清理本项目的旧 GEO、缓存、Feed、点赞和秒杀派生键，重建 `shop:geo:*` 与 `seckill:stock:*`。它不执行 `FLUSHDB`，也不删除翻译缓存。
- `import_manifest.json`：记录 MySQL、Redis、Qdrant 共用的 shopId 列表、shopId SHA-256 与数据集 SHA-256。

P6 可先从 NYC Open Data 抓取一份本地快照，再生成混合数据：

```bash
python3 scripts/mock-data-generator/nyc_open_data.py \
  --count-per-borough 12 \
  --output data/sources/nyc-open-data-restaurants-2026-08-23.json

python3 scripts/mock-data-generator/generate.py \
  --profile medium \
  --real-shops data/sources/nyc-open-data-restaurants-2026-08-23.json \
  --output data/generated/nyc-medium-hybrid

python3 scripts/mock-data-generator/validate_dataset.py data/generated/nyc-medium-hybrid
```

`nyc-hybrid-v1` 中只把公开数据用于名称、地址、行政区、坐标和菜系；评论、博客、价格、评分、标签、营业时间、图片与优惠全部是合成数据。每个商户都包含 `sourceType`、`externalId`、`sourceName`、`sourceUrl`、`sourceFetchedAt` 和 `syntheticFields`。

应用迁移和导入包前必须停止 Spring Boot 与 Agent Service，并确认当前连接的是可替换数据的开发数据库：

```bash
mysql -u root -p hmdp_new < src/main/resources/db/p4_nyc_domain.sql
mysql -u root -p hmdp_new < src/main/resources/db/p8_p6_data_provenance.sql
mysql -u root -p hmdp_new < data/generated/nyc-small/mysql_import.sql
redis-cli --pipe < data/generated/nyc-small/redis_seed.resp
```

完整的首次初始化、验证查询和故障排查见 [P1 NYC 数据 Runbook](../../docs/p1-nyc-data-runbook.md)。

不使用 `--real-shops` 时，数据中的商户身份与业务内容均为虚构。使用该参数时，只有上述公开身份字段真实，所有用户和业务内容仍为合成内容。评论中会有少量带 `security_test` 标记的 Prompt Injection 样本，用于验证 RAG 不会把用户内容当作系统指令。完整流程见 [P6 Runbook](../../docs/p6-hybrid-data-runbook.md)。

## P7 官方 NTA 地理派生数据

P7 使用固定版本与 SHA-256 的 NYC 2020 NTA GeoJSON，为现有生成数据建立官方 neighborhood code、空间点位和类别聚合。原始 polygon 按需下载，hash 不一致时失败关闭：

```bash
python3 scripts/mock-data-generator/nyc_nta.py fetch \
  --output data/sources/nyc-nta-2020-26b.geojson

python3 scripts/mock-data-generator/build_neighborhood_import.py \
  --dataset data/generated/nyc-medium-hybrid \
  --nta-snapshot data/sources/nyc-nta-2020-26b.geojson \
  --output data/generated/nyc-medium-hybrid/p7_neighborhood_import.sql
```

导入包只包含可重建的地图派生数据。它不覆盖 `tb_shop.area`，因此 Agent 的 `Midtown` 等 friendly-area 约束保持不变；地图通过 `tb_shop.neighborhood_code` 和 `tb_shop_map_location` 使用官方 NTA。未落入 polygon 的 Mock 点标记为 `UNASSIGNED`，不会静默分配到最近社区。完整来源、表契约、Docker 和验收步骤见 [P7 Map Runbook](../../docs/p7-map-geospatial-runbook.md)。
