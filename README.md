# hm-dianping

黑马点评 NYC AI 全栈改造项目。Spring Boot、MySQL 和 Redis 继续承载传统业务与手动秒杀；React 提供 NYC 地图和 AI 工作台；独立的 FastAPI + LangGraph 服务负责多 Agent 与 Qdrant RAG。

架构边界与不可回退能力见 [目标架构](docs/target-architecture.md) 和 [验收标准](docs/acceptance-criteria.md)。

## 环境要求

- Java 17
- Maven 3.9+
- MySQL 8+
- Redis 6+
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

新的 Redis Stream 秒杀订单链路还需要应用幂等唯一键：

```bash
mysql -u root -p hmdp_new < src/main/resources/db/p2_redis_stream_order.sql
mysql -u root -p hmdp_new < src/main/resources/db/p3_nyc_compatibility.sql
mysql -u root -p hmdp_new < src/main/resources/db/p4_nyc_domain.sql
mysql -u root -p hmdp_new < src/main/resources/db/p5_agent_actions.sql
```

生成稳定、可复现的 NYC Mock 数据：

```bash
python3 scripts/mock-data-generator/generate.py \
  --profile small \
  --output data/generated/nyc-small
```

生成结果包括六个顶级分类、商户、营业时间、评论、博客、嵌套评论、普通优惠券与必须手动参与的秒杀券，以及 MySQL/Redis 导入包。生成动作不会连接数据库；下面两条命令会归档当前杭州数据并替换开发环境中的活动数据，执行前应停止服务并确认目标实例：

```bash
mysql -u root -p hmdp_new < data/generated/nyc-small/mysql_import.sql
redis-cli --pipe < data/generated/nyc-small/redis_seed.resp
```

详细步骤与校验查询见 [P1 NYC 数据 Runbook](docs/p1-nyc-data-runbook.md) 和 [Mock 数据生成器](scripts/mock-data-generator/README.md)。

## 启动后端

确认 MySQL、Redis 和环境变量均已就绪：

```bash
mvn spring-boot:run
```

后端默认监听 `http://127.0.0.1:8081`。

## 启动多 Agent 与 RAG

```bash
cd agent-service
uv sync --dev
HMDP_AGENT_RAG_ADAPTER=qdrant \
HMDP_AGENT_QDRANT_LOCATION=./.local/qdrant \
HMDP_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-small \
HMDP_AGENT_MODEL_PROVIDER=deepseek \
uv run uvicorn app.main:app --reload --port 8090
```

配置 `HMDP_AGENT_RAG_DATA_DIRECTORY` 后，Agent Service 会校验导入清单并使用同一组 shopId 重建 Qdrant 索引；需要连接 Spring Boot Tool API 时设置 `HMDP_AGENT_ADAPTER=http`。`HMDP_AGENT_MODEL_PROVIDER=deepseek` 会复用 `DEEPSEEK_API_KEY`，未配置或模型不可用时默认受控回退到离线约束解析器。完整配置与 Run/SSE 验证见 [Agent Service README](agent-service/README.md) 和 [P2 Runbook](docs/p2-agent-runbook.md)。模型 Tool Catalog 不包含 `seckill_voucher`，因此 Agent 不能代替用户秒杀。

P3 增加人工审批操作、幂等执行、MySQL 审计、收藏偏好、Run 历史与指标；React 默认英语，可在 `Profile → Edit Profile` 切换中文，DeepSeek 翻译入口只在中文模式显示。迁移、接口和 Docker Compose 验证见 [P3 Runbook](docs/p3-agent-actions-runbook.md)。

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
