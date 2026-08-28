# P6 Scaled Mock + NYC Open Data Runbook

P6 将可复现 Mock 扩展到中等规模，并接入一小部分真实商户身份数据。这里的“真实”只指纽约市公开数据中的名称、地址、行政区、坐标和菜系；NYC Review 的评论、博客、价格、评分、标签、营业时间、图片和优惠仍是合成演示内容，不代表真实顾客或商户声明。

## 1. 数据源与本地快照

仓库包含一份 2026-08-23 抓取、覆盖五区的 60 家商户小型快照：

```text
data/sources/nyc-open-data-restaurants-2026-08-23.json
```

来源是 NYC Department of Health and Mental Hygiene 的 `43nn-pn8j` 数据集。该数据集按检查违规项重复商户记录，抓取器会按稳定的 CAMIS 商户 ID 去重，并只保留每个商户最新窗口中的第一条有效记录。

如需刷新真实快照，可选配置 `NYC_OPEN_DATA_APP_TOKEN` 后执行：

```bash
python3 scripts/mock-data-generator/nyc_open_data.py \
  --count-per-borough 40 \
  --output data/sources/nyc-open-data-restaurants-$(date +%F).json
```

不要让生成器直接依赖当天 API 响应。先保存快照，再用固定快照生成数据，才能复现结果。

## 2. 生成中等规模混合数据

```bash
python3 scripts/mock-data-generator/generate.py \
  --profile medium \
  --seed 20260817 \
  --real-shops data/sources/nyc-open-data-restaurants-2026-08-23.json \
  --output data/generated/nyc-medium-hybrid

python3 scripts/mock-data-generator/validate_dataset.py \
  data/generated/nyc-medium-hybrid
```

预期为 `dataVersion=nyc-hybrid-v1`、2,000 家商户、16,000 条合成评论、五区完整覆盖，并显示 `NYC_OPEN_DATA` 与 `MOCK` 两类来源计数。`manifest.json` 还记录源快照 SHA-256；省略 `--real-shops` 会生成完全合成的 `nyc-mock-v2`。

## 3. 数据库迁移与导入

停止 Spring Boot 与 Agent Service，并确认目标是可替换数据的本地开发库。先执行一次 P6 迁移，再导入新数据：

```bash
mysql -u root -p nyc_review < src/main/resources/db/p8_p6_data_provenance.sql
mysql -u root -p nyc_review < data/generated/nyc-medium-hybrid/mysql_import.sql
redis-cli --pipe < data/generated/nyc-medium-hybrid/redis_seed.resp
redis-cli DEL cache:shopType:list
```

检查来源计数和唯一外部 ID：

```sql
SELECT source_type, COUNT(*) FROM tb_shop GROUP BY source_type;
SELECT COUNT(*) AS duplicate_external_ids
FROM (
  SELECT source_type, external_id
  FROM tb_shop
  GROUP BY source_type, external_id
  HAVING COUNT(*) > 1
) duplicated;
SELECT data_version, profile, shop_count, active
FROM tb_data_import
ORDER BY imported_at DESC;
```

## 4. 重建 RAG 并验证 Tool/MCP

Agent Service 必须指向与 MySQL 同一个生成目录。更换目录后重启服务会完整重建目标 Qdrant Collection：

```bash
cd agent-service
NYC_REVIEW_AGENT_ADAPTER=http \
NYC_REVIEW_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN='0b74cb58d8464601b024811f91b0fbcc' \
NYC_REVIEW_AGENT_RAG_ADAPTER=qdrant \
NYC_REVIEW_AGENT_QDRANT_LOCATION=./.local/qdrant-p6 \
NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-medium-hybrid \
uv run uvicorn app.main:app --port 8090
```

Spring 受限工具与 Agent 候选中的公开来源商户应包含 `sourceType/source_type=NYC_OPEN_DATA`、`externalId/external_id`、`sourceName/source_name`、`sourceUrl/source_url`、抓取时间和 `syntheticFields/synthetic_fields`。MCP 复用相同模型，因此 `search_shops` 与 `get_shop_detail` 也会返回这些字段；六个只读工具的安全边界不变。

## 5. UI 验收

- 英语和中文模式下，商户详情页都显示 `NYC Open Data` 或 `Mock data` 来源徽标。
- 公开来源商户的徽标可打开官方数据集页面。
- 页面明确说明哪些身份字段来自公开数据，哪些业务字段为合成内容。
- 评论区明确说明评论是生成测试内容。
- AI Guide 的候选卡显示商户来源，RAG 引用显示 `Synthetic evidence`，避免把生成评论误认为官方评价。

## 6. 自动化验证

```bash
python3 -m unittest scripts/mock-data-generator/test_generate.py
uv run --project agent-service pytest agent-service/tests -q
mvn clean -Dtest='!NycReviewApplicationTests' test
cd nyc-review-web && npm run build
```

`NycReviewApplicationTests` 仍包含数据库与 Redis 数据构造逻辑，不要在承载有效数据的环境执行。
