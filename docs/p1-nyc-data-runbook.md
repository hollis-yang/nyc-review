# P1 NYC 数据迁移 Runbook

P1 把确定性的 NYC Mock 数据同时送入 MySQL、Redis 和 Qdrant，并以 `shopId + dataVersion + datasetSha256` 约束三边身份。生成器不连接外部服务；真正修改数据的是后续显式导入命令。

## 1. 停止服务并确认环境

停止 Spring Boot、Agent Service 和任何会写入 MySQL/Redis 的本地进程。以下流程会替换 `hmdp_new` 中的活动业务数据，只应在开发或演示环境执行。不要在含有不可替代数据的库上直接运行。

确认 MySQL 数据库名、Redis 主机、端口和 DB 编号。Spring Data Redis 与 Redisson 默认都使用 Redis DB 0，导入时必须指向同一 DB。

## 2. 生成同源数据包

在仓库根目录执行：

```bash
python3 scripts/mock-data-generator/generate.py \
  --profile small \
  --seed 20260817 \
  --output data/generated/nyc-small
```

检查身份清单：

```bash
python3 -m json.tool data/generated/nyc-small/import_manifest.json
```

`small` 用于本地功能验证，`demo` 用于演示，`load` 仅用于专门的压测环境。

## 3. 准备 MySQL Schema

全新数据库按顺序执行四个脚本：

```bash
mysql -u root -p hmdp_new < src/main/resources/db/hmdp_new.sql
mysql -u root -p hmdp_new < src/main/resources/db/p2_redis_stream_order.sql
mysql -u root -p hmdp_new < src/main/resources/db/p3_nyc_compatibility.sql
mysql -u root -p hmdp_new < src/main/resources/db/p4_nyc_domain.sql
```

已经完成前三步的数据库只执行 `p4_nyc_domain.sql`。P4 是一次性增量迁移，新增子分类、标签、营业时间、纽约字段和导入审计表，不会主动删除现有数据。

## 4. 归档杭州数据并导入 NYC

```bash
mysql -u root -p hmdp_new < data/generated/nyc-small/mysql_import.sql
```

导入脚本首先创建 `legacy_hangzhou_tb_*` 表，并在 `tb_legacy_archive_state` 没有 `initial-hangzhou` 标记时复制一次当前活动数据。随后在事务内替换商户、用户、评论、博客、关注、优惠券和秒杀数据。再次执行同一导入包不会重复覆盖杭州归档。

验证 MySQL：

```sql
SELECT archive_key, archived_at FROM tb_legacy_archive_state;
SELECT data_version, profile, seed, dataset_sha256, shop_count, active
FROM tb_data_import ORDER BY imported_at DESC;
SELECT COUNT(*) AS shops, MIN(x) AS west, MAX(x) AS east FROM tb_shop;
SELECT COUNT(*) AS tags FROM tb_shop_tag;
SELECT COUNT(*) AS hours FROM tb_shop_business_hours;
SELECT COUNT(*) AS seckill_vouchers FROM tb_seckill_voucher;
```

`small` Profile 的期望值是 36 家商户、252 条营业时间和 3 张秒杀券；经度应为负数。

## 5. 初始化 Redis GEO 与秒杀库存

仍在服务停止状态下执行：

```bash
redis-cli --pipe < data/generated/nyc-small/redis_seed.resp
```

该脚本只清理本项目的数据派生键，重建 `shop:geo:1` 至 `shop:geo:6` 和 `seckill:stock:<voucherId>`，并清空待发布订单和历史订单流。它不会运行 `FLUSHDB`，也不会清理 `translate:*`，所以原翻译缓存与翻译功能边界保持不变。

验证 Redis：

```bash
redis-cli ZCARD shop:geo:1
redis-cli GET seckill:stock:9
redis-cli GET seckill:stock:10
redis-cli GET seckill:stock:11
redis-cli ZCARD seckill:pending:orders
```

具体秒杀券 ID 和库存以 `import_manifest.json`、`seckill_vouchers.json` 为准。秒杀仍由用户在前端手动触发，Agent Tool Catalog 不包含秒杀执行工具。

## 6. 验证 Spring Tool API

启动 Spring Boot 后执行：

```bash
curl -s -X POST http://127.0.0.1:8081/internal/agent/tools/shops/search \
  -H 'Content-Type: application/json' \
  -H 'authorization: replace-with-current-token' \
  -d '{"typeId":1,"requiredTags":["quiet"],"limit":2}'
```

把占位值替换为前端当前登录 token；header 使用原始 token，不加 `Bearer`。候选结果应包含 `shopId`、`subcategory`、`borough`、`tags`、`businessHours` 和 `dataVersion=nyc-mock-v1`。传统商户页面、博客、评论、关注、翻译和用户手动秒杀仍由 Spring Boot 提供。

## 7. 验证 Qdrant 与多 Agent

```bash
cd agent-service
HMDP_AGENT_ADAPTER=http \
HMDP_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
HMDP_AGENT_BACKEND_AUTH_TOKEN='replace-with-current-token' \
HMDP_AGENT_RAG_ADAPTER=qdrant \
HMDP_AGENT_QDRANT_LOCATION=./.local/qdrant \
HMDP_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-small \
uv run uvicorn app.main:app --port 8090
```

把 token 占位值替换为当前有效 token。Token 默认一小时过期；401 时重新登录并重启 Agent Service。启动时 Agent Service 会验证 shopId 清单并完整重建目标 Collection。在第二个终端调用预览接口：

```bash
curl -sS -X POST http://127.0.0.1:8090/v1/agent/runs/preview \
  -H 'Content-Type: application/json' \
  -d '{"mode":"multi","constraints":{"query":"quiet dinner in Chelsea","neighborhood":"Chelsea","category":"Food & Dining","desired_tags":["quiet"]}}' \
  | python3 -m json.tool
```

`small` 数据集应返回 Chelsea 的 `shopId=2`，并附带 RAG citations。响应 `metadata` 中应出现 `dataVersion=nyc-mock-v1`、`datasetSha256` 和 `indexedDocuments=324`；`events` 应展示 Supervisor、Discovery、Evidence、Itinerary 和 Verifier 的执行轨迹。Verifier 会把 citations 为空的 shopId 判为 `MISSING_EVIDENCE`，Qdrant 还会按 Spring 候选项的 `dataVersion` 过滤。

## 8. 自动化验证

回到仓库根目录后执行以下不连接真实 MySQL/Redis 的安全测试：

```bash
python3 -m unittest scripts/mock-data-generator/test_generate.py
uv run --project agent-service pytest agent-service/tests -q
mvn clean -Dtest='!HmDianPingApplicationTests' test
cd hmdp-react && npm run build
```

`HmDianPingApplicationTests` 含数据库和 Redis 数据构造逻辑，未完成容器化隔离前不要在承载有效数据的环境执行。
