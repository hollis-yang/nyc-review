# NYC Review Agent Service

FastAPI + LangGraph 服务，负责单 Agent/多 Agent 编排、RAG、人工审批和可观测性。Spring Boot 仍是业务事实来源；本服务不得直连业务表执行任意查询或写入。

## 本地运行

```bash
cd agent-service
uv sync --dev
uv run uvicorn app.main:app --reload --port 8090
```

```bash
curl http://127.0.0.1:8090/health
```

默认使用只读的 Mock Adapter、离线约束解析器和 SQLite Run Store，方便无外部依赖地验证工作流。生产环境必须设置 `NYC_REVIEW_AGENT_ADAPTER=http` 并配置后端服务地址。

## P2 Run API 与 SSE

产品入口只需要自然语言，不再要求前端手工填写结构化约束：

```bash
curl -sS -X POST http://127.0.0.1:8090/v1/agent/runs \
  -H 'Content-Type: application/json' \
  -H 'x-agent-session: 12345678-1234-4567-89ab-123456789abc' \
  -H 'authorization: <current-user-token>' \
  -d '{"mode":"multi","query":"Quiet vegan dinner in Midtown for 2 under $120"}'
```

使用响应中的 `run_id` 和相同登录 token 读取实时协作事件和最终快照：

```bash
curl -N -H 'x-agent-session: 12345678-1234-4567-89ab-123456789abc' -H 'authorization: <current-user-token>' http://127.0.0.1:8090/v1/agent/runs/<run-id>/events
curl -sS -H 'x-agent-session: 12345678-1234-4567-89ab-123456789abc' -H 'authorization: <current-user-token>' http://127.0.0.1:8090/v1/agent/runs/<run-id>
```

Run、事件与最终结果默认持久化到 `./.local/agent-runs.sqlite3`。接口同时支持 `single` 和 `multi`；多 Agent 仍由 Supervisor、Discovery、Evidence、Itinerary、Verifier 协作，Evidence 与 Itinerary 并行。

## P3 人工审批执行

推荐完成后，Agent Service 会持久化可选 action proposal，并将 Run 暂停为 `waiting_confirmation`。用户可逐项批准、拒绝或重试；批准后由 Spring 的受限 action endpoint 执行，并以 `actionId` 保证幂等。收藏偏好可补全后续未指定的分类或街区，Run 历史按登录 token 的不可逆 SHA-256 隔离。

```bash
curl -X POST /v1/agent/runs/<run-id>/actions/<action-id>/approve \
  -H 'x-agent-session: 12345678-1234-4567-89ab-123456789abc' \
  -H 'authorization: <current-user-token>'
curl -X POST /v1/agent/runs/<run-id>/actions/<action-id>/reject \
  -H 'x-agent-session: 12345678-1234-4567-89ab-123456789abc' \
  -H 'authorization: <current-user-token>'
curl -H 'x-agent-session: 12345678-1234-4567-89ab-123456789abc' \
  -H 'authorization: <current-user-token>' '/v1/agent/runs?limit=5'
curl /v1/agent/metrics
```

前端产品入口只暴露 Multi Agent；Single Agent 继续保留，用于离线调试和行为对照。

## P4 Observability、恢复与安全

- 每个 Run 持久化 model、tool、agent node、action 和 total span；`GET /v1/agent/runs/{id}/trace` 返回完整 Trace。
- `/v1/agent/metrics` 聚合操作次数、失败数、P50/P95 延迟和模型 Token；配置 `NYC_REVIEW_AGENT_METRICS_TOKEN` 后需传 `x-metrics-token`。
- Agent 启动时会恢复未完成且尚未产生写操作的 Run；Embedding Provider 使用有限 connect/read/pool timeout 与有界重试，Run 仍可由用户主动取消。
- 所有持久 Run API 都要求浏览器生成的 `x-agent-session`；匿名 Run 按该 session 隔离，登录后原子绑定到 token 的 SHA-256 owner key，且不保存原始 token。
- 服务重启不会自动重放已批准的写操作；中断的 Action 会回到可人工重试的 `failed` 状态，并继续使用同一个幂等 `actionId` 对账。
- Prompt Guard 拒绝显式系统提示词窃取与绕过审批指令，创建 Run 还受按 owner/IP 的滑动窗口限流。

```bash
curl -H 'authorization: <current-user-token>' \
  -H 'x-agent-session: 12345678-1234-4567-89ab-123456789abc' \
  http://127.0.0.1:8090/v1/agent/runs/<run-id>/trace

curl -H 'x-metrics-token: <metrics-token>' \
  http://127.0.0.1:8090/v1/agent/metrics
```

## DeepSeek 模型网关

默认 `NYC_REVIEW_AGENT_MODEL_PROVIDER=heuristic`，可离线运行。启用 DeepSeek：

```bash
NYC_REVIEW_AGENT_MODEL_PROVIDER=deepseek \
DEEPSEEK_API_KEY=<your-key> \
DEEPSEEK_MODEL=deepseek-chat \
uv run uvicorn app.main:app --port 8090
```

也可使用 `NYC_REVIEW_AGENT_MODEL_API_KEY`、`NYC_REVIEW_AGENT_MODEL_NAME` 与 `NYC_REVIEW_AGENT_MODEL_BASE_URL` 独立配置。模型失败时默认回退离线解析器，并在结果 `metadata.modelFallbackUsed` 中标记；设置 `NYC_REVIEW_AGENT_MODEL_FALLBACK_TO_HEURISTIC=false` 可改为直接失败。

## P8 Real-only 数据与增量 Qdrant RAG

当前集成 Profile 是 `real-medium`。它从固定的 OpenStreetMap 快照选取 5,000 个真实商户身份，并生成 100,000 条根评论及 52,500 条一、二级回复。仓库根目录可用固定快照复现数据集：

```bash
python3 scripts/mock-data-generator/generate.py \
  --profile real-medium \
  --real-places data/sources/osm-nyc-places-2026-08-23.json \
  --illustrative-images data/sources/wikimedia-illustrative-images-v1.json \
  --output data/generated/nyc-real-medium

python3 scripts/mock-data-generator/validate_dataset.py \
  data/generated/nyc-real-medium
```

推荐使用 Qdrant Server 承载该规模的索引。先启动 Spring Boot 与 Qdrant，再从 `agent-service` 目录运行：

```bash
NYC_REVIEW_AGENT_ADAPTER=http \
NYC_REVIEW_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN=<current-user-token> \
NYC_REVIEW_AGENT_RAG_ADAPTER=qdrant \
NYC_REVIEW_AGENT_QDRANT_LOCATION=http://127.0.0.1:6333 \
NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-real-medium \
NYC_REVIEW_AGENT_RAG_INDEX_BATCH_SIZE=128 \
uv run uvicorn app.main:app --port 8090
```

启动时会校验 `manifest.json` 与 `import_manifest.json`：`merchantIdentityMode` 必须为 `REAL_ONLY`、`mockShops` 必须为 `0`、六个分类都必须存在，shopId、`dataVersion` 与数据集 SHA-256 也必须一致。完整数据集 SHA 会进入 Qdrant payload、point ID、同步 scope 和检索 filter。索引按批次流式读取，不再删除并完整重建 Collection；相同内容哈希会跳过，只批量 upsert 新增或变化文档，并在成功后清理当前数据集 scope 的陈旧文档。批大小由 `NYC_REVIEW_AGENT_RAG_INDEX_BATCH_SIZE` 控制，健康检查和 Run metadata 中的 `ragIndexStats` 可查看 total、upserted、unchanged 和 deleted 数量。生产快照可设置 `NYC_REVIEW_AGENT_RAG_SYNC_MODE=verify`：此模式要求 Collection 与 payload indexes 已存在，并逐条核对 point ID、document ID、content hash 与 scope；任何 missing/changed/stale 文档都会阻止启动，且不会创建索引、调用文档 Embedding、upsert 或 delete。

RAG 将每个根评论及其一、二级回复组合成一份 `shop_review_thread` 文档，并继续索引商户介绍、博客与博客评论。Payload 分开保留商户身份来源和记录自身的内容来源；这些字段用于审计和数据隔离，不会拼进用户可见的 citation excerpt。Loader 会拒绝来源类型或 `dataVersion` 不符合 real-only 契约的数据。营业时间优先采用 OSM `opening_hours`，缺失时使用类别默认值；价格与稀疏发现标签采用稳定估算；评分来自根评论聚合。Verifier 会尊重 Discovery 明确记录的约束放宽，避免把同一缺失标签再按候选逐条报告为失败。

本地磁盘模式 `NYC_REVIEW_AGENT_QDRANT_LOCATION=./.local/qdrant` 只适合单进程小型验证，同一路径不能被多个 Qdrant Client 同时打开。默认 Hash Embedding 仅用于离线开发；production/staging 会拒绝 Hash，除非显式设置测试 override。真实 Provider 复用持久 HTTP Client，带 timeout、有界 retry、返回校验、Query TTL/LRU cache 和 token budget；OpenAI 使用标准 Embeddings API，Qwen 使用 DashScope Native API 区分 query/document。每个 Embedding identity 使用独立索引 scope，版本变化不会错误复用旧向量。

使用根目录 `compose.local.yml` 时，也必须在启动前把当前登录 token 传给 Agent 的 HTTP Adapter，并用 `NYC_REVIEW_DATA_DIR` 指向有效数据包，否则 Compose 或 Spring Tool API 会拒绝请求：

```bash
export NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN='<current-user-token>'
export NYC_REVIEW_DATA_DIR="$PWD/data/generated/nyc-real-p13-full"
docker compose -f compose.local.yml up --build
```

Compose 的 MySQL init 脚本只适用于全新空 volume；已有 P6/P7 数据库应按 Runbook 手工执行 P10 和数据切换，不得重复执行非幂等的 P8 迁移。该 token 只应存在于本地环境或 Secret 管理系统，不要提交到仓库。

数据生成和校验命令见根目录的 [数据生成器 README](../scripts/mock-data-generator/README.md)。

如果只做离线工作流测试，可将 `NYC_REVIEW_AGENT_ADAPTER` 改回 `mock`；接入 Spring Boot Tool API 时必须配置：

```bash
NYC_REVIEW_AGENT_ADAPTER=http \
NYC_REVIEW_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN=<current-user-token>
```

## 安全边界

- 只读检索工具可由 Agent 自动调用。
- 收藏、保存行程、领取普通优惠券和创建秒杀提醒必须经过人工审批。
- `seckill_voucher` 不在模型 Tool Catalog 中；用户手动秒杀由 React 直接调用 Spring Boot。
- RAG 返回的评论和博客必须标记为不可信内容，并携带可回溯引用。

## P5 Read-only MCP Server

Agent Service 同时在 `http://127.0.0.1:8090/mcp` 提供 Streamable HTTP MCP。它复用 AI Guide 的领域服务，只发布 `search_shops`、`get_shop_detail`、`get_shop_evidence`、`get_available_vouchers`、`calculate_route` 和 `validate_itinerary`。MCP Tool Catalog 不包含任何写操作。

本地可设置 `NYC_REVIEW_AGENT_MCP_API_KEY`，客户端随后使用 `Authorization: Bearer <key>`。HTTP Adapter 访问 Spring 时仍使用独立的 `NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN`；不要把用户登录 token 当作 MCP 服务密钥。
