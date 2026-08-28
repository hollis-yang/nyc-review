# NYC Data Generator

生成可重复的 NYC 本地生活数据集。脚本只写入显式指定的输出目录，不连接 MySQL、Redis、Qdrant 或模型服务，因此生成动作本身不会修改正在运行的环境。

## Profile

- `small`：36 家全 Mock 商户，用于单元测试和 Testcontainers。
- `demo`：250 家全 Mock 商户，用于历史演示和 Agent Eval。
- `medium`：2,000 家全 Mock 商户、16,000 条评论，用于 P6 以前的规模测试。
- `load`：20,000 家全 Mock 商户，用于按需压测。
- `real-small`：12 家真实身份商户、60 条根评论，用于 P8 快速契约测试。
- `real-medium`：5,000 家真实身份商户、100,000 条根评论，用于当前完整演示。
- `real-large`：10,000 家真实身份商户、200,000 条根评论，用于扩展验证。
- `real-load`：15,000 家真实身份商户、300,000 条根评论，用于按需压测。

P8 Profile 中的评论数量指有 1–5 星评分的 depth-0 根评论；生成器还会确定性增加 depth-1 和 depth-2 回复。默认随机种子为 `20260817`。`manifest.json` 记录 Profile、种子、数据版本、来源快照、记录数量和每个数据文件的 SHA-256；`import_manifest.json` 记录 MySQL、Redis 与 Qdrant 共用的 shopId 清单和 SHA-256。

## P8 Real-only 数据集

当前本地 P8 数据集固定以下两个输入快照；大体积 OSM JSON 与生成目录被 Git 忽略，仓库保留可审计的 sidecar、抓取脚本和小型图片目录，因此新工作区需先按下文抓取 OSM 数据：

- `data/sources/osm-nyc-places-2026-08-23.json`：OpenStreetMap/Overpass 的 NYC 命名商户身份与位置，使用 ODbL 1.0，覆盖六个产品分类。
- `data/sources/wikimedia-illustrative-images-v1.json`：Wikimedia Commons 分类示意图目录，每条记录保留文件页、作者和许可。

用固定输入复现当前 5,000 家商户数据集：

```bash
python3 scripts/mock-data-generator/generate.py \
  --profile real-medium \
  --real-places data/sources/osm-nyc-places-2026-08-23.json \
  --illustrative-images data/sources/wikimedia-illustrative-images-v1.json \
  --output data/generated/nyc-real-medium

python3 scripts/mock-data-generator/validate_dataset.py \
  data/generated/nyc-real-medium

python3 scripts/mock-data-generator/build_neighborhood_import.py \
  --dataset data/generated/nyc-real-medium \
  --nta-snapshot data/sources/nyc-nta-2020-26b.geojson \
  --output data/generated/nyc-real-medium/p7_neighborhood_import.sql
```

最后一条命令是导入的必要前置步骤，不是可选的地图演示：它会生成手动 SQL 流程和 `compose.local.yml` 共同读取的 P7 投影。如果本机缺少固定的 NTA 快照，请先使用下方 `nyc_nta.py fetch` 命令获取。

`validate_dataset.py` 会失败关闭地校验 `merchantIdentityMode=REAL_ONLY`、`mockShops=0`、六分类覆盖、外部 ID 和显示身份唯一性、五区/官方 NTA 归属、来源字段、图片署名与许可、评论树完整性、1–5 星覆盖、价格/评分/检索标签完整性、每家 7 天营业时间、根评论计数、博客/博客评论/优惠券的内部来源类型和字段长度。

如需刷新公开来源快照，可显式联网执行下面命令；刷新会改变来源时间和 SHA-256，完成审核后才能替换固定文件：

```bash
python3 scripts/mock-data-generator/osm_places.py \
  --nta-snapshot data/sources/nyc-nta-2020-26b.geojson \
  --output data/sources/osm-nyc-places-2026-08-23.json

python3 scripts/mock-data-generator/wikimedia_images.py \
  --images-per-type 3 \
  --output data/sources/wikimedia-illustrative-images-v1.json
```

### 来源边界

- 真实且来源可回溯：商户名称、地址、坐标、Borough、NTA neighborhood、六分类映射、可验证的 OSM 标签和外部 ID。
- 图片补全：Wikimedia 图片按分类近似匹配并可能被多家商户复用；来源与许可保留在后端资源表中，产品界面直接显示图片。
- 平台内容：用户、根评论、一级/二级回复、评分、情感/主题标签、博客、博客评论、优惠券、秒杀券、收藏和其他平台活动由种子生成。这些记录在 JSON、MySQL 与 API 中仍携带内部 `sourceType/source_type`；界面只显示内容本身。评论包含不同星级、正/中/负情感、主题和少量 `securityTest` 样本。应用内新建博客和评论仍由服务端写为 `USER_SUBMITTED`。
- 缺失字段补全：营业时间优先解析 OSM `opening_hours`，不支持或缺失时按类别补全；人均价格按类别、细分类、Borough 与稳定扰动估算；评分只从根评论计算，回复不参与平均分；检索标签由显式 OSM 标签和稳定属性共同组成。

因此 P8 的 “Real-only” 专指活动数据中不混入虚构商户身份，不表示评论或示意图片来自真实顾客和对应商户。

## 导入包

数据生成器会输出前两项；地图构建脚本会输出第三项：

- `mysql_import.sql`：事务化替换 NYC 业务数据；重复导入同一数据集是安全的，不负责创建或升级表结构。
- `redis_seed.resp`：只清理本项目的旧 GEO、缓存、Feed、点赞、秒杀派生键，以及会因实体 ID 复用而失效的商户/评价/博客翻译缓存，再重建 `shop:geo:*` 与 `seckill:stock:*`；不执行 `FLUSHDB`，并保留以内容 SHA-256 为键的任意文本翻译缓存。
- `p7_neighborhood_import.sql`：从固定 NTA polygon 重建地图位置和聚合投影。

应用导入包前先阻止新的秒杀流量，同时保持 Spring RabbitMQ consumer 运行，直到订单/错误队列和 Redis pending 索引均为空；随后停止 Spring Boot 与 Agent Service，并确认当前连接的是可替换数据的开发数据库。已有环境先备份并执行 `src/main/resources/db/migrations/` 中尚未应用的迁移，再导入数据、地图投影和 Redis seed：

```bash
mysql -u root -p nyc_review < data/generated/nyc-real-medium/mysql_import.sql
mysql -u root -p nyc_review < data/generated/nyc-real-medium/p7_neighborhood_import.sql
redis-cli --pipe < data/generated/nyc-real-medium/redis_seed.resp
redis-cli DEL cache:shopType:list
```

全新数据库无需逐条重放历史迁移，依次导入 `bootstrap-schema.sql`、数据 SQL、地图 SQL，并执行 Redis seed。`bootstrap-schema.sql` 仅适用于空数据库；已有数据库不得覆盖导入。

## P6 Hybrid 历史 Profile

P6 混合数据仍可用于回归：

```bash
python3 scripts/mock-data-generator/nyc_open_data.py \
  --count-per-borough 12 \
  --output data/sources/nyc-open-data-restaurants-2026-08-23.json

python3 scripts/mock-data-generator/generate.py \
  --profile medium \
  --real-shops data/sources/nyc-open-data-restaurants-2026-08-23.json \
  --output data/generated/nyc-medium-hybrid

python3 scripts/mock-data-generator/validate_dataset.py \
  data/generated/nyc-medium-hybrid
```

`nyc-hybrid-v1` 只有部分餐厅身份来自 NYC Open Data，其余商户和全部业务内容是合成数据；它不满足 P8 的 `REAL_ONLY` 门禁。

## P7 官方 NTA 地理派生数据

P7 使用固定版本与 SHA-256 的 NYC 2020 NTA GeoJSON 建立 neighborhood code、空间点位和类别聚合。P8 OSM 规范化阶段已经执行 point-in-polygon；需要单独重建地图 SQL 时可运行：

```bash
python3 scripts/mock-data-generator/nyc_nta.py fetch \
  --output data/sources/nyc-nta-2020-26b.geojson

python3 scripts/mock-data-generator/build_neighborhood_import.py \
  --dataset data/generated/nyc-real-medium \
  --nta-snapshot data/sources/nyc-nta-2020-26b.geojson \
  --output data/generated/nyc-real-medium/p7_neighborhood_import.sql
```

该导入包只重建可派生地图数据，不覆盖 `tb_shop.area`。
