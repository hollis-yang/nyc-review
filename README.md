# NYC Review

NYC Review（纽约点评）是面向纽约本地生活的 AI 全栈项目。Spring Boot、MySQL、Redis 与 RabbitMQ 承载传统业务和手动秒杀；React 提供 NYC 地图与 AI 工作台；独立的 FastAPI + LangGraph 服务负责多 Agent、Qdrant RAG、Trace 和 Eval。

仓库只保留可执行的业务代码、测试、数据流水线和部署配置。项目说明分别收敛在本 README、[Agent Service README](agent-service/README.md)、[脚本目录说明](scripts/README.md)、[数据生成器 README](scripts/mock-data-generator/README.md) 与 [生产部署 README](deploy/production/README.md)；阶段计划、生成数据和测试报告均为本地文件，不进入 Git。

面向 4 GB AWS Lightsail 的单机生产部署使用预构建 GHCR 镜像、单 Agent、
仅 80/443 公网入口和服务器外置 P13 数据包。完整步骤见
[生产部署 Runbook](deploy/production/README.md)，不要在服务器上运行开发用的
`compose.local.yml`。

## Docker Compose 入口

仓库只保留三个用途互不重叠的 Compose 文件：

| 文件 | 用途 | 是否操作日常数据 |
| --- | --- | --- |
| `compose.local.yml` | 本地全栈开发，现场构建 Spring、Agent 与 Web | 使用 `NYC_REVIEW_DATA_DIR` 指定的本地数据包 |
| `compose.load-test.yml` | 隔离的 k6/Prometheus 后端压测与故障演练 | 否，使用独立端口、数据库、队列和 Volume |
| `compose.production.yml` | 服务器正式部署，拉取固定版本镜像并由 Caddy 对外服务 | 是，只能配合生产环境变量和备份流程使用 |

旧的 `docker-compose.p3.yml` 已淘汰；原 P4 与 P14.1 文件只是上述本地、压测环境的阶段命名，现已按实际用途重命名。

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
| `NYC_REVIEW_DB_URL` | 否 | JDBC 地址，默认连接本机 `nyc_review` 数据库 |
| `NYC_REVIEW_DB_USERNAME` | 否 | 数据库用户名，默认 `root` |
| `NYC_REVIEW_DB_PASSWORD` | 是 | 数据库密码，无默认值 |
| `NYC_REVIEW_REDIS_HOST` | 否 | Redis 地址，默认 `localhost` |
| `NYC_REVIEW_REDIS_PORT` | 否 | Redis 端口，默认 `6379` |
| `NYC_REVIEW_REDIS_DATABASE` | 否 | Redis 数据库编号，默认 `0` |
| `NYC_REVIEW_REDIS_USERNAME` | 否 | Redis ACL 用户名，默认空 |
| `NYC_REVIEW_REDIS_PASSWORD` | 否 | Redis 密码，默认空 |
| `NYC_REVIEW_RABBITMQ_HOST` | 否 | RabbitMQ 地址，默认 `localhost` |
| `NYC_REVIEW_RABBITMQ_PORT` | 否 | AMQP 端口，默认 `5672` |
| `NYC_REVIEW_RABBITMQ_USERNAME` | 否 | RabbitMQ 用户名，本地默认 `guest` |
| `NYC_REVIEW_RABBITMQ_PASSWORD` | 否 | RabbitMQ 密码，本地默认 `guest` |
| `DEEPSEEK_API_KEY` | 是 | DeepSeek API Key，无默认值 |
| `DEEPSEEK_MODEL` | 否 | 翻译与 Agent 模型，默认 `deepseek-chat` |
| `DEEPSEEK_BASE_URL` | 否 | DeepSeek OpenAI-compatible API 地址 |
| `NYC_REVIEW_IMAGE_UPLOAD_DIR` | 否 | 用户图片保存目录，默认 `./uploads/imgs`；Nginx 部署时应指向其图片目录 |

`.env` 和 `application-local.yaml` 已被 Git 忽略。`.env` 自动导入依赖当前工作目录；请从项目根目录启动后端。不要把真实凭据写入 `.env.example`、`application.yaml`、README 或提交记录。

## 初始化数据

全新环境只需要按顺序导入三份 MySQL 文件：当前空结构、外置业务数据和地图投影。Compose 会自动执行同样的顺序：

```bash
mysql -u root -p nyc_review < src/main/resources/db/bootstrap-schema.sql
mysql -u root -p nyc_review < data/generated/nyc-real-p13-full/mysql_import.sql
mysql -u root -p nyc_review < data/generated/nyc-real-p13-full/p7_neighborhood_import.sql
redis-cli --pipe < data/generated/nyc-real-p13-full/redis_seed.resp
```

默认 Redis 地址为 `localhost:6379`，统一使用数据库编号 `0`。Spring Data Redis 与 Redisson 共用同一套连接配置。部分 GEO、秒杀库存和 Feed 数据需要按项目初始化流程写入 Redis；不要直接运行整个测试类，因为其中包含清表和测试数据回填操作。

`bootstrap-schema.sql` 是从完整迁移链生成的最新空结构，不含杭州种子、legacy 表或业务数据。已有数据库禁止导入这份文件；升级时只执行 `src/main/resources/db/migrations/` 中尚未应用的迁移，并在操作前备份。

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

如果本机尚无固定的 NTA 快照，请按 [NYC 数据生成器](scripts/mock-data-generator/README.md) 中的抓取命令生成。最后一条地图构建命令不是可选步骤：手动导入和 `compose.local.yml` 都会读取该 P7 投影文件。

生成结果包含 5,000 家真实身份商户、100,000 条合成根评论及 52,500 条一、二级回复、博客、普通优惠券、必须手动参与的秒杀券，以及 MySQL/Redis 导入包。优惠券按商户互斥分配：60% 商户有普通券、30% 商户有秒杀券，总覆盖率 90%。图片来自 Wikimedia Commons，是按分类复用并带许可和署名的示意图，不是对应商户实景；评论、评分、博客、用户、优惠和平台行为全部是明确标记的合成内容。OSM 未提供的价格与营业时间保持为空，不会伪造。

生成动作不会连接数据库。切换已有开发环境的数据前，应先确认结构迁移已经完成，再执行数据、地图与 Redis 导入：

```bash
mysql -u root -p nyc_review < data/generated/nyc-real-medium/mysql_import.sql
mysql -u root -p nyc_review < data/generated/nyc-real-medium/p7_neighborhood_import.sql
redis-cli --pipe < data/generated/nyc-real-medium/redis_seed.resp
redis-cli DEL cache:shopType:list
```

这些导入命令会替换开发环境中的活动数据。先阻止新的秒杀请求，同时保持 Spring RabbitMQ consumer 运行，直到订单/错误队列和 Redis pending 索引均为空；随后再停止 Spring Boot 与 Agent Service，并确认目标实例可以被替换。小型 Mock 和 P6 混合 Profile 仍保留用于历史回归与单元测试，但不再是当前 Compose 的活动数据。Profile、生成和校验细节见 [NYC 数据生成器](scripts/mock-data-generator/README.md)。

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

认证采用密码登录与独立注册页，手机号在后端校验并规范化为 E.164，新增密码使用 BCrypt；短信验证码入口已停用。已有数据库需先执行 `src/main/resources/db/migrations/015_password_auth_registration.sql`，再同时更新 Spring 与 Web。

## 启动多 Agent 与 RAG

```bash
cd agent-service
uv sync --dev
NYC_REVIEW_AGENT_ADAPTER=http \
NYC_REVIEW_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN='<current-user-token>' \
NYC_REVIEW_AGENT_RAG_ADAPTER=qdrant \
NYC_REVIEW_AGENT_QDRANT_LOCATION=http://127.0.0.1:6333 \
NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-real-medium \
NYC_REVIEW_AGENT_RAG_INDEX_BATCH_SIZE=128 \
NYC_REVIEW_AGENT_MODEL_PROVIDER=deepseek \
uv run uvicorn app.main:app --reload --port 8090
```

配置 `NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY` 后，Agent Service 会拒绝混入 Mock 商户或缺少六分类的 P8 清单，并使用同一组 shopId、`dataVersion` 和 SHA-256 增量同步 Qdrant；未变化文档按内容哈希跳过，不再每次完整重建。HTTP Adapter 必须使用当前登录 token，否则 Spring Tool API 返回 401。`NYC_REVIEW_AGENT_MODEL_PROVIDER=deepseek` 会复用 `DEEPSEEK_API_KEY`，未配置或模型不可用时默认受控回退到离线约束解析器。完整配置与 Run/SSE 验证见 [Agent Service README](agent-service/README.md)。模型 Tool Catalog 不包含 `seckill_voucher`，因此 Agent 不能代替用户秒杀。

P3 增加人工审批操作、幂等执行、MySQL 审计、收藏偏好、Run 历史与指标；React 默认英语，可在 `Profile → Edit Profile` 切换中文，DeepSeek 翻译入口只在中文模式显示。

P4 将秒杀 MQ 从 Redis Stream 迁移到 RabbitMQ，并增加 Publisher Confirm、Redis 生产侧恢复记录、消费重试和错误队列；Profile 可查看收藏、行程、优惠券、提醒和可控 AI Memory；Agent 增加所有权隔离、Prompt Guard、限流、Trace、Token/延迟指标、超时恢复和自动质量门禁。

P5 在 Agent Service 的 `/mcp` 提供 Streamable HTTP MCP Server，复用 Spring Tool API、Qdrant RAG、路线估算与 Verifier，并且只暴露六个只读工具。收藏、保存、领券和秒杀不会通过 MCP 执行；协议验证命令位于 [Agent Service README](agent-service/README.md)。

P6 增加 2,000 家商户的可复现 `medium` Profile，并将一份覆盖纽约五区的 NYC Open Data 餐厅身份快照与合成业务数据组合为 `nyc-hybrid-v1`。来源、外部 ID、抓取时间与合成字段清单贯穿 MySQL、Spring、Agent、Qdrant、MCP 和双语 UI；所有生成评论均明确标注，不能被误认为真实评价。

P7 将地图升级为面向大数据量的 viewport 查询：Spring `/shop/map` 根据缩放级别返回 Borough 总数、Neighborhood 聚合或轻量商户 Marker，支持多类别筛选、高密度降级和空间索引；React 地图随拖动/缩放防抖请求，处理并发乱序，并在桌面端与移动端逐级展开聚合。数据层固定 NYC 2020 NTA `26b` 官方 polygon 与 SHA-256；P7 最初为 2,000 家商户生成归属，P8 已用同一契约重建 5,000 家真实身份商户的 point-in-polygon 位置和导入审计。原有 `area` 保留给 Agent friendly-area 约束；未匹配点不会被伪造成最近社区。

P8 将活动数据切换为 `nyc-real-v1`：5,000 个商户身份全部取自固定、可校验的 OpenStreetMap 快照，六分类均有覆盖且 `mockShops=0`。P10 增加图片许可、评论线程，以及博客、博客评论和优惠券的内部内容来源字段；这些审计字段不会作为说明性标签显示在产品界面。`real-medium` 生成 100,000 条根评论和 52,500 条回复，评分只由根评论计算；评论会结合具体商户、社区、价格、主题和检索标签生成不同表述，Agent 优先选择不重复的评论线程作为 RAG 证据，并按内容哈希、批次、数据版本和数据集 SHA 增量同步 Qdrant。营业时间优先解析 OSM `opening_hours`，其余时段按类别稳定补全；人均价格按类别、细分类和 Borough 估算，检索标签也会在显式 OSM 属性之外进行稳定补全。

P14 已完成稳定性与性能收尾：保护 Redis Lua 库存原子性和 RabbitMQ ack/nack/重放/幂等语义，增加 Agent 结果数量、Unicode 约束解析、并发取消/恢复与 DeepSeek Trace 观测，并固化地图/列表 P95、双语键和前端回归门禁。

隔离全栈压测由 `compose.load-test.yml` 和 `scripts/load-test/` 提供，覆盖 Actuator/Prometheus、k6 读取/秒杀/重复用户/混合/长稳场景、订单最终一致性校验，以及 RabbitMQ/MySQL/Redis 故障恢复演练；它不会操作日常开发数据库。

使用本地集成 Compose 前先通过 `NYC_REVIEW_DATA_DIR` 指向包含 `mysql_import.sql`、`p7_neighborhood_import.sql` 和 `redis_seed.resp` 的有效数据目录，并将当前用户登录 token 传给 Agent Service；缺少这些变量时 Compose 会直接拒绝启动：

```bash
export NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN='<current-user-token>'
export NYC_REVIEW_DATA_DIR="$PWD/data/generated/nyc-real-p13-full"
docker compose -f compose.local.yml up --build
```

Compose 中的 MySQL init 脚本只会在全新的空 volume 上运行；已有 P6/P7 volume 应先按上面的“现有环境”命令手工升级，不能通过重复执行 P8 迁移来追平。不要将登录 token 写入受版本控制的文件。

## 启动前端开发环境

```bash
cd nyc-review-web
npm ci
npm run dev
```

Vite 默认监听 `http://127.0.0.1:3000`，将 `/api` 代理到 Spring Boot 8081，并将 `/agent-api` 代理到 Agent Service 8090。AI 工作台位于 `/ai`。

生产构建：

```bash
cd nyc-review-web
npm run build
```

构建结果位于 `nyc-review-web/dist`。

## Nginx 部署

当前桌面部署约定为：

- React 静态资源：`nginx-1.18.0/html/nyc-review-web`
- 用户上传图片：`nginx-1.18.0/html/nyc-review/imgs`
- Nginx 监听端口：`8080`
- Spring Boot 上游端口：`8081`

部署到 Nginx 时，请将 `NYC_REVIEW_IMAGE_UPLOAD_DIR` 设置为上述用户图片目录的绝对路径。上传接口仅接受 JPEG、PNG 和 WebP，单文件最大 5MB。

将 `nyc-review-web/dist` 中的内容部署到 React 静态资源目录后，检查并重新加载 Nginx 配置。SPA 路由需要保留 `try_files $uri $uri/ /index.html`，API 请求需要把 `/api` 前缀代理到 Spring Boot。

## 验证

```bash
cd nyc-review-web
npm run release:check
```

这条命令按发布顺序执行前端 lint、测试、生产构建、双语/路由契约检查和视觉资源审计，
再通过锁定的 `uv.lock` 执行 Agent 服务的 Ruff 与完整测试；生产镜像工作流也会在构建并推送
固定 SHA 镜像前运行同一质量门。本地需要已安装 `uv`。

安全的后端回归命令是 `mvn -Dtest='!NycReviewApplicationTests' test`。
`NycReviewApplicationTests` 包含数据构造和 Redis 回填方法；在完成容器化隔离前，不要在承载有效数据的环境执行它。

## 安全说明

- 真实密钥如果曾进入 Git 历史，应立即在对应服务中轮换。
- 从当前文件删除密钥不会自动清除历史提交中的副本。
- Git 历史清理会改写提交历史，需要单独评估并协调所有协作者。
