# hm-dianping

黑马点评 NYC AI 全栈改造项目。Spring Boot、MySQL、Redis 与 RabbitMQ 承载传统业务和手动秒杀；React 提供 NYC 地图与 AI 工作台；独立的 FastAPI + LangGraph 服务负责多 Agent、Qdrant RAG、Trace 和 Eval。

架构边界与不可回退能力见 [目标架构](docs/target-architecture.md) 和 [验收标准](docs/acceptance-criteria.md)。
当前完成状态与后续实施顺序见 [实施路线](docs/implementation-roadmap.md)、[P10–P17 路线图](docs/p10-p17-roadmap.md) 和 [P10/P11 全量数据 Runbook](docs/p10-p11-full-enrichment-runbook.md)。

## 环境要求

- Java 17
- Maven 3.9+
- MySQL 8+
- Redis 6+
- RabbitMQ 4+
- Node.js 20+
- npm 10+
- Nginx（仅部署时需要）
- Python 3.11+ 与 `uv`（Agent Service）

## 本地配置

应用不会在仓库中保存数据库密码或第三方 API Key。先创建本地环境文件：

```bash
cp .env.example .env
```

编辑 `.env`，填入本机数据库密码和 DeepSeek API Key。从项目根目录启动时，Spring Boot 会通过 `spring.config.import` 自动读取该文件，无需手动执行 `source`。操作系统环境变量的优先级高于 `.env`，因此部署环境仍可直接注入同名变量覆盖本地值。

环境变量说明：

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `HMDP_DB_URL` | 否 | JDBC 地址，默认连接本机 `hmdp_new` 数据库 |
| `HMDP_DB_USERNAME` | 否 | 数据库用户名，默认 `root` |
| `HMDP_DB_PASSWORD` | 是 | 数据库密码，无默认值 |
| `HMDP_REDIS_HOST` | 否 | Redis 地址，默认 `localhost` |
| `HMDP_REDIS_PORT` | 否 | Redis 端口，默认 `6379` |
| `HMDP_REDIS_DATABASE` | 否 | Redis 数据库编号，默认 `0` |
| `HMDP_REDIS_USERNAME` | 否 | Redis ACL 用户名，默认空 |
| `HMDP_REDIS_PASSWORD` | 否 | Redis 密码，默认空 |
| `HMDP_RABBITMQ_HOST` | 否 | RabbitMQ 地址，默认 `localhost` |
| `HMDP_RABBITMQ_PORT` | 否 | AMQP 端口，默认 `5672` |
| `HMDP_RABBITMQ_USERNAME` | 否 | RabbitMQ 用户名，本地默认 `guest` |
| `HMDP_RABBITMQ_PASSWORD` | 否 | RabbitMQ 密码，本地默认 `guest` |
| `DEEPSEEK_API_KEY` | 是 | DeepSeek API Key，无默认值 |
| `DEEPSEEK_MODEL` | 否 | 翻译与 Agent 模型，默认 `deepseek-chat` |
| `DEEPSEEK_BASE_URL` | 否 | DeepSeek OpenAI-compatible API 地址 |
| `HMDP_IMAGE_UPLOAD_DIR` | 否 | 用户图片保存目录，默认 `./uploads/imgs`；Nginx 部署时应指向其图片目录 |

`.env` 和 `application-local.yaml` 已被 Git 忽略。`.env` 自动导入依赖当前工作目录；请从项目根目录启动后端。不要把真实凭据写入 `.env.example`、`application.yaml`、README 或提交记录。

## 初始化数据

创建 `hmdp_new` 数据库后导入当前数据集：

```bash
mysql -u root -p hmdp_new < src/main/resources/db/hmdp_new.sql
```

默认 Redis 地址为 `localhost:6379`，统一使用数据库编号 `0`。Spring Data Redis 与 Redisson 共用同一套连接配置。部分 GEO、秒杀库存和 Feed 数据需要按项目初始化流程写入 Redis；不要直接运行整个测试类，因为其中包含清表和测试数据回填操作。

全新数据库在基础 SQL 后按顺序执行秒杀、NYC、Agent、P4 Memory、地图和 P8 内容迁移：

```bash
mysql -u root -p hmdp_new < src/main/resources/db/p2_redis_stream_order.sql
mysql -u root -p hmdp_new < src/main/resources/db/p3_nyc_compatibility.sql
mysql -u root -p hmdp_new < src/main/resources/db/p4_nyc_domain.sql
mysql -u root -p hmdp_new < src/main/resources/db/p5_agent_actions.sql
mysql -u root -p hmdp_new < src/main/resources/db/p6_rabbitmq_profile_memory.sql
mysql -u root -p hmdp_new < src/main/resources/db/p7_p5_mcp_ui.sql
mysql -u root -p hmdp_new < src/main/resources/db/p8_p6_data_provenance.sql
mysql -u root -p hmdp_new < src/main/resources/db/p9_p7_map_geospatial.sql
mysql -u root -p hmdp_new < src/main/resources/db/p10_p8_real_content.sql
redis-cli DEL cache:shopType:list
```

`p8_p6_data_provenance.sql` 不是可重复迁移。已经完成 P6/P7 的数据库不得再次执行 P8/P9；升级现有环境时只补 P10，然后切换活动数据和重建 P7 地图投影。

当前集成数据集是 `real-medium`：5,000 个商户身份全部来自固定的 OpenStreetMap NYC 快照，覆盖六个分类，不混入虚构商户。使用当前工作区已固定的 OSM 与 Wikimedia 快照可重复生成；若 OSM 原始快照不存在，先按 P8 Runbook 联网抓取并核对 sidecar SHA-256：

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

如果本机尚无固定的 NTA 快照，请先按 [P8 Real-only Data Runbook](docs/p8-real-data-runbook.md) 中的命令获取。最后一条地图构建命令不是可选步骤：手动导入和 `docker-compose.p4.yml` 都会读取该 P7 投影文件。

生成结果包含 5,000 家真实身份商户、100,000 条合成根评论及 52,500 条一、二级回复、博客、普通优惠券、必须手动参与的秒杀券，以及 MySQL/Redis 导入包。图片来自 Wikimedia Commons，是按分类复用并带许可和署名的示意图，不是对应商户实景；评论、评分、博客、用户、优惠和平台行为全部是明确标记的合成内容。OSM 未提供的价格与营业时间保持为空，不会伪造。

生成动作不会连接数据库。现有 P6/P7 环境在生成完成后执行下面命令；全新库已经按上文执行过 P10，也可安全重复执行 P10，再使用相同的数据切换步骤：

```bash
mysql -u root -p hmdp_new < src/main/resources/db/p10_p8_real_content.sql
mysql -u root -p hmdp_new < data/generated/nyc-real-medium/mysql_import.sql
mysql -u root -p hmdp_new < data/generated/nyc-real-medium/p7_neighborhood_import.sql
redis-cli --pipe < data/generated/nyc-real-medium/redis_seed.resp
redis-cli DEL cache:shopType:list
```

这些导入命令会归档首次导入前的传统数据并替换开发环境中的活动数据。先阻止新的秒杀请求，同时保持 Spring RabbitMQ consumer 运行，直到订单/错误队列和 Redis pending 索引均为空；随后再停止 Spring Boot 与 Agent Service，并确认目标实例可以被替换。小型 Mock 和 P6 混合 Profile 仍保留用于历史回归与单元测试，但不再是当前 Compose 的活动数据。完整生成、迁移、验证与回滚边界见 [P8 Real Data Runbook](docs/p8-real-data-runbook.md)，Profile 细节见 [NYC 数据生成器](scripts/mock-data-generator/README.md)。

只需快速运行 Mock 单元夹具时仍可生成 `small`：

```bash
python3 scripts/mock-data-generator/generate.py \
  --profile small \
  --output data/generated/nyc-small
```

## 启动后端

确认 MySQL、Redis、RabbitMQ 和环境变量均已就绪：

```bash
mvn spring-boot:run
```

后端默认监听 `http://127.0.0.1:8081`。

## 启动多 Agent 与 RAG

```bash
cd agent-service
uv sync --dev
HMDP_AGENT_ADAPTER=http \
HMDP_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
HMDP_AGENT_BACKEND_AUTH_TOKEN='<current-user-token>' \
HMDP_AGENT_RAG_ADAPTER=qdrant \
HMDP_AGENT_QDRANT_LOCATION=http://127.0.0.1:6333 \
HMDP_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-real-medium \
HMDP_AGENT_RAG_INDEX_BATCH_SIZE=128 \
HMDP_AGENT_MODEL_PROVIDER=deepseek \
uv run uvicorn app.main:app --reload --port 8090
```

配置 `HMDP_AGENT_RAG_DATA_DIRECTORY` 后，Agent Service 会拒绝混入 Mock 商户或缺少六分类的 P8 清单，并使用同一组 shopId、`dataVersion` 和 SHA-256 增量同步 Qdrant；未变化文档按内容哈希跳过，不再每次完整重建。HTTP Adapter 必须使用当前登录 token，否则 Spring Tool API 返回 401。`HMDP_AGENT_MODEL_PROVIDER=deepseek` 会复用 `DEEPSEEK_API_KEY`，未配置或模型不可用时默认受控回退到离线约束解析器。完整配置与 Run/SSE 验证见 [Agent Service README](agent-service/README.md) 和 [P2 Runbook](docs/p2-agent-runbook.md)。模型 Tool Catalog 不包含 `seckill_voucher`，因此 Agent 不能代替用户秒杀。

P3 增加人工审批操作、幂等执行、MySQL 审计、收藏偏好、Run 历史与指标；React 默认英语，可在 `Profile → Edit Profile` 切换中文，DeepSeek 翻译入口只在中文模式显示。迁移、接口和 Docker Compose 验证见 [P3 Runbook](docs/p3-agent-actions-runbook.md)。

P4 将秒杀 MQ 从 Redis Stream 迁移到 RabbitMQ，并增加 Publisher Confirm、Redis 生产侧恢复记录、消费重试和错误队列；Profile 可查看收藏、行程、优惠券、提醒和可控 AI Memory；Agent 增加所有权隔离、Prompt Guard、限流、Trace、Token/延迟指标、超时恢复和自动质量门禁。见 [P4 Runbook](docs/p4-production-agent-runbook.md)。

P5 在 Agent Service 的 `/mcp` 提供 Streamable HTTP MCP Server，复用 Spring Tool API、Qdrant RAG、路线估算与 Verifier，并且只暴露六个只读工具。收藏、保存、领券和秒杀不会通过 MCP 执行。接入本地 coding agent harness 与协议验证见 [P5 MCP Runbook](docs/p5-mcp-runbook.md)。

P6 增加 2,000 家商户的可复现 `medium` Profile，并将一份覆盖纽约五区的 NYC Open Data 餐厅身份快照与合成业务数据组合为 `nyc-hybrid-v1`。来源、外部 ID、抓取时间与合成字段清单贯穿 MySQL、Spring、Agent、Qdrant、MCP 和双语 UI；所有生成评论均明确标注，不能被误认为真实评价。生成、迁移和验收见 [P6 Hybrid Data Runbook](docs/p6-hybrid-data-runbook.md)。

P7 将地图升级为面向大数据量的 viewport 查询：Spring `/shop/map` 根据缩放级别返回 Borough 总数、Neighborhood 聚合或轻量商户 Marker，支持多类别筛选、高密度降级和空间索引；React 地图随拖动/缩放防抖请求，处理并发乱序，并在桌面端与移动端逐级展开聚合。数据层固定 NYC 2020 NTA `26b` 官方 polygon 与 SHA-256；P7 最初为 2,000 家商户生成归属，P8 已用同一契约重建 5,000 家真实身份商户的 point-in-polygon 位置和导入审计。原有 `area` 保留给 Agent friendly-area 约束；未匹配点不会被伪造成最近社区。见 [P7 Map Geospatial Runbook](docs/p7-map-geospatial-runbook.md)。

P8 将活动数据切换为 `nyc-real-v1`：5,000 个商户身份全部取自固定、可校验的 OpenStreetMap 快照，六分类均有覆盖且 `mockShops=0`。P10 增加图片许可、评论线程，以及博客、博客评论和优惠券的内部内容来源字段；这些审计字段不会作为说明性标签显示在产品界面。`real-medium` 生成 100,000 条根评论和 52,500 条回复，评分只由根评论计算；评论会结合具体商户、社区、价格、主题和检索标签生成不同表述，Agent 优先选择不重复的评论线程作为 RAG 证据，并按内容哈希、批次、数据版本和数据集 SHA 增量同步 Qdrant。营业时间优先解析 OSM `opening_hours`，其余时段按类别稳定补全；人均价格按类别、细分类和 Borough 估算，检索标签也会在显式 OSM 属性之外进行稳定补全。

使用集成 Compose 前先生成 `nyc-real-medium`，并将当前用户登录 token 传给 Agent Service；缺少该变量时 Agent 的 HTTP Adapter 调用 Spring Tool API 会返回 401：

```bash
export HMDP_AGENT_BACKEND_AUTH_TOKEN='<current-user-token>'
docker compose -f docker-compose.p4.yml up --build
```

Compose 中的 MySQL init 脚本只会在全新的空 volume 上运行；已有 P6/P7 volume 应先按上面的“现有环境”命令手工升级，不能通过重复执行 P8 迁移来追平。不要将登录 token 写入受版本控制的文件。

## 启动前端开发环境

```bash
cd hmdp-react
npm ci
npm run dev
```

Vite 默认监听 `http://127.0.0.1:3000`，将 `/api` 代理到 Spring Boot 8081，并将 `/agent-api` 代理到 Agent Service 8090。AI 工作台位于 `/ai`。

生产构建：

```bash
cd hmdp-react
npm run build
```

构建结果位于 `hmdp-react/dist`。

## Nginx 部署

当前桌面部署约定为：

- React 静态资源：`nginx-1.18.0/html/hmdp-react`
- 用户上传图片：`nginx-1.18.0/html/hmdp/imgs`
- Nginx 监听端口：`8080`
- Spring Boot 上游端口：`8081`

部署到 Nginx 时，请将 `HMDP_IMAGE_UPLOAD_DIR` 设置为上述用户图片目录的绝对路径。上传接口仅接受 JPEG、PNG 和 WebP，单文件最大 5MB。

将 `hmdp-react/dist` 中的内容部署到 React 静态资源目录后，检查并重新加载 Nginx 配置。SPA 路由需要保留 `try_files $uri $uri/ /index.html`，API 请求需要把 `/api` 前缀代理到 Spring Boot。

## 验证

```bash
cd hmdp-react
npm run build
npm run lint
```

后端测试类目前包含数据构造和 Redis 回填方法，在完成测试隔离前，不要对包含真实数据的数据库直接执行完整 `mvn test`。

## 安全说明

- 真实密钥如果曾进入 Git 历史，应立即在对应服务中轮换。
- 从当前文件删除密钥不会自动清除历史提交中的副本。
- Git 历史清理会改写提交历史，需要单独评估并协调所有协作者。
